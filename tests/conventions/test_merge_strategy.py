"""Tests for conventions/merge_strategy.py merge strategy detection."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from give_back.conventions.merge_strategy import detect_merge_strategy


def _make_fake_run(oneline_stdout: str, merges_stdout: str = ""):
    """Return a mock subprocess.run that dispatches based on the git command."""

    def _run(cmd, **kwargs):
        if "--merges" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=merges_stdout, stderr="")
        # Default: --oneline log
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=oneline_stdout, stderr="")

    return _run


class TestDetectMergeStrategy:
    """detect_merge_strategy classifies from git log patterns."""

    def test_merge_strategy(self):
        oneline = "\n".join(
            [
                "abc1234 Merge pull request #42 from user/branch",
                "def5678 Fix typo",
                "ghi9012 Merge pull request #41 from user/other",
                "jkl3456 Add feature",
                "mno7890 Merge pull request #40 from user/fix",
            ]
        )
        merges = "\n".join(
            [
                "abc1234 Merge pull request #42 from user/branch",
                "ghi9012 Merge pull request #41 from user/other",
                "mno7890 Merge pull request #40 from user/fix",
            ]
        )
        with patch(
            "give_back.conventions.merge_strategy.subprocess.run",
            side_effect=_make_fake_run(oneline, merges),
        ):
            assert detect_merge_strategy(Path("/fake/repo")) == "merge"

    def test_squash_strategy(self):
        oneline = "\n".join(
            [
                "abc1234 Fix login bug (#42)",
                "def5678 Add feature (#41)",
                "ghi9012 Update deps (#40)",
                "jkl3456 Refactor auth (#39)",
                "mno7890 Improve logging (#38)",
            ]
        )
        with patch(
            "give_back.conventions.merge_strategy.subprocess.run",
            side_effect=_make_fake_run(oneline, merges_stdout=""),
        ):
            assert detect_merge_strategy(Path("/fake/repo")) == "squash"

    def test_mixed_strategy(self):
        oneline = "\n".join(
            [
                "abc1234 Merge pull request #42 from user/branch",
                "def5678 Fix login bug (#41)",
                "ghi9012 Add feature",
                "jkl3456 Update deps (#39)",
                "mno7890 Another commit",
            ]
        )
        merges = "abc1234 Merge pull request #42 from user/branch"
        with patch(
            "give_back.conventions.merge_strategy.subprocess.run",
            side_effect=_make_fake_run(oneline, merges),
        ):
            assert detect_merge_strategy(Path("/fake/repo")) == "mixed"

    def test_unknown_few_commits(self):
        oneline = "abc1234 Initial commit\ndef5678 Second commit"
        with patch(
            "give_back.conventions.merge_strategy.subprocess.run",
            side_effect=_make_fake_run(oneline, merges_stdout=""),
        ):
            assert detect_merge_strategy(Path("/fake/repo")) == "unknown"

    def test_empty_repo(self):
        with patch(
            "give_back.conventions.merge_strategy.subprocess.run",
            side_effect=_make_fake_run("", merges_stdout=""),
        ):
            assert detect_merge_strategy(Path("/fake/repo")) == "unknown"

    def test_rebase_strategy(self):
        """No merge commits, no squash markers, enough commits → rebase."""
        oneline = "\n".join(
            [
                "abc1234 Fix typo",
                "def5678 Add feature",
                "ghi9012 Update deps",
                "jkl3456 Refactor auth",
                "mno7890 Improve logging",
            ]
        )
        with patch(
            "give_back.conventions.merge_strategy.subprocess.run",
            side_effect=_make_fake_run(oneline, merges_stdout=""),
        ):
            assert detect_merge_strategy(Path("/fake/repo")) == "rebase"

    def test_subprocess_failure(self):
        def _fail(cmd, **kwargs):
            return subprocess.CompletedProcess(args=cmd, returncode=128, stdout="", stderr="fatal")

        with patch("give_back.conventions.merge_strategy.subprocess.run", side_effect=_fail):
            assert detect_merge_strategy(Path("/fake/repo")) == "unknown"

    def test_subprocess_timeout(self):
        def _timeout(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=30)

        with patch("give_back.conventions.merge_strategy.subprocess.run", side_effect=_timeout):
            assert detect_merge_strategy(Path("/fake/repo")) == "unknown"
