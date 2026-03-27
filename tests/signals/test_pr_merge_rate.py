"""Tests for the PR merge rate signal."""

from give_back.models import RepoData, Tier
from give_back.signals.pr_merge_rate import evaluate_pr_merge_rate


def _make_repo_data(graphql: dict) -> RepoData:
    return RepoData(
        owner="test",
        repo="repo",
        graphql=graphql,
        community={},
        contributing_text=None,
        search={},
    )


def _make_pr(
    *,
    merged: bool = False,
    closed_at: str = "2026-03-01T10:00:00Z",
    created_at: str = "2026-02-28T10:00:00Z",
    association: str = "CONTRIBUTOR",
) -> dict:
    return {
        "state": "MERGED" if merged else "CLOSED",
        "merged": merged,
        "mergedAt": closed_at if merged else None,
        "closedAt": closed_at,
        "createdAt": created_at,
        "author": {"login": "someone"},
        "authorAssociation": association,
        "comments": {
            "nodes": [
                {
                    "createdAt": created_at,
                    "author": {"login": "maintainer"},
                    "authorAssociation": "MEMBER",
                }
            ]
        },
        "reviews": {"nodes": []},
    }


def _make_graphql(prs: list[dict], has_default_branch: bool = True) -> dict:
    repo: dict = {
        "pullRequests": {"nodes": prs},
    }
    if has_default_branch:
        repo["defaultBranchRef"] = {"target": {"committedDate": "2026-03-20T10:00:00Z"}}
    else:
        repo["defaultBranchRef"] = None
    return {"repository": repo}


class TestPrMergeRate:
    def test_healthy_repo_high_merge_rate(self):
        """9 merged + 2 closed = 9/11 = 81.8% merge rate."""
        prs = [_make_pr(merged=True) for _ in range(9)]
        prs += [_make_pr(merged=False) for _ in range(2)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.score > 0.7
        assert result.tier == Tier.GREEN
        assert "82%" in result.summary
        assert not result.low_sample

    def test_low_merge_rate(self):
        """2 merged + 10 closed = 2/12 = 16.7% merge rate."""
        prs = [_make_pr(merged=True) for _ in range(2)]
        prs += [_make_pr(merged=False) for _ in range(10)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.score < 0.4
        assert result.tier == Tier.RED
        assert "17%" in result.summary

    def test_zero_external_prs(self):
        """All internal PRs — should return 0.5 with appropriate message."""
        prs = [_make_pr(merged=True, association="MEMBER") for _ in range(5)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.score == 0.5
        assert "No external PRs" in result.summary

    def test_empty_repo_no_default_branch(self):
        """Empty repo with no default branch."""
        data = _make_repo_data(_make_graphql([], has_default_branch=False))
        result = evaluate_pr_merge_rate(data)
        assert result.score == 0.5
        assert "Empty repository" in result.summary

    def test_low_sample_flag(self):
        """Fewer than 10 external PRs should flag low_sample."""
        prs = [_make_pr(merged=True) for _ in range(5)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.low_sample is True
        assert "(low sample)" in result.summary

    def test_exactly_10_prs_not_low_sample(self):
        """Exactly 10 external PRs should NOT flag low_sample."""
        prs = [_make_pr(merged=True) for _ in range(10)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.low_sample is False

    def test_old_prs_filtered_out(self):
        """PRs older than 12 months should be excluded."""
        old_prs = [_make_pr(merged=True, closed_at="2024-01-01T10:00:00Z") for _ in range(5)]
        recent_prs = [_make_pr(merged=True) for _ in range(3)]
        data = _make_repo_data(_make_graphql(old_prs + recent_prs))
        result = evaluate_pr_merge_rate(data)
        # Only 3 recent PRs should count
        assert result.details["external_closed"] == 3
        assert result.low_sample is True

    def test_collaborator_pr_count_tracked(self):
        """Collaborator PRs should be tracked in details for bias warning."""
        prs = [_make_pr(merged=True) for _ in range(5)]
        prs += [_make_pr(merged=True, association="COLLABORATOR") for _ in range(3)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.details["collaborator_pr_count"] == 3
        # Collaborators should be excluded from external count
        assert result.details["external_closed"] == 5

    def test_100_percent_merge_rate(self):
        """All external PRs merged."""
        prs = [_make_pr(merged=True) for _ in range(15)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert "100%" in result.summary

    def test_0_percent_merge_rate(self):
        """No external PRs merged."""
        prs = [_make_pr(merged=False) for _ in range(15)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_pr_merge_rate(data)
        assert result.score == 0.0
        assert result.tier == Tier.RED
        assert "0%" in result.summary

    def test_empty_graphql_response(self):
        """Handle missing repository key gracefully."""
        data = _make_repo_data({})
        result = evaluate_pr_merge_rate(data)
        # No repository means no defaultBranchRef
        assert result.score == 0.5
        assert "Empty repository" in result.summary
