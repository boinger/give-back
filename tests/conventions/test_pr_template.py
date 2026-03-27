"""Tests for conventions/pr_template.py PR template detection."""

from pathlib import Path

from give_back.conventions.pr_template import find_pr_template


def test_github_template_found(tmp_path: Path) -> None:
    """Template in .github/ directory is found."""
    template_dir = tmp_path / ".github"
    template_dir.mkdir()
    template_file = template_dir / "PULL_REQUEST_TEMPLATE.md"
    template_file.write_text("## Description\n\nFill in.\n\n## Checklist\n- [ ] Tests\n")

    result = find_pr_template(tmp_path)

    assert result is not None
    assert result.path == ".github/PULL_REQUEST_TEMPLATE.md"
    assert "Description" in result.sections
    assert "Checklist" in result.sections
    assert result.raw_content.startswith("## Description")


def test_root_template_found(tmp_path: Path) -> None:
    """Template at the repo root is found."""
    template_file = tmp_path / "PULL_REQUEST_TEMPLATE.md"
    template_file.write_text("# PR Title\n\nDescribe your change.\n")

    result = find_pr_template(tmp_path)

    assert result is not None
    assert result.path == "PULL_REQUEST_TEMPLATE.md"
    assert "PR Title" in result.sections


def test_no_template(tmp_path: Path) -> None:
    """Empty directory returns None."""
    result = find_pr_template(tmp_path)
    assert result is None


def test_sections_extracted(tmp_path: Path) -> None:
    """Section headers (## lines) are extracted from the template."""
    template_dir = tmp_path / ".github"
    template_dir.mkdir()
    content = "## Summary\nWhat does this PR do?\n\n## Test Plan\nHow was this tested?\n\n## Related Issues\nCloses #\n"
    (template_dir / "PULL_REQUEST_TEMPLATE.md").write_text(content)

    result = find_pr_template(tmp_path)

    assert result is not None
    assert result.sections == ["Summary", "Test Plan", "Related Issues"]


def test_case_variations(tmp_path: Path) -> None:
    """Lowercase filename variant is found.

    On case-insensitive filesystems (macOS HFS+/APFS), both casing variants
    resolve to the same file, so we check the path case-insensitively.
    """
    template_dir = tmp_path / ".github"
    template_dir.mkdir()
    (template_dir / "pull_request_template.md").write_text("## Changes\n")

    result = find_pr_template(tmp_path)

    assert result is not None
    assert result.path.lower() == ".github/pull_request_template.md"
    assert "Changes" in result.sections


def test_priority_order(tmp_path: Path) -> None:
    """The .github/ uppercase variant wins over root-level."""
    # Create both .github and root templates
    template_dir = tmp_path / ".github"
    template_dir.mkdir()
    (template_dir / "PULL_REQUEST_TEMPLATE.md").write_text("## GitHub Template\n")
    (tmp_path / "PULL_REQUEST_TEMPLATE.md").write_text("## Root Template\n")

    result = find_pr_template(tmp_path)

    assert result is not None
    assert result.path == ".github/PULL_REQUEST_TEMPLATE.md"
    assert "GitHub Template" in result.sections


def test_template_directory(tmp_path: Path) -> None:
    """Template from .github/PULL_REQUEST_TEMPLATE/ directory is found."""
    template_dir = tmp_path / ".github" / "PULL_REQUEST_TEMPLATE"
    template_dir.mkdir(parents=True)
    (template_dir / "bug_report.md").write_text("## Bug Report\nDescribe the bug.\n")
    (template_dir / "feature.md").write_text("## Feature\nDescribe the feature.\n")

    result = find_pr_template(tmp_path)

    assert result is not None
    assert result.path.startswith(".github/PULL_REQUEST_TEMPLATE/")
    assert len(result.sections) > 0
