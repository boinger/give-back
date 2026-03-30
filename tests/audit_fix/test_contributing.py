"""Tests for audit_fix CONTRIBUTING.md wizard."""

from __future__ import annotations

from unittest.mock import patch

from give_back.audit_fix.contributing import run_wizard


class TestContributingWizard:
    def test_default_sections(self):
        with (
            patch("give_back.audit_fix.contributing.click.confirm", return_value=True),
            patch("give_back.audit_fix.contributing.click.prompt", return_value="1,2,3"),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()

        assert result is not None
        assert "## Getting Started" in result
        assert "## Running Tests" in result
        assert "## Submitting Changes" in result
        assert "## Code Style" not in result

    def test_all_sections(self):
        with (
            patch("give_back.audit_fix.contributing.click.confirm", return_value=True),
            patch("give_back.audit_fix.contributing.click.prompt", return_value="1,2,3,4,5,6"),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()

        assert result is not None
        assert "## Getting Started" in result
        assert "## Code Style" in result
        assert "## Reporting Issues" in result
        assert "## Code of Conduct" in result

    def test_skip(self):
        with (
            patch("give_back.audit_fix.contributing.click.confirm", return_value=False),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()
        assert result is None

    def test_each_section_has_todo(self):
        with (
            patch("give_back.audit_fix.contributing.click.confirm", return_value=True),
            patch("give_back.audit_fix.contributing.click.prompt", return_value="1,2,3,4,5,6"),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()

        assert result is not None
        # Count TODO markers — should match number of sections
        assert result.count("<!-- TODO:") == 6
