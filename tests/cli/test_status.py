"""Tests for the status CLI command — argument parsing and error paths."""

from __future__ import annotations

from click.testing import CliRunner

from give_back.cli.status import status


class TestStatusArgParsing:
    def test_no_args_works_with_empty_workspace(self, tmp_path):
        """status with no flags scans the default workspace; empty dir → no contributions."""
        runner = CliRunner()
        # Point at empty dir so we don't hit the user's actual workspace
        result = runner.invoke(status, ["--dir", str(tmp_path)])
        # Empty workspace → exit 0, no contributions message
        assert result.exit_code == 0
        assert "contribution" in result.output.lower() or "no" in result.output.lower()

    def test_json_output_with_empty_workspace(self, tmp_path):
        """status --json emits a parseable JSON document even when empty."""
        import json

        runner = CliRunner()
        result = runner.invoke(status, ["--dir", str(tmp_path), "--json"])
        assert result.exit_code == 0
        # stdout must be valid JSON
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict) or isinstance(parsed, list)
