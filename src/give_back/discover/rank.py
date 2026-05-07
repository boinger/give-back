"""Light ranking of GitHub search results by contribution-friendliness.

Pure function, no API calls. Uses search metadata only. All weights are
named constants for tuning. No calibration mechanism yet — if ranking
proves unreliable, add calibrate-discover using the same pattern as calibrate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Initial weights — expect tuning after real-world usage.
# GitHub search doesn't return per-label issue counts, so GFI/HW bonuses
# are based on which search query the repo came from (tagged by discover_repos).
_GFI_QUERY_BONUS = 15  # repo matched the good-first-issues search query
_HW_QUERY_BONUS = 5  # repo matched the help-wanted search query
_RECENT_PUSH_7D = 10  # pushed in last 7 days
_RECENT_PUSH_30D = 5  # pushed in last 30 days
_HAS_DESCRIPTION = 5  # repo has a non-empty description
_ACTIVE_ISSUES = 5  # open_issues > 10
_HAS_TOPICS = 3  # 3+ topics (indicates maintained repo)


def rank_repos(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score and sort search results by contribution-friendliness.

    Input: list of GitHub search API repo dicts.
    Output: same list, sorted by score desc, stars desc for ties.
    Each dict gets a ``_rank_score`` key added for debugging.
    """
    for repo in repos:
        repo["_rank_score"] = _score(repo)

    return sorted(repos, key=lambda r: (r["_rank_score"], r.get("stargazers_count", 0)), reverse=True)


def _score(repo: dict[str, Any]) -> int:
    """Compute a contribution-friendliness score from search metadata.

    GitHub's search API doesn't return per-label issue counts in the response.
    The search *query* filters for good-first-issues/help-wanted repos, but the
    response only includes total open_issues_count. We score based on what's
    available: total issues, recency, description, and whether it has topics.
    """
    score = 0

    # Repos from Q1 (good-first-issues) get a bonus if they were tagged by
    # the caller. This is set by discover_repos() after the search.
    if repo.get("_from_gfi_query"):
        score += _GFI_QUERY_BONUS
    elif repo.get("_from_hw_query"):
        score += _HW_QUERY_BONUS

    # Recent push
    pushed_at = repo.get("pushed_at")
    if pushed_at and isinstance(pushed_at, str):
        try:
            pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            days_ago = (datetime.now(timezone.utc) - pushed).days
            if days_ago <= 7:
                score += _RECENT_PUSH_7D
            elif days_ago <= 30:
                score += _RECENT_PUSH_30D
        except (ValueError, TypeError):
            pass  # Unparseable date, skip bonus

    # Has description
    if repo.get("description"):
        score += _HAS_DESCRIPTION

    # Active issues
    open_issues = repo.get("open_issues_count", 0)
    if isinstance(open_issues, int) and open_issues > 10:
        score += _ACTIVE_ISSUES

    # Has topics (indicates maintained, discoverable repo)
    topics = repo.get("topics", [])
    if isinstance(topics, list) and len(topics) >= 3:
        score += _HAS_TOPICS

    return score
