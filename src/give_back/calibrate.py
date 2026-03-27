"""Scoring threshold auto-calibration.

Runs assessments against a set of repos with known expected tiers,
compares actual vs expected, and suggests threshold adjustments.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from give_back.assess import run_assessment as _run_assessment
from give_back.models import (
    TIER_GREEN_THRESHOLD,
    TIER_YELLOW_THRESHOLD,
    WEIGHT_MULTIPLIERS,
    SignalWeight,
    Tier,
)
from give_back.signals import ALL_SIGNALS as _ALL_SIGNALS


@dataclass
class Mismatch:
    """A single repo where actual tier != expected tier."""

    repo: str
    expected: Tier
    actual: Tier
    weighted_avg: float
    signal_summaries: dict[str, str] = field(default_factory=dict)
    """Signal name → summary for verbose mismatch output."""


@dataclass
class CalibrationResult:
    """Output of a calibration run."""

    total: int
    correct: int
    matrix: dict[Tier, dict[Tier, int]]
    """matrix[expected][actual] = count"""

    mismatches: list[Mismatch]
    current_thresholds: tuple[float, float]
    """(green_threshold, yellow_threshold)"""

    suggested_thresholds: tuple[float, float] | None
    """Suggested (green, yellow) thresholds, or None if 100% accuracy."""


@dataclass
class CalibrationEntry:
    """A single entry from the calibration file."""

    repo: str
    expected: Tier


def load_calibration_file(path: str) -> list[CalibrationEntry]:
    """Parse a calibration file (YAML-like or JSON) into entries.

    YAML-like format (detected by .yaml/.yml extension):
        - repo: owner/repo
          expected: green

    JSON format (detected by .json extension):
        [{"repo": "owner/repo", "expected": "green"}]
    """
    p = Path(path)
    text = p.read_text()

    if p.suffix == ".json":
        return _parse_json(text)
    return _parse_yaml(text)


def _parse_json(text: str) -> list[CalibrationEntry]:
    """Parse JSON calibration file."""
    data = json.loads(text)
    entries = []
    for item in data:
        repo = item["repo"]
        expected = Tier(item["expected"].lower())
        entries.append(CalibrationEntry(repo=repo, expected=expected))
    return entries


def _parse_yaml(text: str) -> list[CalibrationEntry]:
    """Parse simple YAML-like calibration file.

    Handles the format:
        - repo: owner/repo
          expected: green
    """
    entries = []
    current_repo: str | None = None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Match "- repo: owner/repo"
        repo_match = re.match(r"^-\s+repo:\s*(.+)$", line)
        if repo_match:
            current_repo = repo_match.group(1).strip()
            continue

        # Match "expected: green"
        expected_match = re.match(r"^expected:\s*(.+)$", line)
        if expected_match and current_repo is not None:
            tier_str = expected_match.group(1).strip().lower()
            entries.append(CalibrationEntry(repo=current_repo, expected=Tier(tier_str)))
            current_repo = None

    return entries


def compute_weighted_average(assessment) -> float:
    """Compute the weighted average score from an Assessment's signals.

    Mirrors the logic in scoring.py but returns the raw average value.
    """
    weighted_sum = 0.0
    weight_total = 0

    for signal_def, result in zip(_ALL_SIGNALS, assessment.signals):
        if signal_def.weight == SignalWeight.GATE:
            continue
        if result.skip:
            continue

        multiplier = WEIGHT_MULTIPLIERS.get(signal_def.weight, 1)
        weighted_sum += result.score * multiplier
        weight_total += multiplier

    if weight_total == 0:
        return 0.0

    return weighted_sum / weight_total


def run_calibration(
    client,
    entries: list[CalibrationEntry],
    verbose: bool = False,
) -> CalibrationResult:
    """Run assessments on all entries and compare to expected tiers.

    Args:
        client: Authenticated GitHubClient.
        entries: Parsed calibration entries with repo and expected tier.
        verbose: Whether to pass verbose to run_assessment.

    Returns:
        CalibrationResult with confusion matrix, accuracy, and suggestions.
    """

    # Initialize confusion matrix
    tiers = [Tier.GREEN, Tier.YELLOW, Tier.RED]
    matrix: dict[Tier, dict[Tier, int]] = {e: {a: 0 for a in tiers} for e in tiers}

    mismatches: list[Mismatch] = []
    correct = 0
    scored_repos: list[tuple[Tier, float]] = []
    """(expected_tier, weighted_avg) for threshold suggestion."""

    for entry in entries:
        owner, repo = entry.repo.split("/", 1)
        assessment = _run_assessment(client, owner, repo, verbose=verbose)
        actual_tier = assessment.overall_tier
        avg = compute_weighted_average(assessment)

        matrix[entry.expected][actual_tier] += 1
        scored_repos.append((entry.expected, avg))

        if actual_tier == entry.expected:
            correct += 1
        else:
            signal_summaries = {}
            for signal_def, result in zip(_ALL_SIGNALS, assessment.signals):
                signal_summaries[signal_def.name] = result.summary

            mismatches.append(
                Mismatch(
                    repo=entry.repo,
                    expected=entry.expected,
                    actual=actual_tier,
                    weighted_avg=avg,
                    signal_summaries=signal_summaries,
                )
            )

    current = (TIER_GREEN_THRESHOLD, TIER_YELLOW_THRESHOLD)
    suggested = _suggest_thresholds(scored_repos, mismatches) if mismatches else None

    return CalibrationResult(
        total=len(entries),
        correct=correct,
        matrix=matrix,
        mismatches=mismatches,
        current_thresholds=current,
        suggested_thresholds=suggested,
    )


def _suggest_thresholds(
    scored_repos: list[tuple[Tier, float]],
    mismatches: list[Mismatch],
) -> tuple[float, float] | None:
    """Suggest adjusted thresholds based on mismatches.

    Strategy: collect all scores grouped by expected tier, then find midpoints
    between the lowest correct-tier score and the highest wrong-tier score
    at each boundary.
    """
    green_scores = [avg for tier, avg in scored_repos if tier == Tier.GREEN]
    yellow_scores = [avg for tier, avg in scored_repos if tier == Tier.YELLOW]
    red_scores = [avg for tier, avg in scored_repos if tier == Tier.RED]

    # Green/Yellow boundary: midpoint between min(green) and max(yellow)
    new_green = TIER_GREEN_THRESHOLD
    if green_scores and yellow_scores:
        new_green = (min(green_scores) + max(yellow_scores)) / 2
    elif green_scores:
        # No yellow repos — threshold should be below the lowest green
        new_green = min(green_scores) - 0.01
    # Clamp to valid range
    new_green = max(0.01, min(0.99, new_green))

    # Yellow/Red boundary: midpoint between min(yellow) and max(red)
    new_yellow = TIER_YELLOW_THRESHOLD
    if yellow_scores and red_scores:
        new_yellow = (min(yellow_scores) + max(red_scores)) / 2
    elif yellow_scores:
        new_yellow = min(yellow_scores) - 0.01
    elif red_scores:
        new_yellow = max(red_scores) + 0.01
    # Clamp and ensure yellow < green
    new_yellow = max(0.01, min(new_yellow, new_green - 0.01))

    # Round to 2 decimal places
    new_green = round(new_green, 2)
    new_yellow = round(new_yellow, 2)

    # Only suggest if different from current
    if new_green == TIER_GREEN_THRESHOLD and new_yellow == TIER_YELLOW_THRESHOLD:
        return None

    return (new_green, new_yellow)
