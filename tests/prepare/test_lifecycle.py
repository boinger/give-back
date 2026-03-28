"""Tests for workspace lifecycle management."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from give_back.prepare.lifecycle import (
    OldBranchState,
    PrInfo,
    ResolveAction,
    archive_current_issue,
    check_old_branch_state,
    find_pr_for_branch,
    parse_fork_owner_from_remote,
    read_workspace_context,
    resolve_old_workspace,
    update_context_status,
)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestReadWorkspaceContext:
    def test_reads_valid_context(self, tmp_path):
        ctx_dir = tmp_path / ".give-back"
        ctx_dir.mkdir()
        ctx = {"issue_number": 42, "branch_name": "fix/42-thing"}
        (ctx_dir / "context.json").write_text(json.dumps(ctx))

        result = read_workspace_context(tmp_path)
        assert result["issue_number"] == 42

    def test_returns_none_if_missing(self, tmp_path):
        assert read_workspace_context(tmp_path) is None

    def test_returns_none_on_invalid_json(self, tmp_path):
        ctx_dir = tmp_path / ".give-back"
        ctx_dir.mkdir()
        (ctx_dir / "context.json").write_text("not json")
        assert read_workspace_context(tmp_path) is None


class TestCheckOldBranchState:
    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_clean_tree_no_commits(self, mock_run):
        mock_run.side_effect = [
            _completed(0, stdout=""),            # git status --porcelain (clean)
            _completed(0, stdout="0\n"),          # git rev-list --count (0 ahead)
            _completed(0, stdout=""),             # git branch -r (not pushed)
        ]
        state = check_old_branch_state(Path("/fake"), "fix/42", "main")
        assert state.commits_ahead == 0
        assert state.has_dirty_tree is False
        assert state.has_unpushed_commits is False
        assert state.pushed_to_origin is False

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_commits_ahead_and_pushed(self, mock_run):
        mock_run.side_effect = [
            _completed(0, stdout=""),             # clean tree
            _completed(0, stdout="3\n"),           # 3 ahead
            _completed(0, stdout="  origin/fix/42\n"),  # pushed
        ]
        state = check_old_branch_state(Path("/fake"), "fix/42", "main")
        assert state.commits_ahead == 3
        assert state.pushed_to_origin is True
        assert state.has_unpushed_commits is False

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_commits_ahead_not_pushed(self, mock_run):
        mock_run.side_effect = [
            _completed(0, stdout=""),             # clean tree
            _completed(0, stdout="3\n"),           # 3 ahead
            _completed(0, stdout=""),             # not pushed
        ]
        state = check_old_branch_state(Path("/fake"), "fix/42", "main")
        assert state.commits_ahead == 3
        assert state.has_unpushed_commits is True

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_dirty_tree(self, mock_run):
        mock_run.side_effect = [
            _completed(0, stdout=" M src/main.py\n"),  # dirty
            _completed(0, stdout="0\n"),
            _completed(0, stdout=""),
        ]
        state = check_old_branch_state(Path("/fake"), "fix/42", "main")
        assert state.has_dirty_tree is True

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_git_failure_returns_safe_default(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)
        state = check_old_branch_state(Path("/fake"), "fix/42", "main")
        # Safe default: assume dirty + unpushed (don't lose data)
        assert state.has_dirty_tree is True
        assert state.has_unpushed_commits is True


class TestFindPrForBranch:
    def test_pr_found_open(self):
        mock_client = MagicMock()
        mock_client.rest_get.return_value = [
            {"number": 123, "html_url": "https://github.com/org/repo/pull/123", "state": "open", "merged_at": None},
        ]
        result = find_pr_for_branch(mock_client, "org", "repo", "myuser", "fix/42")
        assert result is not None
        assert result.pr_number == 123
        assert result.state == "open"

    def test_pr_found_merged(self):
        mock_client = MagicMock()
        mock_client.rest_get.return_value = [
            {
                "number": 456, "html_url": "https://github.com/org/repo/pull/456",
                "state": "closed", "merged_at": "2026-03-01T10:00:00Z",
            },
        ]
        result = find_pr_for_branch(mock_client, "org", "repo", "myuser", "fix/42")
        assert result is not None
        assert result.state == "merged"

    def test_no_pr_found(self):
        mock_client = MagicMock()
        mock_client.rest_get.return_value = []
        result = find_pr_for_branch(mock_client, "org", "repo", "myuser", "fix/42")
        assert result is None

    def test_api_error_returns_none(self):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = Exception("API error")
        result = find_pr_for_branch(mock_client, "org", "repo", "myuser", "fix/42")
        assert result is None

    def test_multiple_prs_returns_most_recent(self):
        mock_client = MagicMock()
        mock_client.rest_get.return_value = [
            {"number": 200, "html_url": "https://github.com/org/repo/pull/200", "state": "open", "merged_at": None},
            {"number": 100, "html_url": "https://github.com/org/repo/pull/100", "state": "closed", "merged_at": None},
        ]
        result = find_pr_for_branch(mock_client, "org", "repo", "myuser", "fix/42")
        assert result.pr_number == 200  # First (most recent)


class TestResolveOldWorkspace:
    def _make_context(self, **overrides):
        defaults = {
            "issue_number": 100,
            "branch_name": "fix/100-old",
            "default_branch": "main",
            "upstream_owner": "org",
            "repo": "repo",
            "previous_issues": [],
        }
        defaults.update(overrides)
        return defaults

    @patch("give_back.prepare.lifecycle.check_old_branch_state")
    @patch("give_back.prepare.lifecycle.cleanup_old_branch")
    def test_clean_no_work(self, mock_cleanup, mock_state):
        mock_state.return_value = OldBranchState(
            commits_ahead=0, pushed_to_origin=False, has_unpushed_commits=False, has_dirty_tree=False,
        )
        result = resolve_old_workspace(Path("/fake"), self._make_context())
        assert result.action == ResolveAction.CLEAN_NO_WORK
        mock_cleanup.assert_called_once()

    @patch("give_back.prepare.lifecycle.check_old_branch_state")
    def test_block_unpushed(self, mock_state):
        mock_state.return_value = OldBranchState(
            commits_ahead=3, pushed_to_origin=False, has_unpushed_commits=True, has_dirty_tree=False,
        )
        result = resolve_old_workspace(Path("/fake"), self._make_context())
        assert result.action == ResolveAction.BLOCK_UNPUSHED
        assert "unpushed" in result.message.lower()

    @patch("give_back.prepare.lifecycle.check_old_branch_state")
    def test_block_dirty_tree(self, mock_state):
        mock_state.return_value = OldBranchState(
            commits_ahead=0, pushed_to_origin=False, has_unpushed_commits=False, has_dirty_tree=True,
        )
        result = resolve_old_workspace(Path("/fake"), self._make_context())
        assert result.action == ResolveAction.BLOCK_UNPUSHED
        assert "uncommitted" in result.message.lower()

    @patch("give_back.prepare.lifecycle.check_old_branch_state")
    @patch("give_back.prepare.lifecycle.find_pr_for_branch")
    @patch("give_back.prepare.lifecycle.cleanup_old_branch")
    def test_archive_pushed_no_pr(self, mock_cleanup, mock_find_pr, mock_state):
        mock_state.return_value = OldBranchState(
            commits_ahead=2, pushed_to_origin=True, has_unpushed_commits=False, has_dirty_tree=False,
        )
        mock_find_pr.return_value = None
        result = resolve_old_workspace(
            Path("/fake"), self._make_context(), client=MagicMock(), fork_owner="myuser",
        )
        assert result.action == ResolveAction.ARCHIVE_PUSHED
        assert result.archived_entry is not None
        assert result.archived_entry["status"] == "abandoned"
        mock_cleanup.assert_called_once()

    @patch("give_back.prepare.lifecycle.check_old_branch_state")
    @patch("give_back.prepare.lifecycle.find_pr_for_branch")
    @patch("give_back.prepare.lifecycle.cleanup_old_branch")
    def test_archive_pr_open(self, mock_cleanup, mock_find_pr, mock_state):
        mock_state.return_value = OldBranchState(
            commits_ahead=2, pushed_to_origin=True, has_unpushed_commits=False, has_dirty_tree=False,
        )
        mock_find_pr.return_value = PrInfo(pr_number=123, pr_url="https://github.com/org/repo/pull/123", state="open")
        result = resolve_old_workspace(
            Path("/fake"), self._make_context(), client=MagicMock(), fork_owner="myuser",
        )
        assert result.action == ResolveAction.ARCHIVE_PR
        assert result.archived_entry["pr_url"] == "https://github.com/org/repo/pull/123"
        assert result.archived_entry["status"] == "pr_open"

    @patch("give_back.prepare.lifecycle.check_old_branch_state")
    @patch("give_back.prepare.lifecycle.find_pr_for_branch")
    @patch("give_back.prepare.lifecycle.cleanup_old_branch")
    def test_archive_pr_merged(self, mock_cleanup, mock_find_pr, mock_state):
        mock_state.return_value = OldBranchState(
            commits_ahead=2, pushed_to_origin=True, has_unpushed_commits=False, has_dirty_tree=False,
        )
        mock_find_pr.return_value = PrInfo(pr_number=456, pr_url="https://github.com/org/repo/pull/456", state="merged")
        result = resolve_old_workspace(
            Path("/fake"), self._make_context(), client=MagicMock(), fork_owner="myuser",
        )
        assert result.action == ResolveAction.ARCHIVE_PR
        assert result.archived_entry["status"] == "merged"


class TestArchiveCurrentIssue:
    def test_basic_archive(self):
        context = {"issue_number": 42, "branch_name": "fix/42-thing"}
        entry = archive_current_issue(context, "pr_open", "https://github.com/org/repo/pull/99")
        assert entry["issue_number"] == 42
        assert entry["branch_name"] == "fix/42-thing"
        assert entry["status"] == "pr_open"
        assert entry["pr_url"] == "https://github.com/org/repo/pull/99"
        assert "archived_at" in entry

    def test_abandoned_no_pr(self):
        context = {"issue_number": 100, "branch_name": "fix/100-old"}
        entry = archive_current_issue(context, "abandoned", None)
        assert entry["status"] == "abandoned"
        assert entry["pr_url"] is None


class TestUpdateContextStatus:
    def test_updates_status_and_pr(self, tmp_path):
        ctx_dir = tmp_path / ".give-back"
        ctx_dir.mkdir()
        ctx = {"status": "working", "pr_url": None, "pr_number": None, "updated_at": "old"}
        (ctx_dir / "context.json").write_text(json.dumps(ctx))

        update_context_status(tmp_path, "pr_open", "https://github.com/org/repo/pull/99", 99)

        updated = json.loads((ctx_dir / "context.json").read_text())
        assert updated["status"] == "pr_open"
        assert updated["pr_url"] == "https://github.com/org/repo/pull/99"
        assert updated["pr_number"] == 99
        assert updated["updated_at"] != "old"

    def test_handles_missing_file(self, tmp_path):
        # Should not raise
        update_context_status(tmp_path, "pr_open", None, None)

    def test_handles_corrupt_json(self, tmp_path):
        ctx_dir = tmp_path / ".give-back"
        ctx_dir.mkdir()
        (ctx_dir / "context.json").write_text("not json")
        # Should not raise
        update_context_status(tmp_path, "pr_open", None, None)


class TestParseForkOwnerFromRemote:
    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_ssh_url(self, mock_run):
        mock_run.return_value = _completed(0, stdout="git@github.com:myuser/myrepo.git\n")
        assert parse_fork_owner_from_remote(Path("/fake")) == "myuser"

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_https_url(self, mock_run):
        mock_run.return_value = _completed(0, stdout="https://github.com/myuser/myrepo.git\n")
        assert parse_fork_owner_from_remote(Path("/fake")) == "myuser"

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_https_no_git_suffix(self, mock_run):
        mock_run.return_value = _completed(0, stdout="https://github.com/myuser/myrepo\n")
        assert parse_fork_owner_from_remote(Path("/fake")) == "myuser"

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_git_failure(self, mock_run):
        mock_run.return_value = _completed(1, stderr="not a git repo")
        assert parse_fork_owner_from_remote(Path("/fake")) is None

    @patch("give_back.prepare.lifecycle.subprocess.run")
    def test_non_github_url(self, mock_run):
        mock_run.return_value = _completed(0, stdout="https://gitlab.com/myuser/myrepo.git\n")
        assert parse_fork_owner_from_remote(Path("/fake")) is None
