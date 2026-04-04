"""CLI commands: skip and unskip."""

from __future__ import annotations

import sys

import click

from give_back.cli._shared import _parse_repo
from give_back.console import stderr_console as _console
from give_back.state import add_to_skip_list, remove_from_skip_list


@click.command()
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
    try:
        add_to_skip_list(slug)
    except PermissionError:
        _console.print("[yellow]Warning:[/yellow] Cannot write state file.")
        return
    _console.print(f"Added {slug} to skip list.")


@click.command()
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
    try:
        remove_from_skip_list(slug)
    except PermissionError:
        _console.print("[yellow]Warning:[/yellow] Cannot write state file.")
        return
    _console.print(f"Removed {slug} from skip list.")
