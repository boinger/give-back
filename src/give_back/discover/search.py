"""Search GitHub for contribution-friendly repositories.

Uses the GitHub search API to find repos that:
1. Match language/topic filters
2. Have recent activity (pushed within 90 days)
3. Have issues labeled "good first issue" or "help wanted"
4. Accept external contributions (not archived, has contributing guide)

Results are then pre-screened with a lightweight viability check
(license gate + basic activity signals) before ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from give_back.github_client import GitHubClient
from give_back.models import Tier


@dataclass
class DiscoverResult:
    """A repository discovered as a potential contribution target."""

    owner: str
    repo: str
    description: str
    stars: int
    language: str | None
    topics: list[str]
    open_issue_count: int
    good_first_issue_count: int
    tier: Tier | None = None
    """Viability tier from pre-screen, or None if not yet assessed."""
    skip_reason: str | None = None
    """If set, this repo was filtered out and this explains why."""


@dataclass
class DiscoverSummary:
    """Summary of a discover search run."""

    query: str
    total_searched: int
    results: list[DiscoverResult] = field(default_factory=list)
    filtered_count: int = 0


def discover_repos(
    client: GitHubClient,
    *,
    language: str | None = None,
    topic: str | None = None,
    min_stars: int = 50,
    limit: int = 20,
) -> DiscoverSummary:
    """Search GitHub for contribution-friendly repos and pre-screen viability.

    Args:
        client: Authenticated GitHub client.
        language: Filter by primary language (e.g., "python", "rust").
        topic: Filter by topic (e.g., "kubernetes", "cli").
        min_stars: Minimum star count to consider.
        limit: Maximum results to return after filtering.

    Returns:
        DiscoverSummary with ranked results.
    """
    raise NotImplementedError("discover_repos is not yet implemented")
