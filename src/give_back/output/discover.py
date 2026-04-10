"""Discover output: ranked repo table + JSON."""

from __future__ import annotations

import json

from rich.table import Table

from give_back.discover.search import DiscoverResult, DiscoverSummary
from give_back.hints import emit_advisory
from give_back.output._shared import _TIER_COLORS, _console


def _format_stars(count: int) -> str:
    """Format star count as 68.2k, 1.2M, etc."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def _build_result_table(results: list[DiscoverResult], start_num: int = 1) -> Table:
    """Build a rich Table from a list of DiscoverResults.

    ``start_num`` controls the first row number (for continuous numbering
    across primary and fallback tables).
    """
    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Repository", min_width=25)
    table.add_column("Stars", justify="right", min_width=6)
    table.add_column("Tier", justify="center", min_width=8)
    table.add_column("Issues", justify="right", min_width=6)
    table.add_column("Description", min_width=30, max_width=60, overflow="fold")

    for i, r in enumerate(results, start_num):
        if r.tier is not None:
            tier_color = _TIER_COLORS.get(r.tier, "white")
            tier_text = r.tier.value.upper()
            if r.from_cache:
                tier_text += " [dim](cached)[/dim]"
        elif r.skip_reason:
            tier_color = "dim"
            tier_text = f"[dim]{r.skip_reason}[/dim]"
        else:
            tier_color = "dim"
            tier_text = "—"

        table.add_row(
            str(i),
            f"{r.owner}/{r.repo}",
            _format_stars(r.stars),
            f"[{tier_color}]{tier_text}[/{tier_color}]",
            str(r.open_issue_count),
            r.description or "",
        )

    return table


def print_discover(summary: DiscoverSummary, verbose: bool = False, limit: int = 10) -> None:
    """Print a ranked discover table to the terminal."""
    _console.print()
    if summary.label_gate_active:
        found = f"  Found [bold]{summary.total_searched}[/bold] repos"
        found += ' with active "good first issue" / "help wanted" labels.'
        _console.print(f"{found} Assessed {summary.assessed_count} ({summary.cache_hits} from cache).")
    else:
        _console.print(
            f"  Found [bold]{summary.total_searched}[/bold] repos matching your filters (no label gate). "
            f"Assessed {summary.assessed_count} ({summary.cache_hits} from cache)."
        )
    _console.print()

    if not summary.results:
        _console.print("  [dim]No repos matched your criteria.[/dim]")
        _console.print()
        return

    _console.print(_build_result_table(summary.results))
    _console.print()
    _console.print("  Use [bold]give-back triage <repo>[/bold] to find starter issues.")
    _console.print()

    # Fallback table: show repos from ungated search when label gate was active
    if summary.fallback_results:
        _console.print('  Also found (no "good first issue" / "help wanted" labels):')
        _console.print()
        fb_start = len(summary.results) + 1
        _console.print(_build_result_table(summary.fallback_results, start_num=fb_start))
        _console.print()

    # Sparse-result advisory: help users understand why canonical repos may be missing.
    # Suppressed when fallback already provided results (the table IS the hint).
    if summary.label_gate_active and not summary.fallback_results and len(summary.results) < min(limit, 5):
        emit_advisory(
            "\n  [dim]Tip: Mature projects often retire stock contribution labels. "
            "To check a specific repo directly:[/dim]\n"
            "    [dim]give-back assess <owner/repo>[/dim]\n"
            "  [dim]To search without the label gate:[/dim]\n"
            "    [dim]give-back discover --any-issues ...[/dim]\n"
        )


def print_discover_json(summary: DiscoverSummary) -> None:
    """Print discover results as JSON to stdout."""
    data = {
        "query": summary.query,
        "total_searched": summary.total_searched,
        "assessed_count": summary.assessed_count,
        "cache_hits": summary.cache_hits,
        "filtered_count": summary.filtered_count,
        "label_gate_active": summary.label_gate_active,
        "results": [
            {
                "owner": r.owner,
                "repo": r.repo,
                "description": r.description,
                "stars": r.stars,
                "language": r.language,
                "topics": r.topics,
                "open_issue_count": r.open_issue_count,
                "good_first_issue_count": r.good_first_issue_count,
                "tier": r.tier.value if r.tier else None,
                "from_cache": r.from_cache,
                "skip_reason": r.skip_reason,
            }
            for r in summary.results
        ],
    }

    # Fallback fields: only present when fallback was attempted (distinguishes
    # "didn't run" from "ran but found nothing")
    if summary.fallback_triggered:
        data["fallback_triggered"] = True
        data["fallback_results"] = [
            {
                "owner": r.owner,
                "repo": r.repo,
                "description": r.description,
                "stars": r.stars,
                "language": r.language,
                "topics": r.topics,
                "open_issue_count": r.open_issue_count,
                "good_first_issue_count": r.good_first_issue_count,
                "tier": r.tier.value if r.tier else None,
                "from_cache": r.from_cache,
                "skip_reason": r.skip_reason,
            }
            for r in summary.fallback_results
        ]

    print(json.dumps(data, indent=2))
