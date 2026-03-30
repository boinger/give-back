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
    write_if_missing,
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


def _fix_community_health(report: AuditReport, repo_dir: Path, summary: FixSummary) -> None:
    """Fix missing community health files."""
    owner, repo = report.owner, report.repo
    items = {item.name: item for item in report.items if item.category == "community_health"}

    if "code_of_conduct" in items and not items["code_of_conduct"].passed:
        content = CODE_OF_CONDUCT.format(owner=owner, repo=repo)
        if write_if_missing(repo_dir / "CODE_OF_CONDUCT.md", content, "CODE_OF_CONDUCT.md"):
            summary.local_files.append("CODE_OF_CONDUCT.md")

    if "security" in items and not items["security"].passed:
        content = SECURITY.format(owner=owner, repo=repo)
        if write_if_missing(repo_dir / "SECURITY.md", content, "SECURITY.md"):
            summary.local_files.append("SECURITY.md")


def _fix_templates(report: AuditReport, repo_dir: Path, summary: FixSummary) -> None:
    """Fix missing PR and issue templates."""
    items = {item.name: item for item in report.items if item.category == "templates"}

    if "pr_template" in items and not items["pr_template"].passed:
        path = repo_dir / ".github" / "PULL_REQUEST_TEMPLATE.md"
        if write_if_missing(path, PR_TEMPLATE, ".github/PULL_REQUEST_TEMPLATE.md"):
            summary.local_files.append(".github/PULL_REQUEST_TEMPLATE.md")

    if "issue_templates" in items and not items["issue_templates"].passed:
        template_dir = repo_dir / ".github" / "ISSUE_TEMPLATE"
        files = [
            (template_dir / "bug_report.yml", BUG_REPORT_YML, ".github/ISSUE_TEMPLATE/bug_report.yml"),
            (template_dir / "feature_request.yml", FEATURE_REQUEST_YML, ".github/ISSUE_TEMPLATE/feature_request.yml"),
            (template_dir / "config.yml", CONFIG_YML, ".github/ISSUE_TEMPLATE/config.yml"),
        ]
        for path, content, label in files:
            if write_if_missing(path, content, label):
                summary.local_files.append(label)


def _fix_license(report: AuditReport, repo_dir: Path, client: GitHubClient, summary: FixSummary) -> None:
    """Interactive license picker."""
    items = {item.name: item for item in report.items if item.category == "community_health"}
    if "license" not in items or items["license"].passed:
        return

    result = pick_license(client)
    if result is None:
        return

    content, _fullname = result
    if write_if_missing(repo_dir / "LICENSE", content, "LICENSE"):
        summary.local_files.append("LICENSE")


def _fix_contributing(report: AuditReport, repo_dir: Path, summary: FixSummary) -> None:
    """Interactive CONTRIBUTING.md wizard."""
    items = {item.name: item for item in report.items if item.category == "community_health"}
    if "contributing" not in items or items["contributing"].passed:
        return

    content = run_wizard()
    if content is None:
        return

    if write_if_missing(repo_dir / "CONTRIBUTING.md", content, "CONTRIBUTING.md"):
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

    # Community health files (except license and contributing, handled separately)
    try:
        _fix_community_health(report, repo_dir, summary)
    except click.Abort:
        raise
    except Exception as exc:
        click.echo(f"  Error fixing community health files: {exc}")

    # Templates
    try:
        _fix_templates(report, repo_dir, summary)
    except click.Abort:
        raise
    except Exception as exc:
        click.echo(f"  Error fixing templates: {exc}")

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
    click.echo()

    if summary.local_files:
        click.echo("  Created locally (commit and push to apply):")
        for f in summary.local_files:
            click.echo(f"    + {f}")

    if summary.remote_labels:
        click.echo()
        click.echo("  Applied to GitHub (effective immediately):")
        for label in summary.remote_labels:
            click.echo(f"    + Label: {label}")

    if not summary.local_files and not summary.remote_labels:
        click.echo("  No changes made.")

    click.echo()
