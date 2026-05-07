"""Audit output: maintainer checklist + comparison + JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from rich.table import Table

from give_back.audit import AuditItem, AuditReport
from give_back.output._shared import _console

_CATEGORY_HEADERS = {
    "community_health": "Community health files",
    "templates": "Templates",
    "labels": "Labels",
    "signals": "Contributor experience",
    "conventions": "Conventions",
}

_CATEGORY_ORDER = ["community_health", "templates", "labels", "signals", "conventions"]


def print_audit(report: AuditReport, verbose: bool = False, previous: dict[str, Any] | None = None) -> None:
    """Print audit results as a checklist, with optional delta from *previous*."""
    _console.print()
    _console.print(f"  Audit: [bold]{report.owner}/{report.repo}[/bold]")
    if report.health_percentage is not None:
        _console.print(f"  GitHub community health: {report.health_percentage}%")
    _console.print()

    # Group items by category
    by_category: dict[str, list[AuditItem]] = {}
    for item in report.items:
        by_category.setdefault(item.category, []).append(item)

    passing = sum(1 for item in report.items if item.passed)
    total = len(report.items)

    for category in _CATEGORY_ORDER:
        items = by_category.get(category)
        if not items:
            continue

        header = _CATEGORY_HEADERS.get(category, category)
        _console.print(f"  [bold]{header}[/bold]")

        for item in items:
            if item.passed:
                _console.print(f"    [green]✓[/green] {item.message}")
            else:
                _console.print(f"    [red]✗[/red] {item.message}")
                if item.recommendation:
                    _console.print(f"      [dim]→ {item.recommendation}[/dim]")

            if verbose and not item.passed and item.recommendation:
                pass  # Recommendation already shown

        _console.print()

    _console.print(f"  Score: {passing}/{total} checks passing")

    if previous is not None:
        _print_delta(report, previous)

    # Suggest --conventions if not already included and basic checks look good
    has_conventions = any(item.category == "conventions" for item in report.items)
    if not has_conventions and passing > total * 0.6:
        _console.print("  [dim]Run with --conventions to also check commit format, code style, and CI setup.[/dim]")
    _console.print()


def _format_audit_date(iso_timestamp: str) -> str:
    """Format an ISO timestamp as a human-friendly date."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        now_year = datetime.now(timezone.utc).year
        if dt.year == now_year:
            return dt.strftime("%B %-d")
        return dt.strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        return "unknown date"


def _compute_delta(report: AuditReport, previous: dict[str, Any]) -> dict[str, Any]:
    """Compute the delta between a current report and a previous snapshot.

    Returns a dict with keys: prev_passing, prev_total, newly_passing,
    newly_failing, change, totals_differ.
    """
    prev_items = previous.get("items", {})
    current_items = {item.name: item.passed for item in report.items}

    # Only compare the intersection of keys
    common_keys = set(prev_items) & set(current_items)
    newly_passing = sorted(k for k in common_keys if current_items[k] and not prev_items[k])
    newly_failing = sorted(k for k in common_keys if not current_items[k] and prev_items[k])

    prev_passing = sum(1 for v in prev_items.values() if v)
    prev_total = len(prev_items)

    return {
        "prev_passing": prev_passing,
        "prev_total": prev_total,
        "newly_passing": newly_passing,
        "newly_failing": newly_failing,
        "change": len(newly_passing) - len(newly_failing),
        "totals_differ": prev_total != len(report.items),
    }


def _print_delta(report: AuditReport, previous: dict[str, Any]) -> None:
    """Print the delta between the current report and the previous snapshot."""
    delta = _compute_delta(report, previous)
    ts = previous.get("timestamp", "")
    date_str = _format_audit_date(ts)

    _console.print(f"  [dim]Last audit: {delta['prev_passing']}/{delta['prev_total']} ({date_str})[/dim]")

    if delta["totals_differ"]:
        _console.print(f"  [dim](check set changed: was {delta['prev_total']}, now {len(report.items)})[/dim]")

    if delta["newly_passing"] or delta["newly_failing"]:
        parts = []
        if delta["newly_passing"]:
            names = ", ".join(delta["newly_passing"])
            parts.append(f"[green]+{len(delta['newly_passing'])} ✓[/green]  ({names} now passing)")
        if delta["newly_failing"]:
            names = ", ".join(delta["newly_failing"])
            parts.append(f"[red]-{len(delta['newly_failing'])} ✗[/red]  ({names} now failing)")
        for part in parts:
            _console.print(f"  Delta: {part}")
    else:
        _console.print("  [dim]No changes since last audit.[/dim]")


def print_audit_comparison(report_a: AuditReport, report_b: AuditReport) -> None:
    """Print side-by-side audit comparison of two repos."""
    _console.print()
    _console.print(
        f"  Audit comparison: [bold]{report_a.owner}/{report_a.repo}[/bold]"
        f" vs [bold]{report_b.owner}/{report_b.repo}[/bold]"
    )
    _console.print()

    # Build name→item maps
    items_a = {item.name: item for item in report_a.items}
    items_b = {item.name: item for item in report_b.items}

    # Collect all item names in order (preserving category grouping)
    all_names: list[str] = []
    seen: set[str] = set()
    for item in report_a.items + report_b.items:
        if item.name not in seen:
            all_names.append(item.name)
            seen.add(item.name)

    # Group by category for display
    by_category: dict[str, list[str]] = {}
    for name in all_names:
        # Distinct name from the earlier loop's `item: AuditItem`; this lookup
        # may return None when one report doesn't have the check.
        category_item = items_a.get(name) or items_b.get(name)
        if category_item:
            by_category.setdefault(category_item.category, []).append(name)

    label_a = report_a.repo
    label_b = report_b.repo

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("Check", min_width=25)
    table.add_column(label_a, justify="center", min_width=12)
    table.add_column(label_b, justify="center", min_width=12)

    for category in _CATEGORY_ORDER:
        names = by_category.get(category)
        if not names:
            continue

        header = _CATEGORY_HEADERS.get(category, category)
        table.add_row(f"[bold]{header}[/bold]", "", "")

        for name in names:
            a = items_a.get(name)
            b = items_b.get(name)
            col_a = "[green]✓[/green]" if (a and a.passed) else "[red]✗[/red]" if a else "[dim]—[/dim]"
            col_b = "[green]✓[/green]" if (b and b.passed) else "[red]✗[/red]" if b else "[dim]—[/dim]"
            display_name = name.replace("_", " ").upper()
            table.add_row(f"  {display_name}", col_a, col_b)

    _console.print(table)

    passing_a = sum(1 for item in report_a.items if item.passed)
    passing_b = sum(1 for item in report_b.items if item.passed)
    _console.print()
    _console.print(
        f"  Score: {label_a} {passing_a}/{len(report_a.items)}  |  {label_b} {passing_b}/{len(report_b.items)}"
    )
    _console.print()


def print_audit_json(report: AuditReport, previous: dict[str, Any] | None = None) -> None:
    """Print audit results as JSON to stdout."""
    data: dict[str, Any] = {
        "owner": report.owner,
        "repo": report.repo,
        "health_percentage": report.health_percentage,
        "signal_tier": report.signal_tier.value if report.signal_tier else None,
        "items": [
            {
                "name": item.name,
                "category": item.category,
                "passed": item.passed,
                "message": item.message,
                "recommendation": item.recommendation,
            }
            for item in report.items
        ],
        "score": {
            "passing": sum(1 for item in report.items if item.passed),
            "total": len(report.items),
        },
    }

    if previous is not None:
        delta = _compute_delta(report, previous)
        data["previous"] = {
            "timestamp": previous.get("timestamp"),
            "passing": delta["prev_passing"],
            "total": delta["prev_total"],
        }
        data["delta"] = {
            "change": delta["change"],
            "newly_passing": delta["newly_passing"],
            "newly_failing": delta["newly_failing"],
        }

    print(json.dumps(data, indent=2))
