"""MEDIUM signal: Median time to first maintainer response.

Measures how quickly maintainers engage with external PRs by finding the median
time from PR creation to the first comment or review from a MEMBER, OWNER, or
COLLABORATOR.

Score mapping:
- <= 24h  = 1.0
- <= 72h  = 0.7
- <= 168h (1 week) = 0.5
- <= 720h (30 days) = 0.3
- > 30 days = 0.1
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from give_back.models import RepoData, SignalResult, SignalWeight, score_to_tier

NAME = "Time-to-first-response"
WEIGHT = SignalWeight.MEDIUM

INTERNAL_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}
LOW_SAMPLE_THRESHOLD = 10
MONTHS_WINDOW = 12

# Score thresholds (hours)
THRESHOLDS = [
    (24, 1.0),
    (72, 0.7),
    (168, 0.5),
    (720, 0.3),
]
FALLBACK_SCORE = 0.1


def _hours_to_score(hours: float) -> float:
    """Map median response hours to a score."""
    for threshold_hours, score in THRESHOLDS:
        if hours <= threshold_hours:
            return score
    return FALLBACK_SCORE


def _parse_dt(iso_str: str) -> datetime:
    """Parse ISO 8601 datetime string to timezone-aware datetime."""
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def _find_first_maintainer_response(pr: dict) -> datetime | None:
    """Find the earliest maintainer comment or review on a PR.

    Scans comments for the first from MEMBER/OWNER/COLLABORATOR, and checks
    the first review. Returns whichever is earlier.
    """
    earliest: datetime | None = None

    # Check comments for maintainer responses
    comments = (pr.get("comments") or {}).get("nodes") or []
    for comment in comments:
        association = comment.get("authorAssociation", "NONE")
        if association in INTERNAL_ASSOCIATIONS:
            created_at = comment.get("createdAt")
            if created_at:
                dt = _parse_dt(created_at)
                if earliest is None or dt < earliest:
                    earliest = dt

    # Check reviews — a review counts as a response
    reviews = (pr.get("reviews") or {}).get("nodes") or []
    for review in reviews:
        created_at = review.get("createdAt")
        if created_at:
            dt = _parse_dt(created_at)
            if earliest is None or dt < earliest:
                earliest = dt

    return earliest


def evaluate_time_to_response(data: RepoData) -> SignalResult:
    """Evaluate median time to first maintainer response on external PRs."""
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

    response_hours: list[float] = []

    for pr in prs:
        # Apply 12-month window filter
        closed_at = pr.get("mergedAt") or pr.get("closedAt")
        if not closed_at:
            continue
        closed_dt = _parse_dt(closed_at)
        if closed_dt < cutoff:
            continue

        association = pr.get("authorAssociation", "NONE")

        # Only measure external PRs
        if association in INTERNAL_ASSOCIATIONS:
            continue

        created_at = pr.get("createdAt")
        if not created_at:
            continue
        created_dt = _parse_dt(created_at)

        first_response = _find_first_maintainer_response(pr)
        if first_response is not None:
            delta = first_response - created_dt
            hours = delta.total_seconds() / 3600
            response_hours.append(max(hours, 0))

    # No qualifying PRs at all
    if not response_hours:
        # Check if there were external PRs but none had maintainer responses
        external_count = 0
        for pr in prs:
            closed_at = pr.get("mergedAt") or pr.get("closedAt")
            if not closed_at:
                continue
            closed_dt = _parse_dt(closed_at)
            if closed_dt < cutoff:
                continue
            association = pr.get("authorAssociation", "NONE")
            if association not in INTERNAL_ASSOCIATIONS:
                external_count += 1

        if external_count > 0:
            return SignalResult(
                score=0.1,
                tier=score_to_tier(0.1),
                summary=f"No maintainer responses found on {external_count} external PRs",
                details={"external_prs": external_count, "responded_prs": 0, "median_hours": None},
                low_sample=external_count < LOW_SAMPLE_THRESHOLD,
            )

        return SignalResult(
            score=0.5,
            tier=score_to_tier(0.5),
            summary="No external PRs found in the last 12 months",
            details={"external_prs": 0, "responded_prs": 0, "median_hours": None},
        )

    median_hours = statistics.median(response_hours)
    score = _hours_to_score(median_hours)
    low_sample = len(response_hours) < LOW_SAMPLE_THRESHOLD

    # Format median for human readability
    if median_hours < 1:
        time_str = f"{round(median_hours * 60)}m"
    elif median_hours < 48:
        time_str = f"{round(median_hours)}h"
    else:
        time_str = f"{round(median_hours / 24)}d"

    summary = f"Median first response: {time_str} ({len(response_hours)} PRs)"

    return SignalResult(
        score=score,
        tier=score_to_tier(score),
        summary=summary,
        details={
            "median_hours": round(median_hours, 1),
            "responded_prs": len(response_hours),
            "external_prs": len(response_hours),  # only counted those with responses
            "score_mapping": "<=24h:1.0, <=72h:0.7, <=1w:0.5, <=30d:0.3, >30d:0.1",
        },
        low_sample=low_sample,
    )
