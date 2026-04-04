"""CLI command: conventions."""

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
from give_back.output import print_conventions, print_conventions_json


@click.command()
@click.argument("repo")
@click.option("--issue", type=int, default=None, help="Issue number to include context in the brief.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON.")
@click.option("--keep-clone", is_flag=True, help="Keep the cloned repo after scanning.")
@click.option("--verbose", "-v", is_flag=True, help="Show detection details.")
def conventions(repo: str, issue: int | None, json_output: bool, keep_clone: bool, verbose: bool) -> None:
    """Scan a repository's contribution conventions and produce a brief.

    REPO can be 'owner/repo' or a full GitHub URL.
    Clones the repo to a temp directory, analyzes commit messages, PR templates,
    branch naming, test frameworks, merge strategy, code style, and DCO requirements.
    """
    from give_back.conventions.brief import scan_conventions
    from give_back.conventions.clone import CloneError

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            if verbose:
                _console.print(f"  [dim]Scanning conventions for {owner}/{repo_name}...[/dim]")

            brief = scan_conventions(
                client,
                owner,
                repo_name,
                issue_number=issue,
                keep_clone=keep_clone,
                verbose=verbose,
            )

            if json_output:
                print_conventions_json(brief)
            else:
                print_conventions(brief, verbose=verbose)

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except CloneError as exc:
        _console.print(f"[red]Error:[/red] Failed to clone repository: {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
