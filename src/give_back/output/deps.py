"""Dependency walk output: table + JSON."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.table import Table

from give_back.output._shared import _TIER_COLORS, _console, _extract_signal_detail

if TYPE_CHECKING:
    from give_back.deps.walker import WalkResult


def print_deps(walk_result: WalkResult, verbose: bool = False) -> None:
    """Print dependency assessment summary table."""
    stats = walk_result.filter_stats
    filtered_total = (
        stats.get("stdlib", 0) + stats.get("same_org", 0) + stats.get("skip_list", 0) + stats.get("archived", 0)
    )

    _console.print()
    _console.print(
        f"  Dependency assessment for [bold]{walk_result.primary_owner}/{walk_result.primary_repo}[/bold] "
        f"({walk_result.resolved_count} deps resolved, {filtered_total} filtered)"
    )
    _console.print()

    if not walk_result.results:
        _console.print("  [dim]No dependencies to assess after filtering.[/dim]")
        _print_deps_footer(walk_result)
        return

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Repository", min_width=25)
    table.add_column("Tier", justify="center", min_width=8)
    table.add_column("Merge Rate", justify="center", min_width=10)
    table.add_column("Response", justify="center", min_width=9)
    table.add_column("Notes", min_width=15)

    for i, dep in enumerate(walk_result.results, 1):
        slug = f"{dep.owner}/{dep.repo}"

        if dep.assessment is None:
            table.add_row(str(i), slug, "[dim]—[/dim]", "[dim]—[/dim]", "[dim]—[/dim]", "[dim]assessment failed[/dim]")
            continue

        tier = dep.assessment.overall_tier
        tier_color = _TIER_COLORS.get(tier, "white")
        tier_label = tier.value.upper()

        merge_rate = _extract_signal_detail(dep.assessment, "merged", "merge_rate")
        response_time = _extract_signal_detail(dep.assessment, "first response", "median_hours")

        notes_parts = []
        if dep.from_cache:
            notes_parts.append("cached")
        low_sample_signals = [s for s in dep.assessment.signals if s.low_sample]
        if low_sample_signals:
            notes_parts.append("low sample")
        notes = ", ".join(notes_parts)

        table.add_row(
            str(i),
            slug,
            f"[{tier_color}]{tier_label}[/{tier_color}]",
            merge_rate,
            response_time,
            notes if notes else "",
        )

    _console.print(table)
    _print_deps_footer(walk_result)


def _print_deps_footer(walk_result: WalkResult) -> None:
    """Print filter summary and unresolvable count below the deps table."""
    stats = walk_result.filter_stats

    filter_parts = []
    if stats.get("stdlib", 0):
        filter_parts.append(f"{stats['stdlib']} stdlib")
    if stats.get("same_org", 0):
        filter_parts.append(f"{stats['same_org']} same-org")
    if stats.get("skip_list", 0):
        filter_parts.append(f"{stats['skip_list']} in skip list")
    if stats.get("archived", 0):
        filter_parts.append(f"{stats['archived']} archived")

    _console.print()
    if filter_parts:
        total_filtered = sum(stats.get(k, 0) for k in ("stdlib", "same_org", "skip_list", "archived"))
        _console.print(f"  {total_filtered} deps filtered: {', '.join(filter_parts)}")

    unresolved = stats.get("unresolved", 0)
    if unresolved:
        _console.print(f"  {unresolved} deps unresolvable (no GitHub URL found)")

    mega = stats.get("mega_projects", [])
    if mega:
        _console.print(f"  [dim]Mega-projects (>50k stars): {', '.join(mega)}[/dim]")

    _console.print()


def print_deps_json(walk_result: WalkResult) -> None:
    """Print dependency walk results as JSON to stdout."""
    data = {
        "primary_owner": walk_result.primary_owner,
        "primary_repo": walk_result.primary_repo,
        "ecosystem": walk_result.ecosystem,
        "total_packages": walk_result.total_packages,
        "resolved_count": walk_result.resolved_count,
        "filter_stats": walk_result.filter_stats,
        "results": [
            {
                "package_name": dep.package_name,
                "owner": dep.owner,
                "repo": dep.repo,
                "from_cache": dep.from_cache,
                "assessment": {
                    "overall_tier": dep.assessment.overall_tier.value,
                    "gate_passed": dep.assessment.gate_passed,
                    "incomplete": dep.assessment.incomplete,
                    "timestamp": dep.assessment.timestamp,
                }
                if dep.assessment
                else None,
            }
            for dep in walk_result.results
        ],
    }
    print(json.dumps(data, indent=2))
