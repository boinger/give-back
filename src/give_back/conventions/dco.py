"""Detect DCO (Developer Certificate of Origin) sign-off requirements."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _check_commits_for_signoff(clone_dir: Path) -> bool:
    """Check if >50% of recent commits have Signed-off-by lines."""
    try:
        result = subprocess.run(
            ["git", "log", "--format=%B", "-10"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False

    if result.returncode != 0:
        return False

    raw = result.stdout.strip()
    if not raw:
        return False

    # We requested 10 commits. Estimate the actual count from double-newline
    # boundaries (git log --format=%B separates commit bodies this way).
    total_commits = min(10, max(1, raw.count("\n\n") + 1))

    # Count Signed-off-by lines. One per commit is the convention.
    signoff_lines = sum(1 for line in raw.splitlines() if line.startswith("Signed-off-by:"))

    return signoff_lines > (total_commits / 2)


def _check_ci_for_dco(clone_dir: Path) -> bool:
    """Check CI configuration for DCO bot or enforcement."""
    # Check GitHub Actions workflows for DCO references.
    workflows_dir = clone_dir / ".github" / "workflows"
    if workflows_dir.is_dir():
        for workflow_file in workflows_dir.iterdir():
            if workflow_file.suffix in (".yml", ".yaml") and workflow_file.is_file():
                try:
                    content = workflow_file.read_text(encoding="utf-8", errors="replace").lower()
                    if "probot/dco" in content or "dco-check" in content or "dco_check" in content:
                        return True
                except OSError:
                    continue

    return False


def _check_dco_file(clone_dir: Path) -> bool:
    """Check for a .dco file in the repo root."""
    return (clone_dir / ".dco").is_file()


def detect_dco(clone_dir: Path, ci_config_dir: Path | None = None) -> bool:
    """Detect whether DCO sign-off appears to be required.

    Checks three signals:
    1. Recent commits for Signed-off-by lines (>50% threshold).
    2. CI config for DCO bot references.
    3. A .dco file in the repo root.

    Args:
        clone_dir: Path to the cloned repository.
        ci_config_dir: Optional override for CI config location (unused, reserved).

    Returns:
        True if DCO sign-off appears to be required.
    """
    if _check_dco_file(clone_dir):
        return True

    if _check_ci_for_dco(clone_dir):
        return True

    return _check_commits_for_signoff(clone_dir)
