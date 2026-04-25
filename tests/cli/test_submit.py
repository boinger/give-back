"""Tests for the submit CLI command — argument parsing and error paths."""

from __future__ import annotations

from click.testing import CliRunner

from give_back.cli.submit import submit


class TestSubmitArgParsing:
    def test_no_workspace_context_errors(self, tmp_path, monkeypatch):
        """submit requires a workspace with .give-back/context.json; missing → exit 1."""
        # Run from a tmpdir with no .give-back directory
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(submit, [])
        assert result.exit_code == 1
        assert "context" in result.output.lower() or "workspace" in result.output.lower() or "Error" in result.output

    def test_help_flag(self):
        """--help shows usage and the command's options."""
        runner = CliRunner()
        result = runner.invoke(submit, ["--help"])
        assert result.exit_code == 0
        assert "--draft" in result.output
        assert "--title" in result.output
