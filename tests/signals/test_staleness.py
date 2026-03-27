"""Tests for staleness signal."""

from datetime import datetime, timedelta, timezone

from give_back.models import RepoData, Tier
from give_back.signals.staleness import evaluate_staleness


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _make_repo_data(
    committed_date: datetime | None = None,
    has_default_branch: bool = True,
    releases: list[datetime] | None = None,
    open_issues: int = 0,
    closed_issues: int = 0,
) -> RepoData:
    repo: dict = {}

    if has_default_branch:
        target = {}
        if committed_date is not None:
            target["committedDate"] = _iso(committed_date)
        repo["defaultBranchRef"] = {"target": target}
    else:
        repo["defaultBranchRef"] = None

    release_nodes = []
    if releases:
        for dt in releases:
            release_nodes.append({"publishedAt": _iso(dt)})
    repo["releases"] = {"nodes": release_nodes}

    repo["openIssues"] = {"totalCount": open_issues}
    repo["closedIssues"] = {"totalCount": closed_issues}

    return RepoData(
        owner="test",
        repo="repo",
        graphql={"repository": repo},
        community={},
        contributing_text=None,
        search={},
    )


class TestStaleness:
    def test_active_repo(self):
        """Recent commit, many releases, high close rate → high score."""
        now = datetime.now(timezone.utc)
        data = _make_repo_data(
            committed_date=now - timedelta(days=2),
            releases=[now - timedelta(days=i * 30) for i in range(5)],
            open_issues=10,
            closed_issues=90,
        )
        result = evaluate_staleness(data)
        # commit=1.0, releases=1.0 (5 in 12mo), issues=1.0 (90%) → avg=1.0
        assert result.score == 1.0
        assert result.tier == Tier.GREEN

    def test_dormant_repo(self):
        """Commit 6 months ago, 1 release, mediocre close rate."""
        now = datetime.now(timezone.utc)
        data = _make_repo_data(
            committed_date=now - timedelta(days=180),
            releases=[now - timedelta(days=200)],
            open_issues=50,
            closed_issues=50,
        )
        result = evaluate_staleness(data)
        # commit=0.3 (within 365d), releases=0.3 (0 in 12mo, 200d ago), issues=0.7 (50%)
        assert 0.3 <= result.score <= 0.5
        assert result.tier == Tier.YELLOW

    def test_dead_repo(self):
        """Commit 2 years ago, no releases, low close rate."""
        now = datetime.now(timezone.utc)
        data = _make_repo_data(
            committed_date=now - timedelta(days=800),
            releases=[],
            open_issues=90,
            closed_issues=10,
        )
        result = evaluate_staleness(data)
        # commit=0.1, releases=0.3, issues=0.3 → avg~0.233
        assert result.score < 0.3
        assert result.tier == Tier.RED

    def test_no_default_branch(self):
        """Empty repo with no default branch."""
        data = _make_repo_data(has_default_branch=False)
        result = evaluate_staleness(data)
        # commit=0.1 (very stale), releases=0.3, issues=0.5 → avg=0.3
        assert result.score <= 0.3

    def test_no_releases(self):
        now = datetime.now(timezone.utc)
        data = _make_repo_data(
            committed_date=now - timedelta(days=5),
            releases=[],
            open_issues=20,
            closed_issues=80,
        )
        result = evaluate_staleness(data)
        # commit=1.0, releases=0.3, issues=1.0 → avg~0.767
        assert 0.7 <= result.score <= 0.8
        assert result.tier == Tier.GREEN

    def test_zero_issues(self):
        now = datetime.now(timezone.utc)
        data = _make_repo_data(
            committed_date=now - timedelta(days=5),
            releases=[now - timedelta(days=10)],
            open_issues=0,
            closed_issues=0,
        )
        result = evaluate_staleness(data)
        # commit=1.0, releases=0.5 (1/yr), issues=0.5 → avg~0.667
        assert 0.6 <= result.score <= 0.7

    def test_details_contain_sub_scores(self):
        now = datetime.now(timezone.utc)
        data = _make_repo_data(committed_date=now - timedelta(days=1))
        result = evaluate_staleness(data)
        assert "commit_score" in result.details
        assert "release_score" in result.details
        assert "issue_score" in result.details

    def test_empty_graphql(self):
        data = RepoData(
            owner="test",
            repo="repo",
            graphql={},
            community={},
            contributing_text=None,
            search={},
        )
        result = evaluate_staleness(data)
        # All sub-scores should handle missing data gracefully
        assert 0.0 <= result.score <= 1.0
