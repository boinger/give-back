"""Fetch and filter open issues from a GitHub repository.

Uses the REST issues endpoint. Filters out pull requests (GitHub returns PRs
in the issues endpoint), applies label priority, activity recency, and clarity
heuristics.
"""

from __future__ import annotations

from datetime import datetime, timezone

from give_back.github_client import GitHubClient
from give_back.triage.models import Clarity, Competition, IssueCandidate, Scope

# Labels that indicate contribution-friendly issues (case-insensitive matching)
PRIORITY_LABELS = {
    "good first issue",
    "good-first-issue",
    "help wanted",
    "help-wanted",
    "bug",
    "easy",
    "beginner",
    "starter",
}

# Scope heuristic keywords in labels
_SMALL_LABEL_KEYWORDS = {"good first issue", "good-first-issue", "easy", "beginner", "typo", "docs", "starter"}
_LARGE_LABEL_KEYWORDS = {"feature", "enhancement", "refactor", "rfc", "redesign"}

# Activity cutoff: issues not updated in this many days are considered stale
_ACTIVITY_CUTOFF_DAYS = 180  # 6 months
_STALENESS_CUTOFF_DAYS = 365  # 1 year


def fetch_issues(
    client: GitHubClient,
    owner: str,
    repo: str,
    label_filter: str | None = None,
    limit: int = 20,
) -> list[IssueCandidate]:
    """Fetch open issues and convert to scored IssueCandidate objects.

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        label_filter: Optional label to filter by (e.g., "good first issue").
        limit: Maximum number of candidates to return.

    Returns:
        List of IssueCandidate objects, pre-filtered but not yet ranked
        (ranking happens in rank.py after competition check).
    """
    params: dict[str, str | int] = {
        "state": "open",
        "sort": "updated",
        "direction": "desc",
        "per_page": 100,
    }
    if label_filter:
        params["labels"] = label_filter

    raw_issues = client.rest_get(f"/repos/{owner}/{repo}/issues", params=params)

    # GitHub REST issues endpoint returns PRs too — filter them out
    if not isinstance(raw_issues, list):
        return []

    candidates = []
    now = datetime.now(timezone.utc)

    for issue in raw_issues:
        # Skip pull requests
        if "pull_request" in issue:
            continue

        candidate = _issue_to_candidate(issue, owner, repo, now)
        if candidate is not None:
            candidates.append(candidate)

        if len(candidates) >= limit * 2:
            # Fetch more than needed so ranking can filter further
            break

    return candidates


def _issue_to_candidate(
    issue: dict,
    owner: str,
    repo: str,
    now: datetime,
) -> IssueCandidate | None:
    """Convert a raw GitHub issue dict to an IssueCandidate.

    Returns None if the issue should be excluded (too stale, no description, etc.).
    """
    body = issue.get("body") or ""
    labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
    labels_lower = {lbl.lower() for lbl in labels}

    # Check activity recency
    updated_at_str = issue.get("updated_at", "")
    if updated_at_str:
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        days_since_update = (now - updated_at).days
    else:
        days_since_update = 9999

    # Skip if no update in 6 months AND no priority labels
    priority = [lbl for lbl in labels if lbl.lower() in PRIORITY_LABELS]
    if days_since_update > _ACTIVITY_CUTOFF_DAYS and not priority:
        return None

    # Staleness risk
    created_at_str = issue.get("created_at", "")
    staleness_risk = False
    if created_at_str:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        if (now - created_at).days > _STALENESS_CUTOFF_DAYS and days_since_update > _ACTIVITY_CUTOFF_DAYS:
            staleness_risk = True

    # Scope estimate
    scope = _estimate_scope(labels_lower, body, issue.get("comments", 0))

    # Clarity estimate
    clarity = _estimate_clarity(body)

    return IssueCandidate(
        number=issue["number"],
        title=issue.get("title", ""),
        url=issue.get("html_url", f"https://github.com/{owner}/{repo}/issues/{issue['number']}"),
        labels=labels,
        scope=scope,
        clarity=clarity,
        competition=Competition.NONE,  # Set later by compete.py
        staleness_risk=staleness_risk,
        created_at=created_at_str,
        updated_at=updated_at_str,
        comment_count=issue.get("comments", 0),
        description_length=len(body),
        body=body,
        priority_labels=priority,
    )


def _estimate_scope(labels_lower: set[str], body: str, comment_count: int) -> Scope:
    """Estimate issue scope from labels, description length, and comment count."""
    # Label-based
    if labels_lower & _SMALL_LABEL_KEYWORDS:
        return Scope.SMALL
    if labels_lower & _LARGE_LABEL_KEYWORDS:
        return Scope.LARGE

    # Description/comment-based
    if len(body) > 2000 or comment_count > 20:
        return Scope.LARGE
    if len(body) < 500:
        return Scope.SMALL

    return Scope.MEDIUM


def _estimate_clarity(body: str) -> Clarity:
    """Estimate how clearly the issue describes expected behavior."""
    if not body or len(body) < 50:
        return Clarity.LOW

    # Heuristics: code blocks, numbered lists, or "steps to reproduce" patterns
    has_code_block = "```" in body or "    " in body
    has_steps = any(
        pattern in body.lower()
        for pattern in ["steps to reproduce", "expected behavior", "actual behavior", "1.", "- [ ]"]
    )

    if len(body) > 200 and (has_code_block or has_steps):
        return Clarity.HIGH
    if len(body) > 200:
        return Clarity.MEDIUM
    return Clarity.LOW
