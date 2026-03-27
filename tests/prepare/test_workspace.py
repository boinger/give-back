"""Tests for give_back.prepare.workspace — all subprocess calls mocked."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from give_back.conventions.models import BranchConvention
from give_back.exceptions import WorkspaceError
from give_back.prepare.workspace import generate_branch_name, setup_workspace


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestSetupWorkspace:
    """Tests for setup_workspace()."""

    @patch("give_back.prepare.workspace.subprocess.run")
    def test_fresh_setup(self, mock_run, tmp_path):
        """No existing dir → clone, add remote, fetch, create branch."""
        mock_run.return_value = _completed(0)

        result = setup_workspace(
            fork_owner="myuser",
            repo="flask",
            upstream_owner="pallets",
            branch_name="fix/123-some-bug",
            default_branch="main",
            workspace_dir=tmp_path,
        )

        clone_dir = tmp_path / "pallets" / "flask"
        assert result == clone_dir

        # Verify call sequence: clone, remote add, fetch, branch --list, checkout -b
        commands = [c[0][0] for c in mock_run.call_args_list]
        assert commands[0][0:2] == ["git", "clone"]
        assert commands[1] == ["git", "remote", "add", "upstream", "https://github.com/pallets/flask.git"]
        assert commands[2] == ["git", "fetch", "upstream"]
        assert commands[3] == ["git", "branch", "--list", "fix/123-some-bug"]
        assert commands[4] == ["git", "checkout", "-b", "fix/123-some-bug", "upstream/main"]

    @patch("give_back.prepare.workspace.subprocess.run")
    def test_resume_existing(self, mock_run, tmp_path):
        """Dir exists with correct upstream → fetch + new branch."""
        clone_dir = tmp_path / "pallets" / "flask"
        clone_dir.mkdir(parents=True)

        mock_run.side_effect = [
            _completed(0, stdout="https://github.com/pallets/flask.git\n"),  # remote get-url
            _completed(0),  # fetch upstream
            _completed(0, stdout=""),  # branch --list (empty = doesn't exist)
            _completed(0),  # checkout -b
        ]

        result = setup_workspace(
            fork_owner="myuser",
            repo="flask",
            upstream_owner="pallets",
            branch_name="fix/456-new-feature",
            default_branch="main",
            workspace_dir=tmp_path,
        )

        assert result == clone_dir
        commands = [c[0][0] for c in mock_run.call_args_list]
        assert commands[0] == ["git", "remote", "get-url", "upstream"]
        assert commands[1] == ["git", "fetch", "upstream"]

    @patch("give_back.prepare.workspace.subprocess.run")
    def test_wrong_upstream(self, mock_run, tmp_path):
        """Dir exists with wrong upstream → WorkspaceError."""
        clone_dir = tmp_path / "pallets" / "flask"
        clone_dir.mkdir(parents=True)

        mock_run.return_value = _completed(0, stdout="https://github.com/other/flask.git\n")

        with pytest.raises(WorkspaceError, match="upstream remote pointing to"):
            setup_workspace(
                fork_owner="myuser",
                repo="flask",
                upstream_owner="pallets",
                branch_name="fix/123-bug",
                default_branch="main",
                workspace_dir=tmp_path,
            )

    @patch("give_back.prepare.workspace.subprocess.run")
    def test_no_upstream_remote(self, mock_run, tmp_path):
        """Dir exists but no upstream remote → WorkspaceError."""
        clone_dir = tmp_path / "pallets" / "flask"
        clone_dir.mkdir(parents=True)

        mock_run.return_value = _completed(1, stderr="No such remote 'upstream'")

        with pytest.raises(WorkspaceError, match="no 'upstream' remote"):
            setup_workspace(
                fork_owner="myuser",
                repo="flask",
                upstream_owner="pallets",
                branch_name="fix/123-bug",
                default_branch="main",
                workspace_dir=tmp_path,
            )

    @patch("give_back.prepare.workspace.subprocess.run")
    def test_branch_exists_clean(self, mock_run, tmp_path):
        """Existing branch with clean working tree → checkout + rebase."""
        clone_dir = tmp_path / "pallets" / "flask"
        clone_dir.mkdir(parents=True)

        mock_run.side_effect = [
            _completed(0, stdout="https://github.com/pallets/flask.git\n"),  # remote get-url
            _completed(0),  # fetch upstream
            _completed(0, stdout="  fix/123-bug\n"),  # branch --list (exists)
            _completed(0, stdout=""),  # status --porcelain (clean)
            _completed(0),  # checkout
            _completed(0),  # pull --rebase
        ]

        result = setup_workspace(
            fork_owner="myuser",
            repo="flask",
            upstream_owner="pallets",
            branch_name="fix/123-bug",
            default_branch="main",
            workspace_dir=tmp_path,
        )

        assert result == clone_dir
        checkout_call = mock_run.call_args_list[4]
        assert checkout_call[0][0] == ["git", "checkout", "fix/123-bug"]

    @patch("give_back.prepare.workspace.subprocess.run")
    def test_branch_exists_dirty(self, mock_run, tmp_path):
        """Existing branch with uncommitted changes → WorkspaceError."""
        clone_dir = tmp_path / "pallets" / "flask"
        clone_dir.mkdir(parents=True)

        mock_run.side_effect = [
            _completed(0, stdout="https://github.com/pallets/flask.git\n"),  # remote get-url
            _completed(0),  # fetch upstream
            _completed(0, stdout="  fix/123-bug\n"),  # branch --list (exists)
            _completed(0, stdout="M  some_file.py\n"),  # status --porcelain (dirty)
        ]

        with pytest.raises(WorkspaceError, match="uncommitted changes"):
            setup_workspace(
                fork_owner="myuser",
                repo="flask",
                upstream_owner="pallets",
                branch_name="fix/123-bug",
                default_branch="main",
                workspace_dir=tmp_path,
            )


class TestGenerateBranchName:
    """Tests for generate_branch_name()."""

    def test_type_description_pattern(self):
        """type/description convention → fix/{issue}-{slug}."""
        conv = BranchConvention(pattern="type/description")
        result = generate_branch_name(conv, 5432, "Fix typo in quickstart guide")
        assert result == "fix/5432-fix-typo-in-quickstart-guide"

    def test_issue_description_pattern(self):
        """issue-description convention → {issue}-{slug}."""
        conv = BranchConvention(pattern="issue-description")
        result = generate_branch_name(conv, 5432, "Some Title")
        assert result == "5432-some-title"

    def test_unknown_pattern(self):
        """Unknown convention → give-back/{issue}-{slug}."""
        conv = BranchConvention(pattern="unknown")
        result = generate_branch_name(conv, 5432, "Some Title")
        assert result == "give-back/5432-some-title"

    def test_mixed_pattern(self):
        """Mixed convention → give-back/{issue}-{slug} (fallback)."""
        conv = BranchConvention(pattern="mixed")
        result = generate_branch_name(conv, 5432, "Some Title")
        assert result == "give-back/5432-some-title"

    def test_slug_truncation(self):
        """Long titles are truncated to 50 chars."""
        conv = BranchConvention(pattern="issue-description")
        long_title = "This is a very long issue title that should definitely be truncated to fit within the limit"
        result = generate_branch_name(conv, 99, long_title)
        slug_part = result.split("-", 1)[1]  # remove "99-" prefix
        # The slug portion should be at most 50 chars
        assert len(slug_part) <= 50

    def test_slug_special_chars(self):
        """Special characters are replaced with hyphens."""
        conv = BranchConvention(pattern="issue-description")
        result = generate_branch_name(conv, 1, "Fix: [bug] in foo/bar (urgent!)")
        assert result == "1-fix-bug-in-foo-bar-urgent"

    def test_slug_no_trailing_hyphens(self):
        """Slugs don't end with hyphens after truncation."""
        conv = BranchConvention(pattern="issue-description")
        # Create a title that will produce a slug ending with hyphen at the truncation point
        title = "a" * 49 + " b" + "c" * 20
        result = generate_branch_name(conv, 1, title)
        slug = result.split("-", 1)[1]
        assert not slug.endswith("-")
