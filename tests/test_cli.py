"""Tests for CLI commands and repo argument parsing."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from give_back.cli import _parse_repo, cli
from give_back.exceptions import ForkError, WorkspaceError


class TestParseRepo:
    def test_simple_slug(self):
        assert _parse_repo("pallets/flask") == ("pallets", "flask")

    def test_github_url(self):
        assert _parse_repo("https://github.com/pallets/flask") == ("pallets", "flask")

    def test_github_url_with_trailing_slash(self):
        assert _parse_repo("https://github.com/pallets/flask/") == ("pallets", "flask")

    def test_github_url_with_path(self):
        assert _parse_repo("https://github.com/pallets/flask/tree/main") == ("pallets", "flask")

    def test_github_url_with_git_suffix(self):
        assert _parse_repo("https://github.com/pallets/flask.git") == ("pallets", "flask")

    def test_slug_with_dots(self):
        assert _parse_repo("some.org/my.repo") == ("some.org", "my.repo")

    def test_slug_with_hyphens(self):
        assert _parse_repo("my-org/my-repo") == ("my-org", "my-repo")

    def test_invalid_no_slash(self):
        with pytest.raises(Exception):
            _parse_repo("justarepo")

    def test_invalid_empty(self):
        with pytest.raises(Exception):
            _parse_repo("")


class TestCliHelp:
    def test_help_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Evaluate whether" in result.output

    def test_assess_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["assess", "--help"])
        assert result.exit_code == 0
        assert "REPO" in result.output
        assert "--json" in result.output
        assert "--no-cache" in result.output
        assert "--verbose" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "give-back" in result.output

    def test_prepare_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["prepare", "--help"])
        assert result.exit_code == 0
        assert "REPO" in result.output
        assert "--issue" in result.output
        assert "--dir" in result.output
        assert "--skip-conventions" in result.output
        assert "--json" in result.output
        assert "--verbose" in result.output

    def test_check_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output


class TestCheckCommand:
    def test_check_not_in_workspace(self, tmp_path):
        """Running check outside a workspace prints an error and exits 1."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["check"])
            assert result.exit_code == 1
            assert "Not in a give-back workspace" in result.output

    def test_check_corrupt_context(self, tmp_path):
        """Running check with corrupt context.json prints an error and exits 1."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            gb_dir = Path(".give-back")
            gb_dir.mkdir()
            (gb_dir / "context.json").write_text("not json")
            result = runner.invoke(cli, ["check"])
            assert result.exit_code == 1
            assert "Cannot read brief" in result.output

    @patch("give_back.cli.resolve_token", return_value=None)
    @patch("subprocess.run")
    def test_check_in_workspace(self, mock_subprocess, mock_token, tmp_path):
        """Running check in a valid workspace runs guardrails and prints results."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            gb_dir = Path(".give-back")
            gb_dir.mkdir()
            context = {
                "upstream_owner": "pallets",
                "repo": "flask",
                "issue_number": 5432,
                "branch_name": "fix/5432-typo",
                "default_branch": "main",
                "dco_required": False,
                "ci_commands": ["pytest"],
                "has_pr_template": False,
            }
            (gb_dir / "context.json").write_text(json.dumps(context))

            # Mock subprocess for git commands
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_subprocess.return_value = mock_result

            result = runner.invoke(cli, ["check"])
            assert result.exit_code == 0
            assert "Pre-flight checks" in result.output


class TestPrepareCommand:
    @patch("give_back.cli.resolve_token", return_value=None)
    def test_prepare_requires_auth(self, mock_token):
        """Prepare refuses to run without authentication."""
        runner = CliRunner()
        result = runner.invoke(cli, ["prepare", "pallets/flask"])
        assert result.exit_code == 1
        assert "requires authentication" in result.output

    @patch("give_back.cli.load_config")
    @patch("give_back.cli.resolve_token", return_value="fake-token")
    def test_prepare_fork_error(self, mock_token, mock_config, tmp_path):
        """Prepare exits 1 when fork fails."""
        from give_back.models import Config

        mock_config.return_value = Config(workspace_dir=str(tmp_path))

        runner = CliRunner()
        with (
            patch("give_back.cli.GitHubClient") as mock_client_cls,
            patch("give_back.prepare.fork.ensure_fork") as mock_fork,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            mock_fork.side_effect = ForkError("gh CLI not authenticated")

            result = runner.invoke(cli, ["prepare", "pallets/flask", "--skip-conventions"])
            assert result.exit_code == 1
            assert "gh CLI not authenticated" in result.output

    @patch("give_back.cli.load_config")
    @patch("give_back.cli.resolve_token", return_value="fake-token")
    def test_prepare_workspace_error(self, mock_token, mock_config, tmp_path):
        """Prepare exits 1 when workspace setup fails."""
        from give_back.models import Config

        mock_config.return_value = Config(workspace_dir=str(tmp_path))

        runner = CliRunner()
        with (
            patch("give_back.cli.GitHubClient") as mock_client_cls,
            patch("give_back.prepare.fork.ensure_fork", return_value="myuser"),
            patch("give_back.prepare.workspace.setup_workspace") as mock_ws,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            mock_ws.side_effect = WorkspaceError("Clone failed: timeout")

            result = runner.invoke(cli, ["prepare", "pallets/flask", "--skip-conventions"])
            assert result.exit_code == 1
            assert "Clone failed" in result.output

    @patch("give_back.cli.load_config")
    @patch("give_back.cli.resolve_token", return_value="fake-token")
    def test_prepare_success(self, mock_token, mock_config, tmp_path):
        """Prepare runs the full pipeline and prints the action plan."""
        from give_back.models import Config

        workspace_path = tmp_path / "pallets" / "flask"
        workspace_path.mkdir(parents=True)
        # Create .git/info for brief_writer
        (workspace_path / ".git" / "info").mkdir(parents=True)

        mock_config.return_value = Config(workspace_dir=str(tmp_path))

        runner = CliRunner()
        with (
            patch("give_back.cli.GitHubClient") as mock_client_cls,
            patch("give_back.prepare.fork.ensure_fork", return_value="myuser"),
            patch("give_back.prepare.workspace.setup_workspace", return_value=workspace_path),
            patch("give_back.prepare.workspace.generate_branch_name", return_value="give-back/0-contribution"),
            patch("give_back.prepare.brief_writer.write_brief") as mock_write_brief,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["prepare", "pallets/flask", "--skip-conventions"])
            assert result.exit_code == 0
            assert "Workspace ready" in result.output
            mock_write_brief.assert_called_once()

    @patch("give_back.cli.load_config")
    @patch("give_back.cli.resolve_token", return_value="fake-token")
    def test_prepare_json_output(self, mock_token, mock_config, tmp_path):
        """Prepare with --json outputs JSON."""
        from give_back.models import Config

        workspace_path = tmp_path / "pallets" / "flask"
        workspace_path.mkdir(parents=True)
        (workspace_path / ".git" / "info").mkdir(parents=True)

        mock_config.return_value = Config(workspace_dir=str(tmp_path))

        runner = CliRunner()
        with (
            patch("give_back.cli.GitHubClient") as mock_client_cls,
            patch("give_back.prepare.fork.ensure_fork", return_value="myuser"),
            patch("give_back.prepare.workspace.setup_workspace", return_value=workspace_path),
            patch("give_back.prepare.workspace.generate_branch_name", return_value="give-back/0-contribution"),
            patch("give_back.prepare.brief_writer.write_brief"),
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.rest_get.return_value = {"default_branch": "main"}
            mock_client_cls.return_value = mock_client

            result = runner.invoke(cli, ["prepare", "pallets/flask", "--skip-conventions", "--json"])
            assert result.exit_code == 0
            parsed = json.loads(result.output)
            assert parsed["branch_name"] == "give-back/0-contribution"
            assert parsed["repo"] == "flask"
