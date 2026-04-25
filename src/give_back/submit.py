"""Create a pull request from the current workspace using convention brief data.

Reads .give-back/context.json and brief.md to:
1. Determine the upstream repo, branch, and issue number
2. Apply conventions: commit format, DCO sign-off, PR template sections
3. Push the branch to the fork
4. Create the PR via gh CLI with the correct title, body, and labels

Requires gh CLI to be installed and authenticated.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from give_back._timeouts import NETWORK_SUBPROCESS_TIMEOUT
from give_back.exceptions import SubmitError
from give_back.prepare.lifecycle import update_context_status

_REQUIRED_CONTEXT_FIELDS = ("upstream_owner", "repo", "branch_name", "default_branch", "fork_owner")

_PR_URL_RE = re.compile(r"https://github\.com/[^/]+/[^/]+/pull/(\d+)")


@dataclass
class SubmitResult:
    """Result of a PR submission attempt."""

    pr_url: str | None = None
    pr_number: int | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.pr_url is not None


def _read_context(workspace_dir: Path) -> dict:
    """Read and validate .give-back/context.json."""
    context_file = workspace_dir / ".give-back" / "context.json"
    if not context_file.exists():
        raise SubmitError(f"Missing context file: {context_file}")

    try:
        ctx = json.loads(context_file.read_text())
    except json.JSONDecodeError as exc:
        raise SubmitError(f"Corrupt context.json: {exc}") from exc

    if not isinstance(ctx, dict):
        raise SubmitError("context.json is not a JSON object")

    missing = [f for f in _REQUIRED_CONTEXT_FIELDS if not ctx.get(f)]
    if missing:
        raise SubmitError(f"context.json missing required fields: {', '.join(missing)}")

    return ctx


def _verify_branch(workspace_dir: Path, expected: str) -> None:
    """Verify the current git branch matches the expected branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=workspace_dir,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubmitError("git branch --show-current timed out") from exc
    except FileNotFoundError as exc:
        raise SubmitError("git is not installed") from exc

    if result.returncode != 0:
        raise SubmitError(f"git branch --show-current failed: {result.stderr.strip()}")

    current = result.stdout.strip()
    if current != expected:
        raise SubmitError(f"Expected branch '{expected}', but on '{current}'")


def _check_gh_auth() -> None:
    """Verify gh CLI is authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise SubmitError("gh CLI required. Install: https://cli.github.com") from exc
    except subprocess.TimeoutExpired as exc:
        raise SubmitError("gh auth status timed out") from exc

    if result.returncode != 0:
        raise SubmitError("gh CLI not authenticated. Run `gh auth login`")


def _build_pr_title(ctx: dict) -> str:
    """Generate a PR title from context metadata."""
    branch = ctx["branch_name"]
    # Strip common prefixes
    slug = re.sub(r"^(give-back|fix)/", "", branch)

    issue_number = ctx.get("issue_number")
    if issue_number:
        return f"Fix #{issue_number}: {slug}"
    return slug


def _build_pr_body(ctx: dict, workspace_dir: Path) -> str:
    """Build PR body from the brief's PR Template section."""
    brief_path = workspace_dir / ".give-back" / "brief.md"
    template_body = ""

    if brief_path.exists():
        try:
            content = brief_path.read_text()
            # Extract "## PR Template" section
            match = re.search(r"^## PR Template\s*\n(.*?)(?=^## |\Z)", content, re.MULTILINE | re.DOTALL)
            if match:
                template_body = match.group(1).strip()
        except OSError:
            pass

    if not template_body:
        template_body = "Created with give-back."

    issue_number = ctx.get("issue_number")
    if issue_number:
        template_body += f"\n\nCloses #{issue_number}"

    return template_body


def _push_branch(workspace_dir: Path, branch_name: str) -> None:
    """Push the current branch to origin."""
    try:
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            capture_output=True,
            text=True,
            cwd=workspace_dir,
            timeout=NETWORK_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubmitError(f"git push timed out after {NETWORK_SUBPROCESS_TIMEOUT}s") from exc
    except FileNotFoundError as exc:
        raise SubmitError("git is not installed") from exc

    if result.returncode != 0:
        raise SubmitError(f"git push failed: {result.stderr.strip()}")


def _open_editor(file_path: Path) -> None:
    """Open the user's editor on a file for interactive editing."""
    try:
        result = subprocess.run(
            ["git", "var", "GIT_EDITOR"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        editor = result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        editor = ""

    if not editor:
        raise SubmitError("No editor configured. Set $EDITOR or git config core.editor.")

    try:
        # Editor doesn't capture stdout/stderr — they pass through to the terminal,
        # so we don't need text=True. We only consume the returncode.
        edit_returncode = subprocess.run(
            shlex.split(editor) + [str(file_path)],
            timeout=600,
        ).returncode
    except FileNotFoundError as exc:
        raise SubmitError(f"Editor '{editor}' not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SubmitError("Editor timed out after 10 minutes") from exc

    if edit_returncode != 0:
        raise SubmitError(f"Editor exited with code {edit_returncode}")


def _create_pr(
    workspace_dir: Path,
    owner: str,
    repo: str,
    branch: str,
    default_branch: str,
    fork_owner: str,
    title: str,
    body: str,
    draft: bool,
    edit: bool,
) -> tuple[str, int]:
    """Create a PR via gh CLI. Returns (pr_url, pr_number)."""
    tmp_path = None
    try:
        # Write body to a temp file so we can optionally edit it
        tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".md", prefix="give-back-pr-")
        tmp_path = Path(tmp_path_str)
        tmp_path.write_text(body)
        # Close the fd opened by mkstemp
        import os

        os.close(tmp_fd)

        if edit:
            _open_editor(tmp_path)

        cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            f"{owner}/{repo}",
            "--base",
            default_branch,
            "--head",
            f"{fork_owner}:{branch}",
            "--title",
            title,
            "--body-file",
            str(tmp_path),
        ]
        if draft:
            cmd.append("--draft")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=workspace_dir,
                timeout=NETWORK_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise SubmitError(f"gh pr create timed out after {NETWORK_SUBPROCESS_TIMEOUT}s") from exc
        except FileNotFoundError as exc:
            raise SubmitError("gh CLI required. Install: https://cli.github.com") from exc

        if result.returncode != 0:
            raise SubmitError(f"gh pr create failed: {result.stderr.strip()}")

        pr_url = result.stdout.strip()
        match = _PR_URL_RE.search(pr_url)
        if not match:
            raise SubmitError(f"Could not parse PR URL from gh output: {pr_url}")

        pr_number = int(match.group(1))
        return pr_url, pr_number

    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def submit_pr(
    workspace_dir: Path,
    *,
    title: str | None = None,
    draft: bool = False,
    edit: bool = False,
) -> SubmitResult:
    """Create a PR from the current workspace.

    Reads the .give-back/context.json for repo metadata and the
    contribution brief for conventions (DCO, commit format, PR template).

    If *title* is not provided, generates one from the issue title and
    branch name.

    Args:
        workspace_dir: Path to the workspace root (contains .give-back/).
        title: Optional PR title override.
        draft: If True, create as draft PR.
        edit: If True, open an editor for the PR body before submitting.

    Returns:
        SubmitResult with the PR URL on success, or error message on failure.
    """
    try:
        ctx = _read_context(workspace_dir)

        # If a PR already exists, return it without creating a duplicate
        if ctx.get("pr_url"):
            return SubmitResult(pr_url=ctx["pr_url"], pr_number=ctx.get("pr_number"))

        branch_name = ctx["branch_name"]
        _verify_branch(workspace_dir, branch_name)
        _check_gh_auth()

        pr_title = title if title else _build_pr_title(ctx)
        pr_body = _build_pr_body(ctx, workspace_dir)

        _push_branch(workspace_dir, branch_name)

        pr_url, pr_number = _create_pr(
            workspace_dir=workspace_dir,
            owner=ctx["upstream_owner"],
            repo=ctx["repo"],
            branch=branch_name,
            default_branch=ctx["default_branch"],
            fork_owner=ctx["fork_owner"],
            title=pr_title,
            body=pr_body,
            draft=draft,
            edit=edit,
        )

        update_context_status(workspace_dir, "pr_open", pr_url, pr_number)

        return SubmitResult(pr_url=pr_url, pr_number=pr_number)

    except SubmitError as exc:
        return SubmitResult(error=str(exc))
