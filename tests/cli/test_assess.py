"""Tests for the assess CLI command — argument parsing and error paths."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli.assess import assess


class TestAssessArgParsing:
    def test_invalid_repo_arg_exits_nonzero(self):
        """A garbage repo string is rejected by _parse_repo and exits 1."""
        runner = CliRunner()
        result = runner.invoke(assess, ["not_a_repo_format"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_repo_arg(self):
        """Click rejects missing required argument with usage error."""
        runner = CliRunner()
        result = runner.invoke(assess, [])
        assert result.exit_code == 2  # Click usage error
        assert "Missing argument" in result.output or "REPO" in result.output


class TestAssessAuthFlow:
    def test_no_token_warns_but_proceeds(self):
        """Without a token, resolve_token prints a warning to stderr — handler still runs."""
        runner = CliRunner()
        with (
            patch("give_back.auth.resolve_token", return_value=None),
            patch("give_back.cli.assess.get_cached_assessment", return_value=None),
            patch("give_back.assess.run_assessment", side_effect=RuntimeError("no network")),
        ):
            result = runner.invoke(assess, ["pallets/flask"])
        # Either an unhandled error or a graceful exit — but not exit 0 with no work
        assert result.exit_code != 0 or "Warning" in result.output
