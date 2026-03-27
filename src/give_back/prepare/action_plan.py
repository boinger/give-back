"""Generate terminal-friendly action plan summary."""

from __future__ import annotations

from pathlib import Path

from give_back.conventions.models import ContributionBrief


def generate_action_plan(
    brief: ContributionBrief,
    workspace_path: Path,
    branch_name: str,
    upstream_owner: str,
) -> str:
    """Return a multi-line string summarizing the workspace setup and next steps."""
    repo = brief.repo
    default_branch = brief.default_branch

    # Issue line
    if brief.issue_number is not None:
        issue_title = brief.issue_title or ""
        issue_line = f"#{brief.issue_number} — {issue_title}"
    else:
        issue_line = "No specific issue"

    # Conventions
    commit_style = brief.commit_format.style
    merge_strategy = brief.merge_strategy

    test_framework = brief.test_info.framework or "Unknown"
    test_command = brief.test_info.run_command or "Unknown"

    dco_status = "Required" if brief.dco_required else "Not required"

    brief_path = workspace_path / ".give-back" / "brief.md"

    return f"""Workspace ready for {upstream_owner}/{repo}

  Location:  {workspace_path}
  Branch:    {branch_name} (from upstream/{default_branch})
  Issue:     {issue_line}

  Conventions detected:
    Commit format: {commit_style}
    Merge strategy: {merge_strategy}
    Tests: {test_framework} — run: {test_command}
    DCO: {dco_status}

  Brief written to: {brief_path}

  Next steps:
    1. Write your fix
    2. Run tests: {test_command}
    3. Run `give-back check` to verify pre-flight checklist
    4. Commit, push, and create PR"""
