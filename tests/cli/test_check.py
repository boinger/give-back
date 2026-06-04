"""Tests for the check CLI command — --ack cla behavior and PR-status detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli.check import check
from give_back.exceptions import GiveBackError
from give_back.guardrails import GuardrailResult, Severity
from give_back.prepare.lifecycle import PrInfo


def _setup_workspace(
    tmp_path: Path,
    cla_required: bool = True,
    cla_system: str = "cla-assistant",
    fork_owner: str | None = None,
) -> Path:
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
    if fork_owner is not None:
        context["fork_owner"] = fork_owner
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


class TestPrStatusDetection:
    """Characterization tests for the PR-detection block (check.py step 5.5).

    Pinned before extracting the block into a helper — see
    plans/PLAN-sloppylint-cleanup.md (these lines were previously uncovered).
    """

    def _run_check(
        self,
        runner: CliRunner,
        workspace: Path,
        find_pr: object,
        dup_check_error: Exception | None = None,
        extra_args: list[str] | None = None,
    ):
        """Invoke check in *workspace* with the API layer mocked out."""
        import shutil

        src = workspace / ".give-back"
        dst = Path.cwd() / ".give-back"
        if not dst.exists():
            shutil.copytree(src, dst)

        dup_result = GuardrailResult(name="duplicate_pr", severity=Severity.INFO, passed=True, message="none")
        dup_kwargs = {"side_effect": dup_check_error} if dup_check_error else {"return_value": dup_result}

        with (
            patch("subprocess.run") as mock_run,
            patch("give_back.cli.check.resolve_token", return_value="tok"),
            patch("give_back.cli.check.GitHubClient"),
            patch("give_back.guardrails.check_duplicate_pr", **dup_kwargs),
            patch("give_back.prepare.lifecycle.find_pr_for_branch", return_value=find_pr) as mock_find,
            patch("give_back.prepare.lifecycle.update_context_status") as mock_update,
        ):
            mock_run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            result = runner.invoke(check, extra_args or [])
        return result, mock_find, mock_update

    def test_open_pr_detected_updates_context(self, tmp_path):
        """An open PR for the branch records pr_open status and surfaces a pr_status result."""
        workspace = _setup_workspace(tmp_path, cla_required=False, fork_owner="me")
        pr = PrInfo(pr_number=42, pr_url="https://github.com/org/project/pull/42", state="open")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            result, mock_find, mock_update = self._run_check(runner, workspace, find_pr=pr)

        assert result.exit_code == 0
        mock_find.assert_called_once()
        mock_update.assert_called_once()
        args = mock_update.call_args[0]
        assert args[1] == "pr_open"
        assert args[2] == "https://github.com/org/project/pull/42"
        assert args[3] == 42

    def test_merged_pr_records_merged_status(self, tmp_path):
        """A merged PR records status 'merged', not 'pr_open'."""
        workspace = _setup_workspace(tmp_path, cla_required=False, fork_owner="me")
        pr = PrInfo(pr_number=7, pr_url="https://github.com/org/project/pull/7", state="merged")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            result, _mock_find, mock_update = self._run_check(runner, workspace, find_pr=pr)

        assert result.exit_code == 0
        assert mock_update.call_args[0][1] == "merged"

    def test_no_pr_found_leaves_context_untouched(self, tmp_path):
        """No PR for the branch: detection runs but nothing is recorded."""
        workspace = _setup_workspace(tmp_path, cla_required=False, fork_owner="me")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            result, mock_find, mock_update = self._run_check(runner, workspace, find_pr=None)

        assert result.exit_code == 0
        mock_find.assert_called_once()
        mock_update.assert_not_called()

    def test_no_fork_owner_skips_pr_lookup(self, tmp_path):
        """Without fork_owner (context or remote), the PR lookup is skipped entirely."""
        workspace = _setup_workspace(tmp_path, cla_required=False, fork_owner=None)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            with patch("give_back.prepare.lifecycle.parse_fork_owner_from_remote", return_value=None):
                result, mock_find, mock_update = self._run_check(runner, workspace, find_pr=None)

        assert result.exit_code == 0
        mock_find.assert_not_called()
        mock_update.assert_not_called()

    def test_api_failure_skips_silently(self, tmp_path):
        """A GiveBackError inside the API block skips PR detection without failing the command."""
        workspace = _setup_workspace(tmp_path, cla_required=False, fork_owner="me")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=workspace):
            result, _mock_find, mock_update = self._run_check(
                runner, workspace, find_pr=None, dup_check_error=GiveBackError("api down")
            )

        assert result.exit_code == 0
        mock_update.assert_not_called()
