"""Contributing signals: existence check (LOW) + content analysis (MEDIUM).

Two signals exported:
- evaluate_contributing_exists: presence check via community profile
- evaluate_contributing_content: friction indicator scan of CONTRIBUTING.md text
"""

from __future__ import annotations

import re

from give_back.models import RepoData, SignalResult, SignalWeight, score_to_tier

# --- Existence signal (LOW) ---

EXISTS_NAME = "CONTRIBUTING.md"
EXISTS_WEIGHT = SignalWeight.LOW

# --- Content signal (MEDIUM) ---

CONTENT_NAME = "Contribution process"
CONTENT_WEIGHT = SignalWeight.MEDIUM

# Friction indicator patterns → score if matched (lower = more friction)
_CLA_PATTERNS = [
    re.compile(r"\bcla\b", re.IGNORECASE),
    re.compile(r"contributor\s+license\s+agreement", re.IGNORECASE),
    re.compile(r"sign\s+the\s+cla", re.IGNORECASE),
]

_CLA_NEGATIONS = [
    re.compile(r"no\s+cla\b", re.IGNORECASE),
    re.compile(r"no\s+contributor\s+license", re.IGNORECASE),
    re.compile(r"cla.{0,20}not\s+required", re.IGNORECASE),
    re.compile(r"don.t.{0,20}require.{0,20}cla", re.IGNORECASE),
]

_DCO_PATTERNS = [
    re.compile(r"\bdco\b", re.IGNORECASE),
    re.compile(r"signed-off-by", re.IGNORECASE),
    re.compile(r"developer\s+certificate", re.IGNORECASE),
]

_DCO_NEGATIONS = [
    re.compile(r"no\s+dco\b", re.IGNORECASE),
    re.compile(r"no\s+sign-off", re.IGNORECASE),
    re.compile(r"dco.{0,20}not\s+required", re.IGNORECASE),
    re.compile(r"don.t.{0,20}require.{0,20}dco", re.IGNORECASE),
    re.compile(r"sign-off.{0,20}not\s+required", re.IGNORECASE),
]

_ONEROUS_PATTERNS = [
    re.compile(r"\bcommittee\b", re.IGNORECASE),
    re.compile(r"approval\s+board", re.IGNORECASE),
    re.compile(r"review\s+period\s+of", re.IGNORECASE),
    re.compile(r"waiting\s+period", re.IGNORECASE),
]

# Each category: (patterns, negations, score, label)
_FRICTION_CATEGORIES: list[tuple[list[re.Pattern[str]], list[re.Pattern[str]], float, str]] = [
    (_CLA_PATTERNS, _CLA_NEGATIONS, 0.3, "CLA required"),
    (_DCO_PATTERNS, _DCO_NEGATIONS, 0.6, "DCO sign-off"),
    (_ONEROUS_PATTERNS, [], 0.3, "onerous process"),
]


def evaluate_contributing_exists(data: RepoData) -> SignalResult:
    """Check whether a CONTRIBUTING file exists via the community profile."""
    contributing = data.community.get("files", {}).get("contributing")
    if contributing is not None:
        return SignalResult(
            score=1.0,
            tier=score_to_tier(1.0),
            summary="CONTRIBUTING file present",
            details={"contributing": True},
        )
    return SignalResult(
        score=0.0,
        tier=score_to_tier(0.0),
        summary="No CONTRIBUTING file found",
        details={"contributing": False},
        skip=True,  # Absence is a non-signal, not a negative signal
    )


def evaluate_contributing_content(data: RepoData) -> SignalResult:
    """Scan CONTRIBUTING.md text for friction indicators."""
    text = data.contributing_text
    if text is None:
        return SignalResult(
            score=0.0,
            tier=score_to_tier(0.0),
            summary="No content to analyze",
            details={"reason": "no_contributing_text"},
            skip=True,  # No file = nothing to score, not a negative
        )

    found: list[str] = []
    lowest_score = 1.0

    for patterns, negations, score, label in _FRICTION_CATEGORIES:
        if any(p.search(text) for p in patterns):
            # Check if the text explicitly negates this requirement
            if negations and any(n.search(text) for n in negations):
                continue
            found.append(label)
            lowest_score = min(lowest_score, score)

    if found:
        summary = f"Friction: {', '.join(found)}"
    else:
        summary = "No friction indicators found"

    return SignalResult(
        score=lowest_score,
        tier=score_to_tier(lowest_score),
        summary=summary,
        details={"friction_indicators": found, "score": lowest_score},
    )
