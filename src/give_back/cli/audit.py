"""CLI command group: audit (repo, fix, mine)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import click

from give_back.auth import resolve_token
from give_back.cli._shared import _parse_repo
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    RateLimitError,
    RepoNotFoundError,
)
from give_back.github_client import GitHubClient


@click.group(invoke_without_command=True)
@click.argument("repo", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show signal details (scores, sample sizes).")
@click.option("--conventions", is_flag=True, help="Also scan contribution conventions (clones the repo, slower).")
@click.option("--compare", default=None, help="Compare against another repo side-by-side.")
@click.pass_context
def audit(
    ctx: click.Context,
    repo: str | None,
    json_output: bool,
    verbose: bool,
    conventions: bool,
    compare: str | None,
) -> None:
    """Audit a repo's contributor-friendliness for maintainers.

    Produces a checklist of community health files, templates, labels, and
    viability signals with actionable recommendations for each failing item.

    Examples:

    \b
        give-back audit pallets/flask
        give-back audit pallets/flask --compare django/django
        give-back audit pallets/flask --conventions
        give-back audit fix pallets/flask
        give-back audit fix pallets/flask --template-repo myorg/standards
        give-back audit mine
        give-back audit mine --limit 10
    """
    # If a subcommand was invoked, let it run
    if ctx.invoked_subcommand is not None:
        return

    # Default behavior: audit a single repo
    if not repo:
        _console.print("[red]Error:[/red] Please provide a REPO argument or use `audit mine`.")
        sys.exit(1)

    _run_audit_repo(repo, json_output, verbose, conventions, compare)


def _run_audit_repo(
    repo: str,
    json_output: bool,
    verbose: bool,
    conventions: bool,
    compare: str | None,
) -> None:
    """Run single-repo audit (shared by group default and explicit invocation)."""
    from give_back.audit import run_audit
    from give_back.output import print_audit, print_audit_comparison, print_audit_json
    from give_back.state import get_previous_audit, save_audit_result

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    compare_owner: str | None = None
    compare_repo: str | None = None
    if compare:
        try:
            compare_owner, compare_repo = _parse_repo(compare)
        except click.BadParameter as exc:
            _console.print(f"[red]Error:[/red] --compare: {exc.format_message()}")
            sys.exit(1)

    token = resolve_token()
    if not token:
        _console.print("[yellow]Warning:[/yellow] No auth token. Audit may be limited by rate limits.")

    try:
        with GitHubClient(token=token) as client:
            report = run_audit(client, owner, repo_name, verbose=verbose, conventions=conventions)

            if compare_owner and compare_repo:
                compare_report = run_audit(
                    client, compare_owner, compare_repo, verbose=verbose, conventions=conventions
                )
                if json_output:
                    print_audit_json(report)
                    print_audit_json(compare_report)
                else:
                    print_audit_comparison(report, compare_report)
            else:
                previous = get_previous_audit(owner, repo_name)
                snapshot = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "items": {item.name: item.passed for item in report.items},
                }
                if json_output:
                    print_audit_json(report, previous=previous)
                else:
                    print_audit(report, verbose=verbose, previous=previous)
                save_audit_result(owner, repo_name, snapshot)

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@audit.command("fix")
@click.argument("repo")
@click.option("--verbose", "-v", is_flag=True, help="Show signal details.")
@click.option("--conventions", is_flag=True, help="Also scan contribution conventions.")
@click.option(
    "--template-repo", default=None, help="Use community health files from this repo as templates (owner/repo)."
)
@click.option(
    "--template-dir", default=None, type=click.Path(exists=True), help="Use templates from a local directory."
)
def audit_fix(
    repo: str,
    verbose: bool,
    conventions: bool,
    template_repo: str | None,
    template_dir: str | None,
) -> None:
    """Interactively fix failing audit checks.

    Generates missing community health files and creates labels.

    \b
        give-back audit fix pallets/flask
        give-back audit fix pallets/flask --template-repo myorg/standards
        give-back audit fix pallets/flask --template-dir ./templates
    """
    from pathlib import Path

    from give_back.audit import run_audit
    from give_back.audit_fix.fix import print_fix_summary, resolve_repo_dir, walk_fixes
    from give_back.audit_fix.resolver import TemplateResolver

    if template_repo and template_dir:
        _console.print("[red]Error:[/red] --template-repo and --template-dir are mutually exclusive.")
        sys.exit(1)

    if not sys.stdin.isatty():
        _console.print("[red]Error:[/red] audit fix requires an interactive terminal.")
        sys.exit(1)

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()
    if not token:
        _console.print("[yellow]Warning:[/yellow] No auth token. Audit may be limited by rate limits.")

    try:
        with GitHubClient(token=token) as client:
            report = run_audit(client, owner, repo_name, verbose=verbose, conventions=conventions)

            resolver = TemplateResolver(
                template_dir=Path(template_dir) if template_dir else None,
                template_repo=template_repo,
                client=client,
            )

            has_failures = any(not item.passed for item in report.items)
            if not has_failures:
                _console.print("\n  [green]Nothing to fix![/green]")
            else:
                repo_dir = resolve_repo_dir(owner, repo_name)
                if repo_dir is not None:
                    try:
                        summary = walk_fixes(report, repo_dir, client, resolver=resolver)
                        print_fix_summary(summary)
                    except click.Abort:
                        _console.print("\n  Interrupted.")

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@audit.command("mine")
@click.option("--include-all", is_flag=True, help="Include private, archived, and forked repos.")
@click.option("--limit", "mine_limit", default=20, show_default=True, help="Max repos to audit.")
def audit_mine(include_all: bool, mine_limit: int) -> None:
    """Batch-audit your own repos, ranked by activity.

    \b
        give-back audit mine
        give-back audit mine --limit 10
        give-back audit mine --include-all
    """
    from give_back.audit_mine import fetch_user_repos, print_batch_results, run_batch_audit

    token = resolve_token()
    if not token:
        _console.print("[red]Error:[/red] audit mine requires authentication. Set GITHUB_TOKEN or install gh CLI.")
        sys.exit(1)

    try:
        with GitHubClient(token=token) as client:
            _console.print("\n  Fetching your repos...")
            repos = fetch_user_repos(client, include_all=include_all)
            if not repos:
                _console.print("  No repos found.")
                return
            _console.print(f"  Found {len(repos)} repos, auditing top {min(mine_limit, len(repos))}...\n")
            results = run_batch_audit(client, repos, limit=mine_limit)
            print_batch_results(results)
    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
