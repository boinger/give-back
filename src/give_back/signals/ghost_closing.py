"""HIGH signal (negative): Ghost-closing rate.

Measures the proportion of external PRs that were closed without any comment or review.
Ghost-closing — silently closing PRs without feedback — is a strong negative signal that
discourages future contributions.

Score = 1.0 - (ghost_closed / total_external_closed), so:
- 0% ghost-closed = 1.0 (best)
- 100% ghost-closed = 0.0 (worst)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from give_back.models import RepoData, SignalResult, SignalWeight, score_to_tier

NAME = "Ghost-closing rate"
WEIGHT = SignalWeight.HIGH

INTERNAL_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}
LOW_SAMPLE_THRESHOLD = 10
MONTHS_WINDOW = 12


def evaluate_ghost_closing(data: RepoData) -> SignalResult:
    """Evaluate how often external PRs are closed without any comment or review."""
    repo = data.graphql.get("repository") or {}

    # Empty repo — no default branch
    if repo.get("defaultBranchRef") is None:
        return SignalResult(
            score=0.5,
            tier=score_to_tier(0.5),
            summary="Empty repository",
            details={"reason": "no default branch"},
        )

    prs = (repo.get("pullRequests") or {}).get("nodes") or []
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=MONTHS_WINDOW * 30)

    ghost_closed = 0
    external_closed = 0

    for pr in prs:
        # Apply 12-month window filter
        closed_at = pr.get("mergedAt") or pr.get("closedAt")
        if not closed_at:
            continue
        closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        if closed_dt < cutoff:
            continue

        association = pr.get("authorAssociation", "NONE")

        # Only count external PRs — internal ghost-closes are normal workflow
        if association in INTERNAL_ASSOCIATIONS:
            continue

        external_closed += 1

        # Check if PR has any comments or reviews
        comments = (pr.get("comments") or {}).get("nodes") or []
        reviews = (pr.get("reviews") or {}).get("nodes") or []

        if len(comments) == 0 and len(reviews) == 0:
            ghost_closed += 1

    # No external PRs found
    if external_closed == 0:
        return SignalResult(
            score=0.5,
            tier=score_to_tier(0.5),
            summary="No external PRs found in the last 12 months",
            details={"ghost_closed": 0, "external_closed": 0},
        )

    ghost_rate = ghost_closed / external_closed
    score = 1.0 - ghost_rate
    low_sample = external_closed < LOW_SAMPLE_THRESHOLD

    ghost_pct = round(ghost_rate * 100)
    summary = f"{ghost_pct}% of external PRs closed without feedback ({ghost_closed}/{external_closed})"
    if low_sample:
        summary += " (low sample)"

    return SignalResult(
        score=score,
        tier=score_to_tier(score),
        summary=summary,
        details={
            "ghost_closed": ghost_closed,
            "external_closed": external_closed,
            "ghost_rate": round(ghost_rate, 3),
        },
        low_sample=low_sample,
    )
