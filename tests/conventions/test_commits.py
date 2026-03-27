"""Tests for conventions/commits.py commit message analysis."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from give_back.conventions.commits import analyze_commits


def _fake_run(stdout: str, returncode: int = 0):
    """Return a mock subprocess.run that yields the given stdout."""

    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=returncode, stdout=stdout, stderr="")

    return _run


class TestAnalyzeCommits:
    """analyze_commits classifies commit style from git log output."""

    def test_conventional_commits(self):
        log = "\n".join(
            [
                "feat: add login",
                "fix: broken auth",
                "chore: update deps",
                "docs: update readme",
                "feat(auth): add OAuth",
                "fix: typo in error message",
                "refactor: extract helper",
                "ci: add GH Actions",
                "test: add unit tests",
                "build: bump version",
            ]
        )
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "conventional"

    def test_imperative_commits(self):
        log = "\n".join(
            [
                "Fix broken auth",
                "Add login page",
                "Update deps",
                "Remove unused import",
                "Refactor helper",
                "Handle edge case",
                "Improve error message",
                "Enable feature flag",
                "Rename variable",
                "Bump version",
            ]
        )
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "imperative"

    def test_mixed_commits(self):
        log = "\n".join(
            [
                "feat: add login",
                "Fix broken auth",
                "chore: update deps",
                "Add login page",
                "fix: typo",
                "Update readme",
                "docs: changelog",
                "Remove old code",
                "refactor: cleanup",
                "Bump version",
            ]
        )
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "mixed"

    def test_empty_log(self):
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run("")):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "unknown"
        assert result.examples == []

    def test_too_few_commits(self):
        log = "feat: one\nfix: two\nchore: three"
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "unknown"
        assert len(result.examples) <= 5

    def test_examples_extracted(self):
        log = "\n".join(
            [
                "feat: add login",
                "fix: broken auth",
                "chore: update deps",
                "docs: update readme",
                "feat(auth): add OAuth",
                "fix: typo in error message",
                "refactor: extract helper",
                "ci: add GH Actions",
                "test: add unit tests",
                "build: bump version",
            ]
        )
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert 3 <= len(result.examples) <= 5
        # All examples should come from the original messages.
        for example in result.examples:
            assert example in log

    def test_prefix_pattern_detected(self):
        log = "\n".join(
            [
                "feat: one",
                "feat: two",
                "feat: three",
                "fix: four",
                "feat: five",
                "feat: six",
                "feat: seven",
                "feat: eight",
                "fix: nine",
                "feat: ten",
            ]
        )
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "conventional"
        assert result.prefix_pattern == "feat:"

    def test_prefix_pattern_none_for_imperative(self):
        log = "\n".join(
            [
                "Fix broken auth",
                "Add login page",
                "Update deps",
                "Remove unused import",
                "Refactor helper",
                "Handle edge case",
            ]
        )
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert result.prefix_pattern is None

    def test_subprocess_failure(self):
        with patch(
            "give_back.conventions.commits.subprocess.run",
            side_effect=_fake_run("", returncode=128),
        ):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "unknown"

    def test_subprocess_timeout(self):
        def _timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=30)

        with patch("give_back.conventions.commits.subprocess.run", side_effect=_timeout):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "unknown"

    def test_conventional_with_scope(self):
        log = "\n".join(
            [
                "feat(auth): add OAuth",
                "fix(api): handle 404",
                "chore(deps): bump lodash",
                "docs(readme): add badge",
                "refactor(core): split module",
                "test(auth): add integration test",
            ]
        )
        with patch("give_back.conventions.commits.subprocess.run", side_effect=_fake_run(log)):
            result = analyze_commits(Path("/fake/repo"))

        assert result.style == "conventional"
