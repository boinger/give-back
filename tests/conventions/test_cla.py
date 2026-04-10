"""Tests for CLA detection and guardrail."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from give_back.conventions.cla import detect_cla
from give_back.conventions.models import CLAInfo
from give_back.exceptions import GiveBackError


@pytest.fixture
def clone_dir(tmp_path):
    """Create a minimal clone directory."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    return tmp_path


class TestClaFileDetection:
    def test_clabot_file(self, clone_dir):
        (clone_dir / ".clabot").write_text("{}")
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "cla-assistant"
        assert result.detection_source == "config-file"

    def test_cla_json(self, clone_dir):
        (clone_dir / "cla.json").write_text("{}")
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "cla-assistant"

    def test_cla_md(self, clone_dir):
        (clone_dir / "CLA.md").write_text("# CLA")
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "unknown"  # CLA.md doesn't identify the system

    def test_dot_cla_json(self, clone_dir):
        (clone_dir / ".cla.json").write_text("{}")
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "cla-assistant"

    def test_no_cla_files(self, clone_dir):
        result = detect_cla(clone_dir)
        assert result.required is False
        assert result.system == "unknown"


class TestClaCiDetection:
    def test_cla_assistant_in_workflow(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "cla.yml"
        wf.write_text("uses: cla-assistant/github-action@v2")
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "cla-assistant"
        assert result.detection_source == "ci-workflow"

    def test_easycla_in_workflow(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "ci.yml"
        wf.write_text("name: CI\njobs:\n  easycla:\n    runs-on: ubuntu")
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "easycla"

    def test_google_cla_in_workflow(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "cla.yml"
        wf.write_text("uses: some/google-cla-action@v1")
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "google"

    def test_unrelated_workflow(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "test.yml"
        wf.write_text("name: Tests\njobs:\n  test:\n    runs-on: ubuntu")
        result = detect_cla(clone_dir)
        assert result.required is False


class TestClaUrlDerivation:
    def test_cla_assistant_url_deterministic(self, clone_dir):
        (clone_dir / ".clabot").write_text("{}")
        result = detect_cla(clone_dir, owner="myorg", repo="myrepo")
        assert result.signing_url == "https://cla-assistant.io/myorg/myrepo"

    def test_easycla_url_generic(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "cla.yml"
        wf.write_text("name: EasyCLA check\nuses: easycla/check@v1")
        result = detect_cla(clone_dir, owner="org", repo="repo")
        assert result.signing_url == "https://easycla.lfx.linuxfoundation.org/"

    def test_google_url_generic(self, clone_dir):
        wf = clone_dir / ".github" / "workflows" / "cla.yml"
        wf.write_text("uses: actions/google-cla@v1")
        result = detect_cla(clone_dir, owner="org", repo="repo")
        assert result.signing_url == "https://cla.developers.google.com/"

    def test_unknown_system_no_url(self, clone_dir):
        (clone_dir / "CLA.md").write_text("# Sign our CLA")
        result = detect_cla(clone_dir)
        assert result.signing_url is None


class TestClaPrCommentDetection:
    def test_cla_bot_comment_found(self, clone_dir):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = [
            [{"number": 1, "merged_at": "2026-03-01T10:00:00Z"}],
            [{"user": {"login": "CLAassistant"}, "body": "Please sign the CLA"}],
        ]
        result = detect_cla(clone_dir, client=mock_client, owner="org", repo="repo")
        assert result.required is True
        assert result.system == "cla-assistant"
        assert result.detection_source == "pr-comment"
        assert result.signing_url == "https://cla-assistant.io/org/repo"

    def test_easycla_bot_extracts_url(self, clone_dir):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = [
            [{"number": 1, "merged_at": "2026-03-01T10:00:00Z"}],
            [
                {
                    "user": {"login": "linux-foundation-easycla"},
                    "body": "Sign here: https://easycla.lfx.linuxfoundation.org/#/project/12345",
                }
            ],
        ]
        result = detect_cla(clone_dir, client=mock_client, owner="org", repo="repo")
        assert result.required is True
        assert result.system == "easycla"
        assert "easycla.lfx" in result.signing_url

    def test_no_cla_bot_comments(self, clone_dir):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = [
            [{"number": 1, "merged_at": "2026-03-01T10:00:00Z"}],
            [{"user": {"login": "human-reviewer"}, "body": "LGTM"}],
        ]
        result = detect_cla(clone_dir, client=mock_client, owner="org", repo="repo")
        assert result.required is False

    def test_api_error_graceful(self, clone_dir):
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = GiveBackError("API error")
        result = detect_cla(clone_dir, client=mock_client, owner="org", repo="repo")
        assert result.required is False

    def test_no_client_skips_api_check(self, clone_dir):
        result = detect_cla(clone_dir)
        assert result.required is False


class TestClaContributingMdDetection:
    def test_apache_icla_detected(self, clone_dir):
        (clone_dir / "CONTRIBUTING.md").write_text(
            "Before contributing, you must sign the Apache ICLA at https://www.apache.org/licenses/"
        )
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "apache"
        assert result.detection_source == "contributing-md"
        assert "apache.org" in result.signing_url

    def test_google_cla_in_contributing(self, clone_dir):
        (clone_dir / "CONTRIBUTING.md").write_text(
            "Sign the Google CLA at https://cla.developers.google.com/ before sending PRs."
        )
        result = detect_cla(clone_dir)
        assert result.required is True
        assert result.system == "google"
        assert "google.com" in result.signing_url

    def test_no_cla_mention(self, clone_dir):
        (clone_dir / "CONTRIBUTING.md").write_text("# Contributing\n\nJust send a PR!")
        result = detect_cla(clone_dir)
        assert result.required is False


class TestClaGuardrail:
    def test_cla_not_required(self):
        from give_back.guardrails import check_cla_signed

        result = check_cla_signed(CLAInfo(required=False))
        assert result.passed is True

    def test_cla_required_blocks(self):
        from give_back.guardrails import check_cla_signed

        info = CLAInfo(required=True, system="cla-assistant", signing_url="https://cla-assistant.io/o/r")
        result = check_cla_signed(info)
        assert result.passed is False
        assert result.severity.value == "block"
        assert "cla-assistant.io/o/r" in result.message
        assert "check --ack cla" in result.message

    def test_cla_acknowledged_passes(self):
        from give_back.guardrails import check_cla_signed

        info = CLAInfo(required=True, system="cla-assistant", signing_url="https://example.com")
        result = check_cla_signed(info, acknowledged=True)
        assert result.passed is True

    def test_unknown_system_no_url_still_blocks(self):
        from give_back.guardrails import check_cla_signed

        info = CLAInfo(required=True, system="unknown")
        result = check_cla_signed(info)
        assert result.passed is False
        assert "CONTRIBUTING.md" in result.message
