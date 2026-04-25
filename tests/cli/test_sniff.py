"""Tests for the sniff CLI command — argument parsing and error paths."""

from __future__ import annotations

from click.testing import CliRunner

from give_back.cli.sniff import sniff


class TestSniffArgParsing:
    def test_invalid_repo_arg(self):
        runner = CliRunner()
        result = runner.invoke(sniff, ["not_a_repo", "1"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_issue_number(self):
        """sniff requires both repo AND issue_number."""
        runner = CliRunner()
        result = runner.invoke(sniff, ["pallets/flask"])
        assert result.exit_code == 2
        assert "ISSUE_NUMBER" in result.output or "Missing" in result.output

    def test_non_integer_issue_number(self):
        """Click's type=int rejects non-integer issue_number with usage error."""
        runner = CliRunner()
        result = runner.invoke(sniff, ["pallets/flask", "abc"])
        assert result.exit_code == 2
        assert "Invalid" in result.output or "abc" in result.output
