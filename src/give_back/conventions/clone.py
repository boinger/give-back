"""Shallow clone management for convention scanning.

Clones to a temp directory with --depth 50 (enough for commit history analysis).
Context manager handles cleanup.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class CloneError(Exception):
    """Failed to clone the repository."""


@contextmanager
def cloned_repo(owner: str, repo: str, keep: bool = False, depth: int = 50) -> Iterator[Path]:
    """Clone a repo to a temp directory and yield the path.

    Args:
        owner: Repository owner.
        repo: Repository name.
        keep: If True, don't delete the clone on exit.
        depth: Git clone depth (default 50 for commit history analysis).

    Yields:
        Path to the cloned repository directory.

    Raises:
        CloneError: If the clone fails.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix=f"give-back-{owner}-{repo}-"))
    clone_dir = tmpdir / repo

    try:
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                str(depth),
                "--single-branch",
                f"https://github.com/{owner}/{repo}.git",
                str(clone_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise CloneError(f"Failed to clone {owner}/{repo}: {result.stderr.strip()}")

        yield clone_dir

    except subprocess.TimeoutExpired as exc:
        raise CloneError(f"Clone of {owner}/{repo} timed out after 120s") from exc

    finally:
        if not keep and tmpdir.exists():
            shutil.rmtree(tmpdir, ignore_errors=True)


def get_default_branch(clone_dir: Path) -> str:
    """Get the default branch name from a cloned repo."""
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        cwd=clone_dir,
        timeout=10,
    )
    if result.returncode == 0:
        # refs/remotes/origin/main → main
        ref = result.stdout.strip()
        return ref.split("/")[-1]
    return "main"
