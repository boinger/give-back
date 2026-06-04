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


class TestContributingWizardPreview:
    """Characterization tests for the preview branches.

    Pinned before extracting the per-section preview into a helper — see
    plans/PLAN-sloppylint-cleanup.md (these branches were previously uncovered).
    """

    def test_per_section_preview_then_yes(self):
        """'p' on a section previews it and re-prompts; 'y' then includes it."""
        prompts = [
            "s",  # Include sections? → some
            "p",  # Getting Started → preview (loops back)
            "y",  # Getting Started → include
            "n",  # Running Tests
            "n",  # Submitting Changes
            "n",  # Code Style
            "n",  # Reporting Issues
            "n",  # Code of Conduct
        ]
        with (
            patch("give_back.audit_fix.contributing.click.prompt", side_effect=prompts),
            patch("give_back.audit_fix.contributing.click.echo") as mock_echo,
        ):
            result = run_wizard()

        assert result is not None
        assert "## Getting Started" in result
        assert "## Running Tests" not in result
        preview_lines = [str(c.args[0]) for c in mock_echo.call_args_list if c.args]
        assert any("── Getting Started ──" in line for line in preview_lines)

    def test_top_level_preview_then_none(self):
        """Top-level 'p' shows all sections, then 'n' declines."""
        with (
            patch("give_back.audit_fix.contributing.click.prompt", side_effect=["p", "n"]),
            patch("give_back.audit_fix.contributing.click.echo"),
        ):
            result = run_wizard()
        assert result is None

    def test_some_with_all_declined_returns_none(self):
        """'s' then 'n' for every section yields no content."""
        with (
            patch("give_back.audit_fix.contributing.click.prompt", side_effect=["s", "n", "n", "n", "n", "n", "n"]),
            patch("give_back.audit_fix.contributing.click.echo") as mock_echo,
        ):
            result = run_wizard()

        assert result is None
        messages = [str(c.args[0]) for c in mock_echo.call_args_list if c.args]
        assert any("No sections selected" in m for m in messages)
