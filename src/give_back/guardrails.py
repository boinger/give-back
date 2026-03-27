"""Pre-flight guardrails for upstream contributions.

These checks prevent objectively embarrassing PR submissions — the kind
of mistakes that get PRs rejected or ignored regardless of who submits them.

Each check returns a GuardrailResult. Phase 4 (fork/fix/PR) runs these
before commit, before push, and before PR creation.

NOT included: personal preferences (AI attribution, commit message style).
Those belong to the convention scan (Phase 3), not hard-coded guardrails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient


class Severity(Enum):
    BLOCK = "block"  # Must fix before proceeding
    WARN = "warn"  # Should fix, but user can override
    INFO = "info"  # FYI only


@dataclass
class GuardrailResult:
    name: str
    severity: Severity
    passed: bool
    message: str
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pre-commit checks
# ---------------------------------------------------------------------------


def check_staged_files_clean(staged_files: list[str]) -> GuardrailResult:
    """Check that no .claude/, CLAUDE.md, or other give-back artifacts are staged.

    This isn't about AI attribution preferences — it's about not leaking
    your local tooling config into someone else's repo.
    """
    bad_patterns = [
        ".claude/",
        "CLAUDE.md",
        ".give-back/",
        "GEMINI.md",
        ".agents/",
    ]
    leaked = [f for f in staged_files if any(p in f for p in bad_patterns)]

    if leaked:
        return GuardrailResult(
            name="tooling_artifacts",
            severity=Severity.BLOCK,
            passed=False,
            message=f"Staged files contain local tooling artifacts: {', '.join(leaked)}. "
            "These should not be committed to upstream repos.",
            details={"leaked_files": leaked},
        )

    return GuardrailResult(
        name="tooling_artifacts",
        severity=Severity.BLOCK,
        passed=True,
        message="No tooling artifacts in staged files.",
    )


def check_dco_signoff(
    commit_message: str,
    dco_required: bool,
    author_name: str | None = None,
    author_email: str | None = None,
) -> GuardrailResult:
    """Check for DCO sign-off when the project requires it.

    Many projects enforce DCO via a CI check (probot/dco). Forgetting it
    wastes a round-trip to CI failure.
    """
    if not dco_required:
        return GuardrailResult(
            name="dco_signoff",
            severity=Severity.INFO,
            passed=True,
            message="Project does not require DCO sign-off.",
        )

    has_signoff = bool(re.search(r"^Signed-off-by:\s+.+\s+<.+>", commit_message, re.MULTILINE))

    if has_signoff:
        return GuardrailResult(
            name="dco_signoff",
            severity=Severity.BLOCK,
            passed=True,
            message="DCO sign-off present.",
        )

    fix_hint = "Add: Signed-off-by: Name <email>"
    if author_name and author_email:
        fix_hint = f"Add: Signed-off-by: {author_name} <{author_email}>"

    return GuardrailResult(
        name="dco_signoff",
        severity=Severity.BLOCK,
        passed=False,
        message=f"This project requires DCO sign-off but none found in commit message. {fix_hint}",
    )


def check_unrelated_changes(staged_files: list[str], expected_paths: list[str] | None = None) -> GuardrailResult:
    """Warn if staged files include paths obviously unrelated to the fix.

    If expected_paths is provided (from the issue/convention scan), check
    that staged files are in the same directories. Otherwise, just flag
    if the diff touches many unrelated directories.
    """
    if not staged_files:
        return GuardrailResult(
            name="unrelated_changes",
            severity=Severity.WARN,
            passed=True,
            message="No staged files to check.",
        )

    if expected_paths:
        expected_dirs = {_parent_dir(p) for p in expected_paths}
        staged_dirs = {_parent_dir(f) for f in staged_files}
        unexpected_dirs = staged_dirs - expected_dirs

        if unexpected_dirs and len(unexpected_dirs) > len(expected_dirs):
            return GuardrailResult(
                name="unrelated_changes",
                severity=Severity.WARN,
                passed=False,
                message=f"Staged files touch {len(unexpected_dirs)} directories outside the expected scope. "
                "Upstream maintainers prefer focused PRs — one concern per PR.",
                details={"unexpected_dirs": sorted(unexpected_dirs), "expected_dirs": sorted(expected_dirs)},
            )

    # Heuristic: if >8 directories are touched, something is probably wrong
    dirs = {_parent_dir(f) for f in staged_files}
    if len(dirs) > 8:
        return GuardrailResult(
            name="unrelated_changes",
            severity=Severity.WARN,
            passed=False,
            message=f"Staged files touch {len(dirs)} different directories. "
            "This looks like a large change — most upstream projects prefer small, focused PRs.",
            details={"directories": sorted(dirs)},
        )

    return GuardrailResult(
        name="unrelated_changes",
        severity=Severity.WARN,
        passed=True,
        message="Staged changes look focused.",
    )


# ---------------------------------------------------------------------------
# Pre-push checks
# ---------------------------------------------------------------------------


def check_local_ci(
    ci_commands: list[str] | None,
    ci_results: list[tuple[str, int]] | None = None,
) -> GuardrailResult:
    """Verify that the project's CI was run locally and passed.

    ci_commands: list of CI commands discovered by convention scan
                 (e.g., ["make test", "make lint"])
    ci_results: list of (command, exit_code) pairs from actually running them.
                If None, it means CI wasn't run at all.
    """
    if not ci_commands:
        return GuardrailResult(
            name="local_ci",
            severity=Severity.INFO,
            passed=True,
            message="No CI commands detected for this project.",
        )

    if ci_results is None:
        return GuardrailResult(
            name="local_ci",
            severity=Severity.BLOCK,
            passed=False,
            message=f"Project CI was not run locally. Run: {', '.join(ci_commands)}. "
            "Don't let upstream CI be the first time your code is tested.",
            details={"ci_commands": ci_commands},
        )

    failures = [(cmd, code) for cmd, code in ci_results if code != 0]
    if failures:
        failed_cmds = [f"{cmd} (exit {code})" for cmd, code in failures]
        return GuardrailResult(
            name="local_ci",
            severity=Severity.BLOCK,
            passed=False,
            message=f"Local CI failed: {', '.join(failed_cmds)}. "
            "Fix these before pushing — upstream CI will reject this.",
            details={"failures": failures},
        )

    return GuardrailResult(
        name="local_ci",
        severity=Severity.BLOCK,
        passed=True,
        message=f"Local CI passed ({len(ci_results)} command(s)).",
    )


def check_base_branch_freshness(
    local_branch: str,
    base_branch: str,
    commits_behind: int,
) -> GuardrailResult:
    """Check if the working branch is significantly behind the base branch.

    A branch that's many commits behind risks merge conflicts, redundant
    changes, or breaking against new code.
    """
    if commits_behind == 0:
        return GuardrailResult(
            name="base_freshness",
            severity=Severity.WARN,
            passed=True,
            message=f"Branch '{local_branch}' is up to date with '{base_branch}'.",
        )

    if commits_behind <= 5:
        return GuardrailResult(
            name="base_freshness",
            severity=Severity.INFO,
            passed=True,
            message=f"Branch '{local_branch}' is {commits_behind} commit(s) behind '{base_branch}'. "
            "Consider rebasing before creating a PR.",
        )

    return GuardrailResult(
        name="base_freshness",
        severity=Severity.WARN,
        passed=False,
        message=f"Branch '{local_branch}' is {commits_behind} commits behind '{base_branch}'. "
        "Rebase before pushing — your PR may have conflicts or redundant changes.",
        details={"commits_behind": commits_behind},
    )


# ---------------------------------------------------------------------------
# Pre-PR checks
# ---------------------------------------------------------------------------


def check_duplicate_pr(
    client: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int | None = None,
    title_keywords: str | None = None,
) -> GuardrailResult:
    """Check for existing open PRs addressing the same issue.

    This is a final check right before PR creation — the triage phase
    checks earlier, but PRs can be opened in the time since triage ran.
    """
    if issue_number is None and title_keywords is None:
        return GuardrailResult(
            name="duplicate_pr",
            severity=Severity.WARN,
            passed=True,
            message="No issue number or keywords to check for duplicates.",
        )

    query_parts = [f"repo:{owner}/{repo}", "is:pr", "is:open"]
    if issue_number:
        query_parts.append(str(issue_number))
    if title_keywords:
        query_parts.append(title_keywords)

    try:
        results = client.search(" ".join(query_parts))
        items = results.get("items", [])
    except GiveBackError:
        return GuardrailResult(
            name="duplicate_pr",
            severity=Severity.WARN,
            passed=True,
            message="Could not search for duplicate PRs (API error). Proceeding.",
        )

    if not items:
        return GuardrailResult(
            name="duplicate_pr",
            severity=Severity.WARN,
            passed=True,
            message="No existing open PRs found for this issue.",
        )

    pr_links = [f"#{item['number']}: {item.get('title', '?')}" for item in items[:3]]
    return GuardrailResult(
        name="duplicate_pr",
        severity=Severity.BLOCK,
        passed=False,
        message=f"Found {len(items)} existing open PR(s) for this issue: {'; '.join(pr_links)}. "
        "Check if your work duplicates theirs before creating a new PR.",
        details={"existing_prs": [{"number": i["number"], "title": i.get("title")} for i in items[:5]]},
    )


def check_pr_targets_correct_branch(
    target_branch: str,
    expected_branch: str,
) -> GuardrailResult:
    """Verify the PR targets the correct base branch.

    Some projects use 'develop', 'release/X', or other branches as
    contribution targets instead of 'main'.
    """
    if target_branch == expected_branch:
        return GuardrailResult(
            name="pr_target_branch",
            severity=Severity.BLOCK,
            passed=True,
            message=f"PR correctly targets '{expected_branch}'.",
        )

    return GuardrailResult(
        name="pr_target_branch",
        severity=Severity.BLOCK,
        passed=False,
        message=f"PR targets '{target_branch}' but this project's contribution branch is '{expected_branch}'. "
        "PRs to the wrong branch will be closed.",
        details={"target": target_branch, "expected": expected_branch},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parent_dir(path: str) -> str:
    """Extract the parent directory from a file path."""
    parts = path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 else "."


def run_pre_commit_checks(
    staged_files: list[str],
    commit_message: str,
    dco_required: bool = False,
    author_name: str | None = None,
    author_email: str | None = None,
    expected_paths: list[str] | None = None,
) -> list[GuardrailResult]:
    """Run all pre-commit guardrail checks."""
    return [
        check_staged_files_clean(staged_files),
        check_dco_signoff(commit_message, dco_required, author_name, author_email),
        check_unrelated_changes(staged_files, expected_paths),
    ]


def run_pre_push_checks(
    local_branch: str,
    base_branch: str,
    commits_behind: int,
    ci_commands: list[str] | None = None,
    ci_results: list[tuple[str, int]] | None = None,
) -> list[GuardrailResult]:
    """Run all pre-push guardrail checks."""
    return [
        check_base_branch_freshness(local_branch, base_branch, commits_behind),
        check_local_ci(ci_commands, ci_results),
    ]


def run_pre_pr_checks(
    client: GitHubClient,
    owner: str,
    repo: str,
    target_branch: str,
    expected_branch: str,
    issue_number: int | None = None,
    title_keywords: str | None = None,
) -> list[GuardrailResult]:
    """Run all pre-PR guardrail checks."""
    return [
        check_duplicate_pr(client, owner, repo, issue_number, title_keywords),
        check_pr_targets_correct_branch(target_branch, expected_branch),
    ]
