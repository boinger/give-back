"""Tests for the ghost-closing signal."""

from give_back.models import RepoData, Tier
from give_back.signals.ghost_closing import evaluate_ghost_closing


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
    has_comments: bool = False,
    has_reviews: bool = False,
) -> dict:
    comments = []
    if has_comments:
        comments = [
            {
                "createdAt": created_at,
                "author": {"login": "maintainer"},
                "authorAssociation": "MEMBER",
            }
        ]
    reviews = []
    if has_reviews:
        reviews = [{"createdAt": created_at, "author": {"login": "reviewer"}, "authorAssociation": "MEMBER"}]

    return {
        "state": "MERGED" if merged else "CLOSED",
        "merged": merged,
        "mergedAt": closed_at if merged else None,
        "closedAt": closed_at,
        "createdAt": created_at,
        "author": {"login": "someone"},
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


class TestGhostClosing:
    def test_no_ghost_closing(self):
        """All external PRs have comments — no ghost closing."""
        prs = [_make_pr(has_comments=True) for _ in range(12)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert "0%" in result.summary

    def test_all_ghost_closed(self):
        """All external PRs closed without any feedback."""
        prs = [_make_pr(has_comments=False, has_reviews=False) for _ in range(12)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.score == 0.0
        assert result.tier == Tier.RED
        assert "100%" in result.summary

    def test_mixed_ghost_closing(self):
        """Mix of ghost-closed and responded-to PRs."""
        prs = [_make_pr(has_comments=True) for _ in range(8)]
        prs += [_make_pr(has_comments=False) for _ in range(4)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        # 4 ghost / 12 total = 33% ghost rate, score = 0.667
        assert 0.6 < result.score < 0.7
        assert result.tier == Tier.YELLOW

    def test_review_counts_as_feedback(self):
        """A PR with only a review (no comments) should not be ghost-closed."""
        prs = [_make_pr(has_comments=False, has_reviews=True) for _ in range(12)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.score == 1.0
        assert "0%" in result.summary

    def test_internal_prs_excluded(self):
        """Internal PRs without comments should not count as ghost-closing."""
        internal_prs = [_make_pr(association="MEMBER", has_comments=False) for _ in range(5)]
        external_prs = [_make_pr(has_comments=True) for _ in range(10)]
        data = _make_repo_data(_make_graphql(internal_prs + external_prs))
        result = evaluate_ghost_closing(data)
        assert result.score == 1.0
        assert result.details["external_closed"] == 10

    def test_zero_external_prs(self):
        """All internal PRs — return 0.5."""
        prs = [_make_pr(association="OWNER") for _ in range(5)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.score == 0.5
        assert "No external PRs" in result.summary

    def test_empty_repo(self):
        """Empty repo with no default branch."""
        data = _make_repo_data(_make_graphql([], has_default_branch=False))
        result = evaluate_ghost_closing(data)
        assert result.score == 0.5
        assert "Empty repository" in result.summary

    def test_low_sample_flag(self):
        """Fewer than 10 external PRs should flag low_sample."""
        prs = [_make_pr(has_comments=True) for _ in range(5)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.low_sample is True

    def test_old_prs_filtered_out(self):
        """PRs older than 12 months should be excluded."""
        old_prs = [_make_pr(closed_at="2024-01-01T10:00:00Z", has_comments=False) for _ in range(5)]
        recent_prs = [_make_pr(has_comments=True) for _ in range(3)]
        data = _make_repo_data(_make_graphql(old_prs + recent_prs))
        result = evaluate_ghost_closing(data)
        assert result.details["external_closed"] == 3
        assert result.details["ghost_closed"] == 0


class TestGhostClosingBotAwareness:
    """Bot-only comments should still count as ghost-closed."""

    def _make_pr_with_bot_comment(self, bot_login, human_comment=False):
        """PR with a bot comment and optionally a human comment."""
        comments = [
            {
                "createdAt": "2026-03-01T10:05:00Z",
                "author": {"login": bot_login},
                "authorAssociation": "MEMBER",
            },
        ]
        if human_comment:
            comments.append(
                {
                    "createdAt": "2026-03-01T12:00:00Z",
                    "author": {"login": "human-maintainer"},
                    "authorAssociation": "MEMBER",
                }
            )
        return {
            "state": "CLOSED",
            "merged": False,
            "mergedAt": None,
            "closedAt": "2026-03-05T10:00:00Z",
            "createdAt": "2026-03-01T10:00:00Z",
            "author": {"login": "ext-dev"},
            "authorAssociation": "CONTRIBUTOR",
            "comments": {"nodes": comments},
            "reviews": {"nodes": []},
        }

    def test_bot_only_comment_counts_as_ghost(self):
        """PR with only a CLA bot comment is still ghost-closed."""
        prs = [self._make_pr_with_bot_comment("CLAassistant[bot]") for _ in range(12)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.details["ghost_closed"] == 12
        assert result.score == 0.0

    def test_bot_plus_human_not_ghost(self):
        """PR with bot comment AND human comment is not ghost-closed."""
        prs = [self._make_pr_with_bot_comment("CLAassistant[bot]", human_comment=True) for _ in range(12)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.details["ghost_closed"] == 0
        assert result.score == 1.0

    def test_known_bot_comment_counts_as_ghost(self):
        """PR with only a known bot (stale) comment is ghost-closed."""
        prs = [self._make_pr_with_bot_comment("stale") for _ in range(12)]
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.details["ghost_closed"] == 12

    def test_bot_review_counts_as_ghost(self):
        """PR with only a bot review (no human review) is ghost-closed."""
        prs = []
        for _ in range(12):
            prs.append(
                {
                    "state": "CLOSED",
                    "merged": False,
                    "mergedAt": None,
                    "closedAt": "2026-03-05T10:00:00Z",
                    "createdAt": "2026-03-01T10:00:00Z",
                    "author": {"login": "ext-dev"},
                    "authorAssociation": "CONTRIBUTOR",
                    "comments": {"nodes": []},
                    "reviews": {
                        "nodes": [
                            {
                                "createdAt": "2026-03-01T10:02:00Z",
                                "author": {"login": "codecov[bot]"},
                                "authorAssociation": "MEMBER",
                            }
                        ]
                    },
                }
            )
        data = _make_repo_data(_make_graphql(prs))
        result = evaluate_ghost_closing(data)
        assert result.details["ghost_closed"] == 12
