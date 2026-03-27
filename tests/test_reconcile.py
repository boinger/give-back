"""Tests for reconcile.py bias detection and adjustment."""

from give_back.models import SignalResult, SignalWeight, Tier
from give_back.reconcile import should_reconcile


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
