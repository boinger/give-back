"""Tests for audit_fix CONTRIBUTING.md wizard."""

from __future__ import annotations

from unittest.mock import patch

from give_back.audit_fix.contributing import run_wizard


class TestContributingWizard:
    def test_all_sections(self):
        with (
            patch("give_back.audit_fix.contributing.click.prompt", return_value="a"),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()

        assert result is not None
        assert "## Getting Started" in result
        assert "## Running Tests" in result
        assert "## Submitting Changes" in result
        assert "## Code Style" in result
        assert "## Reporting Issues" in result
        assert "## Code of Conduct" in result

    def test_some_sections(self):
        """User picks 'some' then y/n per section."""
        prompts = [
            "s",  # Include sections? → some
            "y",  # Getting Started
            "y",  # Running Tests
            "n",  # Submitting Changes
            "n",  # Code Style
            "n",  # Reporting Issues
            "n",  # Code of Conduct
        ]
        with (
            patch("give_back.audit_fix.contributing.click.prompt", side_effect=prompts),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()

        assert result is not None
        assert "## Getting Started" in result
        assert "## Running Tests" in result
        assert "## Code Style" not in result

    def test_none_skips(self):
        with (
            patch("give_back.audit_fix.contributing.click.prompt", return_value="n"),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()
        assert result is None

    def test_each_section_has_heading_and_content(self):
        with (
            patch("give_back.audit_fix.contributing.click.prompt", return_value="a"),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()

        assert result is not None
        assert result.count("## ") == 6
        assert "Fork the repository" in result
        assert "make test" in result or "Run the test suite" in result
