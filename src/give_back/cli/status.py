"""CLI command: status."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    RateLimitError,
)
from give_back.github_client import GitHubClient


@click.command()
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show archived contributions.")
@click.option("--dir", "workspace_dir", default=None, type=click.Path(), help="Scan alternate workspace root.")
def status(json_output: bool, verbose: bool, workspace_dir: str | None) -> None:
    """Check the status of your open contributions across repos.

    Scans your give-back workspaces and checks GitHub for PR status
    (open, reviewed, merged, closed).

    Examples:

        give-back status

        give-back status --verbose

        give-back status --dir ~/my-workspaces
    """
    from pathlib import Path

    from give_back.output import print_status, print_status_json
    from give_back.status import check_contributions

    token = resolve_token()
    dir_override = Path(workspace_dir) if workspace_dir else None

    client: GitHubClient | None = None
    try:
        if token:
            client = GitHubClient(token=token)
        else:
            _console.print("[yellow]No auth token — showing local state only.[/yellow]")

        contributions, archived = check_contributions(client, workspace_dir=dir_override)
    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    finally:
        if client is not None:
            client.close()

    if json_output:
        print_status_json(contributions, archived)
    else:
        print_status(contributions, archived, verbose=verbose)
