"""Workspace setup: clone fork, add upstream remote, create branch.

All git operations use subprocess with list-form arguments (no shell).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from give_back.conventions.models import BranchConvention
from give_back.exceptions import WorkspaceError

_GITHUB_SLUG_RE = re.compile(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/.]+?)(?:\.git)?$")


def _normalize_github_url(url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub URL (SSH or HTTPS). Returns None if not GitHub."""
    match = _GITHUB_SLUG_RE.match(url.strip())
    return match.group(1) if match else None


def setup_workspace(
    fork_owner: str,
    repo: str,
    upstream_owner: str,
    branch_name: str,
    default_branch: str,
    workspace_dir: str | Path,
    fork_repo: str | None = None,
) -> Path:
    """Set up a contribution workspace: clone, remotes, branch.

    *workspace_dir* is the parent (e.g., ``~/give-back-workspaces``).
    The actual clone goes to ``workspace_dir/upstream_owner/repo/``.
    *fork_repo* is the actual fork repo name, which may differ from *repo*
    if the fork was renamed (e.g., ``alloy`` → ``grafana-alloy``).

    Returns the clone directory Path.

    Raises WorkspaceError on clone failure, wrong remote, or dirty branch.
    """
    effective_fork_repo = fork_repo or repo
    workspace_dir = Path(workspace_dir).expanduser()
    clone_dir = workspace_dir / upstream_owner / repo

    upstream_url = f"https://github.com/{upstream_owner}/{repo}.git"

    if clone_dir.exists():
        # Check for correct upstream remote
        result = subprocess.run(
            ["git", "remote", "get-url", "upstream"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
        )
        if result.returncode != 0:
            raise WorkspaceError(
                f"Directory {clone_dir} exists but has no 'upstream' remote. Move or remove it and re-run."
            )

        actual_url = result.stdout.strip()
        actual_slug = _normalize_github_url(actual_url)
        expected_slug = f"{upstream_owner}/{repo}"
        if actual_slug != expected_slug:
            raise WorkspaceError(
                f"Directory {clone_dir} has upstream remote pointing to {actual_url}, "
                f"expected {expected_slug}. Move or remove it and re-run."
            )

        # Existing workspace — fetch upstream
        try:
            result = subprocess.run(
                ["git", "fetch", "upstream"],
                capture_output=True,
                text=True,
                cwd=clone_dir,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise WorkspaceError("git fetch upstream timed out after 60s")
        if result.returncode != 0:
            raise WorkspaceError(f"git fetch upstream failed: {result.stderr.strip()}")
    else:
        # Fresh setup
        fork_url = f"https://github.com/{fork_owner}/{effective_fork_repo}.git"
        clone_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                ["git", "clone", fork_url, str(clone_dir)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            shutil.rmtree(clone_dir, ignore_errors=True)
            raise WorkspaceError("git clone timed out after 120s")
        if result.returncode != 0:
            raise WorkspaceError(f"Clone failed: {result.stderr.strip()}")

        result = subprocess.run(
            ["git", "remote", "add", "upstream", upstream_url],
            capture_output=True,
            text=True,
            cwd=clone_dir,
        )
        if result.returncode != 0:
            raise WorkspaceError(f"Failed to add upstream remote: {result.stderr.strip()}")

        try:
            result = subprocess.run(
                ["git", "fetch", "upstream"],
                capture_output=True,
                text=True,
                cwd=clone_dir,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise WorkspaceError("git fetch upstream timed out after 60s")
        if result.returncode != 0:
            raise WorkspaceError(f"git fetch upstream failed: {result.stderr.strip()}")

    # Branch creation
    result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        capture_output=True,
        text=True,
        cwd=clone_dir,
    )
    branch_exists = bool(result.stdout.strip())

    if branch_exists:
        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
        )
        if result.stdout.strip():
            raise WorkspaceError("Branch has uncommitted changes — commit or stash first")

        subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            check=True,
        )
        try:
            result = subprocess.run(
                ["git", "pull", "--rebase", f"upstream/{default_branch}"],
                capture_output=True,
                text=True,
                cwd=clone_dir,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise WorkspaceError("git pull --rebase timed out after 60s")
        if result.returncode != 0:
            raise WorkspaceError(f"git pull --rebase failed (possible conflict): {result.stderr.strip()}")
    else:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name, f"upstream/{default_branch}"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
        )
        if result.returncode != 0:
            raise WorkspaceError(f"Branch creation failed: {result.stderr.strip()}")

    return clone_dir


def generate_branch_name(convention: BranchConvention, issue_number: int, issue_title: str) -> str:
    """Generate a branch name from convention pattern, issue number, and title.

    Slugifies the title: lowercase, non-alphanum → hyphens, collapsed,
    stripped, truncated to 50 chars.
    """
    slug = _slugify(issue_title)

    if convention.pattern == "type/description":
        return f"fix/{issue_number}-{slug}"
    elif convention.pattern == "issue-description":
        return f"{issue_number}-{slug}"
    else:
        return f"give-back/{issue_number}-{slug}"


def _slugify(text: str, max_length: int = 50) -> str:
    """Convert text to a URL/branch-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    # Truncate without breaking mid-word if possible
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug
