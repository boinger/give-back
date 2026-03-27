"""Tests for AI policy signal."""

from give_back.models import RepoData, Tier
from give_back.signals.ai_policy import evaluate_ai_policy


def _make_repo_data(
    contributing_text: str | None = None,
    search: dict | None = None,
) -> RepoData:
    return RepoData(
        owner="test",
        repo="repo",
        graphql={"repository": {}},
        community={},
        contributing_text=contributing_text,
        search=search or {},
    )


class TestAiPolicyExplicit:
    def test_explicit_ban_no_ai(self):
        data = _make_repo_data(contributing_text="We do not accept No AI generated code.")
        result = evaluate_ai_policy(data)
        assert result.score == 0.0
        assert result.tier == Tier.RED
        assert "banned" in result.summary

    def test_explicit_ban_no_llm(self):
        data = _make_repo_data(contributing_text="No LLM output please.")
        result = evaluate_ai_policy(data)
        assert result.score == 0.0

    def test_explicit_ban_machine_generated(self):
        data = _make_repo_data(contributing_text="machine-generated code is not welcome here.")
        result = evaluate_ai_policy(data)
        assert result.score == 0.0

    def test_explicit_welcome(self):
        data = _make_repo_data(contributing_text="AI-assisted welcome! Use whatever tools you like.")
        result = evaluate_ai_policy(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert "welcomed" in result.summary

    def test_copilot_encouraged(self):
        data = _make_repo_data(contributing_text="Copilot encouraged for boilerplate.")
        result = evaluate_ai_policy(data)
        assert result.score == 1.0

    def test_disclosure_required(self):
        data = _make_repo_data(contributing_text="Please disclose any AI tool usage in your PR.")
        result = evaluate_ai_policy(data)
        assert result.score == 0.5
        assert result.tier == Tier.YELLOW
        assert "disclosure" in result.summary.lower()

    def test_ban_takes_priority_over_search(self):
        """When contributing text has a ban, search results should be ignored."""
        data = _make_repo_data(
            contributing_text="No AI contributions accepted.",
            search={"total_count": 0, "items": []},
        )
        result = evaluate_ai_policy(data)
        assert result.score == 0.0
        assert result.details["source"] == "contributing_text"


class TestAiPolicySearch:
    def test_zero_matches(self):
        data = _make_repo_data(search={"total_count": 0, "items": []})
        result = evaluate_ai_policy(data)
        assert result.score == 1.0
        assert result.details["source"] == "search"

    def test_few_matches(self):
        data = _make_repo_data(
            search={
                "total_count": 2,
                "items": [
                    {"title": "Should we use Copilot?"},
                    {"title": "AI code review"},
                ],
            }
        )
        result = evaluate_ai_policy(data)
        assert result.score == 0.7
        assert len(result.details["titles"]) == 2

    def test_many_matches(self):
        data = _make_repo_data(
            search={
                "total_count": 5,
                "items": [{"title": f"AI issue {i}"} for i in range(5)],
            }
        )
        result = evaluate_ai_policy(data)
        assert result.score == 0.4
        assert "manual review" in result.summary

    def test_no_contributing_text_falls_through_to_search(self):
        data = _make_repo_data(contributing_text=None, search={"total_count": 1, "items": [{"title": "AI?"}]})
        result = evaluate_ai_policy(data)
        assert result.score == 0.7
        assert result.details["source"] == "search"

    def test_contributing_text_without_ai_mention_falls_through(self):
        data = _make_repo_data(
            contributing_text="Fork the repo and submit a PR.",
            search={"total_count": 0, "items": []},
        )
        result = evaluate_ai_policy(data)
        assert result.score == 1.0
        assert result.details["source"] == "search"
