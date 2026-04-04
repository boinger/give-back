"""CLI command: sniff."""

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
from give_back.output import print_sniff, print_sniff_json


@click.command()
@click.argument("repo")
@click.argument("issue_number", type=int)
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed file assessment data.")
def sniff(repo: str, issue_number: int, json_output: bool, verbose: bool) -> None:
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
