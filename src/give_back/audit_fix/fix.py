"""Audit --fix orchestrator: resolve repo, walk fixes, print summary."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import click

from give_back.audit import AuditReport
from give_back.audit_fix.contributing import run_wizard
from give_back.audit_fix.labels import create_labels
from give_back.audit_fix.license import pick_license
from give_back.audit_fix.templates import (
    BUG_REPORT_YML,
    CODE_OF_CONDUCT,
    CONFIG_YML,
    FEATURE_REQUEST_YML,
    PR_TEMPLATE,
    SECURITY,
    write_file,
)
from give_back.github_client import GitHubClient

_SSH_PATTERN = re.compile(r"git@[^:]+:(.+?)(?:\.git)?$")
_HTTPS_PATTERN = re.compile(r"https?://[^/]+/(.+?)(?:\.git)?$")


@dataclass
class FixSummary:
    """Tracks what --fix created."""

    local_files: list[str] = field(default_factory=list)
    remote_labels: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _parse_remote_slug(url: str) -> str | None:
    """Extract owner/repo from a git remote URL (SSH or HTTPS)."""
    for pattern in (_SSH_PATTERN, _HTTPS_PATTERN):
        m = pattern.match(url.strip())
        if m:
            return m.group(1).lower()
    return None


def _get_remote_slugs(repo_dir: Path) -> dict[str, str]:
    """Return {remote_name: owner/repo} for all remotes in a git repo."""
    try:
        result = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=repo_dir,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    slugs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            slug = _parse_remote_slug(parts[1])
            if slug and name not in slugs:
                slugs[name] = slug

    return slugs


def resolve_repo_dir(owner: str, repo: str) -> Path | None:
    """Find or create a local checkout matching owner/repo.

    Returns the repo directory path, or None if the user aborts.
    """
    target_slug = f"{owner}/{repo}".lower()
    cwd = Path.cwd()

    # Check cwd first
    slugs = _get_remote_slugs(cwd)
    if target_slug in slugs.values():
        return cwd

    click.echo()
    click.echo(f"  Current directory doesn't match {owner}/{repo}.")
    click.echo()
    click.echo("  Options:")
    click.echo("    1) Enter path to local clone")
    click.echo("    2) Clone it here")
    click.echo("    3) Abort")
    click.echo()

    choice = click.prompt("  Choice", type=str, default="3").strip()

    if choice == "1":
        path_str = click.prompt("  Path to local clone").strip()
        path = Path(path_str).expanduser().resolve()
        if not path.is_dir():
            click.echo(f"  Not a directory: {path}")
            return None
        path_slugs = _get_remote_slugs(path)
        if target_slug not in path_slugs.values():
            click.echo(f"  That directory's remotes don't match {owner}/{repo}.")
            return None
        return path

    if choice == "2":
        clone_dir = cwd / repo
        if clone_dir.exists():
            # Check if existing dir already matches
            existing_slugs = _get_remote_slugs(clone_dir)
            if target_slug in existing_slugs.values():
                click.echo(f"  Using existing clone at {clone_dir}")
                return clone_dir
            click.echo(f"  Directory {clone_dir} exists but doesn't match. Aborting.")
            return None

        click.echo(f"  Cloning {owner}/{repo} into {clone_dir}...")
        try:
            subprocess.run(
                ["git", "clone", f"https://github.com/{owner}/{repo}.git", str(clone_dir)],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            click.echo(f"  Clone failed: {exc.stderr.strip()}")
            return None
        except subprocess.TimeoutExpired:
            click.echo("  Clone timed out.")
            return None
        return clone_dir

    return None


# ---------------------------------------------------------------------------
# Fix handlers — one per check category
# ---------------------------------------------------------------------------


def _fix_safe_defaults(report: AuditReport, repo_dir: Path, summary: FixSummary) -> None:
    """Batch-fix missing community health files and templates with a single confirm."""
    owner, repo = report.owner, report.repo
    items = {item.name: item for item in report.items if item.category in ("community_health", "templates")}

    # Collect all missing safe-default files (exclude license + contributing, handled by wizards)
    pending: list[tuple[Path, str, str]] = []

    if "code_of_conduct" in items and not items["code_of_conduct"].passed:
        content = CODE_OF_CONDUCT.format(owner=owner, repo=repo)
        pending.append((repo_dir / "CODE_OF_CONDUCT.md", content, "CODE_OF_CONDUCT.md"))

    if "security" in items and not items["security"].passed:
        content = SECURITY.format(owner=owner, repo=repo)
        pending.append((repo_dir / "SECURITY.md", content, "SECURITY.md"))

    if "pr_template" in items and not items["pr_template"].passed:
        pending.append(
            (repo_dir / ".github" / "PULL_REQUEST_TEMPLATE.md", PR_TEMPLATE, ".github/PULL_REQUEST_TEMPLATE.md")
        )

    if "issue_templates" in items and not items["issue_templates"].passed:
        template_dir = repo_dir / ".github" / "ISSUE_TEMPLATE"
        pending.append((template_dir / "bug_report.yml", BUG_REPORT_YML, ".github/ISSUE_TEMPLATE/bug_report.yml"))
        pending.append(
            (template_dir / "feature_request.yml", FEATURE_REQUEST_YML, ".github/ISSUE_TEMPLATE/feature_request.yml")
        )
        pending.append((template_dir / "config.yml", CONFIG_YML, ".github/ISSUE_TEMPLATE/config.yml"))

    # Filter out files that already exist
    pending = [(p, c, lbl) for p, c, lbl in pending if not p.exists()]

    if not pending:
        return

    click.echo("  Missing community health files:")
    for _path, _content, label in pending:
        click.echo(f"    + {label}")
    click.echo()

    choice = click.prompt(
        "  Create these files? [a]ll / [s]ome / [p]review / [n]one",
        type=click.Choice(["a", "s", "p", "n"], case_sensitive=False),
        default="a",
        show_choices=False,
    )

    if choice == "n":
        return

    if choice == "p":
        for _path, content, label in pending:
            click.echo(f"\n  ── {label} ──")
            for line in content.splitlines()[:20]:
                click.echo(f"  │ {line}")
            if content.count("\n") > 20:
                click.echo(f"  │ ... ({content.count(chr(10)) - 20} more lines)")
            click.echo()
        # After preview, ask again (without preview option)
        choice = click.prompt(
            "  Create these files? [a]ll / [s]ome / [n]one",
            type=click.Choice(["a", "s", "n"], case_sensitive=False),
            default="a",
            show_choices=False,
        )

    if choice == "n":
        return

    if choice == "s":
        for path, content, label in pending:
            while True:
                per_file = click.prompt(
                    f"  {label}: [y]es / [n]o / [p]review",
                    type=click.Choice(["y", "n", "p"], case_sensitive=False),
                    default="y",
                    show_choices=False,
                )
                if per_file == "p":
                    from give_back.audit_fix.templates import preview_content

                    preview_content(content, label)
                    continue
                if per_file == "y":
                    write_file(path, content)
                    summary.local_files.append(label)
                break
        return

    # choice == "a"
    for path, content, label in pending:
        write_file(path, content)
        summary.local_files.append(label)


def _fix_license(report: AuditReport, repo_dir: Path, client: GitHubClient, summary: FixSummary) -> None:
    """Interactive license picker."""
    items = {item.name: item for item in report.items if item.category == "community_health"}
    if "license" not in items or items["license"].passed:
        return

    path = repo_dir / "LICENSE"
    if path.exists():
        click.echo("  Already exists: LICENSE — skipping")
        return

    result = pick_license(client)
    if result is None:
        return

    content, _fullname = result
    # Picker already confirmed with user, write directly (no double-prompt)
    write_file(path, content)
    summary.local_files.append("LICENSE")


def _fix_contributing(report: AuditReport, repo_dir: Path, summary: FixSummary) -> None:
    """Interactive CONTRIBUTING.md wizard."""
    items = {item.name: item for item in report.items if item.category == "community_health"}
    if "contributing" not in items or items["contributing"].passed:
        return

    path = repo_dir / "CONTRIBUTING.md"
    if path.exists():
        click.echo("  Already exists: CONTRIBUTING.md — skipping")
        return

    has_coc = (repo_dir / "CODE_OF_CONDUCT.md").exists()
    content = run_wizard(has_coc=has_coc)
    if content is None:
        return

    # Wizard already confirmed with user, write directly (no double-prompt)
    write_file(path, content)
    summary.local_files.append("CONTRIBUTING.md")


def _fix_labels(report: AuditReport, client: GitHubClient, summary: FixSummary) -> None:
    """Create missing contribution-friendly labels."""
    items = {item.name: item for item in report.items if item.category == "labels"}
    label_item = items.get("labels")
    if not label_item or label_item.passed:
        return

    missing = (label_item.metadata or {}).get("missing", [])
    if not missing:
        return

    click.echo()
    display = ", ".join(f'"{m}"' for m in missing)
    if not click.confirm(f"  Create labels on GitHub ({display})?", default=True):
        return

    created = create_labels(client, report.owner, report.repo, missing)
    summary.remote_labels.extend(created)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_FIXABLE_CATEGORIES = {"community_health", "templates", "labels"}


def walk_fixes(report: AuditReport, repo_dir: Path, client: GitHubClient) -> FixSummary:
    """Walk through failing audit checks and offer fixes interactively."""
    summary = FixSummary()

    failing = [item for item in report.items if not item.passed]
    if not failing:
        click.echo("\n  Nothing to fix!")
        return summary

    click.echo()
    click.echo("  Fixing failing checks...")
    click.echo()

    # Safe defaults: community health files + templates (single batch confirm)
    try:
        _fix_safe_defaults(report, repo_dir, summary)
    except click.Abort:
        raise
    except Exception as exc:
        click.echo(f"  Error fixing community health files: {exc}")

    # License (interactive picker)
    try:
        _fix_license(report, repo_dir, client, summary)
    except click.Abort:
        raise
    except Exception as exc:
        click.echo(f"  Error with license picker: {exc}")

    # Contributing (interactive wizard)
    try:
        _fix_contributing(report, repo_dir, summary)
    except click.Abort:
        raise
    except Exception as exc:
        click.echo(f"  Error with CONTRIBUTING wizard: {exc}")

    # Labels (remote API)
    try:
        _fix_labels(report, client, summary)
    except click.Abort:
        raise
    except Exception as exc:
        click.echo(f"  Error creating labels: {exc}")

    # Track skipped items
    for item in report.items:
        if not item.passed and item.category not in _FIXABLE_CATEGORIES:
            summary.skipped.append((item.name, "not fixable via --fix"))

    return summary


def print_fix_summary(summary: FixSummary) -> None:
    """Display what --fix created, distinguishing local vs remote changes."""
    from rich.console import Console

    console = Console()
    console.print()

    has_contributing = "CONTRIBUTING.md" in summary.local_files
    safe_files = [f for f in summary.local_files if f != "CONTRIBUTING.md"]

    if safe_files:
        console.print("  [bold green]Created locally:[/bold green]")
        for f in safe_files:
            console.print(f"    [green]+[/green] {f}")
        console.print()
        console.print("  [dim]These are usable as-is, but we recommend reviewing before you commit.[/dim]")

    if has_contributing:
        if safe_files:
            console.print()
        console.print("  [bold yellow]Created locally (requires editing):[/bold yellow]")
        console.print("    [yellow]+[/yellow] CONTRIBUTING.md")
        console.print()
        console.print("  [yellow]CONTRIBUTING.md contains placeholder text that you need to[/yellow]")
        console.print("  [yellow]fill in with your project's specifics (install steps, test[/yellow]")
        console.print("  [yellow]commands, etc.) before committing.[/yellow]")

    if summary.local_files:
        console.print()
        console.print("  [dim]None of these files are committed or pushed yet.[/dim]")

    if summary.remote_labels:
        console.print()
        console.print("  [bold cyan]Applied to GitHub (effective immediately):[/bold cyan]")
        for label in summary.remote_labels:
            console.print(f"    [cyan]+[/cyan] Label: {label}")

    if not summary.local_files and not summary.remote_labels:
        console.print("  [dim]No changes made.[/dim]")

    console.print()
