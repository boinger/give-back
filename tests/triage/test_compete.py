"""Tests for triage/compete.py competing work detection."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from give_back.github_client import GitHubClient
from give_back.triage.compete import check_competition
from give_back.triage.models import Clarity, Competition, IssueCandidate, Scope

_RATE_HEADERS = {
    "X-RateLimit-Remaining": "4999",
    "X-RateLimit-Limit": "5000",
    "X-RateLimit-Reset": "9999999",
}


def _make_candidate(number: int = 42) -> IssueCandidate:
    return IssueCandidate(
        number=number,
        title=f"Test issue #{number}",
        url=f"https://github.com/test/repo/issues/{number}",
        labels=[],
        scope=Scope.SMALL,
        clarity=Clarity.MEDIUM,
        competition=Competition.NONE,
    )


def _search_response(items: list[dict], total_count: int | None = None) -> httpx.Response:
    count = total_count if total_count is not None else len(items)
    return httpx.Response(200, json={"total_count": count, "items": items}, headers=_RATE_HEADERS)


def _comments_response(comments: list[dict]) -> httpx.Response:
    return httpx.Response(200, json=comments, headers=_RATE_HEADERS)


def _make_pr_item(number: int = 100, days_ago_updated: int = 5) -> dict:
    updated = (datetime.now(timezone.utc) - timedelta(days=days_ago_updated)).isoformat()
    return {
        "number": number,
        "title": f"PR #{number}",
        "updated_at": updated,
    }


def _make_comment(body: str, days_ago: int = 1, author: str = "contributor") -> dict:
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "body": body,
        "created_at": created,
        "user": {"login": author},
    }


@pytest.fixture
def client():
    c = GitHubClient(token="fake")
    yield c
    c.close()


class TestCheckCompetition:
    @respx.mock
    def test_no_competition(self, client):
        """No linked PRs and no claim comments -> NONE."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.NONE
        assert candidate.competition_detail is None

    @respx.mock
    def test_active_pr_found(self, client):
        """Active PR (updated recently) -> HIGH."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([_make_pr_item(number=99, days_ago_updated=5)]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert candidate.competition_detail == "PR #99 active"

    @respx.mock
    def test_stale_pr_found(self, client):
        """PR not updated in >6 months -> LOW."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([_make_pr_item(number=77, days_ago_updated=250)]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.LOW
        assert "PR #77 stale" in candidate.competition_detail
        assert "months" in candidate.competition_detail

    @respx.mock
    def test_recent_claim_comment(self, client):
        """Recent claim comment (<30 days) -> HIGH."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("I'm working on this", days_ago=3, author="alice"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert "claimed by @alice" in candidate.competition_detail
        assert "3 days ago" in candidate.competition_detail

    @respx.mock
    def test_old_claim_comment(self, client):
        """Old claim comment (>30 days) -> LOW."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("I'll take this", days_ago=90, author="bob"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.LOW
        assert "claimed by @bob" in candidate.competition_detail
        assert "may be abandoned" in candidate.competition_detail

    @respx.mock
    def test_both_pr_and_claim_higher_wins(self, client):
        """Active PR (HIGH) + old claim (LOW) -> HIGH with PR detail."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([_make_pr_item(number=55, days_ago_updated=2)]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("I'll take this", days_ago=90, author="bob"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert "PR #55 active" in candidate.competition_detail

    @respx.mock
    def test_both_high_prefers_pr_detail(self, client):
        """Both PR and claim are HIGH -> uses PR detail."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([_make_pr_item(number=88, days_ago_updated=1)]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("I'm working on this", days_ago=2, author="alice"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert "PR #88 active" in candidate.competition_detail

    @respx.mock
    def test_api_error_leaves_competition_none(self, client):
        """API error on search -> competition stays NONE."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"}, headers=_RATE_HEADERS),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.NONE
        assert candidate.competition_detail is None

    @respx.mock
    def test_no_comments_on_issue(self, client):
        """Issue with no comments -> NONE from comments check."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.NONE

    @respx.mock
    def test_claim_pattern_wip(self, client):
        """WIP pattern detected in comment."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("WIP", days_ago=5, author="dev"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert "claimed by @dev" in candidate.competition_detail

    @respx.mock
    def test_claim_pattern_submit_pr(self, client):
        """'I'll submit a PR' pattern detected."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("I'll submit a PR for this soon", days_ago=10, author="carol"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert "claimed by @carol" in candidate.competition_detail

    @respx.mock
    def test_non_claim_comment_ignored(self, client):
        """Regular comments that don't match claim patterns -> NONE."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("This is a bug that needs fixing", days_ago=2, author="user1"),
                    _make_comment("I can reproduce this too", days_ago=1, author="user2"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.NONE

    @respx.mock
    def test_stale_pr_plus_recent_claim_claim_wins(self, client):
        """Stale PR (LOW) + recent claim (HIGH) -> HIGH with claim detail."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            return_value=_search_response([_make_pr_item(number=33, days_ago_updated=250)]),
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response(
                [
                    _make_comment("I'm working on this", days_ago=2, author="newdev"),
                ]
            ),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert "claimed by @newdev" in candidate.competition_detail
