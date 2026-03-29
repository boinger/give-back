"""Tests for discover/search.py repo discovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from give_back.discover.search import (
    DiscoverResult,
    DiscoverSummary,
    _build_query,
    _repo_dict_to_result,
    discover_repos,
)
from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient
from give_back.models import Assessment, SignalResult, Tier


def _make_repo_dict(
    full_name: str = "owner/repo",
    stars: int = 100,
    language: str = "Python",
    description: str = "A test repo",
    open_issues: int = 20,
    topics: list[str] | None = None,
    pushed_at: str | None = None,
) -> dict:
    """Build a minimal GitHub search API repo dict."""
    if pushed_at is None:
        pushed_at = datetime.now(timezone.utc).isoformat()
    return {
        "full_name": full_name,
        "stargazers_count": stars,
        "language": language,
        "description": description,
        "open_issues_count": open_issues,
        "topics": topics or ["cli", "python", "testing"],
        "pushed_at": pushed_at,
    }


def _make_assessment(owner: str = "owner", repo: str = "repo", tier: Tier = Tier.GREEN) -> Assessment:
    return Assessment(
        owner=owner,
        repo=repo,
        overall_tier=tier,
        signals=[SignalResult(score=0.8, tier=Tier.GREEN, summary="OK")],
        gate_passed=True,
        incomplete=False,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


class TestBuildQuery:
    def test_basic_query(self):
        q = _build_query("python", None, 50, "good-first-issues:>0")
        assert "language:python" in q
        assert "stars:>50" in q
        assert "good-first-issues:>0" in q
        assert "archived:false" in q
        assert "sort:stars" in q

    def test_with_topic(self):
        q = _build_query(None, "kubernetes", 100, "help-wanted-issues:>0")
        assert "language:" not in q
        assert "topic:kubernetes" in q
        assert "stars:>100" in q
        assert "help-wanted-issues:>0" in q

    def test_pushed_date_is_90_days_ago(self):
        q = _build_query("rust", None, 50, "good-first-issues:>0")
        expected_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        assert f"pushed:>{expected_date}" in q

    def test_no_language_or_topic(self):
        q = _build_query(None, None, 50, "good-first-issues:>0")
        assert "language:" not in q
        assert "topic:" not in q
        assert "stars:>50" in q


class TestRepoDictToResult:
    def test_basic_conversion(self):
        d = _make_repo_dict("octocat/hello-world", stars=500, language="Go")
        result = _repo_dict_to_result(d)
        assert result.owner == "octocat"
        assert result.repo == "hello-world"
        assert result.stars == 500
        assert result.language == "Go"
        assert result.tier is None
        assert result.from_cache is False
        assert result.skip_reason is None

    def test_missing_fields_use_defaults(self):
        d = {"full_name": "a/b"}
        result = _repo_dict_to_result(d)
        assert result.owner == "a"
        assert result.repo == "b"
        assert result.stars == 0
        assert result.language is None
        assert result.description == ""
        assert result.topics == []


class TestDiscoverRepos:
    """Integration-style tests with mocked API calls and state."""

    def _mock_search_repos(self, repos_q1: list[dict], repos_q2: list[dict] | None = None):
        """Return a side_effect function for client.search_repos."""
        call_count = 0

        def _search(query, per_page=30, sort="stars"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"total_count": len(repos_q1), "items": repos_q1}
            return {"total_count": len(repos_q2 or []), "items": repos_q2 or []}

        return _search

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_basic_flow_no_cache(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """Search, rank, assess, return results."""
        mock_assess.return_value = _make_assessment("owner", "repo")

        repos = [_make_repo_dict("owner/repo")]

        client = _make_mock_client(repos)
        summary = discover_repos(client, language="python", limit=1)

        assert isinstance(summary, DiscoverSummary)
        assert len(summary.results) == 1
        assert summary.results[0].owner == "owner"
        assert summary.results[0].tier == Tier.GREEN
        assert summary.assessed_count == 1
        assert summary.cache_hits == 0
        mock_save_disc.assert_called_once()

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache")
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_discover_cache_hit(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """When discover cache hits, skip the search API entirely."""
        cached_repos = [_make_repo_dict("cached/repo")]
        mock_get_disc.return_value = {"repos": cached_repos}
        mock_assess.return_value = _make_assessment("cached", "repo")

        client = _make_mock_client([])  # Should not be called
        summary = discover_repos(client, language="python", limit=1)

        assert len(summary.results) == 1
        assert summary.results[0].owner == "cached"
        # Discover cache was hit, so save_discover_cache should NOT be called
        mock_save_disc.assert_not_called()

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.save_assessment")
    @patch("give_back.discover.search.get_cached_assessment")
    @patch("give_back.discover.search.reconstruct_assessment")
    def test_assessment_cache_hit(self, mock_recon, mock_get_cached, mock_save, mock_get_disc, mock_save_disc):
        """When an assessment is already cached, use it instead of re-assessing."""
        cached_data = {"overall_tier": "green", "signals": []}
        mock_get_cached.return_value = cached_data
        mock_recon.return_value = (_make_assessment("owner", "repo"), ["License"])

        repos = [_make_repo_dict("owner/repo")]
        client = _make_mock_client(repos)
        summary = discover_repos(client, language="python", limit=1)

        assert summary.cache_hits == 1
        assert summary.assessed_count == 0
        assert summary.results[0].from_cache is True
        assert summary.results[0].tier == Tier.GREEN

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_assessment_failure_sets_skip_reason(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """When run_assessment raises GiveBackError, the result gets a skip_reason."""
        mock_assess.side_effect = GiveBackError("API borked")

        repos = [_make_repo_dict("fail/repo")]
        client = _make_mock_client(repos)
        summary = discover_repos(client, language="python", limit=1)

        assert summary.results[0].skip_reason is not None
        assert "API borked" in summary.results[0].skip_reason
        assert summary.results[0].tier is None
        assert summary.assessed_count == 0

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_rate_limit_stops_assessment(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """When rate budget is insufficient, remaining repos get skip_reason."""
        mock_assess.return_value = _make_assessment()

        repos = [_make_repo_dict(f"org/repo-{i}") for i in range(5)]
        client = _make_mock_client(repos, rate_budget=False)
        summary = discover_repos(client, language="python", limit=5, batch_size=2)

        # All should have skip_reason since budget check fails before the first batch
        skipped = [r for r in summary.results if r.skip_reason]
        assert len(skipped) == 5
        assert summary.assessed_count == 0

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment")
    def test_exclude_assessed_filters(self, mock_get_cached, mock_get_disc, mock_save_disc):
        """exclude_assessed removes repos with existing cached assessments."""

        # First repo has a cached assessment, second doesn't
        def _get_cached(owner, repo, max_age_hours=24):
            if owner == "assessed":
                return {"overall_tier": "green"}
            return None

        mock_get_cached.side_effect = _get_cached

        repos = [
            _make_repo_dict("assessed/repo", stars=200),
            _make_repo_dict("fresh/repo", stars=100),
        ]
        client = _make_mock_client(repos)

        with patch("give_back.discover.search.run_assessment") as mock_assess:
            mock_assess.return_value = _make_assessment("fresh", "repo")
            summary = discover_repos(client, language="python", limit=5, exclude_assessed=True)

        assert summary.filtered_count == 1
        assert len(summary.results) == 1
        assert summary.results[0].owner == "fresh"

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_q2_deduplicates(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """Q2 results that overlap with Q1 are deduplicated."""
        mock_assess.return_value = _make_assessment()

        q1_repos = [_make_repo_dict("shared/repo"), _make_repo_dict("q1only/repo")]
        q2_repos = [_make_repo_dict("shared/repo"), _make_repo_dict("q2only/repo")]

        call_count = 0

        def _search(query, per_page=30, sort="stars"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"total_count": len(q1_repos), "items": q1_repos}
            return {"total_count": len(q2_repos), "items": q2_repos}

        client = _make_mock_client([])
        client.search_repos = _search

        # limit * 3 = 30, and we only have 2 from Q1, so Q2 will run
        summary = discover_repos(client, language="python", limit=10)

        # shared/repo should appear only once, so 3 total
        assert summary.total_searched == 3

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_no_cache_skips_discover_cache(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """no_cache=True skips the discover cache lookup."""
        mock_assess.return_value = _make_assessment()
        repos = [_make_repo_dict("owner/repo")]
        client = _make_mock_client(repos)

        discover_repos(client, language="python", limit=1, no_cache=True)

        mock_get_disc.assert_not_called()
        mock_save_disc.assert_called_once()

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_search_api_failure_returns_empty(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """When the search API fails, return an empty summary without crashing."""
        client = _make_mock_client([], search_error=True)
        summary = discover_repos(client, language="python", limit=5)

        assert summary.total_searched == 0
        assert len(summary.results) == 0

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_limit_caps_results(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """Only top `limit` repos are returned."""
        mock_assess.return_value = _make_assessment()
        repos = [_make_repo_dict(f"org/repo-{i}", stars=100 - i) for i in range(20)]
        client = _make_mock_client(repos)
        summary = discover_repos(client, language="python", limit=3)

        assert len(summary.results) == 3


class TestDiscoverResultDefaults:
    def test_default_fields(self):
        r = DiscoverResult(
            owner="o",
            repo="r",
            description="d",
            stars=1,
            language="Go",
            topics=[],
            open_issue_count=0,
            good_first_issue_count=0,
        )
        assert r.tier is None
        assert r.from_cache is False
        assert r.skip_reason is None


class TestDiscoverSummaryDefaults:
    def test_default_fields(self):
        s = DiscoverSummary(query="q", total_searched=0)
        assert s.results == []
        assert s.filtered_count == 0
        assert s.assessed_count == 0
        assert s.cache_hits == 0


def _make_mock_client(
    repos: list[dict],
    rate_budget: bool = True,
    search_error: bool = False,
) -> GitHubClient:
    """Create a mock GitHubClient with search_repos and has_rate_budget."""

    class MockClient:
        authenticated = True
        _rate_remaining = 5000 if rate_budget else 0

        def search_repos(self, query, per_page=30, sort="stars"):
            if search_error:
                raise GiveBackError("Search API failed")
            return {"total_count": len(repos), "items": repos}

        def has_rate_budget(self, calls):
            return rate_budget

    return MockClient()  # type: ignore[return-value]
