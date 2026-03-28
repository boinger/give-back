"""Tests for conventions/brief.py — brief assembly orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from give_back.conventions.brief import scan_conventions
from give_back.conventions.models import (
    BranchConvention,
    CITestInfo,
    CommitFormat,
    ContributionBrief,
    PrTemplate,
    StyleInfo,
)
from give_back.github_client import GitHubClient


@pytest.fixture()
def mock_client():
    """A GitHubClient with mocked transport for REST calls."""
    return MagicMock(spec=GitHubClient)


@pytest.fixture()
def _patch_clone():
    """Patch the cloned_repo context manager to yield a fake path without cloning."""
    fake_dir = Path("/tmp/fake-clone")
    with patch("give_back.conventions.brief.cloned_repo") as mock_cm:
        mock_cm.return_value.__enter__ = MagicMock(return_value=fake_dir)
        mock_cm.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_cm


@pytest.fixture()
def _patch_detectors():
    """Patch all detector functions to return known values."""
    with (
        patch("give_back.conventions.brief.analyze_commits") as mock_commits,
        patch("give_back.conventions.brief.detect_merge_strategy") as mock_merge,
        patch("give_back.conventions.brief.find_pr_template") as mock_pr,
        patch("give_back.conventions.brief.detect_dco") as mock_dco,
        patch("give_back.conventions.brief.detect_testing") as mock_test,
        patch("give_back.conventions.brief.detect_style") as mock_style,
        patch("give_back.conventions.brief.analyze_branch_names") as mock_branches,
    ):
        mock_commits.return_value = CommitFormat(
            style="conventional",
            examples=["feat: add login", "fix: resolve crash"],
            prefix_pattern="feat:",
        )
        mock_merge.return_value = "squash"
        mock_pr.return_value = PrTemplate(
            path=".github/PULL_REQUEST_TEMPLATE.md",
            sections=["Description", "Checklist"],
            raw_content="## Description\n\n## Checklist\n",
        )
        mock_dco.return_value = True
        mock_test.return_value = CITestInfo(
            framework="pytest",
            test_dir="tests/",
            ci_config="GitHub Actions",
            run_command="pytest",
        )
        mock_style.return_value = StyleInfo(
            linter="ruff",
            formatter="ruff format",
            config_file="ruff.toml",
            line_length=120,
        )
        mock_branches.return_value = BranchConvention(
            pattern="type/description",
            examples=["fix/login-bug", "feat/add-auth"],
        )

        yield {
            "commits": mock_commits,
            "merge": mock_merge,
            "pr": mock_pr,
            "dco": mock_dco,
            "test": mock_test,
            "style": mock_style,
            "branches": mock_branches,
        }


class TestScanAssemblesAllFields:
    """Verify that scan_conventions populates all fields of the brief."""

    @pytest.mark.usefixtures("_patch_clone")
    def test_all_fields_populated(self, mock_client, _patch_detectors):
        """All detectors return known values — brief should have everything."""
        mock_client.rest_get.side_effect = self._make_rest_get_side_effect()

        brief = scan_conventions(mock_client, "pallets", "flask")

        assert isinstance(brief, ContributionBrief)
        assert brief.owner == "pallets"
        assert brief.repo == "flask"
        assert brief.generated_at  # non-empty date string

        # Commit format
        assert brief.commit_format.style == "conventional"
        assert len(brief.commit_format.examples) == 2
        assert brief.commit_format.prefix_pattern == "feat:"

        # Merge strategy
        assert brief.merge_strategy == "squash"

        # PR template
        assert brief.pr_template is not None
        assert brief.pr_template.path == ".github/PULL_REQUEST_TEMPLATE.md"
        assert "Description" in brief.pr_template.sections

        # DCO
        assert brief.dco_required is True

        # Testing
        assert brief.test_info.framework == "pytest"
        assert brief.test_info.test_dir == "tests/"

        # Style
        assert brief.style_info.linter == "ruff"
        assert brief.style_info.line_length == 120

        # Branch convention
        assert brief.branch_convention.pattern == "type/description"

        # Default branch from API
        assert brief.default_branch == "main"

        # Notes should be generated
        assert len(brief.notes) > 0

    @staticmethod
    def _make_rest_get_side_effect():
        """Side effect for mock_client.rest_get to handle multiple endpoints."""

        def side_effect(path, **kwargs):
            if "/repos/pallets/flask" == path and "params" not in kwargs:
                return {"default_branch": "main"}
            if "/pulls" in path and "/reviews" in path:
                return [{"user": {"login": "reviewer1"}, "state": "APPROVED"}]
            if "/pulls" in path:
                return [
                    {
                        "number": 100,
                        "merged_at": "2026-01-01T00:00:00Z",
                        "head": {"ref": "fix/something"},
                    }
                ]
            return {}

        return side_effect


class TestDetectorFailure:
    """Verify that a single detector failure doesn't crash the whole scan."""

    @pytest.mark.usefixtures("_patch_clone")
    def test_commit_detector_fails_others_succeed(self, mock_client, _patch_detectors):
        """If analyze_commits raises, the brief still has results from other detectors."""
        _patch_detectors["commits"].side_effect = RuntimeError("git log failed")

        mock_client.rest_get.side_effect = lambda path, **kwargs: (
            {"default_branch": "main"} if path == "/repos/test/repo" else []
        )

        brief = scan_conventions(mock_client, "test", "repo")

        # Commit format should fall back to unknown
        assert brief.commit_format.style == "unknown"

        # Other detectors should still have their mocked values
        assert brief.merge_strategy == "squash"
        assert brief.dco_required is True
        assert brief.test_info.framework == "pytest"
        assert brief.style_info.linter == "ruff"

    @pytest.mark.usefixtures("_patch_clone")
    def test_multiple_detectors_fail(self, mock_client, _patch_detectors):
        """Multiple detector failures still produce a brief with partial results."""
        _patch_detectors["commits"].side_effect = RuntimeError("boom")
        _patch_detectors["merge"].side_effect = RuntimeError("boom")
        _patch_detectors["style"].side_effect = RuntimeError("boom")

        mock_client.rest_get.side_effect = lambda path, **kwargs: (
            {"default_branch": "develop"} if path == "/repos/test/repo" else []
        )

        brief = scan_conventions(mock_client, "test", "repo")

        assert brief.commit_format.style == "unknown"
        assert brief.merge_strategy == "unknown"  # Default
        assert brief.dco_required is True  # DCO detector succeeded
        assert brief.test_info.framework == "pytest"  # Test detector succeeded


class TestIssueTitle:
    """Verify issue title fetching behavior."""

    @pytest.mark.usefixtures("_patch_clone", "_patch_detectors")
    def test_issue_title_fetched(self, mock_client):
        """When issue_number is provided, the brief should contain the issue title."""

        def rest_get_side_effect(path, **kwargs):
            if "/issues/42" in path:
                return {"title": "Fix typo in docs", "number": 42}
            if path == "/repos/test/repo":
                return {"default_branch": "main"}
            if "/pulls" in path:
                return []
            return {}

        mock_client.rest_get.side_effect = rest_get_side_effect

        brief = scan_conventions(mock_client, "test", "repo", issue_number=42)

        assert brief.issue_number == 42
        assert brief.issue_title == "Fix typo in docs"

    @pytest.mark.usefixtures("_patch_clone", "_patch_detectors")
    def test_no_issue(self, mock_client):
        """When issue_number is None, issue_title should be None."""
        mock_client.rest_get.side_effect = lambda path, **kwargs: (
            {"default_branch": "main"} if path == "/repos/test/repo" else []
        )

        brief = scan_conventions(mock_client, "test", "repo", issue_number=None)

        assert brief.issue_number is None
        assert brief.issue_title is None

    @pytest.mark.usefixtures("_patch_clone", "_patch_detectors")
    def test_issue_fetch_fails_gracefully(self, mock_client):
        """If the issue API call fails, brief still works without issue title."""

        def rest_get_side_effect(path, **kwargs):
            if "/issues/" in path:
                raise RuntimeError("API error")
            if path == "/repos/test/repo":
                return {"default_branch": "main"}
            if "/pulls" in path:
                return []
            return {}

        mock_client.rest_get.side_effect = rest_get_side_effect

        brief = scan_conventions(mock_client, "test", "repo", issue_number=99)

        assert brief.issue_number == 99
        assert brief.issue_title is None


class TestNoteGeneration:
    """Verify that notes are generated correctly based on findings."""

    @pytest.mark.usefixtures("_patch_clone", "_patch_detectors")
    def test_dco_note_generated(self, mock_client):
        """DCO required should generate a note about sign-off."""
        mock_client.rest_get.side_effect = lambda path, **kwargs: (
            {"default_branch": "main"} if path == "/repos/test/repo" else []
        )

        brief = scan_conventions(mock_client, "test", "repo")

        assert any("DCO" in note for note in brief.notes)
        assert any("sign-off" in note.lower() for note in brief.notes)

    @pytest.mark.usefixtures("_patch_clone", "_patch_detectors")
    def test_squash_merge_note(self, mock_client):
        """Squash merge should generate a note about flattened history."""
        mock_client.rest_get.side_effect = lambda path, **kwargs: (
            {"default_branch": "main"} if path == "/repos/test/repo" else []
        )

        brief = scan_conventions(mock_client, "test", "repo")

        assert any("squash" in note.lower() for note in brief.notes)

    @pytest.mark.usefixtures("_patch_clone", "_patch_detectors")
    def test_conventional_commits_note(self, mock_client):
        """Conventional commits should generate a prefix note."""
        mock_client.rest_get.side_effect = lambda path, **kwargs: (
            {"default_branch": "main"} if path == "/repos/test/repo" else []
        )

        brief = scan_conventions(mock_client, "test", "repo")

        assert any("conventional" in note.lower() for note in brief.notes)


class TestReviewInfo:
    """Verify review info fetching."""

    @pytest.mark.usefixtures("_patch_clone", "_patch_detectors")
    def test_reviewers_extracted(self, mock_client):
        """Reviewers from recent merged PRs should appear in the brief."""
        call_count = 0

        def rest_get_side_effect(path, **kwargs):
            nonlocal call_count
            if path == "/repos/test/repo":
                return {"default_branch": "main"}
            if "/pulls" in path and "/reviews" in path:
                return [
                    {"user": {"login": "alice"}, "state": "APPROVED"},
                    {"user": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
                ]
            if "/pulls" in path:
                return [
                    {
                        "number": 1,
                        "merged_at": "2026-01-01T00:00:00Z",
                        "head": {"ref": "fix/bug"},
                    },
                    {
                        "number": 2,
                        "merged_at": "2026-01-02T00:00:00Z",
                        "head": {"ref": "feat/thing"},
                    },
                ]
            return {}

        mock_client.rest_get.side_effect = rest_get_side_effect

        brief = scan_conventions(mock_client, "test", "repo")

        assert "alice" in brief.review_info.typical_reviewers
        assert "bob" in brief.review_info.typical_reviewers


class TestCloneFailure:
    """Verify behavior when the clone itself fails."""

    def test_clone_failure_still_returns_brief(self, mock_client):
        """If cloned_repo raises, the brief still has API-based results."""
        with (
            patch("give_back.conventions.brief.cloned_repo") as mock_cm,
            patch("give_back.conventions.brief.analyze_branch_names") as mock_branches,
        ):
            mock_cm.side_effect = RuntimeError("Clone failed")
            mock_branches.return_value = BranchConvention(
                pattern="type/description",
                examples=["fix/thing"],
            )

            mock_client.rest_get.side_effect = lambda path, **kwargs: (
                {"default_branch": "develop"} if path == "/repos/test/repo" else []
            )

            brief = scan_conventions(mock_client, "test", "repo")

            # Clone-based detectors should have defaults
            assert brief.commit_format.style == "unknown"
            assert brief.merge_strategy == "unknown"

            # API-based detectors should still work
            assert brief.branch_convention.pattern == "type/description"
            assert brief.default_branch == "develop"
