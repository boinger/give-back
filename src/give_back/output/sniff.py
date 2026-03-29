"""Sniff output: file quality assessment + JSON."""

from __future__ import annotations

import json

from give_back.output._shared import _console
from give_back.sniff.models import SniffResult

_VERDICT_COLORS = {
    "LOOKS_GOOD": "green",
    "MESSY": "yellow",
    "DUMPSTER_FIRE": "red",
}

_VERDICT_LABELS = {
    "LOOKS_GOOD": "LOOKS GOOD",
    "MESSY": "MESSY",
    "DUMPSTER_FIRE": "DUMPSTER FIRE",
}


def print_sniff(result: SniffResult) -> None:
    """Print a formatted sniff assessment to the terminal."""
    color = _VERDICT_COLORS.get(result.verdict, "white")
    verdict_label = _VERDICT_LABELS.get(result.verdict, result.verdict)

    _console.print()
    _console.print(f"  Issue #{result.issue_number}: [bold]{result.issue_title}[/bold]")
    _console.print()

    if result.files:
        _console.print("  Referenced files:")
        for fa in result.files:
            test_status = "has tests" if fa.has_tests else "[yellow]no test file[/yellow]"
            _console.print(f"    {fa.path}  — {fa.lines} lines, {fa.recent_commits} recent commits, {test_status}")
            if fa.concerns:
                for concern in fa.concerns:
                    _console.print(f"      [dim]- {concern}[/dim]")
        _console.print()
    else:
        _console.print("  [dim]No source files referenced in issue.[/dim]")
        _console.print()

    _console.print(f"  Assessment: [{color} bold]{verdict_label}[/{color} bold]")
    _console.print(f"    {result.summary}")
    _console.print()

    if result.verdict == "LOOKS_GOOD":
        _console.print("  Next: `give-back conventions <repo>` to understand contribution style.")
    elif result.verdict == "MESSY":
        _console.print("  [yellow]Proceed with caution — or try another issue.[/yellow]")
    else:
        _console.print("  [red]Recommend skipping this issue — try another one.[/red]")
    _console.print()


def print_sniff_json(result: SniffResult) -> None:
    """Print sniff assessment as JSON to stdout."""
    data = {
        "issue_number": result.issue_number,
        "issue_title": result.issue_title,
        "verdict": result.verdict,
        "summary": result.summary,
        "files": [
            {
                "path": fa.path,
                "lines": fa.lines,
                "recent_commits": fa.recent_commits,
                "has_tests": fa.has_tests,
                "max_indent_depth": fa.max_indent_depth,
                "concerns": fa.concerns,
            }
            for fa in result.files
        ],
    }
    print(json.dumps(data, indent=2))
