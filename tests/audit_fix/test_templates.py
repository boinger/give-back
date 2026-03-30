"""Tests for audit_fix template content and write_if_missing."""

from __future__ import annotations

from unittest.mock import patch

from give_back.audit_fix.templates import (
    BUG_REPORT_YML,
    CODE_OF_CONDUCT,
    CONFIG_YML,
    FEATURE_REQUEST_YML,
    PR_TEMPLATE,
    SECURITY,
    write_if_missing,
)


class TestTemplateContent:
    def test_coc_has_contributor_covenant(self):
        assert "Contributor Covenant" in CODE_OF_CONDUCT

    def test_coc_has_owner_placeholder(self):
        assert "{owner}" in CODE_OF_CONDUCT

    def test_security_has_vulnerability_reporting(self):
        assert "vulnerability" in SECURITY.lower()

    def test_security_has_owner_placeholder(self):
        assert "{owner}" in SECURITY

    def test_pr_template_has_sections(self):
        assert "## Summary" in PR_TEMPLATE
        assert "## Test plan" in PR_TEMPLATE

    def test_bug_report_is_valid_yaml_structure(self):
        assert "name: Bug report" in BUG_REPORT_YML
        assert "type: textarea" in BUG_REPORT_YML

    def test_feature_request_is_valid_yaml_structure(self):
        assert "name: Feature request" in FEATURE_REQUEST_YML

    def test_config_enables_blank_issues(self):
        assert "blank_issues_enabled: true" in CONFIG_YML


class TestWriteIfMissing:
    def test_creates_file_when_missing(self, tmp_path):
        path = tmp_path / "test.md"
        with patch("give_back.audit_fix.templates.click.confirm", return_value=True):
            result = write_if_missing(path, "content", "test.md")
        assert result is True
        assert path.read_text() == "content"

    def test_skips_existing_file(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("existing")
        result = write_if_missing(path, "new content", "test.md")
        assert result is False
        assert path.read_text() == "existing"

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug.yml"
        with patch("give_back.audit_fix.templates.click.confirm", return_value=True):
            result = write_if_missing(path, "content", "bug.yml")
        assert result is True
        assert path.exists()

    def test_skips_when_user_declines(self, tmp_path):
        path = tmp_path / "test.md"
        with patch("give_back.audit_fix.templates.click.confirm", return_value=False):
            result = write_if_missing(path, "content", "test.md")
        assert result is False
        assert not path.exists()

    def test_race_guard_skips_if_created_after_confirm(self, tmp_path):
        path = tmp_path / "test.md"

        call_count = 0

        def confirm_and_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Simulate another process creating the file after confirm
            path.write_text("race winner")
            return True

        with patch("give_back.audit_fix.templates.click.confirm", side_effect=confirm_and_create):
            result = write_if_missing(path, "loser content", "test.md")
        assert result is False
        assert path.read_text() == "race winner"
