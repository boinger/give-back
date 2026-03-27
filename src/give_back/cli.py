"""CLI entry point for give-back."""

from __future__ import annotations

import base64
import re
import sys
from datetime import datetime, timezone

import click
from rich.console import Console

from give_back import __version__
from give_back.auth import resolve_token
from give_back.exceptions import (
    AuthenticationError,
    GiveBackError,
    GraphQLError,
    RateLimitError,
    RepoNotFoundError,
    StateCorruptError,
)
from give_back.github_client import GitHubClient
from give_back.graphql.queries import VIABILITY_QUERY
from give_back.models import Assessment, RepoData, SignalWeight, Tier
from give_back.output import print_assessment, print_assessment_json, print_cached_notice, print_sniff, print_sniff_json
from give_back.scoring import compute_tier
from give_back.signals import ALL_SIGNALS
from give_back.state import get_cached_assessment, save_assessment

_console = Console(stderr=True)

# Matches owner/repo or https://github.com/owner/repo (with optional trailing slash/path)
_GITHUB_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$")
_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


def _parse_repo(repo: str) -> tuple[str, str]:
    """Parse a repo argument into (owner, repo) tuple.

    Accepts 'owner/repo' or 'https://github.com/owner/repo'.
    """
    # Try URL first
    m = _GITHUB_URL_RE.match(repo)
    if m:
        return m.group(1), m.group(2)

    # Try slug
    if _SLUG_RE.match(repo):
        owner, name = repo.split("/", 1)
        return owner, name

    raise click.BadParameter(
        f"Invalid repository: '{repo}'. Use 'owner/repo' or a GitHub URL.",
        param_hint="'REPO'",
    )


def _fetch_repo_data(client: GitHubClient, owner: str, repo: str, verbose: bool) -> RepoData:
    """Fetch all data needed for signal evaluation (4 API calls)."""
    if verbose:
        _console.print(f"  [dim]Fetching GraphQL data for {owner}/{repo}...[/dim]")

    # 1. GraphQL: repo metadata + PRs
    graphql_data = client.graphql(VIABILITY_QUERY, {"owner": owner, "repo": repo})

    if verbose:
        remaining = client._rate_remaining
        _console.print(f"  [dim]Rate limit remaining: {remaining}[/dim]")

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


@click.group()
@click.version_option(version=__version__, prog_name="give-back")
def cli() -> None:
    """Evaluate whether an open-source project is viable for outside contributions."""


@cli.command()
@click.argument("repo")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--no-cache", is_flag=True, help="Skip cached results, force fresh API calls.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed signal data and API call info.")
def assess(repo: str, json_output: bool, no_cache: bool, verbose: bool) -> None:
    """Assess a GitHub repository's viability for outside contributions.

    REPO can be 'owner/repo' or a full GitHub URL.
    """
    # Parse repo argument
    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    # Check cache (unless --no-cache)
    if not no_cache:
        cached = get_cached_assessment(owner, repo_name)
        if cached is not None:
            if verbose:
                print_cached_notice(owner, repo_name, cached.get("timestamp", "unknown"))
                _console.print("  [dim]Cache hit — use --no-cache to force fresh API calls[/dim]")
            # For now, just note the cache hit and proceed with fresh data
            # Full cache display would reconstruct the Assessment from cached data
            # TODO: reconstruct and display cached assessment without API calls

    # Resolve auth
    token = resolve_token()

    # Fetch data
    try:
        with GitHubClient(token=token) as client:
            data = _fetch_repo_data(client, owner, repo_name, verbose)
    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except GraphQLError as exc:
        _console.print(f"[red]Error:[/red] GitHub API error: {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # Evaluate signals
    signal_results: list[tuple[SignalWeight, object]] = []
    successful_results = []

    for signal_def in ALL_SIGNALS:
        try:
            result = signal_def.func(data)
            signal_results.append((signal_def.weight, result))
            successful_results.append(result)
        except Exception:
            signal_results.append((signal_def.weight, None))
            # Create a placeholder result for display
            from give_back.models import SignalResult

            successful_results.append(SignalResult(score=0.0, tier=Tier.RED, summary="N/A — evaluation failed"))

    # Score
    tier, gate_passed, incomplete = compute_tier(signal_results)

    # Build assessment
    now = datetime.now(timezone.utc).isoformat()
    assessment = Assessment(
        owner=owner,
        repo=repo_name,
        overall_tier=tier,
        signals=successful_results,
        gate_passed=gate_passed,
        incomplete=incomplete,
        timestamp=now,
    )

    # Save to state
    try:
        save_assessment(assessment)
    except PermissionError:
        _console.print("[yellow]Warning:[/yellow] Cannot write state file. Continuing without cache.")
    except StateCorruptError:
        _console.print("[yellow]Warning:[/yellow] State file corrupted. Backed up and starting fresh.")
        from give_back.state import _empty_state, save_state

        try:
            save_state(_empty_state())
            save_assessment(assessment)
        except PermissionError:
            pass

    # Output
    signal_names = [s.name for s in ALL_SIGNALS]
    signal_weights = [s.weight for s in ALL_SIGNALS]

    if json_output:
        print_assessment_json(assessment, signal_names)
    else:
        print_assessment(assessment, signal_names, signal_weights, verbose=verbose)

    # Exit codes: 0 = success, 1 = gate fail, 2 = incomplete (HIGH/GATE signal errored)
    if not gate_passed:
        sys.exit(1)
    if incomplete:
        sys.exit(2)


@cli.command()
@click.argument("repo")
@click.argument("issue_number", type=int)
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
def sniff(repo: str, issue_number: int, json_output: bool) -> None:
    """Assess code quality for files referenced in a GitHub issue.

    REPO can be 'owner/repo' or a full GitHub URL. ISSUE_NUMBER is the issue to inspect.
    """
    from give_back.sniff.assess import assess_issue

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            result = assess_issue(client, owner, repo_name, issue_number)
    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Issue #{issue_number} not found in {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if json_output:
        print_sniff_json(result)
    else:
        print_sniff(result)
