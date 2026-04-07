"""Regression tests for the audit Click group: parser bug + cwd auto-detect.

The original bug: `give-back audit pallets/flask --verbose` failed with
"No such command '--verbose'" because Click groups with positional + options
fall into subcommand-search mode after consuming the positional.

These tests use CliRunner to validate the actual end-to-end CLI parsing,
not just helper unit tests.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli import cli


class TestAuditParserBugRegression:
    """The actual bug fix: option-after-positional must work."""

    @patch("give_back.cli.audit._run_audit_repo")
    def test_audit_repo_then_verbose(self, mock_run):
        """Regression: `audit pallets/flask --verbose` must parse and route correctly."""
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "pallets/flask", "--verbose"])
        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        # Production code uses kwargs, so this assertion is precise and refactor-safe
        kwargs = mock_run.call_args.kwargs
        assert kwargs["owner"] == "pallets"
        assert kwargs["repo_name"] == "flask"
        assert kwargs["verbose"] is True

    @patch("give_back.cli.audit._run_audit_repo")
    def test_audit_verbose_then_repo(self, mock_run):
        """Backward compat: option-first ordering should also still work."""
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "--verbose", "pallets/flask"])
        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["owner"] == "pallets"
        assert kwargs["repo_name"] == "flask"
        assert kwargs["verbose"] is True

    @patch("give_back.cli.audit._run_audit_repo")
    def test_audit_with_multiple_options_after_positional(self, mock_run):
        """Multiple options after positional should all be parsed."""
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "pallets/flask", "--verbose", "--json"])
        assert result.exit_code == 0, result.output
        kwargs = mock_run.call_args.kwargs
        assert kwargs["verbose"] is True
        assert kwargs["json_output"] is True

    @patch("give_back.cli.audit._run_audit_repo")
    def test_audit_with_compare_after_positional(self, mock_run):
        """--compare with value, after positional."""
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "pallets/flask", "--compare", "django/django"])
        assert result.exit_code == 0, result.output
        kwargs = mock_run.call_args.kwargs
        assert kwargs["owner"] == "pallets"
        assert kwargs["repo_name"] == "flask"
        assert kwargs["compare"] == "django/django"

    @patch("give_back.cli.audit._run_audit_repo")
    def test_explicit_audit_repo_subcommand(self, mock_run):
        """`audit repo pallets/flask` (explicit form) still works."""
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "repo", "pallets/flask"])
        assert result.exit_code == 0, result.output
        kwargs = mock_run.call_args.kwargs
        assert kwargs["owner"] == "pallets"
        assert kwargs["repo_name"] == "flask"


class TestAuditCwdAutoDetect:
    @patch("give_back.cli.audit.detect_repo_from_cwd")
    @patch("give_back.cli.audit._run_audit_repo")
    def test_audit_no_repo_uses_cwd(self, mock_run, mock_detect):
        """`audit` (no args) auto-detects from cwd."""
        mock_detect.return_value = ("boinger", "give-back")
        runner = CliRunner()
        result = runner.invoke(cli, ["audit"])
        assert result.exit_code == 0, result.output
        mock_detect.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["owner"] == "boinger"
        assert kwargs["repo_name"] == "give-back"

    @patch("give_back.cli.audit.detect_repo_from_cwd")
    @patch("give_back.cli.audit._run_audit_repo")
    def test_audit_no_repo_with_options_uses_cwd(self, mock_run, mock_detect):
        """`audit --verbose` (no positional, only options) auto-detects."""
        mock_detect.return_value = ("boinger", "give-back")
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "--verbose"])
        assert result.exit_code == 0, result.output
        kwargs = mock_run.call_args.kwargs
        assert kwargs["owner"] == "boinger"
        assert kwargs["verbose"] is True

    @patch("give_back.cli.audit.detect_repo_from_cwd")
    def test_audit_no_repo_no_cwd_errors_clearly(self, mock_detect):
        """When cwd has no GitHub remote, error message is clear and actionable."""
        mock_detect.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["audit"])
        assert result.exit_code == 1
        assert "could not auto-detect" in result.output.lower()
        assert "owner/repo" in result.output  # tells user the alternative

    @patch("give_back.cli.audit.detect_repo_from_cwd")
    @patch("give_back.cli.audit._run_audit_repo")
    def test_explicit_repo_overrides_cwd_detect(self, mock_run, mock_detect):
        """When repo is given explicitly, cwd detect is NOT called."""
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "pallets/flask"])
        assert result.exit_code == 0, result.output
        mock_detect.assert_not_called()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["owner"] == "pallets"
        assert kwargs["repo_name"] == "flask"


class TestAuditFixCwdAutoDetect:
    """The same auto-detect pattern applies to `audit fix`."""

    @patch("give_back.cli.audit.detect_repo_from_cwd")
    def test_audit_fix_no_repo_no_cwd_errors(self, mock_detect):
        """`audit fix` with no positional and no cwd repo → clear error."""
        mock_detect.return_value = None
        runner = CliRunner()
        # audit fix also requires interactive terminal; CliRunner is not a tty,
        # so we expect the tty check OR the cwd error. Either is acceptable.
        result = runner.invoke(cli, ["audit", "fix"])
        assert result.exit_code == 1
        assert "interactive" in result.output.lower() or "auto-detect" in result.output.lower()
