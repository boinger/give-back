"""Detect DCO (Developer Certificate of Origin) sign-off requirements."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from give_back.conventions._contributing import iter_contributing_md

_REQUIRED_SIGNOFF_RE = re.compile(
    r"(must|required|require)[^.]*signed-off-by",
    re.IGNORECASE,
)


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
    workflows_dir = clone_dir / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return False
    for workflow_file in workflows_dir.iterdir():
        if workflow_file.suffix not in (".yml", ".yaml") or not workflow_file.is_file():
            continue
        if _workflow_mentions_dco(workflow_file):
            return True
    return False


def _workflow_mentions_dco(workflow_file: Path) -> bool:
    """Return True if the workflow file references a known DCO bot or check."""
    try:
        content = workflow_file.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return "probot/dco" in content or "dco-check" in content or "dco_check" in content


def _check_dco_file(clone_dir: Path) -> bool:
    """Check for a .dco file in the repo root."""
    return (clone_dir / ".dco").is_file()


def _check_contributing_for_dco(clone_dir: Path) -> bool:
    """Search CONTRIBUTING.md variants for DCO requirements.

    Two signals (in order of confidence):
    1. Literal phrase "developer certificate of origin" — used by Kubernetes,
       Docker, CNCF projects, grafana/tempo, and the overwhelming majority of
       DCO-requiring projects. High-confidence match.
    2. Requirement regex: ``(must|required|require)[^.]*signed-off-by`` —
       catches projects that document DCO without the literal phrase while
       rejecting example-only mentions like "your commits should look like:
       Signed-off-by: ...".
    """
    for original in iter_contributing_md(clone_dir):
        content = original.lower()
        if "developer certificate of origin" in content:
            return True
        # Requirement regex already uses re.IGNORECASE, but run it on
        # lowercased content for consistency with the phrase check.
        if _REQUIRED_SIGNOFF_RE.search(content):
            return True
    return False


def detect_dco(clone_dir: Path, ci_config_dir: Path | None = None) -> bool:
    """Detect whether DCO sign-off appears to be required.

    Checks four signals in priority order (cheap-and-definitive to noisy):
    1. A ``.dco`` file in the repo root.
    2. CI config for DCO bot references.
    3. CONTRIBUTING.md variants for DCO requirement phrasing.
    4. Recent commits for Signed-off-by lines (>50% threshold).

    Signal 3 runs before signal 4 because reading a file is cheaper than
    spawning a ``git log`` subprocess, and a documentation-level signal is
    more reliable than commit-history heuristics (which miss projects that
    only recently adopted DCO).

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

    if _check_contributing_for_dco(clone_dir):
        return True

    return _check_commits_for_signoff(clone_dir)
