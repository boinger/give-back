"""Submit output: PR creation result display + JSON."""

from __future__ import annotations

import json

from give_back.output._shared import _console
from give_back.submit import SubmitResult


def print_submit_success(result: SubmitResult) -> None:
    """Print submission result to the terminal."""
    if result.success:
        _console.print(f"  [green]PR created:[/green] {result.pr_url}")
    else:
        _console.print(f"  [red]Error:[/red] {result.error}")


def print_submit_json(result: SubmitResult) -> None:
    """Print submission result as JSON to stdout."""
    data = {
        "pr_url": result.pr_url,
        "pr_number": result.pr_number,
        "error": result.error,
        "success": result.success,
    }
    print(json.dumps(data, indent=2))
