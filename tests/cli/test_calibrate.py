"""Tests for the calibrate CLI command — argument parsing and error paths."""

from __future__ import annotations

from click.testing import CliRunner

from give_back.cli.calibrate import calibrate


class TestCalibrateArgParsing:
    def test_missing_calibration_file(self):
        """calibrate requires a calibration file path argument."""
        runner = CliRunner()
        result = runner.invoke(calibrate, [])
        assert result.exit_code == 2
        assert "Missing argument" in result.output or "CALIBRATION_FILE" in result.output

    def test_nonexistent_file_rejected(self):
        """click.Path(exists=True) rejects a missing path with exit 2."""
        runner = CliRunner()
        result = runner.invoke(calibrate, ["/tmp/does-not-exist-123abc.yaml"])
        assert result.exit_code == 2
        assert "does not exist" in result.output or "Invalid" in result.output

    def test_existing_file_accepted_at_arg_layer(self, tmp_path):
        """A real existing file passes click's Path validation; subsequent failure is fine."""
        f = tmp_path / "calib.yaml"
        f.write_text("not real calibration content")
        runner = CliRunner()
        result = runner.invoke(calibrate, [str(f)])
        # The file exists, so click's arg parsing succeeds. The handler may
        # then fail on parsing the content — exit code != 2 (not a usage error).
        assert "does not exist" not in result.output
