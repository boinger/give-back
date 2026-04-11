"""Tests for conventions/dco.py DCO sign-off detection."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from give_back.conventions.dco import detect_dco


def _mock_git_log(output: str, returncode: int = 0):
    """Create a mock for subprocess.run that returns the given git log output."""

    def side_effect(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, returncode=returncode, stdout=output, stderr="")
        return result

    return side_effect


def test_dco_in_commits(tmp_path: Path) -> None:
    """Commits with Signed-off-by lines → True."""
    git_output = (
        "Fix broken login\n\nSigned-off-by: Alice <alice@example.com>\n\n"
        "Add auth feature\n\nSigned-off-by: Bob <bob@example.com>\n\n"
        "Update docs\n\nSigned-off-by: Alice <alice@example.com>\n\n"
        "Refactor tests\n\nSigned-off-by: Bob <bob@example.com>\n\n"
        "Clean up CI\n\nSigned-off-by: Alice <alice@example.com>\n\n"
        "Bump deps\n\nSigned-off-by: Bob <bob@example.com>\n\n"
        "Fix typo\n\nSigned-off-by: Alice <alice@example.com>\n\n"
        "Add tests\n\nSigned-off-by: Bob <bob@example.com>\n\n"
        "Update README\n\nSigned-off-by: Alice <alice@example.com>\n\n"
        "Fix linting\n\nSigned-off-by: Bob <bob@example.com>\n\n"
    )

    with patch("give_back.conventions.dco.subprocess.run", side_effect=_mock_git_log(git_output)):
        result = detect_dco(tmp_path)

    assert result is True


def test_no_dco(tmp_path: Path) -> None:
    """Commits without sign-off → False."""
    git_output = "Fix broken login\n\nAdd auth feature\n\nUpdate docs\n\nRefactor tests\n\nClean up CI\n\n"

    with patch("give_back.conventions.dco.subprocess.run", side_effect=_mock_git_log(git_output)):
        result = detect_dco(tmp_path)

    assert result is False


def test_dco_in_ci(tmp_path: Path) -> None:
    """CI workflow that references probot/dco → True."""
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "dco.yml").write_text("name: DCO\non: [pull_request]\njobs:\n  dco:\n    uses: probot/dco\n")

    # No sign-off in commits, but CI config has probot/dco.
    git_output = "Fix stuff\n\nSome body\n\n"

    with patch("give_back.conventions.dco.subprocess.run", side_effect=_mock_git_log(git_output)):
        result = detect_dco(tmp_path)

    assert result is True


def test_dco_file(tmp_path: Path) -> None:
    """.dco file in repo root → True."""
    (tmp_path / ".dco").write_text("")

    git_output = "Fix stuff\n\n"

    with patch("give_back.conventions.dco.subprocess.run", side_effect=_mock_git_log(git_output)):
        result = detect_dco(tmp_path)

    assert result is True


def test_partial_signoff_below_threshold(tmp_path: Path) -> None:
    """Only 2 of 10 commits have sign-off → False (below 50% threshold)."""
    git_output = (
        "Fix login\n\nSigned-off-by: Alice <a@b.com>\n\n"
        "Add feature\n\nSigned-off-by: Bob <b@b.com>\n\n"
        "Commit 3\n\n"
        "Commit 4\n\n"
        "Commit 5\n\n"
        "Commit 6\n\n"
        "Commit 7\n\n"
        "Commit 8\n\n"
        "Commit 9\n\n"
        "Commit 10\n\n"
    )

    with patch("give_back.conventions.dco.subprocess.run", side_effect=_mock_git_log(git_output)):
        result = detect_dco(tmp_path)

    assert result is False


def test_git_failure_returns_false(tmp_path: Path) -> None:
    """Git command failure returns False gracefully."""
    with patch(
        "give_back.conventions.dco.subprocess.run",
        side_effect=_mock_git_log("", returncode=128),
    ):
        result = detect_dco(tmp_path)

    assert result is False


# ---------------------------------------------------------------------------
# CONTRIBUTING.md signal tests (added for grafana/tempo dogfood regression)
# ---------------------------------------------------------------------------


def _empty_git_log(tmp_path: Path):
    """Context manager equivalent: patch subprocess.run to return no commits."""
    return patch(
        "give_back.conventions.dco.subprocess.run",
        side_effect=_mock_git_log(""),
    )


def test_contributing_md_phrase_match(tmp_path: Path) -> None:
    """CONTRIBUTING.md with 'Developer Certificate of Origin' phrase → True."""
    (tmp_path / "CONTRIBUTING.md").write_text(
        "# Contributing\n\nAll contributions are subject to the Developer Certificate of Origin.\n"
    )

    with _empty_git_log(tmp_path):
        result = detect_dco(tmp_path)

    assert result is True


def test_contributing_md_grafana_tempo_pattern(tmp_path: Path) -> None:
    """Exact phrasing from grafana/tempo CONTRIBUTING.md → True."""
    (tmp_path / "CONTRIBUTING.md").write_text(
        "By submitting a PR you certify the Developer Certificate of Origin (DCO) "
        "— that you have the right to submit the code under this project's license."
    )

    with _empty_git_log(tmp_path):
        result = detect_dco(tmp_path)

    assert result is True


def test_contributing_md_required_signoff_phrasing(tmp_path: Path) -> None:
    """'Commits must include Signed-off-by' triggers the requirement regex → True."""
    (tmp_path / "CONTRIBUTING.md").write_text("Commits must include a Signed-off-by line.")

    with _empty_git_log(tmp_path):
        result = detect_dco(tmp_path)

    assert result is True


def test_contributing_md_example_only_signoff_ignored(tmp_path: Path) -> None:
    """Example-only Signed-off-by (no 'must'/'required' nearby) → False."""
    (tmp_path / "CONTRIBUTING.md").write_text(
        "Here is what a commit should look like:\n\n  Fix typo\n\n  Signed-off-by: Jane Doe <jane@example.com>\n"
    )

    with _empty_git_log(tmp_path):
        result = detect_dco(tmp_path)

    assert result is False


def test_contributing_md_no_dco_mention(tmp_path: Path) -> None:
    """CONTRIBUTING.md with no DCO/sign-off content → False."""
    (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n\nJust send a PR.\n")

    with _empty_git_log(tmp_path):
        result = detect_dco(tmp_path)

    assert result is False


def test_contributing_md_in_github_subdir(tmp_path: Path) -> None:
    """.github/CONTRIBUTING.md is searched → True when DCO phrase present."""
    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    (github_dir / "CONTRIBUTING.md").write_text("Developer Certificate of Origin is required.")

    with _empty_git_log(tmp_path):
        result = detect_dco(tmp_path)

    assert result is True


def test_contributing_md_in_docs_subdir(tmp_path: Path) -> None:
    """docs/CONTRIBUTING.md is searched → True when DCO phrase present."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "CONTRIBUTING.md").write_text("By submitting you certify the Developer Certificate of Origin.")

    with _empty_git_log(tmp_path):
        result = detect_dco(tmp_path)

    assert result is True
