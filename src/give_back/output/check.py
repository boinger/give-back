"""Prepare + check output: guardrail results + prepare JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from give_back.conventions.models import ContributionBrief
from give_back.output._shared import _console

if TYPE_CHECKING:
    from give_back.guardrails import GuardrailResult


def print_check_results(
    results: list[GuardrailResult],
    owner: str,
    repo: str,
    issue_number: int | None,
    verbose: bool = False,
) -> None:
    """Print guardrail check results as a checklist.

    Uses rich markup: green check for pass, red X for BLOCK failures,
    yellow warning for WARN failures.
    """
    from give_back.guardrails import Severity

    issue_str = f" #{issue_number}" if issue_number else ""
    _console.print()
    _console.print(f"  [bold]Pre-flight checks for {owner}/{repo}{issue_str}:[/bold]")
    _console.print()

    blocks = 0
    warns = 0
    infos = 0

    for r in results:
        if r.passed:
            _console.print(f"    [green]\u2713[/green] {r.message}")
        elif r.severity == Severity.BLOCK:
            _console.print(f"    [red]\u2717[/red] {r.message}")
            blocks += 1
        elif r.severity == Severity.WARN:
            _console.print(f"    [yellow]\u26a0[/yellow] {r.message}")
            warns += 1
        else:
            _console.print(f"    [dim]\u2139[/dim] {r.message}")
            infos += 1

        if verbose and not r.passed and r.details:
            for key, value in r.details.items():
                _console.print(f"        [dim]{key}: {value}[/dim]")

    _console.print()

    total_issues = blocks + warns
    if total_issues == 0:
        _console.print("  [green]All checks passed.[/green]")
    else:
        parts = []
        if blocks:
            parts.append(f"{blocks} blocker(s)")
        if warns:
            parts.append(f"{warns} warning(s)")
        _console.print(f"  {', '.join(parts)} to address before pushing.")

    _console.print()


def print_prepare_json(
    workspace_path: Path,
    branch_name: str,
    brief: ContributionBrief,
    action_plan_text: str,
) -> None:
    """Print prepare results as JSON to stdout."""
    data = {
        "workspace_path": str(workspace_path),
        "branch_name": branch_name,
        "upstream_owner": brief.owner,
        "repo": brief.repo,
        "issue_number": brief.issue_number,
        "issue_title": brief.issue_title,
        "default_branch": brief.default_branch,
        "action_plan": action_plan_text,
    }
    print(json.dumps(data, indent=2))
