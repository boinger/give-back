"""Status output: contribution table + JSON."""

from __future__ import annotations

import json

from rich.table import Table

from give_back.output._shared import _console
from give_back.status import ArchivedContribution, ContributionStatus

# Status display colors
_STATUS_COLORS = {
    "merged": "green",
    "open": "yellow",
    "closed": "red",
    "working": "dim",
}

# Review display colors
_REVIEW_COLORS = {
    "approved": "green",
    "changes_requested": "red",
    "pending": "dim",
}


def print_status(
    contributions: list[ContributionStatus],
    archived: list[ArchivedContribution],
    verbose: bool = False,
) -> None:
    """Print a contribution status table to the terminal."""
    _console.print()

    if not contributions and not archived:
        _console.print("  [dim]No tracked contributions found.[/dim]")
        _console.print()
        return

    if contributions:
        repo_set = {f"{c.owner}/{c.repo}" for c in contributions}
        _console.print(f"  Tracking [bold]{len(contributions)}[/bold] contribution(s) across {len(repo_set)} repo(s).")
        _console.print()

        table = Table(show_header=True, header_style="bold", padding=(0, 1))
        table.add_column("Repository", min_width=20)
        table.add_column("Issue", justify="right", min_width=6)
        table.add_column("Branch", min_width=20)
        table.add_column("PR", justify="right", min_width=6)
        table.add_column("Status", min_width=10)
        table.add_column("Review", min_width=12)

        for c in contributions:
            repo_text = f"{c.owner}/{c.repo}"
            issue_text = f"#{c.issue_number}" if c.issue_number else "\u2014"
            branch_text = c.branch_name or "\u2014"
            pr_text = f"#{c.pr_number}" if c.pr_number else "\u2014"

            # Status column
            if c.skip_reason:
                status_text = f"[dim]{c.skip_reason}[/dim]"
            else:
                display_status = c.pr_state or "working"
                color = _STATUS_COLORS.get(display_status, "white")
                status_text = f"[{color}]{display_status}[/{color}]"
                if c.stale:
                    status_text += " [dim](stale)[/dim]"
                if c.local:
                    status_text += " [dim](local)[/dim]"

            # Review column
            if c.review_state:
                review_color = _REVIEW_COLORS.get(c.review_state, "white")
                review_text = f"[{review_color}]{c.review_state}[/{review_color}]"
            else:
                review_text = "\u2014"

            table.add_row(repo_text, issue_text, branch_text, pr_text, status_text, review_text)

        _console.print(table)

        # Explain stale entries if multiple hit rate limit
        stale_count = sum(1 for c in contributions if c.stale)
        if stale_count > 1:
            _console.print(f"  [yellow]{stale_count} contributions could not be refreshed (rate limit low)[/yellow]")
        _console.print()

    if archived:
        if verbose:
            _console.print("  [bold]Archived:[/bold]")
            for a in archived:
                issue_text = f"#{a.issue_number}" if a.issue_number else "\u2014"
                pr_text = f"PR {a.pr_url}" if a.pr_url else "no PR"
                date_text = a.archived_at[:10] if len(a.archived_at) >= 10 else a.archived_at
                _console.print(f"    {a.owner}/{a.repo}  {issue_text}  {a.status}   {pr_text}  archived {date_text}")
            _console.print()
        else:
            _console.print(f"  {len(archived)} archived contribution(s) (use --verbose to see)")
            _console.print()


def print_status_json(
    contributions: list[ContributionStatus],
    archived: list[ArchivedContribution],
) -> None:
    """Print status results as JSON to stdout."""
    data = {
        "contributions": [
            {
                "owner": c.owner,
                "repo": c.repo,
                "issue_number": c.issue_number,
                "branch_name": c.branch_name,
                "pr_url": c.pr_url,
                "pr_number": c.pr_number,
                "pr_state": c.pr_state,
                "review_state": c.review_state,
                "workspace_path": c.workspace_path,
                "stale": c.stale,
                "local": c.local,
                "skip_reason": c.skip_reason,
            }
            for c in contributions
        ],
        "archived": [
            {
                "owner": a.owner,
                "repo": a.repo,
                "issue_number": a.issue_number,
                "pr_url": a.pr_url,
                "status": a.status,
                "archived_at": a.archived_at,
            }
            for a in archived
        ],
    }
    print(json.dumps(data, indent=2))
