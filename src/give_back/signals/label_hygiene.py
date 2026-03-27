"""LOW signal: Issue label hygiene.

Checks for contribution-friendly labels like "good first issue", "help wanted", etc.
"""

from __future__ import annotations

from give_back.models import RepoData, SignalResult, SignalWeight, score_to_tier

NAME = "Issue label hygiene"
WEIGHT = SignalWeight.LOW

# Contribution-friendly label names (checked case-insensitive)
_FRIENDLY_LABELS = {
    "good first issue",
    "good-first-issue",
    "help wanted",
    "help-wanted",
    "bug",
    "easy",
    "beginner",
    "starter",
}


def evaluate_label_hygiene(data: RepoData) -> SignalResult:
    """Check for contribution-friendly labels in the repository."""
    nodes = data.graphql.get("repository", {}).get("labels", {}).get("nodes", [])

    label_names = [node.get("name", "") for node in nodes]
    matched = [name for name in label_names if name.lower() in _FRIENDLY_LABELS]

    count = len(matched)
    if count >= 3:
        score = 1.0
    elif count == 2:
        score = 0.8
    elif count == 1:
        score = 0.6
    else:
        score = 0.3

    if matched:
        summary = f"{count} contribution-friendly label(s): {', '.join(matched)}"
    else:
        summary = "No contribution-friendly labels found"

    return SignalResult(
        score=score,
        tier=score_to_tier(score),
        summary=summary,
        details={"matched_labels": matched, "total_labels": len(label_names)},
    )
