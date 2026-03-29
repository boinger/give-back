"""Calibration output: confusion matrix, accuracy, threshold suggestions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from give_back.models import Tier
from give_back.output._shared import _console

if TYPE_CHECKING:
    from give_back.calibrate import CalibrationResult


def print_calibration(result: CalibrationResult, verbose: bool = False) -> None:
    """Print calibration results: confusion matrix, accuracy, mismatches, suggestions."""
    tiers = [Tier.GREEN, Tier.YELLOW, Tier.RED]
    pct = (result.correct / result.total * 100) if result.total > 0 else 0.0

    _console.print()
    _console.print(f"  [bold]Calibration results ({result.total} repos):[/bold]")
    _console.print()

    # Confusion matrix
    _console.print("  [bold]Confusion Matrix:[/bold]")
    _console.print("                Predicted")

    header = "             "
    for t in tiers:
        header += f" {t.value.upper():>6}"
    _console.print(f"  {header}")

    for expected in tiers:
        label = f"Expected {expected.value.upper():>6}"
        row = f"  {label}"
        for actual in tiers:
            count = result.matrix[expected][actual]
            row += f" {count:>6}"
        _console.print(row)

    _console.print()
    _console.print(f"  Accuracy: {result.correct}/{result.total} ({pct:.1f}%)")
    _console.print()

    if not result.mismatches:
        _console.print("  [green]All repos matched expected tiers.[/green]")
        _console.print()
        return

    # Mismatches
    _console.print("  [bold]Mismatches:[/bold]")
    for m in result.mismatches:
        _console.print(
            f"    {m.repo}: expected [bold]{m.expected.value.upper()}[/bold], got [bold]{m.actual.value.upper()}[/bold]"
        )
        _console.print(f"      (weighted avg: {m.weighted_avg:.2f})")
        if verbose and m.signal_summaries:
            for name, summary in m.signal_summaries.items():
                _console.print(f"        {name}: {summary}")

    _console.print()

    # Threshold suggestions
    green_t, yellow_t = result.current_thresholds
    _console.print(f"  Current thresholds: GREEN >= {green_t}, YELLOW >= {yellow_t}")

    if result.suggested_thresholds:
        new_green, new_yellow = result.suggested_thresholds
        _console.print(f"  Suggested thresholds: GREEN >= {new_green}, YELLOW >= {new_yellow}")
        _console.print()
        _console.print("  [dim]To apply: update TIER_GREEN_THRESHOLD / TIER_YELLOW_THRESHOLD in models.py[/dim]")
    else:
        _console.print("  [dim]No threshold adjustment could improve accuracy for these mismatches.[/dim]")

    _console.print()
