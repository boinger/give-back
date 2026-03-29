"""Reusable viability assessment logic.

Fetches data, evaluates signals, computes tier, and returns an Assessment.
Used by both the `assess` CLI command and the dependency walker.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timedelta, timezone

from give_back.console import stderr_console as _console
from give_back.exceptions import GiveBackError, RateLimitError, RepoNotFoundError
from give_back.github_client import GitHubClient
from give_back.graphql.queries import PULL_REQUESTS_PAGE_QUERY, VIABILITY_QUERY
from give_back.license_eval import LicenseEvaluation, evaluate_license_text
from give_back.models import Assessment, RepoData, SignalResult, Tier
from give_back.reconcile import reconcile_merge_rate, should_reconcile
from give_back.scoring import compute_tier
from give_back.signals import ALL_SIGNALS

_log = logging.getLogger(__name__)

# License file names to try, in order of preference
_LICENSE_FILENAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")

# PR pagination: stop after this many pages to bound API usage
_MAX_PR_PAGES = 10  # 10 pages × 50 PRs = 500 PRs max
_MONTHS_WINDOW = 12


def _fetch_prs_paginated(
    client: GitHubClient,
    owner: str,
    repo: str,
    verbose: bool,
) -> list[dict]:
    """Fetch PRs with cursor-based pagination, stopping at the 12-month boundary.

    Uses ``last: 50`` (newest first) and pages backwards in time via ``before`` cursor.
    Stops when: all PRs on a page are older than the signal window, or max pages reached.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_MONTHS_WINDOW * 30)
    all_prs: list[dict] = []
    cursor: str | None = None

    for page in range(_MAX_PR_PAGES):
        variables: dict = {"owner": owner, "repo": repo}
        if cursor:
            variables["cursor"] = cursor

        try:
            data = client.graphql(PULL_REQUESTS_PAGE_QUERY, variables)
        except GiveBackError:
            break  # API error — return what we have

        pr_data = (data.get("repository") or {}).get("pullRequests") or {}
        nodes = pr_data.get("nodes") or []
        page_info = pr_data.get("pageInfo") or {}

        if not nodes:
            break

        all_prs.extend(nodes)

        # Check if the oldest PR on this page is beyond our window
        oldest_pr = nodes[0]  # last:50 returns oldest-first within the page
        oldest_date_str = oldest_pr.get("createdAt") or oldest_pr.get("closedAt") or ""
        if oldest_date_str:
            try:
                oldest_date = datetime.fromisoformat(oldest_date_str.replace("Z", "+00:00"))
                if oldest_date < cutoff:
                    if verbose:
                        _console.print(f"  [dim]Reached 12-month boundary at page {page + 1}[/dim]")
                    break
            except ValueError:
                pass

        # Check if there are more pages
        if not page_info.get("hasPreviousPage"):
            break
        cursor = page_info.get("startCursor")
        if not cursor:
            break

    return all_prs


def _needs_ai_search(contributing_text: str | None) -> bool:
    """Check if the AI policy signal needs the search API (CONTRIBUTING.md is silent on AI)."""
    if not contributing_text:
        return True

    text_lower = contributing_text.lower()
    # If CONTRIBUTING.md has explicit AI policy (ban, welcome, or disclosure), no search needed
    ban_keywords = [
        "no ai",
        "no llm",
        "no copilot",
        "no chatgpt",
        "ai-generated code is not accepted",
        "machine-generated",
    ]
    welcome_keywords = ["ai-assisted welcome", "copilot encouraged", "ai contributions accepted"]
    disclosure_keywords = ["disclose", "label ai", "ai-assisted must be noted"]

    for kw in ban_keywords + welcome_keywords + disclosure_keywords:
        if kw in text_lower:
            return False

    return True


def _fetch_repo_data(client: GitHubClient, owner: str, repo: str, verbose: bool) -> RepoData:
    """Fetch all data needed for signal evaluation.

    Makes 1 GraphQL call for repo metadata, then paginates PRs (50 per page)
    until we have enough history to cover the 12-month signal window.
    """
    if verbose:
        _console.print(f"  [dim]Fetching GraphQL data for {owner}/{repo}...[/dim]")

    # 1. GraphQL: repo metadata (no PRs — those are paginated separately)
    graphql_data = client.graphql(VIABILITY_QUERY, {"owner": owner, "repo": repo})

    # 2. Paginate PRs until we have 12 months of history
    if verbose:
        _console.print("  [dim]Fetching pull requests...[/dim]")

    all_prs = _fetch_prs_paginated(client, owner, repo, verbose)
    graphql_data.setdefault("repository", {})["pullRequests"] = {"nodes": all_prs}

    if verbose:
        remaining = client._rate_remaining
        _console.print(f"  [dim]Rate limit remaining: {remaining} ({len(all_prs)} PRs fetched)[/dim]")

    # 2. REST: community profile
    if verbose:
        _console.print("  [dim]Fetching community profile...[/dim]")

    try:
        community = client.rest_get(f"/repos/{owner}/{repo}/community/profile")
    except RepoNotFoundError:
        community = {}

    # 3. REST: CONTRIBUTING.md text (only if community profile found one)
    contributing_text = None
    contributing_info = community.get("files", {}).get("contributing") if community else None
    if contributing_info and contributing_info.get("url"):
        if verbose:
            _console.print("  [dim]Fetching CONTRIBUTING.md content...[/dim]")
        try:
            # The community profile gives us the HTML URL; we need the API URL.
            # Extract the path from html_url: https://github.com/owner/repo/blob/main/.github/CONTRIBUTING.md
            html_url = contributing_info.get("html_url", "")
            # Parse path after /blob/branch/
            path_match = re.search(r"/blob/[^/]+/(.+)$", html_url)
            if path_match:
                file_path = path_match.group(1)
                contents = client.rest_get(f"/repos/{owner}/{repo}/contents/{file_path}")
                if contents.get("encoding") == "base64" and contents.get("content"):
                    contributing_text = base64.b64decode(contents["content"]).decode("utf-8", errors="replace")
        except (RepoNotFoundError, GiveBackError, KeyError):
            pass  # Fall through with contributing_text = None

    # 4. REST: search for AI policy keywords (only if CONTRIBUTING.md doesn't have explicit policy)
    search = {}
    if _needs_ai_search(contributing_text):
        if verbose:
            _console.print("  [dim]Searching for AI policy discussions...[/dim]")
        try:
            search = client.search(f'repo:{owner}/{repo} "AI" OR "LLM" OR "copilot" OR "ChatGPT" OR "generated code"')
        except (RateLimitError, GiveBackError):
            search = {}

    return RepoData(
        owner=owner,
        repo=repo,
        graphql=graphql_data,
        community=community,
        contributing_text=contributing_text,
        search=search,
    )


def run_assessment(client: GitHubClient, owner: str, repo: str, verbose: bool = False) -> Assessment:
    """Run the full viability assessment for a single repo.

    Fetches data, evaluates all signals, computes tier, and returns an Assessment.

    Raises:
        RepoNotFoundError: If the repository does not exist.
        GraphQLError: If a GraphQL error occurs.
        RateLimitError: If the rate limit is exceeded.
        GiveBackError: On other API errors.
    """
    data = _fetch_repo_data(client, owner, repo, verbose)

    # Evaluate signals
    signal_results: list[tuple] = []
    successful_results: list[SignalResult] = []

    for signal_def in ALL_SIGNALS:
        try:
            result = signal_def.func(data)
            signal_results.append((signal_def.weight, result))
            successful_results.append(result)
        except GiveBackError:
            signal_results.append((signal_def.weight, None))
            successful_results.append(SignalResult(score=0.0, tier=Tier.RED, summary="N/A — evaluation failed"))
        except Exception as exc:
            _log.warning("Signal %s raised unexpected error: %s", signal_def.name, exc)
            signal_results.append((signal_def.weight, None))
            successful_results.append(SignalResult(score=0.0, tier=Tier.RED, summary="N/A — evaluation failed"))

    # Score (first pass)
    tier, gate_passed, incomplete = compute_tier(signal_results)

    # Bias reconciliation: if PR merge rate looks suspiciously low but other signals
    # are healthy, investigate collaborator role transitions and re-score if warranted.
    signal_names = [s.name for s in ALL_SIGNALS]
    if should_reconcile(signal_results, signal_names):
        # Find the merge rate signal index
        for i, signal_def in enumerate(ALL_SIGNALS):
            if "merge" in signal_def.name.lower() and successful_results[i].score < 0.4:
                adjusted = reconcile_merge_rate(client, owner, repo, successful_results[i], verbose=verbose)
                if adjusted is not None:
                    successful_results[i] = adjusted
                    signal_results[i] = (signal_def.weight, adjusted)
                    # Re-score with adjusted signal
                    tier, gate_passed, incomplete = compute_tier(signal_results)
                break

    # LLM-assisted license classification: if a license signal needs human review,
    # try to fetch the LICENSE file and classify it with an LLM.
    _try_llm_license_classification(client, owner, repo, successful_results, verbose)

    # Build assessment
    now = datetime.now(timezone.utc).isoformat()
    return Assessment(
        owner=owner,
        repo=repo,
        overall_tier=tier,
        signals=successful_results,
        gate_passed=gate_passed,
        incomplete=incomplete,
        timestamp=now,
    )


def _fetch_license_text(client: GitHubClient, owner: str, repo: str) -> str | None:
    """Try to fetch the LICENSE file content from the repository.

    Tries LICENSE, LICENSE.md, LICENSE.txt, COPYING in order.
    Returns the decoded text, or None if not found.
    """
    for filename in _LICENSE_FILENAMES:
        try:
            contents = client.rest_get(f"/repos/{owner}/{repo}/contents/{filename}")
            if contents.get("encoding") == "base64" and contents.get("content"):
                return base64.b64decode(contents["content"]).decode("utf-8", errors="replace")
        except (RepoNotFoundError, GiveBackError):
            continue
    return None


def _try_llm_license_classification(
    client: GitHubClient,
    owner: str,
    repo: str,
    results: list[SignalResult],
    verbose: bool,
) -> None:
    """Post-process: if a license signal needs human review, try LLM classification.

    Mutates the signal result in-place if classification succeeds.
    """
    for result in results:
        if not result.details.get("needs_human"):
            continue

        # Found a license signal that needs review
        if verbose:
            _console.print("  [dim]Fetching LICENSE file for LLM classification...[/dim]")

        license_text = _fetch_license_text(client, owner, repo)
        if license_text is None:
            if verbose:
                _console.print("  [dim]LICENSE file not found, skipping LLM classification.[/dim]")
            return

        if verbose:
            _console.print("  [dim]Sending license text to Claude for classification...[/dim]")

        result_from_llm = evaluate_license_text(license_text)
        if result_from_llm is None:
            if verbose:
                _console.print("  [dim]LLM classification unavailable (no API key or call failed).[/dim]")
            return

        _apply_llm_result(result, result_from_llm)
        if verbose:
            _console.print(
                f"  [dim]LLM says: {result_from_llm.classification} ({result_from_llm.confidence} confidence)[/dim]"
            )
        return  # Only process the first matching signal


def _apply_llm_result(result: SignalResult, llm_result: LicenseEvaluation) -> None:
    """Update a license SignalResult with LLM classification data."""
    license_url = result.details.get("license_url", "")
    llm_summary = f"{llm_result.classification} ({llm_result.summary}, {llm_result.confidence} confidence)"
    result.summary = f"Unrecognized — LLM says: {llm_summary}\n                          verify at {license_url}"
    result.details["llm_classification"] = {
        "classification": llm_result.classification,
        "summary": llm_result.summary,
        "oss_compatible": llm_result.oss_compatible,
        "confidence": llm_result.confidence,
        "details": llm_result.details,
    }
