"""CLI command: calibrate."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    RateLimitError,
    RepoNotFoundError,
)
from give_back.github_client import GitHubClient


@click.command()
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
