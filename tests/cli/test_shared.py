"""Tests for cli/_shared.py: DefaultGroup, detect_repo_from_cwd, regex parsing."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import click
from click.testing import CliRunner

from give_back.cli._shared import (
    _GITHUB_REMOTE_URL_RE,
    DefaultGroup,
    detect_repo_from_cwd,
)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestGithubRemoteUrlRegex:
    """The canonical regex must handle SSH, HTTPS, HTTPS-with-credentials, and trailing .git."""

    def test_ssh_with_dot_git(self):
        m = _GITHUB_REMOTE_URL_RE.match("git@github.com:pallets/flask.git")
        assert m
        assert m.group(1) == "pallets"
        assert m.group(2) == "flask"

    def test_ssh_without_dot_git(self):
        m = _GITHUB_REMOTE_URL_RE.match("git@github.com:pallets/flask")
        assert m
        assert (m.group(1), m.group(2)) == ("pallets", "flask")

    def test_https_with_dot_git(self):
        m = _GITHUB_REMOTE_URL_RE.match("https://github.com/pallets/flask.git")
        assert m
        assert (m.group(1), m.group(2)) == ("pallets", "flask")

    def test_https_without_dot_git(self):
        m = _GITHUB_REMOTE_URL_RE.match("https://github.com/pallets/flask")
        assert m
        assert (m.group(1), m.group(2)) == ("pallets", "flask")

    def test_https_with_credentials(self):
        """HTTPS with embedded auth token (CI environments)."""
        m = _GITHUB_REMOTE_URL_RE.match("https://ghp_abc123@github.com/pallets/flask.git")
        assert m
        assert (m.group(1), m.group(2)) == ("pallets", "flask")

    def test_non_github_https_returns_none(self):
        assert _GITHUB_REMOTE_URL_RE.match("https://gitlab.com/foo/bar.git") is None

    def test_github_enterprise_returns_none(self):
        """GHE is not currently supported."""
        assert _GITHUB_REMOTE_URL_RE.match("https://github.mycorp.com/foo/bar.git") is None


class TestDetectRepoFromCwd:
    @patch("give_back.cli._shared.subprocess.run")
    def test_https_origin(self, mock_run):
        """Standard HTTPS origin → detected."""
        mock_run.side_effect = [
            _completed(0, stdout="/path/to/repo\n"),  # rev-parse --show-toplevel
            _completed(0, stdout="https://github.com/pallets/flask.git\n"),  # remote get-url origin
        ]
        assert detect_repo_from_cwd() == ("pallets", "flask")

    @patch("give_back.cli._shared.subprocess.run")
    def test_ssh_origin(self, mock_run):
        """SSH origin → detected."""
        mock_run.side_effect = [
            _completed(0, stdout="/path/to/repo\n"),
            _completed(0, stdout="git@github.com:pallets/flask.git\n"),
        ]
        assert detect_repo_from_cwd() == ("pallets", "flask")

    @patch("give_back.cli._shared.subprocess.run")
    def test_https_with_credentials(self, mock_run):
        """HTTPS with embedded credentials → detected."""
        mock_run.side_effect = [
            _completed(0, stdout="/path/to/repo\n"),
            _completed(0, stdout="https://ghp_abc123@github.com/pallets/flask.git\n"),
        ]
        assert detect_repo_from_cwd() == ("pallets", "flask")

    @patch("give_back.cli._shared.subprocess.run")
    def test_not_a_git_repo(self, mock_run):
        """rev-parse fails → returns None."""
        mock_run.return_value = _completed(128, stderr="fatal: not a git repository")
        assert detect_repo_from_cwd() is None

    @patch("give_back.cli._shared.subprocess.run")
    def test_no_origin_remote(self, mock_run):
        """In a git repo but no origin remote → returns None."""
        mock_run.side_effect = [
            _completed(0, stdout="/path/to/repo\n"),
            _completed(2, stderr="fatal: No such remote 'origin'"),
        ]
        assert detect_repo_from_cwd() is None

    @patch("give_back.cli._shared.subprocess.run")
    def test_non_github_origin(self, mock_run):
        """In a git repo with a GitLab origin → returns None."""
        mock_run.side_effect = [
            _completed(0, stdout="/path/to/repo\n"),
            _completed(0, stdout="https://gitlab.com/foo/bar.git\n"),
        ]
        assert detect_repo_from_cwd() is None

    @patch("give_back.cli._shared.subprocess.run")
    def test_git_not_installed(self, mock_run):
        """git binary not found → returns None gracefully."""
        mock_run.side_effect = FileNotFoundError("git not found")
        assert detect_repo_from_cwd() is None

    @patch("give_back.cli._shared.subprocess.run")
    def test_subprocess_timeout(self, mock_run):
        """git command hangs → returns None gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=5)
        assert detect_repo_from_cwd() is None

    @patch("give_back.cli._shared.subprocess.run")
    def test_trailing_newline_handled(self, mock_run):
        """git remote get-url returns a trailing newline; must be stripped."""
        mock_run.side_effect = [
            _completed(0, stdout="/path/to/repo\n"),
            _completed(0, stdout="https://github.com/pallets/flask.git\n\n"),
        ]
        assert detect_repo_from_cwd() == ("pallets", "flask")


class TestDefaultGroup:
    """The DefaultGroup class — both orderings of options/positional must work."""

    def _make_group(self):
        @click.group(cls=DefaultGroup, default="repo", default_if_no_args=True)
        def grp():
            pass

        @grp.command("repo")
        @click.argument("name", required=False)
        @click.option("--flag", is_flag=True)
        def repo_cmd(name, flag):
            click.echo(f"name={name} flag={flag}")

        @grp.command("other")
        def other_cmd():
            click.echo("other called")

        return grp

    def test_options_before_positional(self):
        """Standard ordering: `grp --flag myname` should work."""
        runner = CliRunner()
        grp = self._make_group()
        result = runner.invoke(grp, ["--flag", "myname"])
        assert result.exit_code == 0
        assert "name=myname flag=True" in result.output

    def test_options_after_positional(self):
        """The bug fix: `grp myname --flag` must also work."""
        runner = CliRunner()
        grp = self._make_group()
        result = runner.invoke(grp, ["myname", "--flag"])
        assert result.exit_code == 0
        assert "name=myname flag=True" in result.output

    def test_no_args_uses_default_subcommand(self):
        """`grp` (no args) routes to the default subcommand."""
        runner = CliRunner()
        grp = self._make_group()
        result = runner.invoke(grp, [])
        assert result.exit_code == 0
        assert "name=None flag=False" in result.output

    def test_known_subcommand_still_works(self):
        """Other subcommands resolve normally."""
        runner = CliRunner()
        grp = self._make_group()
        result = runner.invoke(grp, ["other"])
        assert result.exit_code == 0
        assert "other called" in result.output

    def test_explicit_default_subcommand(self):
        """`grp repo myname` (explicit form) works."""
        runner = CliRunner()
        grp = self._make_group()
        result = runner.invoke(grp, ["repo", "myname"])
        assert result.exit_code == 0
        assert "name=myname flag=False" in result.output
