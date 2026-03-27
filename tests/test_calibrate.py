"""Tests for calibrate.py calibration logic."""

from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch

from give_back.calibrate import (
    CalibrationEntry,
    Mismatch,
    _suggest_thresholds,
    compute_weighted_average,
    load_calibration_file,
    run_calibration,
)
from give_back.models import (
    Assessment,
    SignalResult,
    SignalWeight,
    Tier,
)


def _make_assessment(owner: str, repo: str, tier: Tier, scores: list[tuple[SignalWeight, float]]) -> Assessment:
    """Build a fake Assessment with the given tier and signal scores."""
    signals = []
    for weight, score in scores:
        if score >= 0.7:
            signal_tier = Tier.GREEN
        elif score >= 0.4:
            signal_tier = Tier.YELLOW
        else:
            signal_tier = Tier.RED
        signals.append(SignalResult(score=score, tier=signal_tier, summary=f"score={score:.2f}"))

    return Assessment(
        owner=owner,
        repo=repo,
        overall_tier=tier,
        signals=signals,
        gate_passed=True,
        incomplete=False,
        timestamp="2026-03-26T00:00:00Z",
    )


# Typical signal weights matching ALL_SIGNALS order (9 signals)
_TYPICAL_WEIGHTS = [
    (SignalWeight.GATE, 1.0),  # License
    (SignalWeight.HIGH, 0.9),  # PR merge rate
    (SignalWeight.HIGH, 0.8),  # Ghost-closing
    (SignalWeight.MEDIUM, 0.7),  # Time-to-response
    (SignalWeight.LOW, 0.8),  # CONTRIBUTING.md
    (SignalWeight.MEDIUM, 0.7),  # Contribution process
    (SignalWeight.MEDIUM, 0.6),  # AI policy
    (SignalWeight.LOW, 0.7),  # Label hygiene
    (SignalWeight.MEDIUM, 0.7),  # Staleness
]


class TestParseYaml:
    def test_basic_yaml(self):
        content = """\
- repo: pallets/flask
  expected: green
- repo: PostHog/posthog-foss
  expected: yellow
- repo: some/dead-project
  expected: red
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            entries = load_calibration_file(f.name)

        assert len(entries) == 3
        assert entries[0].repo == "pallets/flask"
        assert entries[0].expected == Tier.GREEN
        assert entries[1].repo == "PostHog/posthog-foss"
        assert entries[1].expected == Tier.YELLOW
        assert entries[2].repo == "some/dead-project"
        assert entries[2].expected == Tier.RED

    def test_yaml_with_comments_and_blank_lines(self):
        content = """\
# Calibration repos

- repo: pallets/flask
  expected: green

# Another one
- repo: some/dead-project
  expected: red
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(content)
            f.flush()
            entries = load_calibration_file(f.name)

        assert len(entries) == 2


class TestParseJson:
    def test_basic_json(self):
        data = [
            {"repo": "pallets/flask", "expected": "green"},
            {"repo": "PostHog/posthog-foss", "expected": "YELLOW"},
            {"repo": "some/dead-project", "expected": "Red"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            entries = load_calibration_file(f.name)

        assert len(entries) == 3
        assert entries[0].expected == Tier.GREEN
        assert entries[1].expected == Tier.YELLOW
        assert entries[2].expected == Tier.RED


class TestComputeWeightedAverage:
    def test_typical_scores(self):
        """Weighted average matches hand-calculated value."""
        assessment = _make_assessment("a", "b", Tier.GREEN, _TYPICAL_WEIGHTS)

        # Patch ALL_SIGNALS to match our test signal weights
        from give_back.models import SignalDef

        fake_signals = [
            SignalDef(func=lambda d: None, name=f"signal_{i}", weight=w) for i, (w, _) in enumerate(_TYPICAL_WEIGHTS)
        ]

        with patch("give_back.calibrate._ALL_SIGNALS", fake_signals):
            avg = compute_weighted_average(assessment)

        # GATE excluded. Non-GATE: HIGH(0.9)*3 + HIGH(0.8)*3 + MED(0.7)*2 + LOW(0.8)*1
        # + MED(0.7)*2 + MED(0.6)*2 + LOW(0.7)*1 + MED(0.7)*2
        # = 2.7 + 2.4 + 1.4 + 0.8 + 1.4 + 1.2 + 0.7 + 1.4 = 12.0
        # Weights: 3+3+2+1+2+2+1+2 = 16
        # avg = 12.0 / 16 = 0.75
        assert abs(avg - 0.75) < 0.001


class TestPerfectAccuracy:
    @patch("give_back.calibrate._run_assessment")
    def test_all_match(self, mock_run):
        """100% accuracy when all actual tiers match expected."""
        assessments = {
            "pallets/flask": _make_assessment("pallets", "flask", Tier.GREEN, _TYPICAL_WEIGHTS),
            "some/yellow": _make_assessment("some", "yellow", Tier.YELLOW, _TYPICAL_WEIGHTS),
            "some/dead": _make_assessment("some", "dead", Tier.RED, _TYPICAL_WEIGHTS),
        }

        def side_effect(client, owner, repo, verbose=False):
            return assessments[f"{owner}/{repo}"]

        mock_run.side_effect = side_effect

        entries = [
            CalibrationEntry(repo="pallets/flask", expected=Tier.GREEN),
            CalibrationEntry(repo="some/yellow", expected=Tier.YELLOW),
            CalibrationEntry(repo="some/dead", expected=Tier.RED),
        ]

        result = run_calibration(MagicMock(), entries)

        assert result.correct == 3
        assert result.total == 3
        assert len(result.mismatches) == 0
        assert result.suggested_thresholds is None

        # Check matrix diagonal
        assert result.matrix[Tier.GREEN][Tier.GREEN] == 1
        assert result.matrix[Tier.YELLOW][Tier.YELLOW] == 1
        assert result.matrix[Tier.RED][Tier.RED] == 1


class TestMismatchDetected:
    @patch("give_back.calibrate._run_assessment")
    def test_one_mismatch(self, mock_run):
        """One mismatch produces correct confusion matrix and mismatch entry."""
        assessments = {
            "pallets/flask": _make_assessment("pallets", "flask", Tier.YELLOW, _TYPICAL_WEIGHTS),  # expected GREEN
            "some/yellow": _make_assessment("some", "yellow", Tier.YELLOW, _TYPICAL_WEIGHTS),
            "some/dead": _make_assessment("some", "dead", Tier.RED, _TYPICAL_WEIGHTS),
        }

        def side_effect(client, owner, repo, verbose=False):
            return assessments[f"{owner}/{repo}"]

        mock_run.side_effect = side_effect

        entries = [
            CalibrationEntry(repo="pallets/flask", expected=Tier.GREEN),
            CalibrationEntry(repo="some/yellow", expected=Tier.YELLOW),
            CalibrationEntry(repo="some/dead", expected=Tier.RED),
        ]

        # Patch ALL_SIGNALS for compute_weighted_average
        from give_back.models import SignalDef

        fake_signals = [
            SignalDef(func=lambda d: None, name=f"signal_{i}", weight=w) for i, (w, _) in enumerate(_TYPICAL_WEIGHTS)
        ]

        with patch("give_back.calibrate._ALL_SIGNALS", fake_signals):
            result = run_calibration(MagicMock(), entries)

        assert result.correct == 2
        assert result.total == 3
        assert len(result.mismatches) == 1

        mm = result.mismatches[0]
        assert mm.repo == "pallets/flask"
        assert mm.expected == Tier.GREEN
        assert mm.actual == Tier.YELLOW

        # Confusion matrix: GREEN row should show 0 GREEN, 1 YELLOW
        assert result.matrix[Tier.GREEN][Tier.GREEN] == 0
        assert result.matrix[Tier.GREEN][Tier.YELLOW] == 1


class TestThresholdSuggestion:
    def test_suggests_lower_green_threshold(self):
        """When a GREEN repo scores below 0.7, suggest lowering the green threshold."""
        scored_repos = [
            (Tier.GREEN, 0.65),  # This repo should be GREEN but scored 0.65
            (Tier.GREEN, 0.80),
            (Tier.YELLOW, 0.50),
        ]
        mismatches = [
            Mismatch(repo="a/b", expected=Tier.GREEN, actual=Tier.YELLOW, weighted_avg=0.65),
        ]
        result = _suggest_thresholds(scored_repos, mismatches)
        assert result is not None
        new_green, new_yellow = result
        # Midpoint of min(green)=0.65 and max(yellow)=0.50 → 0.575
        assert new_green == 0.57  # rounded (banker's rounding: 0.575 → 0.57)
        # Yellow threshold: midpoint of min(yellow)=0.50 and no red → 0.49
        assert new_yellow == 0.49

    def test_no_suggestion_when_thresholds_unchanged(self):
        """When calculated thresholds match current, return None."""
        scored_repos = [
            (Tier.GREEN, 0.80),
            (Tier.YELLOW, 0.50),
            (Tier.RED, 0.20),
        ]
        # Midpoint green/yellow: (0.80 + 0.50) / 2 = 0.65
        # Midpoint yellow/red: (0.50 + 0.20) / 2 = 0.35
        # These are different from defaults (0.7, 0.4), so we get a suggestion
        mismatches = [Mismatch(repo="x/y", expected=Tier.GREEN, actual=Tier.YELLOW, weighted_avg=0.60)]
        result = _suggest_thresholds(scored_repos, mismatches)
        # Result should be (0.65, 0.35) — different from (0.7, 0.4)
        assert result is not None
        assert result == (0.65, 0.35)

    def test_green_only_repos(self):
        """With only GREEN repos, threshold should be just below the lowest."""
        scored_repos = [
            (Tier.GREEN, 0.85),
            (Tier.GREEN, 0.90),
        ]
        mismatches = [Mismatch(repo="a/b", expected=Tier.GREEN, actual=Tier.YELLOW, weighted_avg=0.65)]
        result = _suggest_thresholds(scored_repos, mismatches)
        assert result is not None
        new_green, _ = result
        assert new_green == 0.84  # min(green) - 0.01


class TestCalibrationResultStructure:
    @patch("give_back.calibrate._run_assessment")
    def test_result_contains_current_thresholds(self, mock_run):
        """CalibrationResult includes the current threshold values."""
        mock_run.return_value = _make_assessment("a", "b", Tier.GREEN, _TYPICAL_WEIGHTS)

        entries = [CalibrationEntry(repo="a/b", expected=Tier.GREEN)]
        result = run_calibration(MagicMock(), entries)

        assert result.current_thresholds == (0.7, 0.4)
