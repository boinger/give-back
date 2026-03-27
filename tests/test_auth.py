"""Tests for auth.py token resolution."""

from unittest.mock import patch

from give_back.auth import resolve_token


class TestResolveToken:
    def test_github_token_env_var(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        assert resolve_token() == "ghp_test123"

    def test_github_token_takes_precedence_over_gh(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
        with patch("give_back.auth._try_gh_auth_token", return_value="ghp_gh_token"):
            assert resolve_token() == "ghp_env_token"

    def test_gh_cli_fallback(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("give_back.auth._try_gh_auth_token", return_value="ghp_from_gh"):
            assert resolve_token() == "ghp_from_gh"

    def test_unauthenticated_returns_none(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("give_back.auth._try_gh_auth_token", return_value=None):
            assert resolve_token() is None

    def test_unauthenticated_prints_warning(self, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("give_back.auth._try_gh_auth_token", return_value=None):
            resolve_token()
        # Warning goes to stderr (rich Console(stderr=True))
        err = capsys.readouterr().err
        assert "No GitHub token found" in err
        assert "60/hour" in err


class TestTryGhAuthToken:
    def test_gh_not_installed(self):
        with patch("give_back.auth.subprocess.run", side_effect=FileNotFoundError):
            from give_back.auth import _try_gh_auth_token

            assert _try_gh_auth_token() is None

    def test_gh_auth_fails(self):
        with patch(
            "give_back.auth.subprocess.run",
            return_value=type("Result", (), {"returncode": 1, "stdout": ""})(),
        ):
            from give_back.auth import _try_gh_auth_token

            assert _try_gh_auth_token() is None

    def test_gh_auth_succeeds(self):
        with patch(
            "give_back.auth.subprocess.run",
            return_value=type("Result", (), {"returncode": 0, "stdout": "ghp_from_gh\n"})(),
        ):
            from give_back.auth import _try_gh_auth_token

            assert _try_gh_auth_token() == "ghp_from_gh"

    def test_gh_timeout(self):
        import subprocess

        with patch("give_back.auth.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 5)):
            from give_back.auth import _try_gh_auth_token

            assert _try_gh_auth_token() is None
