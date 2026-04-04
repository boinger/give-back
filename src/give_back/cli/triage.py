"""CLI command: triage."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.cli._shared import _parse_repo
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    RateLimitError,
    RepoNotFoundError,
)
from give_back.github_client import GitHubClient


@click.command()
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
