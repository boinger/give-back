"""Tests for the check CLI command — specifically --ack cla behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli.check import check


def _setup_workspace(tmp_path: Path, cla_required: bool = True, cla_system: str = "cla-assistant") -> Path:
    """Create a minimal workspace with .give-back/context.json."""
    give_back_dir = tmp_path / ".give-back"
    give_back_dir.mkdir()

    context = {
        "upstream_owner": "org",
        "repo": "project",
        "issue_number": 1,
        "branch_name": "fix/1-test",
        "default_branch": "main",
        "dco_required": False,
        "cla_required": cla_required,
        "cla_system": cla_system if cla_required else None,
        "cla_signing_url": "https://cla-assistant.io/org/project" if cla_required else None,
        "ci_commands": [],
        "status": "working",
    }
    (give_back_dir / "context.json").write_text(json.dumps(context, indent=2))
    return tmp_path


class TestAckCla:
    """Tests for give-back check --ack cla."""

    def test_ack_cla_writes_marker(self, tmp_path):
        """--ack cla writes cla_acknowledged to context.json."""
        workspace = _setup_workspace(tmp_path, cla_required=True)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            # Symlink .give-back so CWD has it
            import shutil

            src = workspace / ".give-back"
            dst = Path.cwd() / ".give-back"
            if not dst.exists():
                shutil.copytree(src, dst)

            # Mock git commands (check runs git status, git log, etc.)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
                result = runner.invoke(check, ["--ack", "cla"])

            assert result.exit_code == 0
            ctx = json.loads((Path.cwd() / ".give-back" / "context.json").read_text())
            assert ctx["cla_acknowledged"] is True

    def test_ack_cla_no_cla_required(self, tmp_path):
        """--ack cla on a non-CLA project exits cleanly."""
        workspace = _setup_workspace(tmp_path, cla_required=False)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            import shutil

            src = workspace / ".give-back"
            dst = Path.cwd() / ".give-back"
            if not dst.exists():
                shutil.copytree(src, dst)

            result = runner.invoke(check, ["--ack", "cla"])

        assert result.exit_code == 0
        assert "nothing to acknowledge" in result.output.lower()

    def test_ack_unknown_guardrail(self, tmp_path):
        """--ack with unknown guardrail name errors."""
        workspace = _setup_workspace(tmp_path)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            import shutil

            src = workspace / ".give-back"
            dst = Path.cwd() / ".give-back"
            if not dst.exists():
                shutil.copytree(src, dst)

            result = runner.invoke(check, ["--ack", "nonexistent"])

        assert result.exit_code == 1
        assert "Unknown guardrail" in result.output
