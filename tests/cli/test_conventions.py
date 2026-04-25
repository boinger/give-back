"""Tests for the conventions CLI command — argument parsing and error paths."""

from __future__ import annotations

from click.testing import CliRunner

from give_back.cli.conventions import conventions


class TestConventionsArgParsing:
    def test_invalid_repo_arg(self):
        runner = CliRunner()
        result = runner.invoke(conventions, ["not_a_repo"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_repo_arg(self):
        runner = CliRunner()
        result = runner.invoke(conventions, [])
        assert result.exit_code == 2

    def test_issue_must_be_int(self):
        """--issue is typed int; non-int rejected at parse time."""
        runner = CliRunner()
        result = runner.invoke(conventions, ["pallets/flask", "--issue", "abc"])
        assert result.exit_code == 2
        assert "Invalid" in result.output or "abc" in result.output
