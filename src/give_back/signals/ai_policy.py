"""MEDIUM signal: AI policy detection.

Two-step process:
1. Scan CONTRIBUTING.md text for explicit AI policy keywords
2. Fall back to REST search results for AI discussion volume
"""

from __future__ import annotations

import re

from give_back.models import RepoData, SignalResult, SignalWeight, score_to_tier

NAME = "AI policy"
WEIGHT = SignalWeight.MEDIUM

# Step 1: Explicit policy patterns in contributing text
_BAN_PATTERNS = [
    re.compile(r"\bno\s+ai\b", re.IGNORECASE),
    re.compile(r"\bno\s+llm\b", re.IGNORECASE),
    re.compile(r"\bno\s+copilot\b", re.IGNORECASE),
    re.compile(r"\bno\s+chatgpt\b", re.IGNORECASE),
    re.compile(r"ai-generated\s+code\s+is\s+not\s+accepted", re.IGNORECASE),
    re.compile(r"\bmachine-generated\b", re.IGNORECASE),
]

_WELCOME_PATTERNS = [
    re.compile(r"ai-assisted\s+welcome", re.IGNORECASE),
    re.compile(r"copilot\s+encouraged", re.IGNORECASE),
    re.compile(r"ai\s+contributions\s+accepted", re.IGNORECASE),
]

_DISCLOSURE_PATTERNS = [
    re.compile(r"\bdisclose\b", re.IGNORECASE),
    re.compile(r"label\s+ai\b", re.IGNORECASE),
    re.compile(r"ai-assisted\s+must\s+be\s+noted", re.IGNORECASE),
]


def evaluate_ai_policy(data: RepoData) -> SignalResult:
    """Detect AI contribution policy from contributing text or search results."""
    text = data.contributing_text

    # Step 1: Check contributing text for explicit policy
    if text is not None:
        if any(p.search(text) for p in _BAN_PATTERNS):
            return SignalResult(
                score=0.0,
                tier=score_to_tier(0.0),
                summary="AI contributions explicitly banned",
                details={"source": "contributing_text", "policy": "ban"},
            )
        if any(p.search(text) for p in _WELCOME_PATTERNS):
            return SignalResult(
                score=1.0,
                tier=score_to_tier(1.0),
                summary="AI contributions explicitly welcomed",
                details={"source": "contributing_text", "policy": "welcome"},
            )
        if any(p.search(text) for p in _DISCLOSURE_PATTERNS):
            return SignalResult(
                score=0.5,
                tier=score_to_tier(0.5),
                summary="AI disclosure required",
                details={"source": "contributing_text", "policy": "disclosure"},
            )

    # Step 2: Fall back to search results
    total_count = data.search.get("total_count", 0)

    # Extract issue/PR titles for verbose output
    items = data.search.get("items", [])
    titles = [item.get("title", "") for item in items if item.get("title")]

    if total_count == 0:
        score = 1.0
        summary = "No AI policy discussion found"
    elif total_count <= 3:
        score = 0.7
        summary = f"{total_count} AI-related discussion(s) found"
    else:
        score = 0.4
        summary = f"{total_count} AI-related discussions found — warrants manual review"

    return SignalResult(
        score=score,
        tier=score_to_tier(score),
        summary=summary,
        details={"source": "search", "total_count": total_count, "titles": titles},
    )
