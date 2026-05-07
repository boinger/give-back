"""Batch audit across the authenticated user's repos."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from give_back.audit import AuditReport, run_audit
from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient
from give_back.state import save_audit_result

_DEFAULT_LIMIT = 20


def fetch_user_repos(client: GitHubClient, *, include_all: bool = False) -> list[dict[str, Any]]:
    """Fetch the authenticated user's repos, sorted by most recent push.

    By default, returns only public, non-archived, non-fork repos.
    With *include_all*, returns everything.
    """
    repos: list[dict[str, Any]] = []
    page = 1
    per_page = 100

    while True:
        data = client.rest_get("/user/repos", params={"per_page": per_page, "page": page, "sort": "pushed"})
        if not isinstance(data, list) or not data:
            break
        repos.extend(data)
        if len(data) < per_page:
            break
        page += 1

    if not include_all:
        repos = [r for r in repos if not r.get("archived") and not r.get("private") and not r.get("fork")]

    return repos


def run_batch_audit(
    client: GitHubClient,
    repos: list[dict[str, Any]],
    *,
    limit: int = _DEFAULT_LIMIT,
) -> list[tuple[dict[str, Any], AuditReport | None, str | None]]:
    """Run audit on up to *limit* repos. Returns list of (repo_dict, report_or_none, error_or_none)."""
    results: list[tuple[dict[str, Any], AuditReport | None, str | None]] = []
    to_audit = repos[:limit]

    for i, repo in enumerate(to_audit, 1):
        owner = repo["owner"]["login"]
        name = repo["name"]
        slug = f"{owner}/{name}"
        click.echo(f"  [{i}/{len(to_audit)}] Auditing {slug}...", nl=False)

        try:
            report = run_audit(client, owner, name)
            click.echo(" done")

            # Save to state for delta tracking
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "items": {item.name: item.passed for item in report.items},
            }
            save_audit_result(owner, name, snapshot)

            results.append((repo, report, None))
        except GiveBackError as exc:
            click.echo(f" error: {exc}")
            results.append((repo, None, str(exc)))

    return results


def print_batch_results(results: list[tuple[dict[str, Any], AuditReport | None, str | None]]) -> None:
    """Display a ranked table of audit results."""
    console = Console()
    console.print()

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", width=3)
    table.add_column("Repository", min_width=30)
    table.add_column("Score", justify="center", min_width=8)
    table.add_column("Top issue", min_width=35)

    # Sort by score descending (errors at bottom)
    scored = []
    errors = []
    for repo, report, error in results:
        if report:
            passing = sum(1 for item in report.items if item.passed)
            total = len(report.items)
            scored.append((repo, report, passing, total))
        else:
            errors.append((repo, error))

    scored.sort(key=lambda x: x[2] / max(x[3], 1), reverse=True)

    for i, (repo, report, passing, total) in enumerate(scored, 1):
        slug = repo["full_name"]
        score_pct = passing / max(total, 1)
        if score_pct >= 0.8:
            score_str = f"[green]{passing}/{total}[/green]"
        elif score_pct >= 0.5:
            score_str = f"[yellow]{passing}/{total}[/yellow]"
        else:
            score_str = f"[red]{passing}/{total}[/red]"

        # Find the first failing check for "top issue"
        first_fail = next((item for item in report.items if not item.passed), None)
        top_issue = first_fail.name.replace("_", " ") if first_fail else "[green]all passing[/green]"

        table.add_row(str(i), slug, score_str, top_issue)

    for repo, error in errors:
        slug = repo["full_name"]
        # The error tuples land here only when report is None and the except path
        # set error = str(exc); mypy still sees Optional via the tuple type, so
        # narrow defensively.
        msg = (error or "")[:40]
        table.add_row("—", slug, "[red]error[/red]", f"[dim]{msg}[/dim]")

    console.print(table)
    console.print()
    console.print(f"  [dim]{len(scored)} repos audited, {len(errors)} errors[/dim]")
    console.print()
