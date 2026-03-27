"""Rank and sort triage candidates.

Sorting priority (best candidates first):
1. Has priority labels (good-first-issue, help-wanted, etc.) first
2. Competition: None > Low > High
3. Scope: S > M > L (smaller is easier to start with)
4. Clarity: HIGH > MED > LOW
5. Staleness risk: non-stale first
"""

from __future__ import annotations

from give_back.triage.models import Clarity, Competition, IssueCandidate, Scope

# Lower number = better rank
_COMPETITION_ORDER = {Competition.NONE: 0, Competition.LOW: 1, Competition.HIGH: 2}
_SCOPE_ORDER = {Scope.SMALL: 0, Scope.MEDIUM: 1, Scope.LARGE: 2}
_CLARITY_ORDER = {Clarity.HIGH: 0, Clarity.MEDIUM: 1, Clarity.LOW: 2}


def rank_candidates(candidates: list[IssueCandidate], limit: int = 20) -> list[IssueCandidate]:
    """Sort candidates by contribution-friendliness and return top N.

    Candidates with HIGH competition are kept in the list (user may still
    want to see them) but sorted to the bottom.
    """
    sorted_candidates = sorted(candidates, key=_sort_key)
    return sorted_candidates[:limit]


def _sort_key(c: IssueCandidate) -> tuple[int, int, int, int, int]:
    """Multi-level sort key. Lower values sort first (= better candidate)."""
    return (
        0 if c.priority_labels else 1,  # Priority-labeled first
        _COMPETITION_ORDER.get(c.competition, 2),
        _SCOPE_ORDER.get(c.scope, 1),
        _CLARITY_ORDER.get(c.clarity, 1),
        1 if c.staleness_risk else 0,
    )
