"""Weighted tier computation.

Scoring pipeline:
    signal results ──► gate check ──► weighted average ──► tier mapping
         │                  │               │                  │
         ▼                  ▼               ▼                  ▼
    list[SignalResult]  any gate    sum(score × weight)    GREEN/YELLOW/RED
                        fail? ──►  ───────────────────
                        RED        sum(weights)

Gate check runs first: any GATE signal with score == -1.0 → overall RED.
Then weighted average of non-GATE signals determines the tier.
HIGH/GATE signal exceptions cap the tier at YELLOW (incomplete assessment).
MEDIUM/LOW signal exceptions are dropped from the average (denominator shrinks).
"""

from __future__ import annotations

from give_back.models import (
    TIER_GREEN_THRESHOLD,
    TIER_YELLOW_THRESHOLD,
    WEIGHT_MULTIPLIERS,
    SignalResult,
    SignalWeight,
    Tier,
)


def compute_tier(
    results: list[tuple[SignalWeight, SignalResult | None]],
) -> tuple[Tier, bool, bool]:
    """Compute overall tier from signal results.

    Args:
        results: List of (weight, result) tuples. Result is None if the signal
                 raised an exception during evaluation.

    Returns:
        (tier, gate_passed, incomplete) tuple.
        - gate_passed is False if any GATE signal failed (score == -1.0) or errored.
        - incomplete is True if any HIGH or GATE signal errored (result is None).
    """
    gate_passed = True
    incomplete = False

    # Track failed high-weight signals
    for weight, result in results:
        if result is None:
            # Signal evaluation failed
            if weight in (SignalWeight.GATE, SignalWeight.HIGH):
                incomplete = True
            continue
        if weight == SignalWeight.GATE and result.score < 0:
            gate_passed = False

    # Gate failure → RED immediately
    if not gate_passed:
        return Tier.RED, False, incomplete

    # Compute weighted average of non-GATE signals that succeeded
    weighted_sum = 0.0
    weight_total = 0

    for weight, result in results:
        if result is None:
            continue
        if weight == SignalWeight.GATE:
            continue

        multiplier = WEIGHT_MULTIPLIERS.get(weight, 1)
        weighted_sum += result.score * multiplier
        weight_total += multiplier

    # No non-GATE signals to average (all failed or only gate signals)
    if weight_total == 0:
        tier = Tier.RED if not incomplete else Tier.YELLOW
        return tier, gate_passed, incomplete

    average = weighted_sum / weight_total

    # Map average to tier
    if average >= TIER_GREEN_THRESHOLD:
        tier = Tier.GREEN
    elif average >= TIER_YELLOW_THRESHOLD:
        tier = Tier.YELLOW
    else:
        tier = Tier.RED

    # Incomplete assessment caps at YELLOW
    if incomplete and tier == Tier.GREEN:
        tier = Tier.YELLOW

    return tier, gate_passed, incomplete
