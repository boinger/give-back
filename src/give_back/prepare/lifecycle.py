"""Workspace lifecycle management.

Tracks workspace state transitions and handles cleanup when switching
between issues in the same workspace.

State machine:
    working → pr_open → merged
                     ↘ abandoned (during re-prepare with different issue)

Decision logic for re-prepare with different issue:
    dirty working tree       → BLOCK (uncommitted changes, user must handle)
    0 commits + clean tree   → CLEAN (delete branch silently)
    unpushed commits         → BLOCK (user must commit+push or discard)
    pushed, no PR            → ARCHIVE (record + delete local branch)
    has PR (open or merged)  → ARCHIVE_PR (record PR URL + delete local branch)
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from give_back.github_client import GitHubClient

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class OldBranchState:
    """Git state of the old branch being evaluated for cleanup."""

    commits_ahead: int
    """Commits beyond upstream/default branch."""

    pushed_to_origin: bool
    """Branch exists on the origin remote."""

    has_unpushed_commits: bool
    """commits_ahead > 0 and not pushed to origin."""

    has_dirty_tree: bool
    """Uncommitted changes in the working tree."""


@dataclass
class PrInfo:
    """GitHub PR associated with a branch."""

    pr_number: int
    pr_url: str
    state: str  # "open", "closed", "merged"


class ResolveAction(Enum):
    CLEAN_NO_WORK = "clean"
    BLOCK_UNPUSHED = "block"
    ARCHIVE_PUSHED = "archive"
    ARCHIVE_PR = "archive_pr"


@dataclass
class ResolveResult:
    action: ResolveAction
    message: str
    archived_entry: dict | None = None


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def read_workspace_context(workspace_dir: Path) -> dict | None:
    """Read .give-back/context.json from a workspace directory.

    Returns the parsed dict, or None if the file doesn't exist or is invalid.
    """
    context_file = workspace_dir / ".give-back" / "context.json"
    if not context_file.exists():
        return None
    try:
        return json.loads(context_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def check_old_branch_state(
    clone_dir: Path,
    branch_name: str,
    default_branch: str,
) -> OldBranchState:
    """Determine the git state of the old branch.

    Checks: commits ahead of upstream, pushed to origin, dirty working tree.
    On any git error, returns a safe state that triggers BLOCK (don't lose data).
    """
    # Check dirty working tree
    has_dirty_tree = False
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            has_dirty_tree = True
    except (subprocess.TimeoutExpired, OSError):
        # Can't determine state — assume dirty (safe)
        return OldBranchState(commits_ahead=1, pushed_to_origin=False, has_unpushed_commits=True, has_dirty_tree=True)

    # Count commits ahead of upstream
    commits_ahead = 0
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"upstream/{default_branch}..{branch_name}"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
        if result.returncode == 0:
            commits_ahead = int(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError, ValueError):
        # Can't determine state — assume work exists (safe)
        return OldBranchState(
            commits_ahead=1, pushed_to_origin=False, has_unpushed_commits=True, has_dirty_tree=has_dirty_tree,
        )

    # Check if branch exists on origin
    pushed_to_origin = False
    try:
        result = subprocess.run(
            ["git", "branch", "-r", "--list", f"origin/{branch_name}"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            pushed_to_origin = True
    except (subprocess.TimeoutExpired, OSError):
        pass  # Assume not pushed (safe — won't delete data)

    has_unpushed = commits_ahead > 0 and not pushed_to_origin

    return OldBranchState(
        commits_ahead=commits_ahead,
        pushed_to_origin=pushed_to_origin,
        has_unpushed_commits=has_unpushed,
        has_dirty_tree=has_dirty_tree,
    )


def find_pr_for_branch(
    client: GitHubClient,
    upstream_owner: str,
    repo: str,
    fork_owner: str,
    branch_name: str,
) -> PrInfo | None:
    """Search for a PR from fork_owner:branch_name targeting upstream_owner/repo.

    Uses REST pulls endpoint (not search API) to avoid consuming search rate limit.
    Returns the most recent matching PR, or None.
    """
    try:
        prs = client.rest_get(
            f"/repos/{upstream_owner}/{repo}/pulls",
            params={
                "head": f"{fork_owner}:{branch_name}",
                "state": "all",
                "per_page": "5",
                "sort": "updated",
                "direction": "desc",
            },
        )
    except Exception:
        return None

    if not isinstance(prs, list) or not prs:
        return None

    pr = prs[0]  # Most recent
    pr_number = pr.get("number")
    html_url = pr.get("html_url", "")

    # Determine state: merged takes precedence
    if pr.get("merged_at"):
        state = "merged"
    elif pr.get("state") == "open":
        state = "open"
    else:
        state = "closed"

    return PrInfo(pr_number=pr_number, pr_url=html_url, state=state)


def resolve_old_workspace(
    clone_dir: Path,
    old_context: dict,
    client: GitHubClient | None = None,
    fork_owner: str | None = None,
) -> ResolveResult:
    """Decide how to handle an existing workspace with a different issue.

    Returns a ResolveResult indicating the action to take.
    """
    old_branch = old_context.get("branch_name", "")
    default_branch = old_context.get("default_branch", "main")
    upstream_owner = old_context.get("upstream_owner", "")
    repo = old_context.get("repo", "")
    old_issue = old_context.get("issue_number")

    if not old_branch:
        return ResolveResult(action=ResolveAction.CLEAN_NO_WORK, message="No previous branch found.")

    # Check git state of old branch
    branch_state = check_old_branch_state(clone_dir, old_branch, default_branch)

    # Dirty working tree — block regardless of commit state
    if branch_state.has_dirty_tree:
        return ResolveResult(
            action=ResolveAction.BLOCK_UNPUSHED,
            message=f"Branch '{old_branch}' (issue #{old_issue}) has uncommitted changes. "
            "Commit, stash, or discard them before switching issues.",
        )

    # No work done — clean up silently
    if branch_state.commits_ahead == 0:
        cleanup_old_branch(clone_dir, old_branch)
        return ResolveResult(
            action=ResolveAction.CLEAN_NO_WORK,
            message=f"Cleaned up empty branch '{old_branch}' (issue #{old_issue}).",
        )

    # Unpushed commits — block
    if branch_state.has_unpushed_commits:
        return ResolveResult(
            action=ResolveAction.BLOCK_UNPUSHED,
            message=f"Branch '{old_branch}' (issue #{old_issue}) has {branch_state.commits_ahead} unpushed commit(s). "
            "Push your work or discard it before switching issues.",
        )

    # Pushed — check for PR
    pr_info = None
    if client and fork_owner and upstream_owner and repo:
        pr_info = find_pr_for_branch(client, upstream_owner, repo, fork_owner, old_branch)

    if pr_info:
        pr_status = "pr_open" if pr_info.state == "open" else pr_info.state
        archived = archive_current_issue(old_context, pr_status, pr_info.pr_url)
        cleanup_old_branch(clone_dir, old_branch)
        return ResolveResult(
            action=ResolveAction.ARCHIVE_PR,
            message=f"Archived issue #{old_issue} (PR {pr_info.pr_url}, {pr_info.state}). "
            f"Branch '{old_branch}' cleaned up.",
            archived_entry=archived,
        )

    # Pushed but no PR found
    archived = archive_current_issue(old_context, "abandoned", None)
    cleanup_old_branch(clone_dir, old_branch)
    return ResolveResult(
        action=ResolveAction.ARCHIVE_PUSHED,
        message=f"Archived issue #{old_issue} (pushed but no PR). Branch '{old_branch}' cleaned up.",
        archived_entry=archived,
    )


def archive_current_issue(context: dict, status: str, pr_url: str | None) -> dict:
    """Create an archive entry for the current issue.

    Returns the entry dict (for appending to previous_issues).
    """
    return {
        "issue_number": context.get("issue_number"),
        "branch_name": context.get("branch_name"),
        "status": status,
        "pr_url": pr_url,
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }


def cleanup_old_branch(clone_dir: Path, branch_name: str) -> None:
    """Delete a local branch. Safe to call even if branch doesn't exist."""
    try:
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass  # Best-effort cleanup


def update_context_status(
    workspace_dir: Path,
    status: str,
    pr_url: str | None = None,
    pr_number: int | None = None,
) -> None:
    """Update status, pr_url, pr_number, and updated_at in context.json."""
    context_file = workspace_dir / ".give-back" / "context.json"
    try:
        context = json.loads(context_file.read_text())
        context["status"] = status
        context["updated_at"] = datetime.now(timezone.utc).isoformat()
        if pr_url is not None:
            context["pr_url"] = pr_url
        if pr_number is not None:
            context["pr_number"] = pr_number
        context_file.write_text(json.dumps(context, indent=2) + "\n")
    except (json.JSONDecodeError, OSError, KeyError):
        pass  # Non-critical — check command will warn


_GITHUB_REMOTE_RE = re.compile(
    r"(?:git@github\.com:|https://github\.com/)([^/]+)/([^/.]+?)(?:\.git)?$"
)


def parse_fork_owner_from_remote(clone_dir: Path) -> str | None:
    """Extract the fork owner from the origin remote URL.

    Handles both SSH and HTTPS GitHub URLs. Returns the owner or None.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        match = _GITHUB_REMOTE_RE.match(result.stdout.strip())
        if match:
            return match.group(1)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None
