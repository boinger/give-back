"""Triage output: ranked issue table + JSON."""

from __future__ import annotations

import json

from rich.table import Table

from give_back.output._shared import _console
from give_back.triage.models import Competition, IssueCandidate

_COMPETITION_COLORS = {
    Competition.NONE: "green",
    Competition.LOW: "yellow",
    Competition.HIGH: "red",
}


def print_triage(candidates: list[IssueCandidate], owner: str, repo: str, verbose: bool = False) -> None:
    """Print a ranked triage table to the terminal."""
    _console.print()
    _console.print(f"  Found [bold]{len(candidates)}[/bold] candidate issues for {owner}/{repo}")
    _console.print()

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Issue", justify="right", min_width=6)
    table.add_column("Scope", justify="center", min_width=5)
    table.add_column("Clarity", justify="center", min_width=7)
    table.add_column("Competition", justify="center", min_width=11)
    table.add_column("Title", min_width=40)

    for i, c in enumerate(candidates, 1):
        comp_color = _COMPETITION_COLORS.get(c.competition, "white")
        comp_text = c.competition.value
        if verbose and c.competition_detail:
            comp_text += f"\n[dim]({c.competition_detail})[/dim]"

        title = c.title
        if c.priority_labels:
            label_str = ", ".join(c.priority_labels)
            title += f"\n[dim][{label_str}][/dim]"
        if verbose and c.staleness_risk:
            title += "\n[yellow](stale — >1yr old, no recent activity)[/yellow]"

        table.add_row(
            str(i),
            f"#{c.number}",
            c.scope.value,
            c.clarity.value,
            f"[{comp_color}]{comp_text}[/{comp_color}]",
            title,
        )

    _console.print(table)
    _console.print()
    _console.print(f"  Use [bold]give-back sniff {owner}/{repo} <ISSUE_NUMBER>[/bold] to inspect code quality.")
    _console.print()


def print_triage_json(candidates: list[IssueCandidate], owner: str, repo: str) -> None:
    """Print triage results as JSON to stdout."""
    data = {
        "owner": owner,
        "repo": repo,
        "candidates": [
            {
                "number": c.number,
                "title": c.title,
                "url": c.url,
                "labels": c.labels,
                "priority_labels": c.priority_labels,
                "scope": c.scope.value,
                "clarity": c.clarity.value,
                "competition": c.competition.value,
                "competition_detail": c.competition_detail,
                "staleness_risk": c.staleness_risk,
                "comment_count": c.comment_count,
            }
            for c in candidates
        ],
    }
    print(json.dumps(data, indent=2))
