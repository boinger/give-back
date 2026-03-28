"""Tests for brief_writer: .give-back/brief.md, context.json, and git exclude."""

from __future__ import annotations

import json
from pathlib import Path

from give_back.conventions.models import (
    CITestInfo,
    CommitFormat,
    ContributionBrief,
    PrTemplate,
    StyleInfo,
)
from give_back.prepare.brief_writer import write_brief


def _make_brief(**overrides) -> ContributionBrief:
    """Build a minimal ContributionBrief with sensible defaults."""
    defaults = {
        "owner": "pallets",
        "repo": "flask",
        "issue_number": 5432,
        "issue_title": "Typo in quickstart docs",
        "commit_format": CommitFormat(
            style="conventional",
            examples=["fix: correct typo in docs", "feat: add new endpoint", "chore: update deps"],
        ),
        "merge_strategy": "squash",
        "test_info": CITestInfo(framework="pytest", run_command="pytest"),
        "style_info": StyleInfo(linter="ruff", config_file="pyproject.toml"),
        "default_branch": "main",
        "dco_required": False,
    }
    defaults.update(overrides)
    return ContributionBrief(**defaults)


def _setup_git_dir(tmp_path: Path) -> Path:
    """Create a minimal .git/info/ structure in tmp_path."""
    git_info = tmp_path / ".git" / "info"
    git_info.mkdir(parents=True)
    return tmp_path


def test_writes_brief_md(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief()

    result = write_brief(
        workspace, brief, issue_number=5432, branch_name="fix/5432-typo-quickstart", upstream_owner="pallets"
    )

    assert result == workspace / ".give-back" / "brief.md"
    assert result.exists()

    content = result.read_text()
    assert "# Contribution Brief" in content
    assert "pallets/flask" in content
    assert "#5432" in content
    assert "Typo in quickstart docs" in content
    assert "fix/5432-typo-quickstart" in content
    assert "conventional" in content
    assert "squash" in content
    assert "pytest" in content
    assert "ruff" in content
    assert "Not required" in content


def test_writes_context_json(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief()

    write_brief(workspace, brief, issue_number=5432, branch_name="fix/5432-typo-quickstart", upstream_owner="pallets")

    context_path = workspace / ".give-back" / "context.json"
    assert context_path.exists()

    ctx = json.loads(context_path.read_text())
    assert ctx["upstream_owner"] == "pallets"
    assert ctx["repo"] == "flask"
    assert ctx["issue_number"] == 5432
    assert ctx["branch_name"] == "fix/5432-typo-quickstart"
    assert ctx["default_branch"] == "main"
    assert ctx["dco_required"] is False
    assert ctx["test_command"] == "pytest"
    assert ctx["has_pr_template"] is False
    assert isinstance(ctx["ci_commands"], list)
    assert "pytest" in ctx["ci_commands"]


def test_adds_to_exclude(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief()

    write_brief(workspace, brief, issue_number=5432, branch_name="fix/5432-typo", upstream_owner="pallets")

    exclude_path = workspace / ".git" / "info" / "exclude"
    assert exclude_path.exists()
    lines = exclude_path.read_text().splitlines()
    assert ".give-back/" in lines


def test_exclude_not_duplicated(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief()

    write_brief(workspace, brief, issue_number=5432, branch_name="fix/5432-typo", upstream_owner="pallets")
    write_brief(workspace, brief, issue_number=5432, branch_name="fix/5432-typo", upstream_owner="pallets")

    exclude_path = workspace / ".git" / "info" / "exclude"
    lines = exclude_path.read_text().splitlines()
    assert lines.count(".give-back/") == 1


def test_creates_info_dir(tmp_path: Path) -> None:
    """If .git/info/ doesn't exist, write_brief creates it."""
    # Only create .git/, not .git/info/
    (tmp_path / ".git").mkdir()
    brief = _make_brief()

    write_brief(workspace_dir=tmp_path, brief=brief, issue_number=1, branch_name="fix/1-test", upstream_owner="owner")

    assert (tmp_path / ".git" / "info" / "exclude").exists()


def test_no_pr_template(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief(pr_template=None)

    result = write_brief(workspace, brief, issue_number=1, branch_name="fix/1-test", upstream_owner="pallets")

    content = result.read_text()
    assert "No PR template found." in content


def test_dco_required(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief(dco_required=True)

    result = write_brief(workspace, brief, issue_number=1, branch_name="fix/1-test", upstream_owner="pallets")

    content = result.read_text()
    assert "Required (use `git commit -s`)" in content
    assert "DCO sign-off included" in content


def test_pr_template_present(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    template = PrTemplate(
        path=".github/PULL_REQUEST_TEMPLATE.md",
        sections=["Description", "Testing"],
        raw_content="## Description\n\n## Testing\n",
    )
    brief = _make_brief(pr_template=template)

    result = write_brief(workspace, brief, issue_number=1, branch_name="fix/1-test", upstream_owner="pallets")

    content = result.read_text()
    assert "## Description" in content
    assert "PR template sections filled out" in content
    ctx = json.loads((workspace / ".give-back" / "context.json").read_text())
    assert ctx["has_pr_template"] is True


def test_no_issue_number(tmp_path: Path) -> None:
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief(issue_number=None, issue_title=None)

    result = write_brief(workspace, brief, issue_number=None, branch_name="fix/general", upstream_owner="pallets")

    content = result.read_text()
    assert "No specific issue" in content
    ctx = json.loads((workspace / ".give-back" / "context.json").read_text())
    assert ctx["issue_number"] is None


def test_context_has_lifecycle_fields(tmp_path: Path) -> None:
    """New lifecycle fields appear in context.json."""
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief()

    write_brief(
        workspace, brief, issue_number=1, branch_name="fix/1-test", upstream_owner="pallets",
        fork_owner="myuser", previous_issues=[{"issue_number": 99, "status": "merged"}],
    )

    ctx = json.loads((workspace / ".give-back" / "context.json").read_text())
    assert ctx["status"] == "working"
    assert ctx["fork_owner"] == "myuser"
    assert ctx["pr_url"] is None
    assert ctx["pr_number"] is None
    assert "created_at" in ctx
    assert "updated_at" in ctx
    assert ctx["previous_issues"] == [{"issue_number": 99, "status": "merged"}]


def test_context_defaults_without_lifecycle_params(tmp_path: Path) -> None:
    """Omitting fork_owner and previous_issues produces safe defaults."""
    workspace = _setup_git_dir(tmp_path)
    brief = _make_brief()

    write_brief(workspace, brief, issue_number=1, branch_name="fix/1-test", upstream_owner="pallets")

    ctx = json.loads((workspace / ".give-back" / "context.json").read_text())
    assert ctx["status"] == "working"
    assert ctx["fork_owner"] is None
    assert ctx["previous_issues"] == []
