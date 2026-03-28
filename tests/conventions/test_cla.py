"""Tests for CLA detection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from give_back.conventions.cla import detect_cla


@pytest.fixture
def clone_dir(tmp_path):
    """Create a minimal clone directory."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    return tmp_path


class TestClaFileDetection:
    def test_clabot_file(self, clone_dir):
        (clone_dir / ".clabot").write_text("{}")
        assert detect_cla(clone_dir) is True

    def test_cla_json(self, clone_dir):
        (clone_dir / "cla.json").write_text("{}")
        assert detect_cla(clone_dir) is True

    def test_cla_md(self, clone_dir):
        (clone_dir / "CLA.md").write_text("# CLA")
        assert detect_cla(clone_dir) is True

    def test_dot_cla_json(self, clone_dir):
        (clone_dir / ".cla.json").write_text("{}")
        assert detect_cla(clone_dir) is True

    def test_no_cla_files(self, clone_dir):
        assert detect_cla(clone_dir) is False


class TestClaCiDetection:
    def test_cla_assistant_in_workflow(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "cla.yml"
        wf.write_text("uses: cla-assistant/github-action@v2")
        assert detect_cla(clone_dir) is True

    def test_easycla_in_workflow(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "ci.yml"
        wf.write_text("name: CI\njobs:\n  easycla:\n    runs-on: ubuntu")
        assert detect_cla(clone_dir) is True

    def test_unrelated_workflow(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "test.yml"
        wf.write_text("name: Tests\njobs:\n  test:\n    runs-on: ubuntu")
        assert detect_cla(clone_dir) is False


class TestClaPrCommentDetection:
    def test_cla_bot_comment_found(self, clone_dir):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = [
            # First call: list PRs
            [{"number": 1, "merged_at": "2026-03-01T10:00:00Z"}],
            # Second call: PR comments
            [{"user": {"login": "CLAassistant"}, "body": "Please sign the CLA"}],
        ]
        assert detect_cla(clone_dir, client=mock_client, owner="org", repo="repo") is True

    def test_no_cla_bot_comments(self, clone_dir):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = [
            [{"number": 1, "merged_at": "2026-03-01T10:00:00Z"}],
            [{"user": {"login": "human-reviewer"}, "body": "LGTM"}],
        ]
        assert detect_cla(clone_dir, client=mock_client, owner="org", repo="repo") is False

    def test_api_error_graceful(self, clone_dir):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = Exception("API error")
        # Should not raise, just return False
        assert detect_cla(clone_dir, client=mock_client, owner="org", repo="repo") is False

    def test_no_client_skips_api_check(self, clone_dir):
        """Without a client, only file/CI checks run."""
        assert detect_cla(clone_dir) is False


class TestClaGuardrail:
    def test_cla_not_required(self):
        from give_back.guardrails import check_cla_signed

        result = check_cla_signed(cla_required=False)
        assert result.passed is True

    def test_cla_required_warns(self):
        from give_back.guardrails import check_cla_signed

        result = check_cla_signed(cla_required=True)
        assert result.passed is False
        assert "CLA" in result.message
        assert result.severity.value == "warn"
