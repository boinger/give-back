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

_EMPTY_SEARCH = httpx.Response(200, json={"total_count": 0, "items": []}, headers=_RATE_HEADERS)


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


def _make_merged_pr_item(number: int = 200, days_ago_closed: int = 3) -> dict:
    closed = (datetime.now(timezone.utc) - timedelta(days=days_ago_closed)).isoformat()
    return {
        "number": number,
        "title": f"PR #{number}",
        "closed_at": closed,
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


# ---------------------------------------------------------------------------
# Existing competition checks (open PRs + claim comments)
# ---------------------------------------------------------------------------
# check_competition now makes 3 API calls per candidate:
#   1. search merged PRs
#   2. search open PRs
#   3. issue comments
# Tests use side_effect on search to control responses in order.


class TestCheckCompetition:
    @respx.mock
    def test_no_competition(self, client):
        """No merged PRs, no open PRs, no claim comments -> NONE."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[_EMPTY_SEARCH, _EMPTY_SEARCH],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.NONE
        assert candidate.competition_detail is None

    @respx.mock
    def test_active_pr_found(self, client):
        """Active open PR (updated recently) -> HIGH."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _EMPTY_SEARCH,  # merged: none
                _search_response([_make_pr_item(number=99, days_ago_updated=5)]),  # open: active
            ],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert candidate.competition_detail == "PR #99 active"

    @respx.mock
    def test_stale_pr_found(self, client):
        """Open PR not updated in >6 months -> LOW."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _EMPTY_SEARCH,
                _search_response([_make_pr_item(number=77, days_ago_updated=250)]),
            ],
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
            side_effect=[_EMPTY_SEARCH, _EMPTY_SEARCH],
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
            side_effect=[_EMPTY_SEARCH, _EMPTY_SEARCH],
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
        """Active open PR (HIGH) + old claim (LOW) -> HIGH with PR detail."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _EMPTY_SEARCH,
                _search_response([_make_pr_item(number=55, days_ago_updated=2)]),
            ],
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
        """Both open PR and claim are HIGH -> uses PR detail."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _EMPTY_SEARCH,
                _search_response([_make_pr_item(number=88, days_ago_updated=1)]),
            ],
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
        """API error on first search -> competition stays NONE."""
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
            side_effect=[_EMPTY_SEARCH, _EMPTY_SEARCH],
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
            side_effect=[_EMPTY_SEARCH, _EMPTY_SEARCH],
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
            side_effect=[_EMPTY_SEARCH, _EMPTY_SEARCH],
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
            side_effect=[_EMPTY_SEARCH, _EMPTY_SEARCH],
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
        """Stale open PR (LOW) + recent claim (HIGH) -> HIGH with claim detail."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _EMPTY_SEARCH,
                _search_response([_make_pr_item(number=33, days_ago_updated=250)]),
            ],
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


# ---------------------------------------------------------------------------
# Merged PR detection (new)
# ---------------------------------------------------------------------------


class TestMergedPrDetection:
    @respx.mock
    def test_merged_pr_found(self, client):
        """Merged PR referencing issue -> RESOLVED."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _search_response([_make_merged_pr_item(number=3064, days_ago_closed=4)]),  # merged: found
                _EMPTY_SEARCH,  # open: none (not reached due to RESOLVED short-circuit)
            ],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.RESOLVED
        assert "PR #3064 merged" in candidate.competition_detail
        assert "may already address this" in candidate.competition_detail

    @respx.mock
    def test_merged_pr_trumps_active_open_pr(self, client):
        """Merged PR takes priority over active open PR."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _search_response([_make_merged_pr_item(number=500, days_ago_closed=1)]),  # merged
                _search_response([_make_pr_item(number=501, days_ago_updated=1)]),  # open (active)
            ],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([_make_comment("I'm working on this", days_ago=1, author="someone")]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.RESOLVED
        assert "PR #500 merged" in candidate.competition_detail

    @respx.mock
    def test_merged_pr_picks_most_recent(self, client):
        """When multiple merged PRs exist, picks the most recently closed."""
        old_pr = _make_merged_pr_item(number=100, days_ago_closed=30)
        recent_pr = _make_merged_pr_item(number=200, days_ago_closed=2)
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _search_response([old_pr, recent_pr]),
                _EMPTY_SEARCH,
            ],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.RESOLVED
        assert "PR #200 merged" in candidate.competition_detail

    @respx.mock
    def test_merged_search_empty_falls_through(self, client):
        """No merged PRs -> falls through to open PR check."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _EMPTY_SEARCH,  # merged: none
                _search_response([_make_pr_item(number=99, days_ago_updated=5)]),  # open: active
            ],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.HIGH
        assert "PR #99 active" in candidate.competition_detail

    @respx.mock
    def test_merged_pr_missing_closed_at(self, client):
        """Merged PR item without closed_at is ignored."""
        bad_item = {"number": 300, "title": "PR #300"}  # no closed_at
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _search_response([bad_item]),  # merged: item but no date
                _EMPTY_SEARCH,
            ],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        assert candidate.competition == Competition.NONE

    @respx.mock
    def test_merged_pr_date_format(self, client):
        """Merged PR detail includes formatted date."""
        candidate = _make_candidate()
        respx.get("https://api.github.com/search/issues").mock(
            side_effect=[
                _search_response([_make_merged_pr_item(number=3064, days_ago_closed=4)]),
                _EMPTY_SEARCH,
            ],
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=_comments_response([]),
        )
        check_competition(client, "test", "repo", [candidate])
        expected_date = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")
        assert expected_date in candidate.competition_detail
