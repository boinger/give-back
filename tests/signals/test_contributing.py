"""Tests for contributing signals (existence + content)."""

from give_back.models import RepoData, Tier
from give_back.signals.contributing import (
    evaluate_contributing_content,
    evaluate_contributing_exists,
)


def _make_repo_data(
    community: dict | None = None,
    contributing_text: str | None = None,
) -> RepoData:
    return RepoData(
        owner="test",
        repo="repo",
        graphql={"repository": {}},
        community=community or {},
        contributing_text=contributing_text,
        search={},
    )


class TestContributingExists:
    def test_present(self):
        data = _make_repo_data(community={"files": {"contributing": {"url": "https://example.com"}}})
        result = evaluate_contributing_exists(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert result.skip is False

    def test_absent_is_skipped(self):
        data = _make_repo_data(community={"files": {"contributing": None}})
        result = evaluate_contributing_exists(data)
        assert result.skip is True
        assert "No CONTRIBUTING" in result.summary

    def test_missing_files_key_is_skipped(self):
        data = _make_repo_data(community={})
        result = evaluate_contributing_exists(data)
        assert result.skip is True

    def test_empty_files_is_skipped(self):
        data = _make_repo_data(community={"files": {}})
        result = evaluate_contributing_exists(data)
        assert result.skip is True


class TestContributingContent:
    def test_cla_detected(self):
        data = _make_repo_data(contributing_text="Please sign the CLA before submitting.")
        result = evaluate_contributing_content(data)
        assert result.score == 0.3
        assert "CLA" in result.summary

    def test_contributor_license_agreement(self):
        data = _make_repo_data(contributing_text="You must accept the Contributor License Agreement.")
        result = evaluate_contributing_content(data)
        assert result.score == 0.3

    def test_dco_detected(self):
        data = _make_repo_data(contributing_text="All commits must include a Signed-off-by line.")
        result = evaluate_contributing_content(data)
        assert result.score == 0.6
        assert "DCO" in result.summary

    def test_developer_certificate(self):
        data = _make_repo_data(contributing_text="By contributing, you agree to the Developer Certificate of Origin.")
        result = evaluate_contributing_content(data)
        assert result.score == 0.6

    def test_onerous_process(self):
        data = _make_repo_data(contributing_text="Changes must be approved by the committee.")
        result = evaluate_contributing_content(data)
        assert result.score == 0.3
        assert "onerous" in result.summary

    def test_clean_contributing(self):
        data = _make_repo_data(contributing_text="Fork the repo, make changes, open a PR. That's it!")
        result = evaluate_contributing_content(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert "No friction" in result.summary

    def test_no_text_is_skipped(self):
        data = _make_repo_data(contributing_text=None)
        result = evaluate_contributing_content(data)
        assert result.skip is True
        assert "No content" in result.summary

    def test_multiple_indicators_uses_lowest(self):
        """CLA (0.3) + DCO (0.6) → should use 0.3."""
        data = _make_repo_data(contributing_text="Sign the CLA. All commits must have Signed-off-by.")
        result = evaluate_contributing_content(data)
        assert result.score == 0.3
        assert "CLA" in result.summary
        assert "DCO" in result.summary

    def test_case_insensitive(self):
        data = _make_repo_data(contributing_text="you must sign the cla before contributing")
        result = evaluate_contributing_content(data)
        assert result.score == 0.3

    def test_negated_cla(self):
        """'No CLA' should not trigger friction."""
        data = _make_repo_data(contributing_text="No CLA. No DCO. No sign-off required. Just clean code.")
        result = evaluate_contributing_content(data)
        assert result.score == 1.0
        assert "No friction" in result.summary

    def test_negated_dco(self):
        """'No DCO' alone should not trigger friction."""
        data = _make_repo_data(contributing_text="We don't require DCO sign-off.")
        result = evaluate_contributing_content(data)
        assert result.score == 1.0

    def test_negated_cla_but_real_dco(self):
        """'No CLA' negated but real DCO requirement still detected."""
        data = _make_repo_data(contributing_text="No CLA required. All commits must include a Signed-off-by line.")
        result = evaluate_contributing_content(data)
        assert result.score == 0.6
        assert "DCO" in result.summary
        assert "CLA" not in result.summary
