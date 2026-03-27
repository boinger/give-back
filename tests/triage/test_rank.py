"""Tests for triage/rank.py candidate ranking."""

from give_back.triage.models import Clarity, Competition, IssueCandidate, Scope
from give_back.triage.rank import rank_candidates


def _candidate(
    number: int = 1,
    priority_labels: list[str] | None = None,
    competition: Competition = Competition.NONE,
    scope: Scope = Scope.MEDIUM,
    clarity: Clarity = Clarity.MEDIUM,
    staleness_risk: bool = False,
) -> IssueCandidate:
    return IssueCandidate(
        number=number,
        title=f"Issue #{number}",
        url=f"https://github.com/t/r/issues/{number}",
        labels=[],
        scope=scope,
        clarity=clarity,
        competition=competition,
        staleness_risk=staleness_risk,
        priority_labels=priority_labels or [],
    )


class TestRanking:
    def test_priority_labels_first(self):
        a = _candidate(1, priority_labels=["good first issue"])
        b = _candidate(2)
        result = rank_candidates([b, a])
        assert result[0].number == 1

    def test_no_competition_before_low(self):
        a = _candidate(1, competition=Competition.NONE)
        b = _candidate(2, competition=Competition.LOW)
        result = rank_candidates([b, a])
        assert result[0].number == 1

    def test_low_competition_before_high(self):
        a = _candidate(1, competition=Competition.LOW)
        b = _candidate(2, competition=Competition.HIGH)
        result = rank_candidates([b, a])
        assert result[0].number == 1

    def test_small_scope_before_large(self):
        a = _candidate(1, scope=Scope.SMALL)
        b = _candidate(2, scope=Scope.LARGE)
        result = rank_candidates([b, a])
        assert result[0].number == 1

    def test_high_clarity_before_low(self):
        a = _candidate(1, clarity=Clarity.HIGH)
        b = _candidate(2, clarity=Clarity.LOW)
        result = rank_candidates([b, a])
        assert result[0].number == 1

    def test_non_stale_before_stale(self):
        a = _candidate(1, staleness_risk=False)
        b = _candidate(2, staleness_risk=True)
        result = rank_candidates([b, a])
        assert result[0].number == 1

    def test_limit_applied(self):
        candidates = [_candidate(i) for i in range(10)]
        result = rank_candidates(candidates, limit=3)
        assert len(result) == 3

    def test_multi_level_sort(self):
        # Priority + no competition + small scope should be #1
        best = _candidate(1, priority_labels=["bug"], competition=Competition.NONE, scope=Scope.SMALL)
        # Priority + high competition should be after non-priority + no competition
        bad_priority = _candidate(2, priority_labels=["bug"], competition=Competition.HIGH)
        # No priority + no competition + small scope
        ok = _candidate(3, competition=Competition.NONE, scope=Scope.SMALL)

        result = rank_candidates([bad_priority, ok, best])
        assert result[0].number == 1  # best: priority + none + small
        assert result[1].number == 2  # bad_priority: priority but HIGH competition
        assert result[2].number == 3  # ok: no priority

    def test_empty_list(self):
        assert rank_candidates([]) == []
