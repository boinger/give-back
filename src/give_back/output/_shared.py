"""Shared constants and helpers for output formatting."""

from __future__ import annotations

from rich.console import Console

from give_back.console import _effective_width
from give_back.models import Assessment, SignalWeight, Tier

_console = Console(width=_effective_width())

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


def _extract_signal_detail(assessment: Assessment, keyword: str, detail_key: str) -> str:
    """Extract a specific metric from assessment signals for table display."""
    for signal in assessment.signals:
        if keyword in signal.summary.lower():
            value = signal.details.get(detail_key)
            if value is not None:
                if detail_key == "merge_rate":
                    return f"{value:.0%}" if isinstance(value, float) else str(value)
                if detail_key == "median_hours":
                    if isinstance(value, (int, float)):
                        if value < 1:
                            return f"{value * 60:.0f}m"
                        if value < 48:
                            return f"{value:.0f}h"
                        return f"{value / 24:.0f}d"
                return str(value)

            return signal.summary[:20] if signal.summary else "—"

    return "—"
