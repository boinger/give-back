"""Tests for the status CLI command — argument parsing and error paths."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli.status import status


class TestStatusArgParsing:
    def test_no_args_works_with_empty_workspace(self, tmp_path):
        """status with no flags scans the default workspace; empty dir → no contributions."""
        runner = CliRunner()
        # Patch resolve_token so behavior is identical regardless of caller env
        # (gh auth on localhost vs no token on CI). Otherwise the auth-warning
        # text would change result.output and make the test flaky across envs.
        with patch("give_back.cli.status.resolve_token", return_value=None):
            result = runner.invoke(status, ["--dir", str(tmp_path)])
        # Empty workspace → exit 0; output mentions contributions or "no auth token"
        assert result.exit_code == 0

    def test_json_output_with_empty_workspace(self, tmp_path):
        """status --json emits a parseable JSON document on stdout even when empty.

        Uses result.stdout (not .output) so the assertion is unaffected by any
        warning text written to stderr — Click 8.3 separates the streams.
        """
        import json

        runner = CliRunner()
        with patch("give_back.cli.status.resolve_token", return_value=None):
            result = runner.invoke(status, ["--dir", str(tmp_path), "--json"])
        assert result.exit_code == 0
        # stdout must be valid JSON; stderr (auth warning, if any) is separate.
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict) or isinstance(parsed, list)
