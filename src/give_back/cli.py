"""CLI entry point for give-back."""

from __future__ import annotations

import base64
import re
import sys

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
from give_back.models import RepoData
from give_back.output import print_assessment, print_assessment_json, print_cached_notice, print_sniff, print_sniff_json
from give_back.signals import ALL_SIGNALS
from give_back.state import add_to_skip_list, get_cached_assessment, remove_from_skip_list, save_assessment

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
@click.option("--deps", is_flag=True, help="Also assess the project's dependencies for contribution opportunities.")
@click.option("--limit", default=20, help="Maximum number of dependencies to assess (with --deps).")
def assess(repo: str, json_output: bool, no_cache: bool, verbose: bool, deps: bool, limit: int) -> None:
    """Assess a GitHub repository's viability for outside contributions.

    REPO can be 'owner/repo' or a full GitHub URL.
    """
    from give_back.assess import run_assessment

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

    # Fetch data and run assessment
    try:
        with GitHubClient(token=token) as client:
            assessment = run_assessment(client, owner, repo_name, verbose)

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

            # --deps: also walk dependencies
            if deps:
                if not client.authenticated:
                    _console.print(
                        "\n[red]Error:[/red] --deps requires authentication. Set GITHUB_TOKEN or run `gh auth login`."
                    )
                    sys.exit(1)

                from give_back.deps.walker import walk_deps
                from give_back.output import print_deps, print_deps_json

                try:
                    walk_result = walk_deps(client, owner, repo_name, limit=limit, verbose=verbose)
                    if json_output:
                        print_deps_json(walk_result)
                    else:
                        print_deps(walk_result, verbose=verbose)
                except GiveBackError as exc:
                    _console.print(f"\n[yellow]Warning:[/yellow] Dependency walking failed: {exc}")

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

    # Exit codes: 0 = success, 1 = gate fail, 2 = incomplete (HIGH/GATE signal errored)
    if not assessment.gate_passed:
        sys.exit(1)
    if assessment.incomplete:
        sys.exit(2)


@cli.command()
@click.argument("repo")
@click.option("--label", default=None, help="Filter issues by label (e.g., 'good first issue').")
@click.option("--limit", default=20, help="Maximum number of candidates to show.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--verbose", "-v", is_flag=True, help="Show competition details and staleness info.")
def triage(repo: str, label: str | None, limit: int, json_output: bool, verbose: bool) -> None:
    """Find good starter issues for contribution.

    REPO can be 'owner/repo' or a full GitHub URL.
    Fetches open issues, checks for competing work, and ranks by contribution-friendliness.
    """
    from give_back.triage.compete import check_competition
    from give_back.triage.fetch import fetch_issues
    from give_back.triage.rank import rank_candidates

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            if verbose:
                _console.print(f"  [dim]Fetching open issues for {owner}/{repo_name}...[/dim]")

            candidates = fetch_issues(client, owner, repo_name, label_filter=label, limit=limit)

            if not candidates:
                _console.print(f"\n  No candidate issues found for {owner}/{repo_name}.")
                if label:
                    _console.print("  [dim]Try without --label, or use a different label.[/dim]")
                return

            if verbose:
                _console.print(f"  [dim]Checking for competing work on {len(candidates)} candidates...[/dim]")

            check_competition(client, owner, repo_name, candidates)
            ranked = rank_candidates(candidates, limit=limit)

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    from give_back.output import print_triage, print_triage_json

    if json_output:
        print_triage_json(ranked, owner, repo_name)
    else:
        print_triage(ranked, owner, repo_name, verbose=verbose)


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


@cli.command()
@click.argument("repo")
@click.option("--limit", default=20, help="Maximum number of dependencies to assess.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress and signal data.")
def deps(repo: str, limit: int, json_output: bool, verbose: bool) -> None:
    """Walk a project's dependencies and assess each for contribution viability.

    REPO can be 'owner/repo' or a full GitHub URL.
    Parses the project's manifest (go.mod, pyproject.toml, requirements.txt),
    resolves each dependency to a GitHub repo, and runs viability assessment.
    """
    from give_back.deps.walker import walk_deps
    from give_back.output import print_deps, print_deps_json

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()
    if token is None:
        _console.print("[red]Error:[/red] `deps` requires authentication. Set GITHUB_TOKEN or run `gh auth login`.")
        sys.exit(1)

    try:
        with GitHubClient(token=token) as client:
            walk_result = walk_deps(client, owner, repo_name, limit=limit, verbose=verbose)
    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except GiveBackError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if json_output:
        print_deps_json(walk_result)
    else:
        print_deps(walk_result, verbose=verbose)


@cli.command()
@click.argument("calibration_file", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed signal data for mismatches.")
def calibrate(calibration_file: str, verbose: bool) -> None:
    """Run scoring threshold calibration against a set of repos with known tiers.

    CALIBRATION_FILE is a YAML or JSON file mapping repos to expected tiers.

    YAML format:

        - repo: pallets/flask

          expected: green

    JSON format:

        [{"repo": "pallets/flask", "expected": "green"}]
    """
    from give_back.calibrate import load_calibration_file, run_calibration
    from give_back.output import print_calibration

    try:
        entries = load_calibration_file(calibration_file)
    except (ValueError, KeyError) as exc:
        _console.print(f"[red]Error:[/red] Invalid calibration file: {exc}")
        sys.exit(1)

    if not entries:
        _console.print("[red]Error:[/red] Calibration file contains no entries.")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            _console.print(f"  Running calibration on {len(entries)} repos...")
            result = run_calibration(client, entries, verbose=verbose)

        print_calibration(result, verbose=verbose)

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError as exc:
        _console.print(f"[red]Error:[/red] Repository not found: {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@cli.command()
@click.argument("repo")
def skip(repo: str) -> None:
    """Add a repository to the skip list (excluded from dep-walking results).

    REPO should be 'owner/repo'.
    """
    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    slug = f"{owner}/{repo_name}"
    add_to_skip_list(slug)
    _console.print(f"Added {slug} to skip list.")


@cli.command()
@click.argument("repo")
def unskip(repo: str) -> None:
    """Remove a repository from the skip list.

    REPO should be 'owner/repo'.
    """
    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    slug = f"{owner}/{repo_name}"
    remove_from_skip_list(slug)
    _console.print(f"Removed {slug} from skip list.")
