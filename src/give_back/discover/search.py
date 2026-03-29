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

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from give_back.assess import run_assessment
from give_back.console import stderr_console as _console
from give_back.discover.rank import rank_repos
from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient
from give_back.models import Tier
from give_back.signals import ALL_SIGNALS
from give_back.state import (
    get_cached_assessment,
    get_discover_cache,
    reconstruct_assessment,
    save_assessment,
    save_discover_cache,
)

_log = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 5
_WORST_CASE_CALLS_PER_REPO = 6
_RECENCY_DAYS = 90


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
    from_cache: bool = False
    """True if the assessment tier came from cache rather than a fresh API call."""
    skip_reason: str | None = None
    """If set, this repo was filtered out and this explains why."""


@dataclass
class DiscoverSummary:
    """Summary of a discover search run."""

    query: str
    total_searched: int
    results: list[DiscoverResult] = field(default_factory=list)
    filtered_count: int = 0
    assessed_count: int = 0
    cache_hits: int = 0


def _build_query(
    language: str | None,
    topic: str | None,
    min_stars: int,
    label_filter: str,
) -> str:
    """Assemble a GitHub repository search query string.

    Args:
        language: Filter by primary language (e.g. "python").
        topic: Filter by topic (e.g. "cli").
        min_stars: Minimum star count.
        label_filter: Either "good-first-issues:>0" or "help-wanted-issues:>0".

    Returns:
        GitHub search query string.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RECENCY_DAYS)
    pushed_date = cutoff.strftime("%Y-%m-%d")

    parts: list[str] = []
    if language:
        parts.append(f"language:{language}")
    if topic:
        parts.append(f"topic:{topic}")
    parts.append(f"stars:>{min_stars}")
    parts.append(label_filter)
    parts.append("archived:false")
    parts.append(f"pushed:>{pushed_date}")
    parts.append("sort:stars")

    return " ".join(parts)


def _repo_dict_to_result(repo: dict) -> DiscoverResult:
    """Convert a GitHub search API repo dict to a DiscoverResult."""
    full_name = repo.get("full_name", "/")
    owner, _, name = full_name.partition("/")
    return DiscoverResult(
        owner=owner,
        repo=name,
        description=repo.get("description") or "",
        stars=repo.get("stargazers_count", 0),
        language=repo.get("language"),
        topics=repo.get("topics") or [],
        open_issue_count=repo.get("open_issues_count", 0),
        good_first_issue_count=0,  # Not available from search API
    )


def discover_repos(
    client: GitHubClient,
    *,
    language: str | None = None,
    topic: str | None = None,
    min_stars: int = 50,
    limit: int = 10,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    no_cache: bool = False,
    exclude_assessed: bool = False,
) -> DiscoverSummary:
    """Search GitHub for contribution-friendly repos and pre-screen viability.

    Args:
        client: Authenticated GitHub client.
        language: Filter by primary language (e.g., "python", "rust").
        topic: Filter by topic (e.g., "kubernetes", "cli").
        min_stars: Minimum star count to consider.
        limit: Maximum results to return after filtering.
        batch_size: Number of repos to assess in each API batch.
        no_cache: If True, skip the discover search cache (assessments still cached).
        exclude_assessed: If True, filter out repos that already have a cached assessment.

    Returns:
        DiscoverSummary with ranked results.
    """
    # Step 1: Build queries
    q1 = _build_query(language, topic, min_stars, "good-first-issues:>0")
    q2 = _build_query(language, topic, min_stars, "help-wanted-issues:>0")

    # Step 2: Compute cache key from the primary query
    query_hash = hashlib.sha256(q1.encode()).hexdigest()[:16]

    # Step 3: Check discover cache
    repos: list[dict] = []
    used_cache = False
    if not no_cache:
        cached = get_discover_cache(query_hash)
        if cached is not None:
            repos = cached.get("repos", [])
            _log.debug("Discover cache hit for hash %s (%d repos)", query_hash, len(repos))
            used_cache = True

    # Steps 4-5: Search if cache miss
    if not used_cache:
        _console.print("[dim]Searching GitHub for contribution-friendly repos...[/dim]")

        # Q1: good-first-issues
        try:
            q1_response = client.search_repos(q1, per_page=30)
            q1_items = q1_response.get("items", [])
        except GiveBackError as exc:
            _log.warning("Q1 search failed: %s", exc)
            q1_items = []

        for item in q1_items:
            item["_from_gfi_query"] = True
        repos = list(q1_items)

        # Q2: help-wanted if Q1 didn't return enough headroom
        headroom = limit * 3
        if len(repos) < headroom:
            _log.debug("Q1 returned %d repos (need %d headroom), running Q2", len(repos), headroom)
            try:
                q2_response = client.search_repos(q2, per_page=30)
                q2_items = q2_response.get("items", [])
            except GiveBackError as exc:
                _log.warning("Q2 search failed: %s", exc)
                q2_items = []

            # Deduplicate by full_name
            seen = {r.get("full_name") for r in repos}
            for item in q2_items:
                if item.get("full_name") not in seen:
                    item["_from_hw_query"] = True
                    repos.append(item)
                    seen.add(item.get("full_name"))

    total_searched = len(repos)

    # Step 6: Rank
    repos = rank_repos(repos)

    # Step 7: Filter out already-assessed repos if requested
    filtered_count = 0
    if exclude_assessed:
        pre_filter = len(repos)
        repos = [
            r
            for r in repos
            if get_cached_assessment(
                r.get("full_name", "/").split("/")[0],
                r.get("full_name", "/").split("/", 1)[-1],
            )
            is None
        ]
        filtered_count = pre_filter - len(repos)

    # Step 8: Take top `limit`
    repos = repos[:limit]

    # Step 9: Check assessment cache for each, queue unknowns
    results: list[DiscoverResult] = []
    assess_queue: list[DiscoverResult] = []
    cache_hits = 0

    for repo_dict in repos:
        result = _repo_dict_to_result(repo_dict)

        cached_assessment = get_cached_assessment(result.owner, result.repo)
        if cached_assessment is not None:
            try:
                assessment, _ = reconstruct_assessment(cached_assessment, result.owner, result.repo)
                result.tier = assessment.overall_tier
                result.from_cache = True
                cache_hits += 1
            except ValueError:
                _log.debug("Failed to reconstruct cached assessment for %s/%s", result.owner, result.repo)
                assess_queue.append(result)
        else:
            assess_queue.append(result)

        results.append(result)

    # Step 10: Batch-assess unknowns
    assessed_count = 0
    signal_names = [s.name for s in ALL_SIGNALS]

    for batch_start in range(0, len(assess_queue), batch_size):
        batch = assess_queue[batch_start : batch_start + batch_size]
        budget_needed = len(batch) * _WORST_CASE_CALLS_PER_REPO

        if not client.has_rate_budget(budget_needed):
            _console.print(
                f"[yellow]Rate limit low — stopping assessment after {assessed_count} repos "
                f"({len(assess_queue) - batch_start} remaining).[/yellow]"
            )
            for remaining in assess_queue[batch_start:]:
                remaining.skip_reason = "Skipped — rate limit too low for assessment"
            break

        for result in batch:
            slug = f"{result.owner}/{result.repo}"
            _console.print(f"  [dim]Assessing {slug}...[/dim]")

            try:
                assessment = run_assessment(client, result.owner, result.repo)
                result.tier = assessment.overall_tier
                save_assessment(assessment, signal_names)
                assessed_count += 1
            except GiveBackError as exc:
                _log.warning("Assessment failed for %s: %s", slug, exc)
                result.skip_reason = f"Assessment failed: {exc}"

    # Step 11: Save discover cache (search metadata, not assessments)
    if not used_cache:
        # Strip internal keys before caching
        cache_repos = []
        for r in repos:
            cleaned = {k: v for k, v in r.items() if not k.startswith("_")}
            cache_repos.append(cleaned)
        save_discover_cache(query_hash, q1, cache_repos)

    # Step 12: Build and return summary
    return DiscoverSummary(
        query=q1,
        total_searched=total_searched,
        results=results,
        filtered_count=filtered_count,
        assessed_count=assessed_count,
        cache_hits=cache_hits,
    )
