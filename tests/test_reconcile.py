"""Tests for reconcile.py bias detection and adjustment."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from give_back.models import SignalResult, SignalWeight, Tier
from give_back.reconcile import (
    _check_author_transition,
    _get_collaborator_authors,
    reconcile_merge_rate,
    should_reconcile,
)


def _result(score: float, skip: bool = False) -> SignalResult:
    if score >= 0.7:
        tier = Tier.GREEN
    elif score >= 0.4:
        tier = Tier.YELLOW
    else:
        tier = Tier.RED
    return SignalResult(score=score, tier=tier, summary="test", skip=skip)


class TestShouldReconcile:
    def test_low_merge_rate_healthy_others_triggers(self):
        """Low merge rate + healthy other signals → should reconcile."""
        results = [
            (SignalWeight.GATE, _result(1.0)),
            (SignalWeight.HIGH, _result(0.2)),  # merge rate - LOW
            (SignalWeight.HIGH, _result(0.8)),  # ghost closing - healthy
            (SignalWeight.MEDIUM, _result(0.9)),  # time to response - healthy
            (SignalWeight.MEDIUM, _result(0.8)),  # staleness - healthy
            (SignalWeight.LOW, _result(0.7)),  # labels - healthy
        ]
        names = [
            "License",
            "External PR merge rate",
            "Ghost-closing rate",
            "Time-to-first-response",
            "Staleness",
            "Issue label hygiene",
        ]
        assert should_reconcile(results, names) is True

    def test_low_merge_rate_unhealthy_others_no_trigger(self):
        """Low merge rate + unhealthy other signals → don't reconcile."""
        results = [
            (SignalWeight.GATE, _result(1.0)),
            (SignalWeight.HIGH, _result(0.1)),  # merge rate - RED
            (SignalWeight.HIGH, _result(0.2)),  # ghost closing - RED
            (SignalWeight.MEDIUM, _result(0.1)),  # response - RED
        ]
        names = ["License", "External PR merge rate", "Ghost-closing rate", "Time-to-first-response"]
        assert should_reconcile(results, names) is False

    def test_high_merge_rate_no_trigger(self):
        """High merge rate → no need to reconcile."""
        results = [
            (SignalWeight.GATE, _result(1.0)),
            (SignalWeight.HIGH, _result(0.8)),  # merge rate - GREEN
            (SignalWeight.MEDIUM, _result(0.9)),
        ]
        names = ["License", "External PR merge rate", "Staleness"]
        assert should_reconcile(results, names) is False

    def test_no_merge_signal_no_trigger(self):
        """No merge rate signal → no reconciliation."""
        results = [
            (SignalWeight.GATE, _result(1.0)),
            (SignalWeight.MEDIUM, _result(0.9)),
        ]
        names = ["License", "Staleness"]
        assert should_reconcile(results, names) is False

    def test_skipped_signals_excluded(self):
        """Skipped signals don't count toward 'healthy other signals'."""
        results = [
            (SignalWeight.GATE, _result(1.0)),
            (SignalWeight.HIGH, _result(0.1)),  # merge rate - RED
            (SignalWeight.LOW, _result(0.0, skip=True)),  # skipped
            (SignalWeight.MEDIUM, _result(0.0, skip=True)),  # skipped
            (SignalWeight.MEDIUM, _result(0.9)),  # only real other signal - healthy
        ]
        names = ["License", "External PR merge rate", "CONTRIBUTING.md", "Contribution process", "Staleness"]
        # Only 1 real other signal, it's healthy (1/1 = 100%)
        assert should_reconcile(results, names) is True


def _make_search_item(created_days_ago: int, merged: bool = True) -> dict:
    """Build a fake search API item with created_at and merged_at."""
    created = (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()
    merged_at = created if merged else None
    return {
        "created_at": created,
        "pull_request": {"merged_at": merged_at},
    }


class TestCheckAuthorTransition:
    def test_old_prs_counted(self):
        """Merged PRs older than 180 days are counted as pre-promotion."""
        client = MagicMock()
        client.search.return_value = {
            "items": [
                _make_search_item(created_days_ago=365),
                _make_search_item(created_days_ago=300),
                _make_search_item(created_days_ago=200),
            ]
        }
        assert _check_author_transition(client, "org", "repo", "alice") == 3

    def test_recent_prs_excluded(self):
        """Merged PRs within 180 days are assumed post-promotion and excluded."""
        client = MagicMock()
        client.search.return_value = {
            "items": [
                _make_search_item(created_days_ago=30),
                _make_search_item(created_days_ago=60),
                _make_search_item(created_days_ago=90),
            ]
        }
        assert _check_author_transition(client, "org", "repo", "alice") == 0

    def test_mixed_old_and_recent(self):
        """Only old PRs count, recent ones are excluded."""
        client = MagicMock()
        client.search.return_value = {
            "items": [
                _make_search_item(created_days_ago=400),  # old, counts
                _make_search_item(created_days_ago=200),  # old, counts
                _make_search_item(created_days_ago=30),  # recent, excluded
                _make_search_item(created_days_ago=10),  # recent, excluded
            ]
        }
        assert _check_author_transition(client, "org", "repo", "alice") == 2

    def test_unmerged_prs_excluded(self):
        """Closed but not merged PRs are not counted."""
        client = MagicMock()
        client.search.return_value = {
            "items": [
                _make_search_item(created_days_ago=365, merged=False),
                _make_search_item(created_days_ago=300, merged=True),
            ]
        }
        assert _check_author_transition(client, "org", "repo", "alice") == 1

    def test_no_items_returns_zero(self):
        """Empty search results return 0."""
        client = MagicMock()
        client.search.return_value = {"items": []}
        assert _check_author_transition(client, "org", "repo", "alice") == 0

    def test_api_error_returns_zero(self):
        """GiveBackError during search returns 0 gracefully."""
        from give_back.exceptions import GiveBackError

        client = MagicMock()
        client.search.side_effect = GiveBackError("rate limit")
        assert _check_author_transition(client, "org", "repo", "alice") == 0

    def test_missing_created_at_skipped(self):
        """Items without created_at are silently skipped."""
        client = MagicMock()
        client.search.return_value = {
            "items": [
                {"pull_request": {"merged_at": "2024-01-01T00:00:00Z"}},  # no created_at
                _make_search_item(created_days_ago=365),
            ]
        }
        assert _check_author_transition(client, "org", "repo", "alice") == 1


class TestGetCollaboratorAuthors:
    def test_extracts_from_collaborator_prs(self):
        """Extracts unique author logins from details."""
        result = SignalResult(
            score=0.2,
            tier=Tier.RED,
            summary="test",
            details={"collaborator_prs": ["alice", "bob", "alice"]},
        )
        authors = _get_collaborator_authors(result)
        assert authors == ["alice", "bob"]

    def test_empty_list(self):
        result = SignalResult(score=0.2, tier=Tier.RED, summary="test", details={"collaborator_prs": []})
        assert _get_collaborator_authors(result) == []

    def test_missing_key(self):
        result = SignalResult(score=0.2, tier=Tier.RED, summary="test", details={})
        assert _get_collaborator_authors(result) == []

    def test_count_without_names_returns_empty(self):
        """If we have a count but no names, can't investigate."""
        result = SignalResult(score=0.2, tier=Tier.RED, summary="test", details={"collaborator_pr_count": 5})
        assert _get_collaborator_authors(result) == []


class TestReconcileMergeRate:
    def _make_original_result(self, collaborator_prs=None):
        return SignalResult(
            score=0.2,
            tier=Tier.RED,
            summary="20% of external PRs merged",
            details={
                "external_merged": 2,
                "external_closed": 10,
                "collaborator_prs": collaborator_prs or [],
            },
        )

    def test_adjustment_applied(self):
        """When transitions found, score is adjusted upward."""
        original = self._make_original_result(collaborator_prs=["alice"])
        client = MagicMock()

        with patch(
            "give_back.reconcile._check_author_transition",
            return_value=3,
        ):
            result = reconcile_merge_rate(client, "org", "repo", original)

        assert result is not None
        assert result.score > original.score
        assert result.details["adjusted"] is True
        assert result.details["transitioned_authors"] == ["alice"]
        assert result.details["transitioned_pr_count"] == 3
        assert "adjusted" in result.summary.lower()

    def test_no_collaborator_authors(self):
        """No collaborator authors → no adjustment."""
        original = SignalResult(
            score=0.2, tier=Tier.RED, summary="test", details={"external_merged": 2, "external_closed": 10}
        )
        result = reconcile_merge_rate(MagicMock(), "org", "repo", original)
        assert result is None

    def test_no_transitions_found(self):
        """Authors checked but no transitions detected → no adjustment."""
        original = self._make_original_result(collaborator_prs=["alice"])
        client = MagicMock()

        with patch("give_back.reconcile._check_author_transition", return_value=0):
            result = reconcile_merge_rate(client, "org", "repo", original)

        assert result is None

    def test_verbose_output(self, capsys):
        """Verbose mode prints investigation progress."""
        original = self._make_original_result(collaborator_prs=["alice"])
        client = MagicMock()

        with patch("give_back.reconcile._check_author_transition", return_value=2):
            reconcile_merge_rate(client, "org", "repo", original, verbose=True)

        output = capsys.readouterr().err
        assert "Investigating" in output or "role transitions" in output

    def test_limits_authors_investigated(self):
        """Only investigates up to _MAX_AUTHORS_TO_INVESTIGATE authors."""
        original = self._make_original_result(collaborator_prs=[f"user{i}" for i in range(20)])
        client = MagicMock()
        call_count = 0

        def count_calls(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return 0

        with patch("give_back.reconcile._check_author_transition", side_effect=count_calls):
            reconcile_merge_rate(client, "org", "repo", original)

        assert call_count == 5  # _MAX_AUTHORS_TO_INVESTIGATE
