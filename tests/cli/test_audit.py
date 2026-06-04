"""Tests for the audit fix CLI command — fix-walk orchestration.

Characterization tests pinned before extracting the fix-walk block into a
helper — see plans/PLAN-sloppylint-cleanup.md (these lines were previously
uncovered).

The command gates on a real TTY (`sys.stdin.isatty()`), which CliRunner cannot
simulate, so the orchestration tests call the click callback directly with
sys.stdin patched; the TTY gate itself is pinned through CliRunner where the
gate failing IS the expected behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner

from give_back.cli.audit import audit_fix


def _report(has_failures: bool) -> SimpleNamespace:
    items = [SimpleNamespace(name="license", passed=True)]
    if has_failures:
        items.append(SimpleNamespace(name="contributing", passed=False))
    return SimpleNamespace(items=items)


class TestAuditFixWalk:
    def _run_fix(self, report, repo_dir, walk_error=None):
        summary = object()
        walk_kwargs = {"side_effect": walk_error} if walk_error else {"return_value": summary}

        with (
            patch("sys.stdin", MagicMock(isatty=MagicMock(return_value=True))),
            patch("give_back.cli.audit._resolve_repo_or_exit", return_value=("org", "project")),
            patch("give_back.cli.audit.resolve_token", return_value="tok"),
            patch("give_back.cli.audit.GitHubClient"),
            patch("give_back.audit.run_audit", return_value=report),
            patch("give_back.audit_fix.resolver.TemplateResolver"),
            patch("give_back.audit_fix.fix.resolve_repo_dir", return_value=repo_dir),
            patch("give_back.audit_fix.fix.walk_fixes", **walk_kwargs) as mock_walk,
            patch("give_back.audit_fix.fix.print_fix_summary") as mock_summary,
        ):
            audit_fix.callback(
                repo="org/project", verbose=False, conventions=False, template_repo=None, template_dir=None
            )
        return summary, mock_walk, mock_summary

    def test_failures_walk_fixes_and_print_summary(self, tmp_path):
        """With failing items and a resolvable repo dir, fixes are walked and summarized."""
        summary, mock_walk, mock_summary = self._run_fix(_report(has_failures=True), repo_dir=tmp_path)
        mock_walk.assert_called_once()
        mock_summary.assert_called_once()
        assert mock_summary.call_args[0][0] is summary

    def test_nothing_to_fix_skips_walk(self, tmp_path):
        """All items passing: no fix walk, no summary."""
        _summary, mock_walk, mock_summary = self._run_fix(_report(has_failures=False), repo_dir=tmp_path)
        mock_walk.assert_not_called()
        mock_summary.assert_not_called()

    def test_unresolvable_repo_dir_skips_walk(self):
        """Failures present but no local repo dir: walk is skipped."""
        _summary, mock_walk, _mock_summary = self._run_fix(_report(has_failures=True), repo_dir=None)
        mock_walk.assert_not_called()

    def test_interrupt_during_walk_is_handled(self, tmp_path):
        """click.Abort mid-walk prints 'Interrupted.' instead of propagating."""
        _summary, mock_walk, mock_summary = self._run_fix(
            _report(has_failures=True), repo_dir=tmp_path, walk_error=click.Abort()
        )
        mock_walk.assert_called_once()
        mock_summary.assert_not_called()


class TestAuditFixGates:
    def test_non_tty_exits_1(self):
        """Under CliRunner stdin is not a TTY — the command refuses to run."""
        runner = CliRunner()
        result = runner.invoke(audit_fix, ["org/project"])
        assert result.exit_code == 1
        assert "interactive terminal" in result.output

    def test_mutually_exclusive_template_flags_exit_1(self, tmp_path):
        """--template-repo and --template-dir together are rejected before the TTY gate."""
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        runner = CliRunner()
        result = runner.invoke(
            audit_fix, ["org/project", "--template-repo", "o/std", "--template-dir", str(template_dir)]
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output
