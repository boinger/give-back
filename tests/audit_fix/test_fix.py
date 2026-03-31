"""Tests for audit_fix orchestrator: resolve_repo_dir, walk_fixes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from give_back.audit import AuditItem, AuditReport
from give_back.audit_fix.fix import FixSummary, _parse_remote_slug, resolve_repo_dir, walk_fixes


class TestParseRemoteSlug:
    def test_ssh_standard(self):
        assert _parse_remote_slug("git@github.com:pallets/flask.git") == "pallets/flask"

    def test_ssh_no_dot_git(self):
        assert _parse_remote_slug("git@github.com:pallets/flask") == "pallets/flask"

    def test_https_standard(self):
        assert _parse_remote_slug("https://github.com/pallets/flask.git") == "pallets/flask"

    def test_https_no_dot_git(self):
        assert _parse_remote_slug("https://github.com/pallets/flask") == "pallets/flask"

    def test_case_insensitive(self):
        assert _parse_remote_slug("git@github.com:Pallets/Flask.git") == "pallets/flask"

    def test_invalid_url(self):
        assert _parse_remote_slug("not-a-url") is None

    def test_ssh_custom_host(self):
        assert _parse_remote_slug("git@gitlab.com:org/project.git") == "org/project"


class TestResolveRepoDir:
    def test_cwd_matches(self, tmp_path):
        """When cwd's remote matches, return cwd."""
        git_output = "origin\tgit@github.com:pallets/flask.git (fetch)\n"
        with (
            patch("give_back.audit_fix.fix.Path.cwd", return_value=tmp_path),
            patch("give_back.audit_fix.fix.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(stdout=git_output, returncode=0)
            result = resolve_repo_dir("pallets", "flask")
        assert result == tmp_path

    def test_cwd_no_match_abort(self, tmp_path):
        """When cwd doesn't match and user aborts, return None."""
        with (
            patch("give_back.audit_fix.fix.Path.cwd", return_value=tmp_path),
            patch("give_back.audit_fix.fix.subprocess.run") as mock_run,
            patch("give_back.audit_fix.fix.click.prompt", return_value="3"),
        ):
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = resolve_repo_dir("pallets", "flask")
        assert result is None


class TestWalkFixes:
    def _make_report(self, *items: tuple[str, str, bool]) -> AuditReport:
        return AuditReport(
            owner="test",
            repo="repo",
            items=[AuditItem(name=n, category=c, passed=p, message=f"{n} status") for n, c, p in items],
        )

    def test_nothing_to_fix(self, tmp_path):
        report = self._make_report(("license", "community_health", True))
        client = MagicMock()
        summary = walk_fixes(report, tmp_path, client)
        assert summary.local_files == []
        assert summary.remote_labels == []

    def test_skips_unfixable_categories(self, tmp_path):
        report = self._make_report(("staleness", "signals", False))
        client = MagicMock()
        summary = walk_fixes(report, tmp_path, client)
        assert ("staleness", "not fixable via --fix") in summary.skipped

    def test_handler_failure_continues(self, tmp_path):
        """If one handler raises, others still run."""
        report = self._make_report(
            ("code_of_conduct", "community_health", False),
            ("contributing", "community_health", False),
        )
        client = MagicMock()

        with (
            patch("give_back.audit_fix.fix._fix_safe_defaults", side_effect=RuntimeError("boom")),
            patch("give_back.audit_fix.fix._fix_contributing") as mock_contributing,
        ):
            walk_fixes(report, tmp_path, client)
            mock_contributing.assert_called_once()

    def test_fix_summary_dataclass(self):
        s = FixSummary()
        s.local_files.append("test.md")
        s.remote_labels.append("help wanted")
        s.skipped.append(("staleness", "not fixable"))
        assert len(s.local_files) == 1
        assert len(s.remote_labels) == 1
        assert len(s.skipped) == 1
