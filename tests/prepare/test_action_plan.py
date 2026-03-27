"""Tests for action_plan: terminal-friendly workspace summary."""

from __future__ import annotations

from pathlib import Path

from give_back.conventions.models import (
    CommitFormat,
    ContributionBrief,
    TestInfo,
)
from give_back.prepare.action_plan import generate_action_plan


def _make_brief(**overrides) -> ContributionBrief:
    """Build a minimal ContributionBrief with sensible defaults."""
    defaults = {
        "owner": "pallets",
        "repo": "flask",
        "issue_number": 5432,
        "issue_title": "Typo in quickstart docs",
        "commit_format": CommitFormat(style="conventional", examples=[]),
        "merge_strategy": "squash",
        "test_info": TestInfo(framework="pytest", run_command="pytest"),
        "default_branch": "main",
    }
    defaults.update(overrides)
    return ContributionBrief(**defaults)


def test_basic_plan() -> None:
    brief = _make_brief()
    workspace = Path("/tmp/workspaces/pallets/flask")

    plan = generate_action_plan(brief, workspace, branch_name="fix/5432-typo-quickstart", upstream_owner="pallets")

    assert "pallets/flask" in plan
    assert str(workspace) in plan
    assert "fix/5432-typo-quickstart" in plan
    assert "#5432" in plan
    assert "Typo in quickstart docs" in plan
    assert "upstream/main" in plan
    assert "give-back check" in plan
    assert ".give-back/brief.md" in plan


def test_no_issue() -> None:
    brief = _make_brief(issue_number=None, issue_title=None)
    workspace = Path("/tmp/workspaces/pallets/flask")

    plan = generate_action_plan(brief, workspace, branch_name="fix/general", upstream_owner="pallets")

    assert "No specific issue" in plan


def test_conventions_shown() -> None:
    brief = _make_brief(
        commit_format=CommitFormat(style="imperative", examples=[]),
        merge_strategy="rebase",
    )
    workspace = Path("/tmp/workspaces/pallets/flask")

    plan = generate_action_plan(brief, workspace, branch_name="fix/5432-typo", upstream_owner="pallets")

    assert "imperative" in plan
    assert "rebase" in plan


def test_dco_shown() -> None:
    brief = _make_brief(dco_required=True)
    workspace = Path("/tmp/workspaces/pallets/flask")

    plan = generate_action_plan(brief, workspace, branch_name="fix/5432-typo", upstream_owner="pallets")

    assert "Required" in plan


def test_dco_not_required() -> None:
    brief = _make_brief(dco_required=False)
    workspace = Path("/tmp/workspaces/pallets/flask")

    plan = generate_action_plan(brief, workspace, branch_name="fix/5432-typo", upstream_owner="pallets")

    assert "Not required" in plan
