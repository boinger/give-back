"""Fork management via the gh CLI.

Requires `gh` (https://cli.github.com) to be installed and authenticated.
All subprocess calls use list form — no shell injection risk.
"""

from __future__ import annotations

import subprocess
import sys

from give_back.exceptions import ForkError


def ensure_fork(owner: str, repo: str) -> tuple[str, str]:
    """Ensure the authenticated user has a fork of *owner/repo*.

    Returns ``(fork_owner, fork_repo)`` — the owner's username and the
    actual fork repo name (which GitHub may rename, e.g. ``alloy`` →
    ``grafana-alloy``). If the user already owns the repo, returns
    ``(owner, repo)`` directly.

    Raises ForkError if ``gh`` is not installed or not authenticated.
    """
    # 1. Check gh is installed
    try:
        subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise ForkError("gh CLI required. Install: https://cli.github.com")
    except subprocess.TimeoutExpired:
        raise ForkError("gh --version timed out after 10s")

    # 2. Check gh is authenticated
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise ForkError("gh auth status timed out after 10s")
    if result.returncode != 0:
        raise ForkError("gh CLI not authenticated. Run `gh auth login`")

    # 3. Get current user
    try:
        result = subprocess.run(
            ["gh", "api", "user", "-q", ".login"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise ForkError("gh api user timed out after 30s")
    if result.returncode != 0:
        raise ForkError(f"Failed to get GitHub username: {result.stderr.strip()}")
    fork_owner = result.stdout.strip()

    # 4. If user owns the repo, skip fork
    if fork_owner == owner:
        print(f"You own {owner}/{repo} — skipping fork", file=sys.stderr)
        return owner, repo

    # 5. Fork (gh handles "already forked" idempotently)
    try:
        result = subprocess.run(
            ["gh", "repo", "fork", f"{owner}/{repo}", "--clone=false"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise ForkError("gh repo fork timed out after 60s")
    if result.returncode != 0:
        raise ForkError(f"Fork failed: {result.stderr.strip()}")

    # 6. Get actual fork name (GitHub may rename, e.g. "alloy" → "grafana-alloy")
    fork_repo = _resolve_fork_name(fork_owner, owner, repo)

    return fork_owner, fork_repo


def _resolve_fork_name(fork_owner: str, upstream_owner: str, upstream_repo: str) -> str:
    """Query GitHub API for the actual fork repo name.

    GitHub can rename forks to avoid collisions (e.g. ``alloy`` → ``grafana-alloy``).
    Falls back to the upstream repo name if the API call fails.
    """
    # Try the obvious name first
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{fork_owner}/{upstream_repo}", "-q", ".name"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return upstream_repo
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    # Repo was renamed. Search the user's forks for one whose parent matches.
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{upstream_owner}/{upstream_repo}/forks",
                "-q",
                f'.[] | select(.owner.login == "{fork_owner}") | .name',
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return upstream_repo
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()[0]

    # Last resort: assume name matches upstream
    return upstream_repo
