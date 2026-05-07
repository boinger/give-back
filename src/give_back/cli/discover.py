"""CLI command: discover."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from give_back.auth import resolve_token
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    GiveBackError,
    RateLimitError,
)
from give_back.github_client import GitHubClient

if TYPE_CHECKING:
    from give_back.discover.search import DiscoverSummary


def _run_interactive_discover_loop(
    client: GitHubClient,
    summary: DiscoverSummary,
    *,
    language: str | None,
    topic: str | None,
    min_stars: int,
    limit: int,
    batch_size: int,
    exclude_assessed: bool,
    any_issues: bool,
    auto_fallback: bool,
    verbose: bool,
) -> None:
    """Prompt the user to assess additional batches after the initial discover run."""
    from give_back.discover.search import discover_repos
    from give_back.output import print_discover

    shown_count = len(summary.results) + len(summary.fallback_results)
    remaining = summary.total_searched - shown_count

    while remaining > 0:
        try:
            if not click.confirm("  Assess next batch?", default=True):
                return
        except (EOFError, KeyboardInterrupt):
            _console.print()
            return

        new_limit = shown_count + batch_size
        new_summary = discover_repos(
            client,
            language=language,
            topic=topic,
            min_stars=min_stars,
            limit=new_limit,
            batch_size=batch_size,
            no_cache=False,
            exclude_assessed=exclude_assessed,
            any_issues=any_issues,
            verbose=verbose,
            auto_fallback=auto_fallback,
        )
        new_only = new_summary.slice_results(
            shown_count,
            prior_assessed=summary.assessed_count,
            prior_cache_hits=summary.cache_hits,
        )
        if not (new_only.results or new_only.fallback_results):
            _console.print("  [dim]No more repos to assess.[/dim]")
            return

        print_discover(new_only, verbose=verbose, limit=limit)
        shown_count = len(new_summary.results) + len(new_summary.fallback_results)
        remaining = new_summary.total_searched - shown_count
        summary = new_summary


@click.command()
@click.option("--language", "-l", default=None, help="Filter by primary language (e.g., 'python', 'rust').")
@click.option("--topic", "-t", default=None, help="Filter by topic (e.g., 'kubernetes', 'cli').")
@click.option("--min-stars", default=50, help="Minimum star count.")
@click.option("--limit", default=10, help="Total repos to display (cached + freshly assessed).")
@click.option("--batch-size", default=5, help="Repos to assess per batch.")
@click.option("--interactive", "interactive", is_flag=True, help="Prompt to assess more after each batch.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON.")
@click.option("--no-cache", is_flag=True, help="Skip all caches.")
@click.option("--exclude-assessed", is_flag=True, help="Filter out repos already in assessment cache.")
@click.option("--any-issues", is_flag=True, help="Skip the good-first-issue / help-wanted label gate.")
@click.option(
    "--auto-fallback/--no-auto-fallback",
    default=None,
    help="Auto-search without label gate when results are sparse.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show search queries and viability pre-screen details.")
def discover(
    language: str | None,
    topic: str | None,
    min_stars: int,
    limit: int,
    batch_size: int,
    interactive: bool,
    json_output: bool,
    no_cache: bool,
    exclude_assessed: bool,
    any_issues: bool,
    auto_fallback: bool | None,
    verbose: bool,
) -> None:
    """Find open-source repos worth contributing to.

    Searches GitHub for repos matching your filters, recent activity, and
    viable contribution signals. By default, results are limited to repos
    with open "good first issue" or "help wanted" labels. Use --any-issues
    to bypass this label gate (useful for mature projects that use custom
    label taxonomies).

    When results are sparse, discover automatically searches without the
    label gate and shows additional repos in a second table. Use
    --no-auto-fallback to disable this, or --auto-fallback with --json
    to enable it for machine-readable output.

    Examples:

        give-back discover --language python

        give-back discover --topic kubernetes --min-stars 100

        give-back discover --language rust --limit 5 --interactive

        give-back discover --topic pi-hole --any-issues
    """
    from give_back.discover.search import discover_repos
    from give_back.output import print_discover, print_discover_json

    if not language and not topic:
        _console.print("[red]Error:[/red] Provide at least --language or --topic to search.")
        sys.exit(1)

    # Resolve tri-state: None → True for terminal, False for JSON
    if auto_fallback is None:
        auto_fallback = not json_output

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            summary = discover_repos(
                client,
                language=language,
                topic=topic,
                min_stars=min_stars,
                limit=limit,
                batch_size=batch_size,
                no_cache=no_cache,
                exclude_assessed=exclude_assessed,
                any_issues=any_issues,
                verbose=verbose,
                auto_fallback=auto_fallback,
            )

            if json_output:
                print_discover_json(summary)
            else:
                print_discover(summary, verbose=verbose, limit=limit)

                if interactive and sys.stdin.isatty():
                    _run_interactive_discover_loop(
                        client,
                        summary,
                        language=language,
                        topic=topic,
                        min_stars=min_stars,
                        limit=limit,
                        batch_size=batch_size,
                        exclude_assessed=exclude_assessed,
                        any_issues=any_issues,
                        auto_fallback=auto_fallback,
                        verbose=verbose,
                    )

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except GiveBackError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
