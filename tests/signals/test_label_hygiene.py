"""Tests for label hygiene signal."""

from give_back.models import RepoData, Tier
from give_back.signals.label_hygiene import evaluate_label_hygiene


def _make_repo_data(labels: list[str]) -> RepoData:
    return RepoData(
        owner="test",
        repo="repo",
        graphql={
            "repository": {
                "labels": {
                    "nodes": [{"name": name} for name in labels],
                },
            },
        },
        community={},
        contributing_text=None,
        search={},
    )


class TestLabelHygiene:
    def test_many_labels(self):
        data = _make_repo_data(["good first issue", "help wanted", "bug", "enhancement"])
        result = evaluate_label_hygiene(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert len(result.details["matched_labels"]) == 3

    def test_two_labels(self):
        data = _make_repo_data(["bug", "easy"])
        result = evaluate_label_hygiene(data)
        assert result.score == 0.8
        assert result.tier == Tier.GREEN

    def test_one_label(self):
        data = _make_repo_data(["bug", "enhancement", "wontfix"])
        result = evaluate_label_hygiene(data)
        assert result.score == 0.6
        assert result.tier == Tier.YELLOW

    def test_no_labels(self):
        data = _make_repo_data([])
        result = evaluate_label_hygiene(data)
        assert result.score == 0.3
        assert result.tier == Tier.RED

    def test_no_matching_labels(self):
        data = _make_repo_data(["enhancement", "wontfix", "duplicate", "question"])
        result = evaluate_label_hygiene(data)
        assert result.score == 0.3
        assert "No contribution-friendly" in result.summary

    def test_case_insensitive(self):
        data = _make_repo_data(["Good First Issue", "Help Wanted", "BUG"])
        result = evaluate_label_hygiene(data)
        assert result.score == 1.0
        assert len(result.details["matched_labels"]) == 3

    def test_hyphenated_variants(self):
        data = _make_repo_data(["good-first-issue", "help-wanted"])
        result = evaluate_label_hygiene(data)
        assert result.score == 0.8

    def test_empty_graphql(self):
        data = RepoData(
            owner="test",
            repo="repo",
            graphql={},
            community={},
            contributing_text=None,
            search={},
        )
        result = evaluate_label_hygiene(data)
        assert result.score == 0.3
