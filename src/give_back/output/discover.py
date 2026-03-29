"""Discover output: ranked repo table + JSON."""

from __future__ import annotations

import json

from rich.table import Table

from give_back.discover.search import DiscoverSummary
from give_back.output._shared import _TIER_COLORS, _console


def _format_stars(count: int) -> str:
    """Format star count as 68.2k, 1.2M, etc."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def print_discover(summary: DiscoverSummary, verbose: bool = False) -> None:
    """Print a ranked discover table to the terminal."""
    _console.print()
    _console.print(
        f"  Found [bold]{summary.total_searched}[/bold] repos. "
        f"Assessed {summary.assessed_count} ({summary.cache_hits} from cache)."
    )
    _console.print()

    if not summary.results:
        _console.print("  [dim]No repos matched your criteria.[/dim]")
        _console.print()
        return

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Repository", min_width=25)
    table.add_column("Stars", justify="right", min_width=6)
    table.add_column("Tier", justify="center", min_width=8)
    table.add_column("Issues", justify="right", min_width=6)
    table.add_column("Description", min_width=30)

    for i, r in enumerate(summary.results, 1):
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

        desc = (r.description or "")[:60]

        table.add_row(
            str(i),
            f"{r.owner}/{r.repo}",
            _format_stars(r.stars),
            f"[{tier_color}]{tier_text}[/{tier_color}]",
            str(r.open_issue_count),
            desc,
        )

    _console.print(table)
    _console.print()
    _console.print("  Use [bold]give-back triage <repo>[/bold] to find starter issues.")
    _console.print()


def print_discover_json(summary: DiscoverSummary) -> None:
    """Print discover results as JSON to stdout."""
    data = {
        "query": summary.query,
        "total_searched": summary.total_searched,
        "assessed_count": summary.assessed_count,
        "cache_hits": summary.cache_hits,
        "filtered_count": summary.filtered_count,
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
    print(json.dumps(data, indent=2))
