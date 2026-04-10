"""CLI command: discover."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    GiveBackError,
    RateLimitError,
)
from give_back.github_client import GitHubClient


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
    verbose: bool,
) -> None:
    """Find open-source repos worth contributing to.

    Searches GitHub for repos matching your filters, recent activity, and
    viable contribution signals. By default, results are limited to repos
    with open "good first issue" or "help wanted" labels. Use --any-issues
    to bypass this label gate (useful for mature projects that use custom
    label taxonomies).

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
            )

            if json_output:
                print_discover_json(summary)
            else:
                print_discover(summary, verbose=verbose, limit=limit)

                # Interactive loop — assess additional batches
                if interactive and not json_output and sys.stdin.isatty():
                    shown_count = len(summary.results)
                    remaining = summary.total_searched - shown_count
                    while remaining > 0:
                        try:
                            if not click.confirm("  Assess next batch?", default=True):
                                break
                        except (EOFError, KeyboardInterrupt):
                            _console.print()
                            break

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
                        )
                        # Only display the new repos (skip already-shown ones)
                        new_only = new_summary.slice_results(
                            shown_count,
                            prior_assessed=summary.assessed_count,
                            prior_cache_hits=summary.cache_hits,
                        )
                        if new_only.results:
                            print_discover(new_only, verbose=verbose, limit=limit)
                        else:
                            _console.print("  [dim]No more repos to assess.[/dim]")
                            break
                        shown_count = len(new_summary.results)
                        remaining = new_summary.total_searched - shown_count
                        summary = new_summary

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except GiveBackError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
