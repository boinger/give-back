"""Tests for the time-to-response signal."""

from give_back.models import RepoData, Tier
from give_back.signals.time_to_response import evaluate_time_to_response


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
    created_at: str = "2026-03-01T10:00:00Z",
    closed_at: str = "2026-03-05T10:00:00Z",
    association: str = "CONTRIBUTOR",
    maintainer_comment_at: str | None = None,
    review_at: str | None = None,
    non_maintainer_comment_at: str | None = None,
) -> dict:
    comments = []
    if non_maintainer_comment_at:
        comments.append(
            {
                "createdAt": non_maintainer_comment_at,
                "author": {"login": "random-user"},
                "authorAssociation": "NONE",
            }
        )
    if maintainer_comment_at:
        comments.append(
            {
                "createdAt": maintainer_comment_at,
                "author": {"login": "maintainer"},
                "authorAssociation": "MEMBER",
            }
        )

    reviews = []
    if review_at:
        reviews.append({"createdAt": review_at})

    return {
        "state": "MERGED",
        "merged": True,
        "mergedAt": closed_at,
        "closedAt": closed_at,
        "createdAt": created_at,
        "author": {"login": "ext-dev"},
        "authorAssociation": association,
        "comments": {"nodes": comments},
        "reviews": {"nodes": reviews},
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


class TestTimeToResponse:
    def test_fast_response(self):
        """Maintainer responds within 2 hours — score 1.0."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                maintainer_comment_at="2026-03-01T12:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert result.details["median_hours"] == 2.0

    def test_slow_response_72h(self):
        """Maintainer responds in ~48 hours — score 0.7."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                maintainer_comment_at="2026-03-03T10:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 0.7
        assert result.tier == Tier.GREEN

    def test_slow_response_1_week(self):
        """Maintainer responds in 5 days — score 0.5."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                maintainer_comment_at="2026-03-06T10:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 0.5
        assert result.tier == Tier.YELLOW

    def test_very_slow_response_30_days(self):
        """Maintainer responds in 15 days — score 0.3."""
        prs = [
            _make_pr(
                created_at="2026-02-01T10:00:00Z",
                closed_at="2026-03-15T10:00:00Z",
                maintainer_comment_at="2026-02-16T10:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 0.3
        assert result.tier == Tier.RED

    def test_extremely_slow_response(self):
        """Maintainer responds in 45 days — score 0.1."""
        prs = [
            _make_pr(
                created_at="2026-01-01T10:00:00Z",
                closed_at="2026-03-15T10:00:00Z",
                maintainer_comment_at="2026-02-15T10:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 0.1
        assert result.tier == Tier.RED

    def test_no_maintainer_comments(self):
        """External PRs exist but no maintainer ever responded — score 0.1."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                non_maintainer_comment_at="2026-03-01T12:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 0.1
        assert result.tier == Tier.RED
        assert "No maintainer responses" in result.summary

    def test_review_counts_as_response(self):
        """A review (without comments) should count as a maintainer response."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                review_at="2026-03-01T14:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 1.0
        assert result.details["median_hours"] == 4.0

    def test_review_earlier_than_comment(self):
        """When review comes before maintainer comment, use review time."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                maintainer_comment_at="2026-03-02T10:00:00Z",
                review_at="2026-03-01T14:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        # Review at 4h should be used, not comment at 24h
        assert result.details["median_hours"] == 4.0
        assert result.score == 1.0

    def test_zero_external_prs(self):
        """All internal PRs — return 0.5."""
        prs = [_make_pr(association="MEMBER") for _ in range(5)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.score == 0.5
        assert "No external PRs" in result.summary

    def test_empty_repo(self):
        """Empty repo with no default branch."""
        data = _make_repo_data(_make_graphql([], has_default_branch=False))
        result = evaluate_time_to_response(data)
        assert result.score == 0.5
        assert "Empty repository" in result.summary

    def test_low_sample_flag(self):
        """Fewer than 10 responding PRs should flag low_sample."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                maintainer_comment_at="2026-03-01T12:00:00Z",
            )
            for _ in range(5)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        assert result.low_sample is True
        assert "(low sample)" in result.summary

    def test_mixed_response_times(self):
        """Median of mixed response times."""
        prs = [
            # Fast: 2h
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                closed_at="2026-03-05T10:00:00Z",
                maintainer_comment_at="2026-03-01T12:00:00Z",
            ),
            # Medium: 48h
            _make_pr(
                created_at="2026-03-02T10:00:00Z",
                closed_at="2026-03-06T10:00:00Z",
                maintainer_comment_at="2026-03-04T10:00:00Z",
            ),
            # Slow: 120h (5 days)
            _make_pr(
                created_at="2026-03-03T10:00:00Z",
                closed_at="2026-03-10T10:00:00Z",
                maintainer_comment_at="2026-03-08T10:00:00Z",
            ),
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        # Median of [2, 48, 120] = 48
        assert result.details["median_hours"] == 48.0
        assert result.score == 0.7  # <=72h

    def test_ignores_non_maintainer_comments(self):
        """Non-maintainer comments should not count as responses."""
        prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                non_maintainer_comment_at="2026-03-01T11:00:00Z",
                maintainer_comment_at="2026-03-03T10:00:00Z",
            )
            for _ in range(12)
        ]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_time_to_response(data)
        # Should use maintainer comment at 48h, not non-maintainer at 1h
        assert result.details["median_hours"] == 48.0
        assert result.score == 0.7

    def test_old_prs_filtered_out(self):
        """PRs older than 12 months should be excluded."""
        old_prs = [
            _make_pr(
                created_at="2024-01-01T10:00:00Z",
                closed_at="2024-01-05T10:00:00Z",
                maintainer_comment_at="2024-01-01T12:00:00Z",
            )
            for _ in range(5)
        ]
        recent_prs = [
            _make_pr(
                created_at="2026-03-01T10:00:00Z",
                maintainer_comment_at="2026-03-01T12:00:00Z",
            )
            for _ in range(3)
        ]
        data = _make_repo_data(_make_graphql(old_prs + recent_prs))
        result = evaluate_time_to_response(data)
        assert result.details["responded_prs"] == 3
        assert result.low_sample is True
