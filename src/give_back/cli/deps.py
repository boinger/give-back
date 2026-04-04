"""CLI command: deps."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.cli._shared import _parse_repo
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    GiveBackError,
    RateLimitError,
    RepoNotFoundError,
)
from give_back.github_client import GitHubClient
from give_back.output import print_deps, print_deps_json


@click.command()
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
