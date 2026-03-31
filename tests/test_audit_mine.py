"""Tests for audit --mine batch mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from give_back.audit import AuditItem, AuditReport
from give_back.audit_mine import fetch_user_repos, print_batch_results, run_batch_audit


def _make_repo(full_name: str, *, private: bool = False, archived: bool = False, fork: bool = False) -> dict:
    owner, name = full_name.split("/")
    return {
        "full_name": full_name,
        "name": name,
        "owner": {"login": owner},
        "private": private,
        "archived": archived,
        "fork": fork,
        "pushed_at": "2026-03-29T00:00:00Z",
    }


class TestFetchUserRepos:
    def test_filters_private_and_archived(self):
        client = MagicMock()
        client.rest_get.return_value = [
            _make_repo("user/public"),
            _make_repo("user/private", private=True),
            _make_repo("user/archived", archived=True),
            _make_repo("user/fork", fork=True),
        ]
        repos = fetch_user_repos(client)
        assert len(repos) == 1
        assert repos[0]["full_name"] == "user/public"

    def test_include_all(self):
        client = MagicMock()
        client.rest_get.return_value = [
            _make_repo("user/public"),
            _make_repo("user/private", private=True),
            _make_repo("user/archived", archived=True),
        ]
        repos = fetch_user_repos(client, include_all=True)
        assert len(repos) == 3

    def test_empty_response(self):
        client = MagicMock()
        client.rest_get.return_value = []
        repos = fetch_user_repos(client)
        assert repos == []

    def test_pagination(self):
        client = MagicMock()
        # First page returns 100, second page returns 50 (less than per_page → stop)
        page1 = [_make_repo(f"user/repo{i}") for i in range(100)]
        page2 = [_make_repo(f"user/repo{i}") for i in range(100, 150)]
        client.rest_get.side_effect = [page1, page2]
        repos = fetch_user_repos(client)
        assert len(repos) == 150


class TestRunBatchAudit:
    def test_audits_up_to_limit(self):
        repos = [_make_repo(f"user/repo{i}") for i in range(5)]
        report = AuditReport(
            owner="user",
            repo="repo0",
            items=[AuditItem(name="license", category="community_health", passed=True, message="ok")],
        )

        with (
            patch("give_back.audit_mine.run_audit", return_value=report),
            patch("give_back.audit_mine.save_audit_result"),
        ):
            results = run_batch_audit(MagicMock(), repos, limit=3)
        assert len(results) == 3

    def test_handles_errors_gracefully(self):
        repos = [_make_repo("user/good"), _make_repo("user/bad")]

        report = AuditReport(
            owner="user",
            repo="good",
            items=[AuditItem(name="license", category="community_health", passed=True, message="ok")],
        )

        from give_back.exceptions import RepoNotFoundError

        def mock_audit(client, owner, name, **kwargs):
            if name == "bad":
                raise RepoNotFoundError("not found")
            return report

        with (
            patch("give_back.audit_mine.run_audit", side_effect=mock_audit),
            patch("give_back.audit_mine.save_audit_result"),
        ):
            results = run_batch_audit(MagicMock(), repos, limit=2)

        assert len(results) == 2
        assert results[0][1] is not None  # good: has report
        assert results[1][1] is None  # bad: error
        assert results[1][2] is not None  # bad: has error message


class TestPrintBatchResults:
    def test_prints_without_error(self, capsys):
        """Smoke test: print_batch_results doesn't crash."""
        report = AuditReport(
            owner="user",
            repo="repo",
            items=[
                AuditItem(name="license", category="community_health", passed=True, message="ok"),
                AuditItem(name="security", category="community_health", passed=False, message="missing"),
            ],
        )
        results = [
            (_make_repo("user/repo"), report, None),
            (_make_repo("user/broken"), None, "API error"),
        ]
        print_batch_results(results)
        output = capsys.readouterr().out
        assert "user/repo" in output
        assert "user/broken" in output
        assert "1/2" in output
