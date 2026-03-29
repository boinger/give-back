"""authorAssociation bias reconciliation.

When PR merge rate scores LOW/RED but other signals suggest a healthy project,
investigate collaborator role transitions via additional API calls.

The GitHub API's authorAssociation field reflects a contributor's CURRENT role,
not their role at PR time. If a prolific external contributor was later added as
a COLLABORATOR, all their historical PRs retroactively appear "internal." This
systematically penalizes the healthiest repos.

Reconciliation flow (runs in assess.py after initial scoring):
1. Check if PR merge rate is suspiciously low (score < 0.4)
2. Check if other signals suggest a healthy project (majority GREEN/YELLOW)
3. For collaborator-authored PRs, check if those authors have older PRs
   with CONTRIBUTOR or FIRST_TIME_CONTRIBUTOR association
4. If role transitions detected, re-count external PRs and re-score

This only triggers when the data looks suspicious, minimizing extra API calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient
from give_back.models import SignalResult, SignalWeight, Tier, score_to_tier

# Only investigate if merge rate is below this threshold
_SUSPICION_THRESHOLD = 0.4

# Max collaborator authors to investigate (each costs 1 API call)
_MAX_AUTHORS_TO_INVESTIGATE = 5

# PRs created more recently than this are assumed post-promotion
_TRANSITION_RECENCY_CUTOFF = timedelta(days=180)

# Internal association values (from GitHub API)
_INTERNAL_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}
_EXTERNAL_ASSOCIATIONS = {"CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE"}


def should_reconcile(
    signal_results: list[tuple[SignalWeight, SignalResult | None]],
    signal_names: list[str],
) -> bool:
    """Check if the assessment shows a suspicious pattern worth investigating.

    Returns True if:
    - PR merge rate signal exists and scored < 0.4 (RED)
    - Majority of other non-gate, non-skip signals are GREEN or YELLOW
    """
    merge_rate_score = None
    other_healthy = 0
    other_total = 0

    for (weight, result), name in zip(signal_results, signal_names):
        if result is None or result.skip:
            continue
        if weight == SignalWeight.GATE:
            continue

        if "merge" in name.lower():
            merge_rate_score = result.score
        else:
            other_total += 1
            if result.tier in (Tier.GREEN, Tier.YELLOW):
                other_healthy += 1

    if merge_rate_score is None or merge_rate_score >= _SUSPICION_THRESHOLD:
        return False

    if other_total == 0:
        return False

    # Majority of other signals are healthy
    return other_healthy / other_total >= 0.5


def reconcile_merge_rate(
    client: GitHubClient,
    owner: str,
    repo: str,
    original_result: SignalResult,
    verbose: bool = False,
) -> SignalResult | None:
    """Investigate collaborator role transitions and re-score if warranted.

    Returns a new SignalResult if the score changed, or None if no adjustment needed.
    """
    from give_back.console import stderr_console as _console

    # Extract collaborator authors from the original signal's details
    # The PR merge rate signal stores PR data we need
    collaborator_authors = _get_collaborator_authors(original_result)
    if not collaborator_authors:
        return None

    # Limit investigation scope
    authors_to_check = list(collaborator_authors)[:_MAX_AUTHORS_TO_INVESTIGATE]

    if verbose:
        _console.print(
            f"  [dim]Investigating {len(authors_to_check)} collaborator author(s) for role transitions...[/dim]"
        )

    # For each collaborator, check if they have older PRs with external association
    transitioned_authors: list[str] = []
    transitioned_pr_count = 0

    for author in authors_to_check:
        transition_count = _check_author_transition(client, owner, repo, author)
        if transition_count > 0:
            transitioned_authors.append(author)
            transitioned_pr_count += transition_count

    if not transitioned_authors:
        if verbose:
            _console.print("  [dim]No role transitions detected.[/dim]")
        return None

    if verbose:
        _console.print(
            f"  [yellow]Found {len(transitioned_authors)} author(s) with role transitions "
            f"({transitioned_pr_count} PRs reclassified as external).[/yellow]"
        )

    # Re-calculate merge rate with adjusted counts
    original_external_merged = original_result.details.get("external_merged", 0)
    original_external_closed = original_result.details.get("external_closed", 0)

    # Add reclassified PRs to external counts. Only PRs older than the
    # recency cutoff are counted (see _check_author_transition).
    adjusted_merged = original_external_merged + transitioned_pr_count
    adjusted_closed = original_external_closed + transitioned_pr_count

    if adjusted_closed == 0:
        return None

    adjusted_rate = adjusted_merged / adjusted_closed
    adjusted_score = min(adjusted_rate, 1.0)

    pct = round(adjusted_rate * 100)
    summary = (
        f"{pct}% of external PRs merged ({adjusted_merged}/{adjusted_closed}) "
        f"(adjusted: {len(transitioned_authors)} collaborator(s) reclassified)"
    )

    return SignalResult(
        score=adjusted_score,
        tier=score_to_tier(adjusted_score),
        summary=summary,
        details={
            **original_result.details,
            "adjusted": True,
            "transitioned_authors": transitioned_authors,
            "transitioned_pr_count": transitioned_pr_count,
            "original_score": original_result.score,
            "adjusted_merged": adjusted_merged,
            "adjusted_closed": adjusted_closed,
        },
        low_sample=original_result.low_sample,
    )


def _get_collaborator_authors(result: SignalResult) -> list[str]:
    """Extract unique collaborator author logins from PR merge rate signal details."""
    collaborator_prs = result.details.get("collaborator_prs", [])
    if isinstance(collaborator_prs, list):
        return list(dict.fromkeys(collaborator_prs))  # dedupe preserving order

    # Fallback: check if there's a count but no list
    count = result.details.get("collaborator_pr_count", 0)
    if count > 0:
        # Can't investigate without author names
        return []

    return []


def _check_author_transition(
    client: GitHubClient,
    owner: str,
    repo: str,
    author: str,
) -> int:
    """Check if an author has older PRs suggesting they were once external.

    Uses a date-based heuristic: finds the author's earliest merged PR, then
    only counts merged PRs from the "early period" (older than 6 months ago).
    PRs created recently are likely post-promotion and excluded.

    GitHub's authorAssociation reflects the current role, not the role at PR
    time, so there is no API way to know exactly when someone was promoted.
    This heuristic reduces overcounting compared to counting all merged PRs.
    """
    try:
        results = client.search(f"repo:{owner}/{repo} is:pr is:closed author:{author}")
        items = results.get("items", [])

        # Collect merged PRs with their creation dates
        merged_prs: list[datetime] = []
        for item in items[:10]:
            if not item.get("pull_request", {}).get("merged_at"):
                continue
            created_at = item.get("created_at")
            if not created_at or not isinstance(created_at, str):
                continue
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                merged_prs.append(created)
            except (ValueError, TypeError):
                continue

        if not merged_prs:
            return 0

        # Only count PRs older than the recency cutoff. Recent PRs are likely
        # post-promotion and should not be reclassified as external.
        cutoff = datetime.now(timezone.utc) - _TRANSITION_RECENCY_CUTOFF
        early_count = sum(1 for d in merged_prs if d < cutoff)

        # If all their PRs are recent, no evidence of a transition
        return early_count

    except GiveBackError:
        return 0
