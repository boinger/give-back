"""Detect the merge strategy a project uses (squash / merge / rebase)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# GitHub "Merge pull request #123 from owner/branch" pattern.
_MERGE_PR_RE = re.compile(r"^[0-9a-f]+ Merge pull request #\d+", re.MULTILINE)

# GitHub squash-merge appends "(#123)" to the subject.
_SQUASH_PR_RE = re.compile(r"\(#\d+\)$")


def detect_merge_strategy(clone_dir: Path) -> str:
    """Infer the merge strategy from recent git history.

    Returns one of: ``"squash"`` / ``"merge"`` / ``"rebase"`` / ``"mixed"`` / ``"unknown"``.
    """
    # Fetch the last 30 oneline entries to look for patterns.
    try:
        oneline_result = subprocess.run(
            ["git", "log", "--oneline", "-30"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"

    if oneline_result.returncode != 0:
        return "unknown"

    oneline_output = oneline_result.stdout.strip()
    if not oneline_output:
        return "unknown"

    lines = oneline_output.splitlines()
    if len(lines) < 3:
        return "unknown"

    # Check for explicit merge commits via --merges.
    try:
        merges_result = subprocess.run(
            ["git", "log", "--merges", "--oneline", "-5"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        merges_result = None

    has_merge_commits = bool(merges_result and merges_result.returncode == 0 and merges_result.stdout.strip())

    # Count merge-PR and squash-PR patterns in the oneline output.
    merge_pr_count = len(_MERGE_PR_RE.findall(oneline_output))
    squash_pr_count = sum(1 for line in lines if _SQUASH_PR_RE.search(line))

    # Heuristics ---------------------------------------------------------
    if merge_pr_count > 0 and squash_pr_count > 0:
        return "mixed"

    if has_merge_commits or merge_pr_count > 0:
        return "merge"

    if squash_pr_count > 0:
        return "squash"

    # No merge commits, no squash markers → likely rebase (or very small repo).
    if not has_merge_commits and len(lines) >= 5:
        return "rebase"

    return "unknown"
