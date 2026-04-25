"""Tests for the triage CLI command — argument parsing and error paths."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli.triage import triage


class TestTriageArgParsing:
    def test_invalid_repo_arg(self):
        runner = CliRunner()
        result = runner.invoke(triage, ["not_a_repo"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_repo_arg(self):
        runner = CliRunner()
        result = runner.invoke(triage, [])
        assert result.exit_code == 2

    def test_label_option_default_none(self):
        """Verify --label is optional (default None) — invocation must not 422."""
        runner = CliRunner()
        with patch("give_back.auth.resolve_token", return_value=None):
            # Force fetch_issues to error so we don't hit the network
            with patch(
                "give_back.triage.fetch.fetch_issues",
                side_effect=RuntimeError("stop here"),
            ):
                result = runner.invoke(triage, ["pallets/flask"])
        # Click parsed args successfully; subsequent error is fine
        assert "Missing" not in result.output
