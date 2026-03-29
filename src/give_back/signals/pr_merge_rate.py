"""HIGH signal: External PR merge rate.

Measures the percentage of external PRs that were merged (vs. closed without merge)
in the last 12 months. A high merge rate indicates the project actively accepts
outside contributions.

External authors are identified by authorAssociation: CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, NONE.
Internal authors (MEMBER, OWNER, COLLABORATOR) are excluded from the calculation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from give_back.models import RepoData, SignalResult, SignalWeight, score_to_tier
from give_back.signals._bots import is_bot

NAME = "External PR merge rate"
WEIGHT = SignalWeight.HIGH

INTERNAL_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}
LOW_SAMPLE_THRESHOLD = 10
MONTHS_WINDOW = 12


def evaluate_pr_merge_rate(data: RepoData) -> SignalResult:
    """Evaluate external PR merge rate over the last 12 months."""
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

    external_merged = 0
    external_closed = 0
    collaborator_pr_count = 0
    collaborator_authors: list[str] = []

    for pr in prs:
        # Apply 12-month window filter on closedAt/mergedAt
        closed_at = pr.get("mergedAt") or pr.get("closedAt")
        if not closed_at:
            continue
        closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        if closed_dt < cutoff:
            continue

        association = pr.get("authorAssociation", "NONE")

        # Track collaborator PRs and authors for bias reconciliation
        if association == "COLLABORATOR":
            collaborator_pr_count += 1
            author_login = (pr.get("author") or {}).get("login")
            if author_login and author_login not in collaborator_authors:
                collaborator_authors.append(author_login)

        # Skip internal PRs
        if association in INTERNAL_ASSOCIATIONS:
            continue

        # Skip bot-authored PRs (Dependabot, Renovate, etc.)
        author_login = (pr.get("author") or {}).get("login", "")
        if is_bot(author_login):
            continue

        external_closed += 1
        if pr.get("merged", False):
            external_merged += 1

    # No external PRs found
    if external_closed == 0:
        return SignalResult(
            score=0.5,
            tier=score_to_tier(0.5),
            summary="No external PRs found in the last 12 months",
            details={
                "external_merged": 0,
                "external_closed": 0,
                "collaborator_pr_count": collaborator_pr_count,
                "collaborator_prs": collaborator_authors,
            },
        )

    merge_rate = external_merged / external_closed
    low_sample = external_closed < LOW_SAMPLE_THRESHOLD

    pct = round(merge_rate * 100)
    summary = f"{pct}% of external PRs merged ({external_merged}/{external_closed})"

    return SignalResult(
        score=merge_rate,
        tier=score_to_tier(merge_rate),
        summary=summary,
        details={
            "external_merged": external_merged,
            "external_closed": external_closed,
            "merge_rate": round(merge_rate, 3),
            "collaborator_pr_count": collaborator_pr_count,
            "collaborator_prs": collaborator_authors,
        },
        low_sample=low_sample,
    )
