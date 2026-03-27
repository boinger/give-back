"""MEDIUM signal: Repository staleness assessment.

Composite score from three sub-signals:
- Last commit age
- Release cadence (releases in last 12 months)
- Issue close rate (closed / total issues)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from give_back.models import RepoData, SignalResult, SignalWeight, score_to_tier

NAME = "Staleness"
WEIGHT = SignalWeight.MEDIUM


def _commit_age_score(data: RepoData) -> tuple[float, str]:
    """Score based on age of the last commit on the default branch."""
    default_branch = data.graphql.get("repository", {}).get("defaultBranchRef")
    if default_branch is None:
        return 0.1, "no default branch"

    committed_date_str = default_branch.get("target", {}).get("committedDate")
    if not committed_date_str:
        return 0.1, "no commit date"

    committed_date = datetime.fromisoformat(committed_date_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age = now - committed_date

    if age <= timedelta(days=7):
        return 1.0, "last commit within 7 days"
    if age <= timedelta(days=30):
        return 0.8, "last commit within 30 days"
    if age <= timedelta(days=90):
        return 0.6, "last commit within 90 days"
    if age <= timedelta(days=365):
        return 0.3, "last commit within 1 year"
    return 0.1, "last commit over 1 year ago"


def _release_cadence_score(data: RepoData) -> tuple[float, str]:
    """Score based on number of releases in the last 12 months."""
    nodes = data.graphql.get("repository", {}).get("releases", {}).get("nodes", [])
    now = datetime.now(timezone.utc)
    one_year_ago = now - timedelta(days=365)

    recent_count = 0
    for node in nodes:
        created_at = node.get("createdAt")
        if not created_at:
            continue
        pub_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if pub_date >= one_year_ago:
            recent_count += 1

    if recent_count >= 4:
        return 1.0, f"{recent_count} releases in last 12 months"
    if recent_count >= 2:
        return 0.7, f"{recent_count} releases in last 12 months"
    if recent_count >= 1:
        return 0.5, f"{recent_count} release in last 12 months"
    return 0.3, "no releases in last 12 months"


def _issue_close_rate_score(data: RepoData) -> tuple[float, str]:
    """Score based on ratio of closed to total issues."""
    repo = data.graphql.get("repository", {})
    open_count = repo.get("openIssues", {}).get("totalCount", 0)
    closed_count = repo.get("closedIssues", {}).get("totalCount", 0)
    total = open_count + closed_count

    if total == 0:
        return 0.5, "no issues found"

    ratio = closed_count / total
    if ratio >= 0.7:
        return 1.0, f"{ratio:.0%} issues closed"
    if ratio >= 0.5:
        return 0.7, f"{ratio:.0%} issues closed"
    if ratio >= 0.3:
        return 0.5, f"{ratio:.0%} issues closed"
    return 0.3, f"{ratio:.0%} issues closed"


def evaluate_staleness(data: RepoData) -> SignalResult:
    """Assess repository activity from commits, releases, and issue resolution."""
    commit_score, commit_detail = _commit_age_score(data)
    release_score, release_detail = _release_cadence_score(data)
    issue_score, issue_detail = _issue_close_rate_score(data)

    final_score = (commit_score + release_score + issue_score) / 3.0

    summary = f"Commit: {commit_detail}; Releases: {release_detail}; Issues: {issue_detail}"

    return SignalResult(
        score=round(final_score, 4),
        tier=score_to_tier(final_score),
        summary=summary,
        details={
            "commit_score": commit_score,
            "commit_detail": commit_detail,
            "release_score": release_score,
            "release_detail": release_detail,
            "issue_score": issue_score,
            "issue_detail": issue_detail,
        },
    )
