"""CLI command: assess."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.cli._shared import _parse_repo
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    GiveBackError,
    GraphQLError,
    RateLimitError,
    RepoNotFoundError,
    StateCorruptError,
)
from give_back.github_client import GitHubClient
from give_back.output import (
    print_assessment,
    print_assessment_json,
    print_cached_notice,
)
from give_back.signals import ALL_SIGNALS
from give_back.state import get_cached_assessment, save_assessment


@click.command()
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
            from give_back.state import reconstruct_assessment

            print_cached_notice(owner, repo_name, cached.get("timestamp", "unknown"))
            if verbose:
                _console.print("  [dim]Cache hit — use --no-cache to force fresh API calls[/dim]")

            try:
                assessment, cached_names = reconstruct_assessment(cached, owner, repo_name)
            except ValueError:
                _console.print("  [dim]Cache data invalid, fetching fresh...[/dim]")
            else:
                # Use cached names if available, fall back to registry for old caches
                signal_names = cached_names if any(cached_names) else [s.name for s in ALL_SIGNALS]
                signal_weights = [s.weight for s in ALL_SIGNALS]

                if json_output:
                    print_assessment_json(assessment, signal_names)
                else:
                    print_assessment(assessment, signal_names, signal_weights, verbose=verbose)

                if not deps:
                    if not assessment.gate_passed:
                        sys.exit(3)
                    if assessment.incomplete:
                        sys.exit(2)
                    return

                # Fall through to deps handling below with fresh client
                # (deps always needs API calls)

    # Resolve auth
    token = resolve_token()

    # Fetch data and run assessment
    try:
        with GitHubClient(token=token) as client:
            assessment = run_assessment(client, owner, repo_name, verbose)

            # Output
            signal_names = [s.name for s in ALL_SIGNALS]

            # Save to state (with signal names for stable reconstruction)
            try:
                save_assessment(assessment, signal_names=signal_names)
            except PermissionError:
                _console.print("[yellow]Warning:[/yellow] Cannot write state file. Continuing without cache.")
            except StateCorruptError:
                _console.print("[yellow]Warning:[/yellow] State file corrupted. Backed up and starting fresh.")
                from give_back.state import _empty_state, save_state

                try:
                    save_state(_empty_state())
                    save_assessment(assessment, signal_names=signal_names)
                except PermissionError:
                    pass
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

    # Exit codes: 0 = success, 1 = fatal error, 2 = incomplete, 3 = gate fail (RED)
    if not assessment.gate_passed:
        sys.exit(3)
    if assessment.incomplete:
        sys.exit(2)
