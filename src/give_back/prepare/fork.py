"""Fork management via the gh CLI.

Requires `gh` (https://cli.github.com) to be installed and authenticated.
All subprocess calls use list form — no shell injection risk.
"""

from __future__ import annotations

import subprocess
import sys

from give_back.exceptions import ForkError


def ensure_fork(owner: str, repo: str) -> str:
    """Ensure the authenticated user has a fork of *owner/repo*.

    Returns the fork owner's GitHub username. If the user already owns
    the repo, skips the fork and returns *owner* directly.

    Raises ForkError if ``gh`` is not installed or not authenticated.
    """
    # 1. Check gh is installed
    try:
        subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        raise ForkError("gh CLI required. Install: https://cli.github.com")

    # 2. Check gh is authenticated
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise ForkError("gh CLI not authenticated. Run `gh auth login`")

    # 3. Get current user
    result = subprocess.run(
        ["gh", "api", "user", "-q", ".login"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ForkError(f"Failed to get GitHub username: {result.stderr.strip()}")
    fork_owner = result.stdout.strip()

    # 4. If user owns the repo, skip fork
    if fork_owner == owner:
        print(f"You own {owner}/{repo} — skipping fork", file=sys.stderr)
        return owner

    # 5. Fork (gh handles "already forked" idempotently)
    result = subprocess.run(
        ["gh", "repo", "fork", f"{owner}/{repo}", "--clone=false"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ForkError(f"Fork failed: {result.stderr.strip()}")

    return fork_owner
