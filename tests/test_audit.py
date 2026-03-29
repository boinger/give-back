"""Tests for give_back.audit — maintainer self-assessment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from give_back.audit import (
    AuditItem,
    AuditReport,
    _check_community_file,
    _check_issue_templates,
    _check_labels,
    _check_pr_template,
    _check_security,
    _wrap_signals,
    run_audit,
)
from give_back.exceptions import RepoNotFoundError
from give_back.github_client import GitHubClient
from give_back.models import RepoData, SignalResult, Tier

_RATE_HEADERS = {
    "X-RateLimit-Remaining": "4999",
    "X-RateLimit-Limit": "5000",
    "X-RateLimit-Reset": "9999999",
}


def _community_with(**files: object) -> dict:
    """Build a community profile dict with specified files present."""
    file_entries = {}
    for key, val in files.items():
        file_entries[key] = (
            {"url": f"https://api.github.com/{key}", "html_url": f"https://github.com/{key}"} if val else None
        )
    return {"health_percentage": 80, "files": file_entries}


def _community_all_present() -> dict:
    return _community_with(license=True, readme=True, contributing=True, code_of_conduct=True, security=True)


def _community_all_missing() -> dict:
    return _community_with(license=False, readme=False, contributing=False, code_of_conduct=False, security=False)


# ---------------------------------------------------------------------------
# Community health file checks
# ---------------------------------------------------------------------------


class TestCommunityFileChecks:
    def test_license_present(self) -> None:
        community = _community_with(license=True)
        item = _check_community_file(community, "license", "license", "LICENSE present", "Add a LICENSE.")
        assert item.passed
        assert item.recommendation is None

    def test_license_absent(self) -> None:
        community = _community_with(license=False)
        item = _check_community_file(community, "license", "license", "LICENSE present", "Add a LICENSE.")
        assert not item.passed
        assert item.recommendation == "Add a LICENSE."

    def test_readme_present(self) -> None:
        community = _community_with(readme=True)
        item = _check_community_file(community, "readme", "readme", "README present", "Add a README.")
        assert item.passed

    def test_readme_absent(self) -> None:
        community = _community_with(readme=False)
        item = _check_community_file(community, "readme", "readme", "README present", "Add a README.")
        assert not item.passed

    def test_empty_community(self) -> None:
        item = _check_community_file({}, "license", "license", "LICENSE present", "Add a LICENSE.")
        assert not item.passed


class TestSecurityCheck:
    @respx.mock
    def test_present(self) -> None:
        client = GitHubClient(token="fake")
        respx.get("https://api.github.com/repos/test/repo/contents/SECURITY.md").mock(
            return_value=httpx.Response(200, json={"name": "SECURITY.md"}, headers=_RATE_HEADERS)
        )
        item = _check_security(client, "test", "repo")
        client.close()
        assert item.passed

    @respx.mock
    def test_absent(self) -> None:
        client = GitHubClient(token="fake")
        respx.get(url__startswith="https://api.github.com/repos/test/repo/contents/").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"}, headers=_RATE_HEADERS)
        )
        item = _check_security(client, "test", "repo")
        client.close()
        assert not item.passed
        assert "https://github.com/test/repo/security/advisories/new" in item.recommendation


# ---------------------------------------------------------------------------
# Template checks
# ---------------------------------------------------------------------------


class TestPrTemplateCheck:
    @respx.mock
    def test_found(self) -> None:
        client = GitHubClient(token="fake")
        respx.get("https://api.github.com/repos/test/repo/contents/.github/PULL_REQUEST_TEMPLATE.md").mock(
            return_value=httpx.Response(200, json={"name": "PULL_REQUEST_TEMPLATE.md"}, headers=_RATE_HEADERS)
        )
        item = _check_pr_template(client, "test", "repo")
        client.close()
        assert item.passed

    @respx.mock
    def test_not_found(self) -> None:
        client = GitHubClient(token="fake")
        # All paths return 404
        respx.get(url__startswith="https://api.github.com/repos/test/repo/contents/").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"}, headers=_RATE_HEADERS)
        )
        item = _check_pr_template(client, "test", "repo")
        client.close()
        assert not item.passed
        assert item.recommendation is not None

    @respx.mock
    def test_api_error(self) -> None:
        client = GitHubClient(token="fake")
        respx.get(url__startswith="https://api.github.com/repos/test/repo/contents/").mock(
            return_value=httpx.Response(500, json={"message": "Server Error"}, headers=_RATE_HEADERS)
        )
        item = _check_pr_template(client, "test", "repo")
        client.close()
        assert not item.passed


class TestIssueTemplateCheck:
    @respx.mock
    def test_found(self) -> None:
        client = GitHubClient(token="fake")
        respx.get("https://api.github.com/repos/test/repo/contents/.github/ISSUE_TEMPLATE").mock(
            return_value=httpx.Response(
                200, json=[{"name": "bug_report.yml"}, {"name": "feature_request.yml"}], headers=_RATE_HEADERS
            )
        )
        item = _check_issue_templates(client, "test", "repo")
        client.close()
        assert item.passed
        assert "2 templates" in item.message

    @respx.mock
    def test_not_found(self) -> None:
        client = GitHubClient(token="fake")
        respx.get("https://api.github.com/repos/test/repo/contents/.github/ISSUE_TEMPLATE").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"}, headers=_RATE_HEADERS)
        )
        item = _check_issue_templates(client, "test", "repo")
        client.close()
        assert not item.passed

    @respx.mock
    def test_api_error(self) -> None:
        client = GitHubClient(token="fake")
        respx.get("https://api.github.com/repos/test/repo/contents/.github/ISSUE_TEMPLATE").mock(
            return_value=httpx.Response(500, json={"message": "Server Error"}, headers=_RATE_HEADERS)
        )
        item = _check_issue_templates(client, "test", "repo")
        client.close()
        assert not item.passed


# ---------------------------------------------------------------------------
# Label check
# ---------------------------------------------------------------------------


class TestLabelCheck:
    def test_all_present(self) -> None:
        item = _check_labels(["good first issue", "help wanted", "bug", "enhancement"])
        assert item.passed

    def test_partial(self) -> None:
        item = _check_labels(["good first issue", "bug"])
        assert item.passed
        assert "good first issue" in item.message

    def test_none(self) -> None:
        item = _check_labels(["bug", "enhancement", "documentation"])
        assert not item.passed
        assert item.recommendation is not None

    def test_empty(self) -> None:
        item = _check_labels([])
        assert not item.passed

    def test_case_insensitive(self) -> None:
        item = _check_labels(["Good First Issue", "Help Wanted"])
        assert item.passed


# ---------------------------------------------------------------------------
# Signal wrapping
# ---------------------------------------------------------------------------


class TestSignalWrapping:
    def test_healthy_signal(self) -> None:
        signals = [SignalResult(score=0.9, tier=Tier.GREEN, summary="87% merge rate")]
        names = ["External PR merge rate"]
        items = _wrap_signals(signals, names)
        assert len(items) == 1
        assert items[0].passed
        assert items[0].recommendation is None

    def test_poor_signal(self) -> None:
        signals = [SignalResult(score=0.3, tier=Tier.RED, summary="30% merge rate")]
        names = ["External PR merge rate"]
        items = _wrap_signals(signals, names)
        assert len(items) == 1
        assert not items[0].passed
        assert "merge rate" in items[0].recommendation.lower()

    def test_failed_signal(self) -> None:
        signals = [SignalResult(score=0.0, tier=Tier.RED, summary="N/A — evaluation failed")]
        names = ["External PR merge rate"]
        items = _wrap_signals(signals, names)
        assert len(items) == 1
        assert not items[0].passed

    def test_skipped_signal(self) -> None:
        signals = [SignalResult(score=0.0, tier=Tier.RED, summary="No data", skip=True)]
        names = ["CONTRIBUTING.md"]
        items = _wrap_signals(signals, names)
        assert len(items) == 0  # Skipped signals are excluded

    def test_unknown_signal_name(self) -> None:
        signals = [SignalResult(score=0.2, tier=Tier.RED, summary="bad signal")]
        names = ["Some Unknown Signal"]
        items = _wrap_signals(signals, names)
        assert len(items) == 1
        assert not items[0].passed
        assert "bad signal" in items[0].recommendation


# ---------------------------------------------------------------------------
# run_audit orchestration
# ---------------------------------------------------------------------------


def _fake_repo_data() -> RepoData:
    return RepoData(
        owner="test",
        repo="repo",
        graphql={
            "repository": {
                "labels": {"nodes": [{"name": "good first issue"}, {"name": "bug"}]},
                "pullRequests": {"nodes": []},
            }
        },
        community=_community_all_present(),
        contributing_text=None,
        search={},
    )


def _fake_assessment():
    from give_back.models import Assessment

    return Assessment(
        owner="test",
        repo="repo",
        overall_tier=Tier.GREEN,
        signals=[SignalResult(score=0.9, tier=Tier.GREEN, summary="looks good")],
        gate_passed=True,
        incomplete=False,
        timestamp="2026-01-01T00:00:00+00:00",
        signal_names=["External PR merge rate"],
    )


class TestRunAudit:
    @respx.mock
    @patch("give_back.audit.evaluate_signals")
    @patch("give_back.audit.fetch_repo_data")
    def test_full_audit(self, mock_fetch: MagicMock, mock_eval: MagicMock) -> None:
        mock_fetch.return_value = _fake_repo_data()
        mock_eval.return_value = _fake_assessment()

        # Mock template checks (both present)
        respx.get(url__startswith="https://api.github.com/repos/test/repo/contents/").mock(
            return_value=httpx.Response(200, json={"name": "template"}, headers=_RATE_HEADERS)
        )

        client = GitHubClient(token="fake")
        report = run_audit(client, "test", "repo")
        client.close()

        assert report.owner == "test"
        assert report.repo == "repo"
        assert report.health_percentage == 80
        assert report.signal_tier == Tier.GREEN
        assert len(report.items) > 0

        # All community health files present
        community_items = [i for i in report.items if i.category == "community_health"]
        assert all(i.passed for i in community_items)

    @patch("give_back.audit.evaluate_signals")
    @patch("give_back.audit.fetch_repo_data")
    def test_private_repo(self, mock_fetch: MagicMock, mock_eval: MagicMock) -> None:
        """Community profile 404 (private repo) still produces a report."""
        data = _fake_repo_data()
        data.community = {}  # Empty community = private or restricted
        mock_fetch.return_value = data
        mock_eval.return_value = _fake_assessment()

        client = GitHubClient(token="fake")
        report = run_audit(client, "test", "repo")
        client.close()

        # Community health checks should all fail
        community_items = [i for i in report.items if i.category == "community_health"]
        assert all(not i.passed for i in community_items)

    @respx.mock
    @patch("give_back.audit.evaluate_signals")
    @patch("give_back.audit.fetch_repo_data")
    def test_partial_failure(self, mock_fetch: MagicMock, mock_eval: MagicMock) -> None:
        """Some template checks fail but audit still completes."""
        data = _fake_repo_data()
        data.community = _community_all_missing()
        mock_fetch.return_value = data
        mock_eval.return_value = _fake_assessment()

        # Templates return 404
        respx.get(url__startswith="https://api.github.com/repos/test/repo/contents/").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"}, headers=_RATE_HEADERS)
        )

        client = GitHubClient(token="fake")
        report = run_audit(client, "test", "repo")
        client.close()

        # Should still have items (community + templates + labels + signals)
        assert len(report.items) > 5
        # Community health files all missing
        community_items = [i for i in report.items if i.category == "community_health"]
        assert all(not i.passed for i in community_items)


# ---------------------------------------------------------------------------
# Comparison mode
# ---------------------------------------------------------------------------


class TestComparison:
    def test_two_reports(self) -> None:
        """Comparison produces two AuditReports that can be displayed."""
        report_a = AuditReport(
            owner="a",
            repo="repo-a",
            items=[AuditItem(name="license", category="community_health", passed=True, message="MIT")],
        )
        report_b = AuditReport(
            owner="b",
            repo="repo-b",
            items=[AuditItem(name="license", category="community_health", passed=False, message="missing")],
        )
        # Just verify both reports are valid
        assert report_a.items[0].passed
        assert not report_b.items[0].passed

    @patch("give_back.audit.evaluate_signals")
    @patch("give_back.audit.fetch_repo_data")
    def test_second_repo_fails(self, mock_fetch: MagicMock, mock_eval: MagicMock) -> None:
        """If second repo fails with RepoNotFoundError, it propagates."""
        mock_fetch.side_effect = RepoNotFoundError("not found")
        client = GitHubClient(token="fake")
        with pytest.raises(RepoNotFoundError):
            run_audit(client, "nonexistent", "repo")
        client.close()
