"""Tests for CLI commands and repo argument parsing."""

import pytest
from click.testing import CliRunner

from give_back.cli import _parse_repo, cli


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
