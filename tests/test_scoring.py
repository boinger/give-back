"""Tests for scoring.py tier computation."""

from give_back.models import SignalResult, SignalWeight, Tier
from give_back.scoring import compute_tier


def _result(score: float, tier: Tier | None = None) -> SignalResult:
    """Helper to create a SignalResult with just a score."""
    if tier is None:
        if score >= 0.7:
            tier = Tier.GREEN
        elif score >= 0.4:
            tier = Tier.YELLOW
        else:
            tier = Tier.RED
    return SignalResult(score=score, tier=tier, summary="test")


class TestGateCheck:
    def test_gate_pass(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, _result(0.8)),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert gate_passed is True
        assert tier == Tier.GREEN

    def test_gate_fail_forces_red(self):
        results = [
            (SignalWeight.GATE, _result(-1.0, Tier.RED)),
            (SignalWeight.HIGH, _result(1.0)),
            (SignalWeight.MEDIUM, _result(1.0)),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert gate_passed is False
        assert tier == Tier.RED

    def test_gate_error_marks_incomplete(self):
        results = [
            (SignalWeight.GATE, None),  # Signal failed to evaluate
            (SignalWeight.HIGH, _result(0.8)),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert incomplete is True
        # Gate error means gate didn't pass
        assert gate_passed is True  # None != failure, just unknown
        assert tier == Tier.YELLOW  # Capped due to incomplete


class TestWeightedAverage:
    def test_all_green(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, _result(0.9)),
            (SignalWeight.MEDIUM, _result(0.8)),
            (SignalWeight.LOW, _result(0.7)),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert tier == Tier.GREEN

    def test_mixed_signals(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, _result(0.3)),  # RED, weighted 3x
            (SignalWeight.MEDIUM, _result(0.8)),  # GREEN, weighted 2x
            (SignalWeight.LOW, _result(0.9)),  # GREEN, weighted 1x
        ]
        # Weighted avg: (0.3*3 + 0.8*2 + 0.9*1) / (3+2+1) = (0.9+1.6+0.9)/6 = 3.4/6 = 0.567
        tier, gate_passed, incomplete = compute_tier(results)
        assert tier == Tier.YELLOW

    def test_all_red(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, _result(0.1)),
            (SignalWeight.MEDIUM, _result(0.2)),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert tier == Tier.RED


class TestIncompleteAssessment:
    def test_high_signal_failure_caps_at_yellow(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, None),  # Failed to evaluate
            (SignalWeight.MEDIUM, _result(0.9)),
            (SignalWeight.LOW, _result(0.9)),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert incomplete is True
        assert tier == Tier.YELLOW  # Would be GREEN without the cap

    def test_medium_failure_drops_from_average(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, _result(0.9)),
            (SignalWeight.MEDIUM, None),  # Dropped from average
            (SignalWeight.LOW, _result(0.8)),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert incomplete is False  # MEDIUM failure doesn't trigger incomplete
        assert tier == Tier.GREEN  # (0.9*3 + 0.8*1) / (3+1) = 3.5/4 = 0.875

    def test_low_failure_drops_from_average(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, _result(0.5)),
            (SignalWeight.LOW, None),  # Dropped
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert incomplete is False
        assert tier == Tier.YELLOW  # 0.5 alone

    def test_all_non_gate_failed(self):
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, None),
            (SignalWeight.MEDIUM, None),
        ]
        tier, gate_passed, incomplete = compute_tier(results)
        assert incomplete is True
        assert tier == Tier.YELLOW  # No data, but incomplete caps at YELLOW

    def test_skipped_signal_dropped_from_average(self):
        """A signal with skip=True should not affect the weighted average."""
        skipped = SignalResult(score=0.0, tier=Tier.RED, summary="skipped", skip=True)
        results = [
            (SignalWeight.GATE, _result(1.0, Tier.GREEN)),
            (SignalWeight.HIGH, _result(0.9)),
            (SignalWeight.LOW, (SignalWeight.LOW, skipped)[1]),  # skip=True, score=0.0
        ]
        # Without skip: (0.9*3 + 0.0*1) / (3+1) = 2.7/4 = 0.675 → YELLOW
        # With skip: (0.9*3) / 3 = 0.9 → GREEN
        tier, gate_passed, incomplete = compute_tier(results)
        assert tier == Tier.GREEN
        assert incomplete is False
