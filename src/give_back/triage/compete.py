"""Competing work detection for candidate issues.

For each IssueCandidate, checks:
1. Linked open PRs (via search API) — active vs. stale
2. Claim comments on the issue (patterns like "I'm working on this", "WIP", etc.)

Updates the candidate's ``competition`` and ``competition_detail`` fields in-place.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient
from give_back.triage.models import Competition, IssueCandidate

# Patterns that indicate someone has claimed an issue (case-insensitive)
_CLAIM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"i[''']m working on this", re.IGNORECASE),
    re.compile(r"i[''']ll take this", re.IGNORECASE),
    re.compile(r"working on a fix", re.IGNORECASE),
    re.compile(r"i[''']d like to work on", re.IGNORECASE),
    re.compile(r"assigned to me", re.IGNORECASE),
    re.compile(r"i[''']ll submit a pr", re.IGNORECASE),
    re.compile(r"\bwip\b", re.IGNORECASE),
]

# Thresholds
_STALE_PR_DAYS = 180  # 6 months
_RECENT_CLAIM_DAYS = 30


def check_competition(
    client: GitHubClient,
    owner: str,
    repo: str,
    candidates: list[IssueCandidate],
) -> None:
    """Check each candidate for competing work and update fields in-place.

    For each candidate:
    - Searches for linked open PRs mentioning the issue number.
    - Scans recent issue comments for claim patterns.
    - Sets ``competition`` to the higher of the two signals and fills
      ``competition_detail`` with a human-readable explanation.

    API errors (any GiveBackError subclass) are caught per-candidate so that
    one failure does not block the rest. On error, the candidate's competition
    remains NONE.
    """
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        try:
            pr_competition, pr_detail = _check_linked_prs(client, owner, repo, candidate.number, now)
            claim_competition, claim_detail = _check_claim_comments(client, owner, repo, candidate.number, now)
        except GiveBackError:
            # Leave competition as NONE on API errors
            continue

        # Pick the higher competition level; prefer PR detail when both are HIGH
        winner = _max_competition(pr_competition, claim_competition)
        candidate.competition = winner

        if winner == Competition.NONE:
            candidate.competition_detail = None
        elif pr_competition == Competition.HIGH and claim_competition == Competition.HIGH:
            # Both HIGH — prefer the PR detail
            candidate.competition_detail = pr_detail
        elif pr_competition == winner:
            candidate.competition_detail = pr_detail
        else:
            candidate.competition_detail = claim_detail


def _max_competition(a: Competition, b: Competition) -> Competition:
    """Return the higher competition level."""
    order = {Competition.NONE: 0, Competition.LOW: 1, Competition.HIGH: 2}
    return a if order[a] >= order[b] else b


def _check_linked_prs(
    client: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
    now: datetime,
) -> tuple[Competition, str | None]:
    """Search for open PRs that reference this issue number.

    Returns (competition_level, detail_string).
    """
    query = f"repo:{owner}/{repo} is:pr is:open {issue_number}"
    result = client.search(query)

    if not isinstance(result, dict):
        return Competition.NONE, None

    total = result.get("total_count", 0)
    items = result.get("items", [])

    if total == 0 or not items:
        return Competition.NONE, None

    # Find the most recently updated PR
    most_recent_pr = None
    most_recent_updated: datetime | None = None

    for item in items:
        updated_str = item.get("updated_at", "")
        if not updated_str:
            continue
        updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
        if most_recent_updated is None or updated > most_recent_updated:
            most_recent_updated = updated
            most_recent_pr = item

    if most_recent_pr is None or most_recent_updated is None:
        return Competition.NONE, None

    pr_number = most_recent_pr.get("number", "?")
    days_since_update = (now - most_recent_updated).days
    months_since_update = days_since_update // 30

    if days_since_update > _STALE_PR_DAYS:
        return Competition.LOW, f"PR #{pr_number} stale {months_since_update} months"
    return Competition.HIGH, f"PR #{pr_number} active"


def _check_claim_comments(
    client: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
    now: datetime,
) -> tuple[Competition, str | None]:
    """Scan issue comments for claim patterns.

    Returns (competition_level, detail_string).
    """
    comments = client.rest_get(
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        params={"per_page": 10},
    )

    if not isinstance(comments, list) or not comments:
        return Competition.NONE, None

    # Scan comments newest-first for claim patterns
    for comment in reversed(comments):
        body = comment.get("body", "")
        if not body:
            continue

        if not _matches_claim_pattern(body):
            continue

        # Found a claim — check how recent it is
        created_str = comment.get("created_at", "")
        if not created_str:
            continue

        created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        days_ago = (now - created).days
        author = comment.get("user", {}).get("login", "unknown")

        if days_ago <= _RECENT_CLAIM_DAYS:
            return Competition.HIGH, f"claimed by @{author} {days_ago} days ago"

        months_ago = days_ago // 30
        return Competition.LOW, f"claimed by @{author} {months_ago} months ago — may be abandoned"

    return Competition.NONE, None


def _matches_claim_pattern(text: str) -> bool:
    """Return True if text matches any claim pattern."""
    return any(pattern.search(text) for pattern in _CLAIM_PATTERNS)
