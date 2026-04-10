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


class TestDiscoverReposAnyIssues:
    """T5-T8: --any-issues mode and verbose output."""

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_any_issues_single_query_no_label_gate(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T5: any_issues=True → single query, no Q2 fallback, label_gate_active=False."""
        mock_assess.return_value = _make_assessment("owner", "repo")
        repos = [_make_repo_dict("owner/repo")]

        queries_seen: list[str] = []

        def _tracking_search(query, per_page=30, sort="stars"):
            queries_seen.append(query)
            return {"total_count": len(repos), "items": repos}

        client = _make_mock_client(repos)
        client.search_repos = _tracking_search

        summary = discover_repos(client, language="python", limit=1, any_issues=True)

        assert summary.label_gate_active is False
        assert len(queries_seen) == 1  # Only one query, no Q2
        assert "good-first-issues" not in queries_seen[0]
        assert "help-wanted-issues" not in queries_seen[0]

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_cache_key_differs_gated_vs_ungated(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T6: any_issues and non-any_issues use different cache keys."""
        mock_assess.return_value = _make_assessment()
        repos = [_make_repo_dict("owner/repo")]
        client = _make_mock_client(repos)

        # Run with gate
        discover_repos(client, language="python", limit=1, any_issues=False)
        call1_hash = mock_save_disc.call_args_list[-1][0][0]

        # Run without gate
        discover_repos(client, language="python", limit=1, any_issues=True)
        call2_hash = mock_save_disc.call_args_list[-1][0][0]

        assert call1_hash != call2_hash, "Cache keys must differ between gated and ungated queries"

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_default_has_label_gate_active(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T7: REGRESSION — default discover_repos has label_gate_active=True."""
        mock_assess.return_value = _make_assessment()
        repos = [_make_repo_dict("owner/repo")]
        client = _make_mock_client(repos)

        summary = discover_repos(client, language="python", limit=1)

        assert summary.label_gate_active is True

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_verbose_prints_queries(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc, capsys):
        """T8: verbose=True prints query strings to stderr."""
        mock_assess.return_value = _make_assessment()
        repos = [_make_repo_dict("owner/repo")]
        client = _make_mock_client(repos)

        import io

        from rich.console import Console

        buf = io.StringIO()
        test_console = Console(file=buf, force_terminal=False, width=200)

        import give_back.discover.search as search_mod

        original = search_mod._console
        search_mod._console = test_console
        try:
            discover_repos(client, language="python", limit=1, verbose=True)
        finally:
            search_mod._console = original

        output = buf.getvalue()
        assert "Q1:" in output
        assert "returned" in output


class TestInteractiveLoopFlagPreservation:
    """T15: Interactive loop re-entry preserves --any-issues flag."""

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_slice_results_preserves_label_gate(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T15: When the interactive loop slices results for a second batch,
        the label_gate_active field is preserved from the original summary."""
        mock_assess.return_value = _make_assessment()
        repos = [_make_repo_dict(f"org/repo-{i}", stars=100 - i) for i in range(10)]
        client = _make_mock_client(repos)

        # First call with any_issues=True
        summary = discover_repos(client, language="python", limit=5, any_issues=True)
        assert summary.label_gate_active is False

        # Simulate the interactive loop: get a new summary, then slice
        new_summary = discover_repos(client, language="python", limit=10, any_issues=True)
        sliced = new_summary.slice_results(
            5,
            prior_assessed=summary.assessed_count,
            prior_cache_hits=summary.cache_hits,
        )

        assert sliced.label_gate_active is False, "Interactive loop second batch must preserve label_gate_active=False"


class TestAutoFallback:
    """T1-T8: Auto-fallback pipeline tests."""

    def _make_multi_query_client(
        self,
        gated_repos: list[dict],
        ungated_repos: list[dict],
        rate_budget: bool = True,
    ):
        """Mock client that returns different results based on query content."""

        class MultiQueryClient:
            authenticated = True
            _rate_remaining = 5000 if rate_budget else 0

            def search_repos(self, query, per_page=30, sort="stars"):
                # Ungated queries lack "good-first-issues" and "help-wanted-issues"
                if "good-first-issues" in query or "help-wanted-issues" in query:
                    return {"total_count": len(gated_repos), "items": list(gated_repos)}
                return {"total_count": len(ungated_repos), "items": list(ungated_repos)}

            def has_rate_budget(self, calls):
                return rate_budget

        return MultiQueryClient()

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_fallback_fires_when_sparse(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T1: Sparse gated + auto_fallback=True → fallback fires."""
        mock_assess.return_value = _make_assessment()
        gated = [_make_repo_dict("gated/repo1"), _make_repo_dict("gated/repo2")]
        ungated = [
            _make_repo_dict("gated/repo1"),  # overlap — should be deduped
            _make_repo_dict("ungated/repo3", stars=500),
            _make_repo_dict("ungated/repo4", stars=400),
        ]
        client = self._make_multi_query_client(gated, ungated)

        summary = discover_repos(client, language="python", limit=10, auto_fallback=True)

        assert summary.fallback_triggered is True
        assert len(summary.fallback_results) > 0
        # gated/repo1 should NOT appear in fallback (deduped)
        fb_names = [f"{r.owner}/{r.repo}" for r in summary.fallback_results]
        assert "gated/repo1" not in fb_names

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_no_fallback_when_not_sparse(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T2: Non-sparse gated → fallback does NOT fire."""
        mock_assess.return_value = _make_assessment()
        gated = [_make_repo_dict(f"org/repo-{i}") for i in range(10)]
        client = self._make_multi_query_client(gated, [])

        summary = discover_repos(client, language="python", limit=10, auto_fallback=True)

        assert summary.fallback_triggered is False
        assert summary.fallback_results == []

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_no_fallback_when_disabled(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T3: auto_fallback=False → no fallback regardless of sparsity."""
        mock_assess.return_value = _make_assessment()
        gated = [_make_repo_dict("gated/repo1")]
        client = self._make_multi_query_client(gated, [_make_repo_dict("ungated/repo2")])

        summary = discover_repos(client, language="python", limit=10, auto_fallback=False)

        assert summary.fallback_triggered is False
        assert summary.fallback_results == []

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_no_fallback_with_any_issues(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T4: --any-issues → no fallback (gate already off)."""
        mock_assess.return_value = _make_assessment()
        repos = [_make_repo_dict("org/repo")]
        client = _make_mock_client(repos)

        summary = discover_repos(client, language="python", limit=10, any_issues=True, auto_fallback=True)

        assert summary.fallback_triggered is False
        assert summary.label_gate_active is False

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_dedup_case_insensitive(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T5: Case-insensitive dedup — repo in both pools stays in primary only."""
        mock_assess.return_value = _make_assessment()
        gated = [_make_repo_dict("Owner/Repo")]
        ungated = [_make_repo_dict("owner/repo"), _make_repo_dict("other/new")]
        client = self._make_multi_query_client(gated, ungated)

        summary = discover_repos(client, language="python", limit=10, auto_fallback=True)

        assert summary.fallback_triggered is True
        fb_names = [f"{r.owner}/{r.repo}" for r in summary.fallback_results]
        # "owner/repo" deduped against "Owner/Repo" in primary
        assert "owner/repo" not in fb_names
        assert "other/new" in fb_names

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_fill_to_limit(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T6: Gated=3, limit=10 → up to 7 fallback repos."""
        mock_assess.return_value = _make_assessment()
        gated = [_make_repo_dict(f"gated/r{i}") for i in range(3)]
        ungated = [_make_repo_dict(f"ungated/r{i}", stars=100 - i) for i in range(20)]
        client = self._make_multi_query_client(gated, ungated)

        summary = discover_repos(client, language="python", limit=10, auto_fallback=True)

        assert len(summary.results) == 3
        assert len(summary.fallback_results) <= 7
        assert len(summary.results) + len(summary.fallback_results) <= 10

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_rate_budget_exhausted(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T7: Rate budget exhausted → fallback repos get skip_reason."""
        mock_assess.return_value = _make_assessment()
        gated = [_make_repo_dict("gated/r0")]
        ungated = [_make_repo_dict(f"ungated/r{i}") for i in range(5)]
        client = self._make_multi_query_client(gated, ungated, rate_budget=False)

        summary = discover_repos(client, language="python", limit=10, auto_fallback=True)

        assert summary.fallback_triggered is True
        for r in summary.fallback_results:
            assert r.skip_reason is not None

    @patch("give_back.discover.search.save_discover_cache")
    @patch("give_back.discover.search.get_discover_cache", return_value=None)
    @patch("give_back.discover.search.get_cached_assessment", return_value=None)
    @patch("give_back.discover.search.run_assessment")
    def test_fallback_triggered_with_zero_results(self, mock_assess, mock_get_cached, mock_get_disc, mock_save_disc):
        """T8: fallback_triggered=True even when fallback returns 0 repos."""
        mock_assess.return_value = _make_assessment()
        gated = [_make_repo_dict("gated/r0")]
        # Ungated returns only the same repo as gated — all deduped
        ungated = [_make_repo_dict("gated/r0")]
        client = self._make_multi_query_client(gated, ungated)

        summary = discover_repos(client, language="python", limit=10, auto_fallback=True)

        assert summary.fallback_triggered is True
        assert summary.fallback_results == []


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
        assert s.label_gate_active is True
        assert s.fallback_results == []
        assert s.fallback_triggered is False


class TestBuildQueryNoLabelGate:
    """T4: _build_query with label_filter=None omits the label qualifier."""

    def test_no_label_filter(self):
        q = _build_query("python", "cli", 50, None)
        assert "language:python" in q
        assert "topic:cli" in q
        assert "stars:>50" in q
        assert "archived:false" in q
        assert "good-first-issues" not in q
        assert "help-wanted-issues" not in q


class TestSliceResults:
    """T9: DiscoverSummary.slice_results carries all fields."""

    def _make_result(self, owner: str) -> DiscoverResult:
        return DiscoverResult(
            owner=owner,
            repo="r",
            description="d",
            stars=100,
            language="Go",
            topics=[],
            open_issue_count=10,
            good_first_issue_count=0,
        )

    def test_slice_basic(self):
        results = [self._make_result(f"o{i}") for i in range(5)]
        summary = DiscoverSummary(
            query="q",
            total_searched=100,
            results=results,
            filtered_count=2,
            assessed_count=5,
            cache_hits=3,
            label_gate_active=False,
        )
        sliced = summary.slice_results(3, prior_assessed=2, prior_cache_hits=1)

        assert len(sliced.results) == 2
        assert sliced.results[0].owner == "o3"
        assert sliced.total_searched == 100
        assert sliced.filtered_count == 2
        assert sliced.assessed_count == 3  # 5 - 2
        assert sliced.cache_hits == 2  # 3 - 1
        assert sliced.label_gate_active is False
        assert sliced.query == "q"

    def test_slice_with_fallback(self):
        """slice_results carries fallback_results with correct two-pool offset."""
        primary = [self._make_result(f"p{i}") for i in range(3)]
        fallback = [self._make_result(f"f{i}") for i in range(7)]
        summary = DiscoverSummary(
            query="q",
            total_searched=100,
            results=primary,
            fallback_results=fallback,
            fallback_triggered=True,
        )
        # Offset 5 = skip all 3 primary + first 2 fallback
        sliced = summary.slice_results(5)
        assert sliced.results == []
        assert len(sliced.fallback_results) == 5  # fallback[2:]
        assert sliced.fallback_results[0].owner == "f2"
        assert sliced.fallback_triggered is True

    def test_slice_offset_within_primary(self):
        """When offset < len(results), all fallback is preserved."""
        primary = [self._make_result(f"p{i}") for i in range(5)]
        fallback = [self._make_result(f"f{i}") for i in range(3)]
        summary = DiscoverSummary(
            query="q",
            total_searched=100,
            results=primary,
            fallback_results=fallback,
            fallback_triggered=True,
        )
        sliced = summary.slice_results(2)
        assert len(sliced.results) == 3  # primary[2:]
        assert len(sliced.fallback_results) == 3  # all preserved


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
