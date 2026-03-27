"""Tests for triage/fetch.py issue fetching and filtering."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from give_back.github_client import GitHubClient
from give_back.triage.fetch import _estimate_clarity, _estimate_scope, fetch_issues
from give_back.triage.models import Clarity, Scope


def _make_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str = "A description of the issue.",
    labels: list[str] | None = None,
    comments: int = 2,
    days_ago_updated: int = 5,
    days_ago_created: int = 30,
    is_pr: bool = False,
) -> dict:
    now = datetime.now(timezone.utc)
    created = (now - timedelta(days=days_ago_created)).isoformat()
    updated = (now - timedelta(days=days_ago_updated)).isoformat()

    issue = {
        "number": number,
        "title": title,
        "body": body,
        "html_url": f"https://github.com/test/repo/issues/{number}",
        "labels": [{"name": lbl} for lbl in (labels or [])],
        "comments": comments,
        "created_at": created,
        "updated_at": updated,
        "state": "open",
    }
    if is_pr:
        issue["pull_request"] = {"url": "..."}
    return issue


@pytest.fixture
def client():
    c = GitHubClient(token="fake")
    yield c
    c.close()


class TestFetchIssues:
    @respx.mock
    def test_basic_fetch(self, client):
        issues = [_make_issue(number=1), _make_issue(number=2)]
        respx.get("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=issues,
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = fetch_issues(client, "test", "repo")
        assert len(result) == 2
        assert result[0].number == 1

    @respx.mock
    def test_filters_pull_requests(self, client):
        issues = [_make_issue(number=1), _make_issue(number=2, is_pr=True)]
        respx.get("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=issues,
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = fetch_issues(client, "test", "repo")
        assert len(result) == 1
        assert result[0].number == 1

    @respx.mock
    def test_filters_stale_without_priority_labels(self, client):
        issues = [_make_issue(number=1, days_ago_updated=200)]
        respx.get("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=issues,
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = fetch_issues(client, "test", "repo")
        assert len(result) == 0

    @respx.mock
    def test_keeps_stale_with_priority_label(self, client):
        issues = [_make_issue(number=1, days_ago_updated=200, labels=["good first issue"])]
        respx.get("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=issues,
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = fetch_issues(client, "test", "repo")
        assert len(result) == 1

    @respx.mock
    def test_staleness_risk_flagged(self, client):
        issues = [
            _make_issue(number=1, days_ago_created=400, days_ago_updated=200, labels=["help wanted"]),
        ]
        respx.get("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=issues,
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = fetch_issues(client, "test", "repo")
        assert len(result) == 1
        assert result[0].staleness_risk is True

    @respx.mock
    def test_priority_labels_extracted(self, client):
        issues = [_make_issue(number=1, labels=["good first issue", "bug", "unrelated"])]
        respx.get("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=issues,
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = fetch_issues(client, "test", "repo")
        assert "good first issue" in result[0].priority_labels
        assert "bug" in result[0].priority_labels
        assert "unrelated" not in result[0].priority_labels

    @respx.mock
    def test_empty_response(self, client):
        respx.get("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=[],
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = fetch_issues(client, "test", "repo")
        assert result == []


class TestEstimateScope:
    def test_small_from_label(self):
        assert _estimate_scope({"good first issue"}, "short body", 1) == Scope.SMALL

    def test_large_from_label(self):
        assert _estimate_scope({"feature"}, "some body", 5) == Scope.LARGE

    def test_large_from_long_body(self):
        assert _estimate_scope(set(), "x" * 2500, 5) == Scope.LARGE

    def test_large_from_many_comments(self):
        assert _estimate_scope(set(), "some body", 25) == Scope.LARGE

    def test_small_from_short_body(self):
        assert _estimate_scope(set(), "short", 1) == Scope.SMALL

    def test_medium_default(self):
        assert _estimate_scope(set(), "x" * 800, 5) == Scope.MEDIUM


class TestEstimateClarity:
    def test_high_with_code_block(self):
        body = "x" * 250 + "\n```python\ncode\n```"
        assert _estimate_clarity(body) == Clarity.HIGH

    def test_high_with_steps(self):
        body = "x" * 250 + "\nSteps to reproduce:\n1. Do this"
        assert _estimate_clarity(body) == Clarity.HIGH

    def test_medium_long_no_structure(self):
        body = "x" * 250
        assert _estimate_clarity(body) == Clarity.MEDIUM

    def test_low_short(self):
        assert _estimate_clarity("fix this") == Clarity.LOW

    def test_low_empty(self):
        assert _estimate_clarity("") == Clarity.LOW
