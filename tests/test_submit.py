"""Tests for give_back.submit — PR creation from workspace."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from give_back.submit import (
    _build_pr_body,
    _build_pr_title,
    _check_gh_auth,
    _create_pr,
    _push_branch,
    _read_context,
    _verify_branch,
    submit_pr,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_context(tmp_path: Path, ctx: dict) -> Path:
    """Write a context.json under .give-back/ and return the workspace dir."""
    gb_dir = tmp_path / ".give-back"
    gb_dir.mkdir(parents=True, exist_ok=True)
    (gb_dir / "context.json").write_text(json.dumps(ctx))
    return tmp_path


def _write_brief(tmp_path: Path, content: str) -> None:
    """Write brief.md under .give-back/."""
    gb_dir = tmp_path / ".give-back"
    gb_dir.mkdir(parents=True, exist_ok=True)
    (gb_dir / "brief.md").write_text(content)


def _valid_context(**overrides: object) -> dict:
    """Return a minimal valid context dict with optional overrides."""
    ctx = {
        "upstream_owner": "pallets",
        "repo": "flask",
        "branch_name": "give-back/fix-typo",
        "default_branch": "main",
        "fork_owner": "contributor",
        "issue_number": 42,
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# _read_context
# ---------------------------------------------------------------------------


class TestReadContext:
    def test_valid_context(self, tmp_path: Path) -> None:
        ctx = _valid_context()
        ws = _write_context(tmp_path, ctx)
        result = _read_context(ws)
        assert result["upstream_owner"] == "pallets"
        assert result["repo"] == "flask"

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(Exception, match="Missing context file"):
            _read_context(tmp_path)

    def test_corrupt_json(self, tmp_path: Path) -> None:
        gb_dir = tmp_path / ".give-back"
        gb_dir.mkdir()
        (gb_dir / "context.json").write_text("{bad json")
        with pytest.raises(Exception, match="Corrupt context.json"):
            _read_context(tmp_path)

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        ws = _write_context(tmp_path, {"upstream_owner": "pallets"})
        with pytest.raises(Exception, match="missing required fields"):
            _read_context(ws)

    def test_empty_dict(self, tmp_path: Path) -> None:
        ws = _write_context(tmp_path, {})
        with pytest.raises(Exception, match="missing required fields"):
            _read_context(ws)


# ---------------------------------------------------------------------------
# _build_pr_title
# ---------------------------------------------------------------------------


class TestBuildPrTitle:
    def test_with_issue(self) -> None:
        ctx = _valid_context(branch_name="give-back/fix-typo", issue_number=42)
        assert _build_pr_title(ctx) == "Fix #42: fix-typo"

    def test_without_issue(self) -> None:
        ctx = _valid_context(branch_name="fix/add-logging", issue_number=None)
        assert _build_pr_title(ctx) == "add-logging"

    def test_no_prefix(self) -> None:
        ctx = _valid_context(branch_name="my-feature", issue_number=None)
        assert _build_pr_title(ctx) == "my-feature"


# ---------------------------------------------------------------------------
# _build_pr_body
# ---------------------------------------------------------------------------


class TestBuildPrBody:
    def test_with_template_section(self, tmp_path: Path) -> None:
        ws = _write_context(tmp_path, _valid_context())
        _write_brief(
            tmp_path,
            "## Summary\nSome summary.\n\n## PR Template\nFixes the thing.\n\nDetails here.\n\n## Notes\nExtra.\n",
        )
        body = _build_pr_body(_valid_context(), ws)
        assert "Fixes the thing." in body
        assert "Details here." in body
        assert "Extra." not in body

    def test_without_template_section(self, tmp_path: Path) -> None:
        ws = _write_context(tmp_path, _valid_context())
        _write_brief(tmp_path, "## Summary\nJust a summary.\n")
        body = _build_pr_body(_valid_context(), ws)
        assert "Created with give-back." in body

    def test_brief_missing(self, tmp_path: Path) -> None:
        ws = _write_context(tmp_path, _valid_context())
        body = _build_pr_body(_valid_context(), ws)
        assert "Created with give-back." in body

    def test_with_issue_reference(self, tmp_path: Path) -> None:
        ws = _write_context(tmp_path, _valid_context())
        body = _build_pr_body(_valid_context(issue_number=99), ws)
        assert "Closes #99" in body

    def test_no_issue_no_closes(self, tmp_path: Path) -> None:
        ws = _write_context(tmp_path, _valid_context())
        body = _build_pr_body(_valid_context(issue_number=None), ws)
        assert "Closes" not in body


# ---------------------------------------------------------------------------
# _push_branch
# ---------------------------------------------------------------------------


class TestPushBranch:
    @patch("give_back.submit.subprocess")
    def test_success(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0, stderr="")
        _push_branch(tmp_path, "my-branch")
        mock_subprocess.run.assert_called_once()
        args = mock_subprocess.run.call_args
        assert "push" in args[0][0]

    @patch("give_back.submit.subprocess")
    def test_failure(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=1, stderr="rejected")
        mock_subprocess.TimeoutExpired = TimeoutError
        mock_subprocess.CalledProcessError = Exception
        with pytest.raises(Exception, match="git push failed"):
            _push_branch(tmp_path, "my-branch")

    @patch("give_back.submit.subprocess")
    def test_timeout(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        import subprocess as real_subprocess

        mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
        mock_subprocess.run.side_effect = real_subprocess.TimeoutExpired("git push", 60)
        with pytest.raises(Exception, match="timed out"):
            _push_branch(tmp_path, "my-branch")


# ---------------------------------------------------------------------------
# _check_gh_auth
# ---------------------------------------------------------------------------


class TestCheckGhAuth:
    @patch("give_back.submit.subprocess")
    def test_authenticated(self, mock_subprocess: MagicMock) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        _check_gh_auth()  # Should not raise

    @patch("give_back.submit.subprocess")
    def test_not_authenticated(self, mock_subprocess: MagicMock) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=1)
        with pytest.raises(Exception, match="not authenticated"):
            _check_gh_auth()


# ---------------------------------------------------------------------------
# _verify_branch
# ---------------------------------------------------------------------------


class TestVerifyBranch:
    @patch("give_back.submit.subprocess")
    def test_matching(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="give-back/fix-typo\n")
        _verify_branch(tmp_path, "give-back/fix-typo")  # Should not raise

    @patch("give_back.submit.subprocess")
    def test_mismatched(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="main\n")
        with pytest.raises(Exception, match="Expected branch"):
            _verify_branch(tmp_path, "give-back/fix-typo")


# ---------------------------------------------------------------------------
# _create_pr
# ---------------------------------------------------------------------------


class TestCreatePr:
    @patch("give_back.submit._open_editor")
    @patch("give_back.submit.subprocess")
    def test_success(self, mock_subprocess: MagicMock, _mock_editor: MagicMock, tmp_path: Path) -> None:
        mock_subprocess.run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/pallets/flask/pull/42\n",
            stderr="",
        )
        mock_subprocess.TimeoutExpired = TimeoutError
        pr_url, pr_number = _create_pr(
            workspace_dir=tmp_path,
            owner="pallets",
            repo="flask",
            branch="give-back/fix-typo",
            default_branch="main",
            fork_owner="contributor",
            title="Fix #42: fix-typo",
            body="Fixes the thing.",
            draft=False,
            edit=False,
        )
        assert pr_url == "https://github.com/pallets/flask/pull/42"
        assert pr_number == 42

    @patch("give_back.submit._open_editor")
    @patch("give_back.submit.subprocess")
    def test_failure(self, mock_subprocess: MagicMock, _mock_editor: MagicMock, tmp_path: Path) -> None:
        mock_subprocess.run.return_value = MagicMock(returncode=1, stdout="", stderr="HTTP 422")
        mock_subprocess.TimeoutExpired = TimeoutError
        with pytest.raises(Exception, match="gh pr create failed"):
            _create_pr(
                workspace_dir=tmp_path,
                owner="pallets",
                repo="flask",
                branch="give-back/fix-typo",
                default_branch="main",
                fork_owner="contributor",
                title="Fix",
                body="Body",
                draft=False,
                edit=False,
            )

    @patch("give_back.submit._open_editor")
    @patch("give_back.submit.subprocess")
    def test_draft_flag(self, mock_subprocess: MagicMock, _mock_editor: MagicMock, tmp_path: Path) -> None:
        mock_subprocess.run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/pallets/flask/pull/99\n",
            stderr="",
        )
        mock_subprocess.TimeoutExpired = TimeoutError
        _create_pr(
            workspace_dir=tmp_path,
            owner="pallets",
            repo="flask",
            branch="give-back/fix-typo",
            default_branch="main",
            fork_owner="contributor",
            title="Fix",
            body="Body",
            draft=True,
            edit=False,
        )
        call_args = mock_subprocess.run.call_args[0][0]
        assert "--draft" in call_args


# ---------------------------------------------------------------------------
# submit_pr (integration)
# ---------------------------------------------------------------------------


class TestSubmitPr:
    @patch("give_back.submit.update_context_status")
    @patch("give_back.submit._create_pr", return_value=("https://github.com/pallets/flask/pull/42", 42))
    @patch("give_back.submit._push_branch")
    @patch("give_back.submit._check_gh_auth")
    @patch("give_back.submit._verify_branch")
    def test_full_flow(
        self,
        _mock_verify: MagicMock,
        _mock_auth: MagicMock,
        _mock_push: MagicMock,
        _mock_create: MagicMock,
        _mock_update: MagicMock,
        tmp_path: Path,
    ) -> None:
        ws = _write_context(tmp_path, _valid_context())
        result = submit_pr(ws)
        assert result.success
        assert result.pr_url == "https://github.com/pallets/flask/pull/42"
        assert result.pr_number == 42
        _mock_update.assert_called_once_with(ws, "pr_open", "https://github.com/pallets/flask/pull/42", 42)

    def test_already_has_pr(self, tmp_path: Path) -> None:
        ctx = _valid_context(pr_url="https://github.com/pallets/flask/pull/10", pr_number=10)
        ws = _write_context(tmp_path, ctx)
        result = submit_pr(ws)
        assert result.success
        assert result.pr_url == "https://github.com/pallets/flask/pull/10"
        assert result.pr_number == 10

    def test_missing_context_returns_error(self, tmp_path: Path) -> None:
        result = submit_pr(tmp_path)
        assert not result.success
        assert "Missing context file" in (result.error or "")
