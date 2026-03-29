"""Audit output: maintainer checklist + comparison + JSON."""

from __future__ import annotations

import json

from rich.table import Table

from give_back.audit import AuditReport
from give_back.output._shared import _console

_CATEGORY_HEADERS = {
    "community_health": "Community health files",
    "templates": "Templates",
    "labels": "Labels",
    "signals": "Contributor experience",
    "conventions": "Conventions",
}

_CATEGORY_ORDER = ["community_health", "templates", "labels", "signals", "conventions"]


def print_audit(report: AuditReport, verbose: bool = False) -> None:
    """Print audit results as a checklist."""
    _console.print()
    _console.print(f"  Audit: [bold]{report.owner}/{report.repo}[/bold]")
    if report.health_percentage is not None:
        _console.print(f"  GitHub community health: {report.health_percentage}%")
    _console.print()

    # Group items by category
    by_category: dict[str, list] = {}
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
    _console.print()


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
        item = items_a.get(name) or items_b.get(name)
        if item:
            by_category.setdefault(item.category, []).append(name)

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


def print_audit_json(report: AuditReport) -> None:
    """Print audit results as JSON to stdout."""
    data = {
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
    print(json.dumps(data, indent=2))
