"""Assessment output: rich table + JSON."""

from __future__ import annotations

import json

from rich.table import Table

from give_back.models import Assessment, SignalWeight, Tier
from give_back.output._shared import _TIER_COLORS, _TIER_LABELS, _WEIGHT_LABELS, _console


def print_assessment(
    assessment: Assessment,
    signal_names: list[str],
    signal_weights: list[SignalWeight],
    verbose: bool = False,
) -> None:
    """Print a formatted assessment to the terminal."""
    color = _TIER_COLORS[assessment.overall_tier]

    _console.print()
    _console.print(f"  Repository: [bold]{assessment.owner}/{assessment.repo}[/bold]")

    tier_label = _TIER_LABELS[assessment.overall_tier]
    _console.print(f"  Overall:    [{color} bold]{tier_label}[/{color} bold]")

    if assessment.incomplete:
        _console.print("  [yellow]Note: Incomplete assessment — some signals failed to evaluate[/yellow]")

    _console.print()

    summary = _build_summary(assessment, signal_names)
    _console.print(f"  {summary}")
    _console.print()

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

        collaborator_count = result.details.get("collaborator_pr_count", 0)
        if collaborator_count > 0 and "merge" in name.lower():
            _console.print(
                f"      [yellow]Note: {collaborator_count} PR(s) from current collaborators "
                f"may have been external contributions. authorAssociation reflects "
                f"current role, not role at PR time.[/yellow]"
            )
    _console.print()
