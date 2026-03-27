"""Terminal output formatting for give-back assessments.

Produces a rich table with signal breakdown and a natural-language summary.
"""

from __future__ import annotations

import json

from rich.console import Console
from rich.table import Table

from give_back.models import Assessment, SignalWeight, Tier
from give_back.sniff.models import SniffResult
from give_back.triage.models import Competition, IssueCandidate

_console = Console()

_TIER_COLORS = {
    Tier.GREEN: "green",
    Tier.YELLOW: "yellow",
    Tier.RED: "red",
}

_TIER_LABELS = {
    Tier.GREEN: "GREEN — Viable for outside contributions",
    Tier.YELLOW: "YELLOW — Mixed signals, proceed with caution",
    Tier.RED: "RED — Not viable for outside contributions",
}

_WEIGHT_LABELS = {
    SignalWeight.GATE: "GATE",
    SignalWeight.HIGH: "HIGH",
    SignalWeight.MEDIUM: "MED",
    SignalWeight.LOW: "LOW",
}


def print_assessment(
    assessment: Assessment,
    signal_names: list[str],
    signal_weights: list[SignalWeight],
    verbose: bool = False,
) -> None:
    """Print a formatted assessment to the terminal."""
    color = _TIER_COLORS[assessment.overall_tier]

    # Header
    _console.print()
    _console.print(f"  Repository: [bold]{assessment.owner}/{assessment.repo}[/bold]")

    tier_label = _TIER_LABELS[assessment.overall_tier]
    _console.print(f"  Overall:    [{color} bold]{tier_label}[/{color} bold]")

    if assessment.incomplete:
        _console.print("  [yellow]Note: Incomplete assessment — some signals failed to evaluate[/yellow]")

    _console.print()

    # Natural-language summary
    summary = _build_summary(assessment, signal_names)
    _console.print(f"  {summary}")
    _console.print()

    # Signal table
    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("Signal", min_width=25)
    table.add_column("Weight", justify="center", min_width=6)
    table.add_column("Tier", justify="center", min_width=8)
    table.add_column("Finding", min_width=40)

    for name, weight, result in zip(signal_names, signal_weights, assessment.signals):
        weight_label = _WEIGHT_LABELS.get(weight, str(weight.value))

        if result.skip:
            tier_display = "—"
            tier_color = "dim"
            finding = f"[dim]{result.summary}[/dim]"
        else:
            tier_color = _TIER_COLORS.get(result.tier, "white")
            tier_display = result.tier.value.upper()
            if weight == SignalWeight.GATE:
                if result.score < 0:
                    tier_display = "FAIL"
                elif result.details.get("needs_human"):
                    tier_display = "REVIEW"
                else:
                    tier_display = "PASS"
            finding = result.summary
            if result.low_sample:
                finding += " [dim](low sample)[/dim]"

        table.add_row(
            name,
            weight_label,
            f"[{tier_color}]{tier_display}[/{tier_color}]",
            finding,
        )

    _console.print(table)
    _console.print()

    # Verbose details
    if verbose:
        _print_verbose_details(assessment, signal_names)


def print_assessment_json(assessment: Assessment, signal_names: list[str]) -> None:
    """Print assessment as JSON to stdout."""
    data = {
        "owner": assessment.owner,
        "repo": assessment.repo,
        "overall_tier": assessment.overall_tier.value,
        "gate_passed": assessment.gate_passed,
        "incomplete": assessment.incomplete,
        "timestamp": assessment.timestamp,
        "signals": [
            {
                "name": name,
                "score": r.score,
                "tier": r.tier.value,
                "summary": r.summary,
                "low_sample": r.low_sample,
                "details": r.details,
            }
            for name, r in zip(signal_names, assessment.signals)
        ],
    }
    print(json.dumps(data, indent=2))


def print_cached_notice(owner: str, repo: str, timestamp: str) -> None:
    """Print a notice that cached results are being used."""
    _console.print(f"  [dim]Using cached assessment from {timestamp}. Use --no-cache to refresh.[/dim]")


def _build_summary(assessment: Assessment, signal_names: list[str]) -> str:
    """Build a natural-language summary paragraph from signal results."""
    parts = []

    for name, result in zip(signal_names, assessment.signals):
        # Only include interesting findings in the summary
        if "merge" in name.lower() and result.score >= 0:
            parts.append(result.summary)
        elif "response" in name.lower() and result.tier != Tier.RED:
            parts.append(f"{result.summary} median response time")
        elif "ghost" in name.lower() and result.score < 1.0:
            parts.append(result.summary)
        elif "ai policy" in name.lower() and result.score < 1.0:
            parts.append(f"AI policy: {result.summary.lower()}")

    if not parts:
        if assessment.overall_tier == Tier.GREEN:
            return "This project shows strong signals for accepting outside contributions."
        elif assessment.overall_tier == Tier.YELLOW:
            return "This project shows mixed signals for outside contributions."
        else:
            return "This project does not appear to accept outside contributions."

    return ". ".join(parts) + "."


def _print_verbose_details(assessment: Assessment, signal_names: list[str]) -> None:
    """Print detailed signal data for --verbose mode."""
    _console.print("  [bold]Detailed signal data:[/bold]")
    for name, result in zip(signal_names, assessment.signals):
        if result.details:
            _console.print(f"    [dim]{name}:[/dim]")
            for key, value in result.details.items():
                _console.print(f"      {key}: {value}")

        # Collaborator bias warning
        collaborator_count = result.details.get("collaborator_pr_count", 0)
        if collaborator_count > 0 and "merge" in name.lower():
            _console.print(
                f"      [yellow]Note: {collaborator_count} PR(s) from current collaborators "
                f"may have been external contributions. authorAssociation reflects "
                f"current role, not role at PR time.[/yellow]"
            )
    _console.print()


# --- Triage output ---

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


# --- Sniff output ---

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
