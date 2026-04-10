"""Write .give-back/brief.md and context.json to the workspace directory."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from give_back.conventions.models import ContributionBrief
from give_back.state import atomic_write_text


def write_brief(
    workspace_dir: Path,
    brief: ContributionBrief,
    issue_number: int | None,
    branch_name: str,
    upstream_owner: str,
    fork_owner: str | None = None,
    previous_issues: list[dict] | None = None,
) -> Path:
    """Write human-readable brief and machine-readable context to workspace.

    Creates .give-back/ directory with brief.md and context.json, and adds
    .give-back/ to .git/info/exclude so it never gets committed upstream.

    Returns the path to brief.md.
    """
    give_back_dir = workspace_dir / ".give-back"
    give_back_dir.mkdir(parents=True, exist_ok=True)

    brief_path = give_back_dir / "brief.md"
    atomic_write_text(brief_path, _render_brief_md(brief, issue_number, branch_name, upstream_owner))

    context_path = give_back_dir / "context.json"
    atomic_write_text(
        context_path,
        json.dumps(
            _build_context(brief, issue_number, branch_name, upstream_owner, fork_owner, previous_issues),
            indent=2,
        )
        + "\n",
    )

    _add_to_git_exclude(workspace_dir)

    return brief_path


def _render_brief_md(
    brief: ContributionBrief,
    issue_number: int | None,
    branch_name: str,
    upstream_owner: str,
) -> str:
    """Render the human-readable contribution brief as Markdown."""
    repo = brief.repo
    issue_title = brief.issue_title or ""

    # Target section
    if issue_number is not None:
        issue_line = f"- Issue: #{issue_number} — {issue_title}"
    else:
        issue_line = "- Issue: No specific issue"

    # Commit examples
    examples_lines = ""
    for ex in brief.commit_format.examples[:5]:
        examples_lines += f"    {ex}\n"

    # Test info
    test_framework = brief.test_info.framework or "Unknown"
    test_command = brief.test_info.run_command or "Unknown"
    tests_line = f"- Tests: {test_framework} (run: `{test_command}`)"

    # Linter info
    linter_name = brief.style_info.linter or "None detected"
    config_file = brief.style_info.config_file or "N/A"
    linter_line = f"- Linter: {linter_name} (config: {config_file})"

    # DCO
    if brief.dco_required:
        dco_line = "- DCO sign-off: Required (use `git commit -s`)"
    else:
        dco_line = "- DCO sign-off: Not required"

    # PR template
    if brief.pr_template:
        pr_template_section = brief.pr_template.raw_content
    else:
        pr_template_section = "No PR template found."

    # Pre-flight checklist
    checklist = _build_checklist(brief)

    # Reviewers
    if brief.review_info.typical_reviewers:
        reviewers = "\n".join(brief.review_info.typical_reviewers)
    else:
        reviewers = "No reviewer data available."

    # Notes
    if brief.notes:
        notes = "\n".join(brief.notes)
    else:
        notes = "No additional notes."

    return f"""# Contribution Brief

## Target
- Repository: {upstream_owner}/{repo}
{issue_line}
- Base branch: {brief.default_branch}
- Your branch: {branch_name}

## Conventions
- Commit format: {brief.commit_format.style}
  Examples:
{examples_lines}\
- Merge strategy: {brief.merge_strategy}
{tests_line}
{linter_line}
{dco_line}

## PR Template
{pr_template_section}

## Pre-flight Checklist
{checklist}

## Reviewers
{reviewers}

## Notes
{notes}
"""


def _build_checklist(brief: ContributionBrief) -> str:
    """Build the pre-flight checklist from guardrail checks."""
    lines: list[str] = []

    # Before committing
    lines.append("Before committing:")
    lines.append("  - [ ] No .claude/, CLAUDE.md, .give-back/, or .agents/ in staged files")
    lines.append("  - [ ] Changes address only the target issue — no drive-by fixes")
    if brief.dco_required:
        lines.append("  - [ ] DCO sign-off included")

    lines.append("")

    # Before pushing
    test_command = brief.test_info.run_command or "Unknown"
    lines.append("Before pushing:")
    lines.append(f"  - [ ] Tests pass locally: `{test_command}`")
    if brief.style_info.linter:
        lint_cmd = _build_lint_command(brief)
        lines.append(f"  - [ ] Linter passes: `{lint_cmd}`")
    lines.append(f"  - [ ] Branch is up to date with upstream/{brief.default_branch}")

    lines.append("")

    # Before creating PR
    lines.append("Before creating PR:")
    lines.append("  - [ ] No duplicate PRs for this issue")
    lines.append(f"  - [ ] PR targets {brief.owner}/{brief.repo}:{brief.default_branch}")
    if brief.pr_template:
        lines.append("  - [ ] PR template sections filled out")

    return "\n".join(lines)


def _build_lint_command(brief: ContributionBrief) -> str:
    """Build a lint command string from style info."""
    linter = brief.style_info.linter
    if not linter:
        return ""
    # Common patterns
    if linter.lower() == "ruff":
        config = brief.style_info.config_file
        if config:
            return f"ruff check --config {config} ."
        return "ruff check ."
    return linter


def _build_context(
    brief: ContributionBrief,
    issue_number: int | None,
    branch_name: str,
    upstream_owner: str,
    fork_owner: str | None = None,
    previous_issues: list[dict] | None = None,
) -> dict:
    """Build machine-readable context dict for the check command."""
    ci_commands: list[str] = []
    if brief.test_info.run_command:
        ci_commands.append(brief.test_info.run_command)

    lint_cmd = _build_lint_command(brief)
    if lint_cmd:
        ci_commands.append(lint_cmd)

    now = datetime.now(timezone.utc).isoformat()

    return {
        "upstream_owner": upstream_owner,
        "repo": brief.repo,
        "issue_number": issue_number,
        "branch_name": branch_name,
        "default_branch": brief.default_branch,
        "fork_owner": fork_owner,
        "dco_required": brief.dco_required,
        "cla_required": brief.cla_required,
        "cla_system": brief.cla_info.system if brief.cla_required else None,
        "cla_signing_url": brief.cla_info.signing_url if brief.cla_required else None,
        "test_command": brief.test_info.run_command,
        "lint_command": lint_cmd or None,
        "ci_commands": ci_commands,
        "has_pr_template": brief.pr_template is not None,
        "status": "working",
        "pr_url": None,
        "pr_number": None,
        "created_at": now,
        "updated_at": now,
        "previous_issues": previous_issues or [],
    }


def _add_to_git_exclude(workspace_dir: Path) -> None:
    """Add .give-back/ to .git/info/exclude if not already present."""
    info_dir = workspace_dir / ".git" / "info"
    info_dir.mkdir(parents=True, exist_ok=True)

    exclude_file = info_dir / "exclude"
    exclude_entry = ".give-back/"

    if exclude_file.exists():
        content = exclude_file.read_text()
        if exclude_entry in content.splitlines():
            return
        # Ensure we start on a new line
        if content and not content.endswith("\n"):
            content += "\n"
        content += exclude_entry + "\n"
        exclude_file.write_text(content)
    else:
        exclude_file.write_text(exclude_entry + "\n")
