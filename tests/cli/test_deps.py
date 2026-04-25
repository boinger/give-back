"""Tests for the deps CLI command — argument parsing and error paths."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli.deps import deps


class TestDepsArgParsing:
    def test_invalid_repo_arg(self):
        runner = CliRunner()
        result = runner.invoke(deps, ["not_a_repo"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_repo_arg(self):
        runner = CliRunner()
        result = runner.invoke(deps, [])
        assert result.exit_code == 2

    def test_no_token_errors(self):
        """deps requires authentication; without a token it must error.

        Patch the binding inside cli.deps (where resolve_token was imported),
        not the source in give_back.auth — the former is what the handler sees.
        """
        runner = CliRunner()
        with patch("give_back.cli.deps.resolve_token", return_value=None):
            result = runner.invoke(deps, ["pallets/flask"])
        assert result.exit_code == 1
        assert "auth" in result.output.lower() or "token" in result.output.lower()
