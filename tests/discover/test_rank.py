"""Tests for discover/rank.py — contribution-friendliness ranking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from give_back.discover.rank import rank_repos


def _repo(
    name: str = "org/repo",
    stars: int = 100,
    pushed_days_ago: int | None = 3,
    description: str | None = "A repo",
    open_issues: int = 5,
    topics: list[str] | None = None,
    from_gfi: bool = False,
    from_hw: bool = False,
) -> dict:
    pushed_at = None
    if pushed_days_ago is not None:
        pushed_at = (datetime.now(timezone.utc) - timedelta(days=pushed_days_ago)).isoformat()
    d: dict = {
        "full_name": name,
        "stargazers_count": stars,
        "pushed_at": pushed_at,
        "description": description,
        "open_issues_count": open_issues,
        "topics": topics or [],
    }
    if from_gfi:
        d["_from_gfi_query"] = True
    if from_hw:
        d["_from_hw_query"] = True
    return d


class TestRankRepos:
    def test_gfi_query_ranked_above_hw(self):
        repos = [_repo("hw", from_hw=True), _repo("gfi", from_gfi=True)]
        ranked = rank_repos(repos)
        assert ranked[0]["full_name"] == "gfi"

    def test_recent_push_ranked_higher(self):
        repos = [_repo("old", pushed_days_ago=60), _repo("new", pushed_days_ago=1)]
        ranked = rank_repos(repos)
        assert ranked[0]["full_name"] == "new"

    def test_ties_broken_by_stars(self):
        repos = [_repo("low", stars=50), _repo("high", stars=5000)]
        ranked = rank_repos(repos)
        assert ranked[0]["full_name"] == "high"

    def test_empty_list(self):
        assert rank_repos([]) == []

    def test_single_repo(self):
        repos = [_repo("only")]
        ranked = rank_repos(repos)
        assert len(ranked) == 1
        assert "_rank_score" in ranked[0]

    def test_description_gives_bonus(self):
        with_desc = _repo("with", description="Has one")
        without_desc = _repo("without", description=None)
        ranked = rank_repos([without_desc, with_desc])
        assert ranked[0]["full_name"] == "with"

    def test_active_issues_bonus(self):
        active = _repo("active", open_issues=50)
        quiet = _repo("quiet", open_issues=2)
        ranked = rank_repos([quiet, active])
        assert ranked[0]["full_name"] == "active"

    def test_topics_bonus(self):
        with_topics = _repo("topics", topics=["a", "b", "c"])
        without = _repo("none", topics=[])
        ranked = rank_repos([without, with_topics])
        assert ranked[0]["full_name"] == "topics"

    def test_missing_pushed_at_no_crash(self):
        repo = _repo("missing", pushed_days_ago=None)
        ranked = rank_repos([repo])
        assert ranked[0]["_rank_score"] >= 0

    def test_invalid_pushed_at_no_crash(self):
        repo = _repo("bad")
        repo["pushed_at"] = "not-a-date"
        ranked = rank_repos([repo])
        assert ranked[0]["_rank_score"] >= 0

    def test_negative_open_issues_no_bonus(self):
        repo = _repo("weird", open_issues=-5)
        ranked = rank_repos([repo])
        # Should not get active issues bonus
        no_issues_repo = _repo("zero", open_issues=0)
        ranked2 = rank_repos([no_issues_repo])
        assert ranked[0]["_rank_score"] == ranked2[0]["_rank_score"]

    def test_pushed_30d_gets_medium_bonus(self):
        recent = _repo("week", pushed_days_ago=3)
        month = _repo("month", pushed_days_ago=20)
        old = _repo("old", pushed_days_ago=60)
        ranked = rank_repos([old, month, recent])
        assert ranked[0]["full_name"] == "week"
        assert ranked[1]["full_name"] == "month"
        assert ranked[2]["full_name"] == "old"
