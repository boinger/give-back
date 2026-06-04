"""Tests for assess.py core assessment logic."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from give_back.assess import _fetch_prs_paginated, run_assessment
from give_back.exceptions import GiveBackError, RateLimitError
from give_back.models import Assessment, RepoData, SignalDef, SignalResult, SignalWeight, Tier


def _fake_repo_data() -> RepoData:
    return RepoData(
        owner="test-owner",
        repo="test-repo",
        graphql={},
        community={},
        contributing_text=None,
        search={},
    )


def _ok_result(score: float = 0.9, tier: Tier = Tier.GREEN, summary: str = "looks good") -> SignalResult:
    return SignalResult(score=score, tier=tier, summary=summary)


def _gate_pass() -> SignalResult:
    return SignalResult(score=1.0, tier=Tier.GREEN, summary="gate passed")


def _gate_fail() -> SignalResult:
    return SignalResult(score=-1.0, tier=Tier.RED, summary="gate failed")


def _make_signals(specs: list[tuple]) -> list[SignalDef]:
    """Build a list of SignalDef from (func, name, weight) tuples."""
    return [SignalDef(func=fn, name=name, weight=weight) for fn, name, weight in specs]


# Shared patches applied to every test: avoid real API calls, skip reconciliation and LLM license.
_PATCH_FETCH = patch("give_back.assess.fetch_repo_data", return_value=_fake_repo_data())
_PATCH_RECONCILE = patch("give_back.assess.should_reconcile", return_value=False)
_PATCH_LLM_LICENSE = patch("give_back.assess._try_llm_license_classification")


class TestAllSignalsSucceed:
    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_green_assessment(self, _mock_fetch, _mock_reconcile, _mock_llm):
        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (lambda _: _ok_result(0.9), "PR merge rate", SignalWeight.HIGH),
                (lambda _: _ok_result(0.8), "Time-to-response", SignalWeight.MEDIUM),
            ]
        )
        with patch("give_back.assess.ALL_SIGNALS", signals):
            result = run_assessment(MagicMock(), "test-owner", "test-repo")

        assert isinstance(result, Assessment)
        assert result.owner == "test-owner"
        assert result.repo == "test-repo"
        assert result.overall_tier == Tier.GREEN
        assert result.gate_passed is True
        assert result.incomplete is False
        assert len(result.signals) == 3
        assert result.timestamp  # non-empty ISO string

    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_signal_results_preserved_in_order(self, _mock_fetch, _mock_reconcile, _mock_llm):
        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (lambda _: _ok_result(0.5, Tier.YELLOW, "medium quality"), "Staleness", SignalWeight.MEDIUM),
                (lambda _: _ok_result(0.2, Tier.RED, "poor labels"), "Labels", SignalWeight.LOW),
            ]
        )
        with patch("give_back.assess.ALL_SIGNALS", signals):
            result = run_assessment(MagicMock(), "test-owner", "test-repo")

        assert result.signals[0].summary == "gate passed"
        assert result.signals[1].summary == "medium quality"
        assert result.signals[2].summary == "poor labels"


class TestGiveBackErrorInSignal:
    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_known_error_falls_back_to_red(self, _mock_fetch, _mock_reconcile, _mock_llm):
        def exploding_signal(_):
            raise RateLimitError("rate limited")

        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (exploding_signal, "PR merge rate", SignalWeight.HIGH),
                (lambda _: _ok_result(0.8), "Time-to-response", SignalWeight.MEDIUM),
            ]
        )
        with patch("give_back.assess.ALL_SIGNALS", signals):
            result = run_assessment(MagicMock(), "test-owner", "test-repo")

        # The failed signal should have the RED fallback
        failed = result.signals[1]
        assert failed.score == 0.0
        assert failed.tier == Tier.RED
        assert "evaluation failed" in failed.summary

        # The other signals should be unaffected
        assert result.signals[0].summary == "gate passed"
        assert result.signals[2].score == 0.8

    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_base_give_back_error(self, _mock_fetch, _mock_reconcile, _mock_llm):
        def exploding_signal(_):
            raise GiveBackError("something went wrong")

        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (exploding_signal, "Broken", SignalWeight.MEDIUM),
            ]
        )
        with patch("give_back.assess.ALL_SIGNALS", signals):
            result = run_assessment(MagicMock(), "test-owner", "test-repo")

        assert result.signals[1].score == 0.0
        assert result.signals[1].tier == Tier.RED


class TestUnexpectedExceptionLogsWarning:
    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_type_error_logged_and_falls_back(self, _mock_fetch, _mock_reconcile, _mock_llm, caplog):
        def buggy_signal(_):
            raise TypeError("NoneType has no attribute 'get'")

        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (buggy_signal, "Buggy signal", SignalWeight.MEDIUM),
                (lambda _: _ok_result(0.8), "Good signal", SignalWeight.HIGH),
            ]
        )
        with caplog.at_level(logging.WARNING, logger="give_back.assess"):
            with patch("give_back.assess.ALL_SIGNALS", signals):
                result = run_assessment(MagicMock(), "test-owner", "test-repo")

        # Warning logged
        assert any(
            "Buggy signal" in record.message and "unexpected" in record.message.lower() for record in caplog.records
        )

        # Fallback to RED
        assert result.signals[1].score == 0.0
        assert result.signals[1].tier == Tier.RED
        assert "evaluation failed" in result.signals[1].summary

        # Other signals unaffected
        assert result.signals[2].score == 0.8

    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_key_error_logged(self, _mock_fetch, _mock_reconcile, _mock_llm, caplog):
        def buggy_signal(_):
            raise KeyError("missing_key")

        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (buggy_signal, "KeyErr signal", SignalWeight.LOW),
            ]
        )
        with caplog.at_level(logging.WARNING, logger="give_back.assess"):
            with patch("give_back.assess.ALL_SIGNALS", signals):
                run_assessment(MagicMock(), "test-owner", "test-repo")

        assert any("KeyErr signal" in record.message for record in caplog.records)


class TestGateFailure:
    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_gate_failure_returns_red(self, _mock_fetch, _mock_reconcile, _mock_llm):
        signals = _make_signals(
            [
                (lambda _: _gate_fail(), "License", SignalWeight.GATE),
                (lambda _: _ok_result(1.0), "PR merge rate", SignalWeight.HIGH),
                (lambda _: _ok_result(1.0), "Everything else", SignalWeight.MEDIUM),
            ]
        )
        with patch("give_back.assess.ALL_SIGNALS", signals):
            result = run_assessment(MagicMock(), "test-owner", "test-repo")

        assert result.overall_tier == Tier.RED
        assert result.gate_passed is False


class TestIncompleteAssessment:
    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_high_signal_failure_marks_incomplete(self, _mock_fetch, _mock_reconcile, _mock_llm):
        def exploding_high(_):
            raise GiveBackError("API down")

        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (exploding_high, "PR merge rate", SignalWeight.HIGH),
                (lambda _: _ok_result(0.9), "Time-to-response", SignalWeight.MEDIUM),
                (lambda _: _ok_result(0.9), "Labels", SignalWeight.LOW),
            ]
        )
        with patch("give_back.assess.ALL_SIGNALS", signals):
            result = run_assessment(MagicMock(), "test-owner", "test-repo")

        assert result.incomplete is True
        # Tier capped at YELLOW due to incomplete (would be GREEN otherwise)
        assert result.overall_tier == Tier.YELLOW

    @_PATCH_LLM_LICENSE
    @_PATCH_RECONCILE
    @_PATCH_FETCH
    def test_medium_signal_failure_not_incomplete(self, _mock_fetch, _mock_reconcile, _mock_llm):
        def exploding_medium(_):
            raise GiveBackError("oops")

        signals = _make_signals(
            [
                (lambda _: _gate_pass(), "License", SignalWeight.GATE),
                (lambda _: _ok_result(0.9), "PR merge rate", SignalWeight.HIGH),
                (exploding_medium, "AI policy", SignalWeight.MEDIUM),
            ]
        )
        with patch("give_back.assess.ALL_SIGNALS", signals):
            result = run_assessment(MagicMock(), "test-owner", "test-repo")

        # MEDIUM failure does not trigger incomplete
        assert result.incomplete is False


# ---------------------------------------------------------------------------
# _fetch_prs_paginated — characterization tests pinned before extracting the
# page-boundary check into a helper (plans/PLAN-sloppylint-cleanup.md; the
# boundary branch was previously uncovered).
# ---------------------------------------------------------------------------


def _page(nodes, has_prev=False, start_cursor=None):
    return {
        "repository": {
            "pullRequests": {
                "nodes": nodes,
                "pageInfo": {"hasPreviousPage": has_prev, "startCursor": start_cursor},
            }
        }
    }


def _pr(created_at: str) -> dict:
    return {"createdAt": created_at}


def _recent_iso() -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestFetchPrsPaginatedBoundary:
    def test_stops_at_twelve_month_boundary(self):
        """A page whose oldest PR predates the window stops pagination despite more pages."""
        client = MagicMock()
        client.graphql.return_value = _page([_pr("2020-01-01T00:00:00Z")], has_prev=True, start_cursor="c1")

        prs = _fetch_prs_paginated(client, "o", "r", verbose=False)

        assert client.graphql.call_count == 1
        assert len(prs) == 1

    def test_boundary_stop_verbose(self):
        """Verbose mode logs the boundary but stops identically."""
        client = MagicMock()
        client.graphql.return_value = _page([_pr("2020-01-01T00:00:00Z")], has_prev=True, start_cursor="c1")

        prs = _fetch_prs_paginated(client, "o", "r", verbose=True)

        assert client.graphql.call_count == 1
        assert len(prs) == 1

    def test_invalid_date_does_not_stop_pagination(self):
        """An unparseable createdAt is ignored; pagination continues to the cursor logic."""
        client = MagicMock()
        client.graphql.side_effect = [
            _page([_pr("not-a-date")], has_prev=True, start_cursor="c1"),
            _page([], has_prev=False),
        ]

        prs = _fetch_prs_paginated(client, "o", "r", verbose=False)

        assert client.graphql.call_count == 2
        assert len(prs) == 1

    def test_empty_page_stops(self):
        """An empty page ends pagination, keeping previously fetched PRs."""
        client = MagicMock()
        client.graphql.side_effect = [
            _page([_pr(_recent_iso())], has_prev=True, start_cursor="c1"),
            _page([], has_prev=True, start_cursor="c2"),
        ]

        prs = _fetch_prs_paginated(client, "o", "r", verbose=False)

        assert client.graphql.call_count == 2
        assert len(prs) == 1

    def test_missing_cursor_stops(self):
        """hasPreviousPage without a startCursor ends pagination after the current page."""
        client = MagicMock()
        client.graphql.return_value = _page([_pr(_recent_iso())], has_prev=True, start_cursor=None)

        prs = _fetch_prs_paginated(client, "o", "r", verbose=False)

        assert client.graphql.call_count == 1
        assert len(prs) == 1
