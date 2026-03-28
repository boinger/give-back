"""Tests for give_back.prepare.fork — all subprocess calls mocked."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from give_back.exceptions import ForkError
from give_back.prepare.fork import ensure_fork


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestEnsureFork:
    """Tests for ensure_fork()."""

    @patch("give_back.prepare.fork.subprocess.run")
    def test_gh_not_installed(self, mock_run):
        """FileNotFoundError from gh → ForkError with install URL."""
        mock_run.side_effect = FileNotFoundError("No such file: gh")

        with pytest.raises(ForkError, match="gh CLI required.*https://cli.github.com"):
            ensure_fork("pallets", "flask")

    @patch("give_back.prepare.fork.subprocess.run")
    def test_gh_not_authed(self, mock_run):
        """gh auth status exit code 1 → ForkError."""
        mock_run.side_effect = [
            _completed(0),  # gh --version
            _completed(1, stderr="not logged in"),  # gh auth status
        ]

        with pytest.raises(ForkError, match="not authenticated.*gh auth login"):
            ensure_fork("pallets", "flask")

    @patch("give_back.prepare.fork.subprocess.run")
    def test_user_owns_repo(self, mock_run):
        """When fork_owner == owner, skip fork and return (owner, repo)."""
        mock_run.side_effect = [
            _completed(0),  # gh --version
            _completed(0),  # gh auth status
            _completed(0, stdout="pallets\n"),  # gh api user
        ]

        result = ensure_fork("pallets", "flask")

        assert result == ("pallets", "flask")
        # Should NOT have called gh repo fork (only 3 calls total)
        assert mock_run.call_count == 3

    @patch("give_back.prepare.fork.subprocess.run")
    def test_fork_succeeds(self, mock_run):
        """Successful fork returns (fork_owner, fork_repo)."""
        mock_run.side_effect = [
            _completed(0),  # gh --version
            _completed(0),  # gh auth status
            _completed(0, stdout="myuser\n"),  # gh api user
            _completed(0),  # gh repo fork
            _completed(0, stdout="flask\n"),  # _resolve_fork_name: direct check
        ]

        result = ensure_fork("pallets", "flask")

        assert result == ("myuser", "flask")
        # Verify the fork call
        fork_call = mock_run.call_args_list[3]
        assert fork_call[0][0] == ["gh", "repo", "fork", "pallets/flask", "--clone=false"]

    @patch("give_back.prepare.fork.subprocess.run")
    def test_fork_with_renamed_repo(self, mock_run):
        """Fork where GitHub renamed the repo returns the actual name."""
        mock_run.side_effect = [
            _completed(0),  # gh --version
            _completed(0),  # gh auth status
            _completed(0, stdout="myuser\n"),  # gh api user
            _completed(0),  # gh repo fork
            _completed(1),  # _resolve_fork_name: direct check fails (renamed)
            _completed(0, stdout="grafana-alloy\n"),  # _resolve_fork_name: search forks
        ]

        result = ensure_fork("grafana", "alloy")

        assert result == ("myuser", "grafana-alloy")

    @patch("give_back.prepare.fork.subprocess.run")
    def test_fork_already_exists(self, mock_run):
        """gh fork says 'already exists' → still returns (fork_owner, fork_repo)."""
        mock_run.side_effect = [
            _completed(0),  # gh --version
            _completed(0),  # gh auth status
            _completed(0, stdout="myuser\n"),  # gh api user
            _completed(0, stderr="already exists"),  # gh repo fork
            _completed(0, stdout="flask\n"),  # _resolve_fork_name: direct check
        ]

        result = ensure_fork("pallets", "flask")

        assert result == ("myuser", "flask")
