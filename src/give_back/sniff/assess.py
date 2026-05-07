"""Heuristic code quality assessment for a single issue.

Fetches the issue, identifies referenced files, and scores each file on
size, test coverage, churn, and nesting depth. No LLM — pure heuristics.
"""

from __future__ import annotations

from typing import Any

from give_back.github_client import GitHubClient
from give_back.sniff.files import (
    check_test_file,
    fetch_file_content,
    get_recent_commits,
    identify_files,
)
from give_back.sniff.models import FileAssessment, SniffResult

# Thresholds
_LARGE_FILE_LINES = 500
_HUGE_FILE_LINES = 1000
_HIGH_CHURN_COMMITS = 10
_DEEP_NESTING_LEVELS = 6

# Extensions that use 2-space indent by convention
_TWO_SPACE_EXTENSIONS = frozenset({".js", ".ts", ".jsx", ".tsx", ".rb", ".yaml", ".yml"})


def _compute_max_indent_depth(content: str, file_path: str) -> int:
    """Compute the maximum indentation depth in a file.

    For tab-indented files, counts tabs.
    For space-indented files, divides by 4 (or 2 for .js/.ts/.rb).
    """
    if not content:
        return 0

    ext = ""
    dot_idx = file_path.rfind(".")
    if dot_idx >= 0:
        ext = file_path[dot_idx:].lower()

    divisor = 2 if ext in _TWO_SPACE_EXTENSIONS else 4
    max_depth = 0

    for line in content.splitlines():
        if not line or line.isspace():
            continue

        leading = len(line) - len(line.lstrip())
        if leading == 0:
            continue

        # Detect tabs vs spaces from the first indented character
        if line[0] == "\t":
            depth = leading  # Each tab = 1 level
        else:
            depth = leading // divisor

        if depth > max_depth:
            max_depth = depth

    return max_depth


def _assess_file(
    client: GitHubClient,
    owner: str,
    repo: str,
    path: str,
) -> FileAssessment:
    """Assess a single file for code quality concerns."""
    content, line_count = fetch_file_content(client, owner, repo, path)
    has_tests = check_test_file(client, owner, repo, path)
    recent_commits = get_recent_commits(client, owner, repo, path, limit=15)
    max_indent = _compute_max_indent_depth(content, path)

    concerns: list[str] = []
    if line_count > _LARGE_FILE_LINES:
        concerns.append(f"large file ({line_count} lines)")
    if not has_tests:
        concerns.append("no test file found")
    if recent_commits > _HIGH_CHURN_COMMITS:
        concerns.append(f"high churn ({recent_commits} commits recently)")
    if max_indent > _DEEP_NESTING_LEVELS:
        concerns.append(f"deep nesting ({max_indent} levels)")

    return FileAssessment(
        path=path,
        lines=line_count,
        recent_commits=recent_commits,
        has_tests=has_tests,
        max_indent_depth=max_indent,
        concerns=concerns,
    )


def _compute_verdict(files: list[FileAssessment]) -> str:
    """Determine overall verdict from file assessments.

    - LOOKS_GOOD: no files have >1 concern
    - MESSY: 1+ files have 2+ concerns
    - DUMPSTER_FIRE: majority of files have 3+ concerns OR any file has >1000 lines with no tests
    """
    if not files:
        return "LOOKS_GOOD"

    files_with_3plus = sum(1 for f in files if len(f.concerns) >= 3)
    files_with_2plus = sum(1 for f in files if len(f.concerns) >= 2)
    has_huge_untested = any(f.lines > _HUGE_FILE_LINES and not f.has_tests for f in files)

    if has_huge_untested or (files_with_3plus > len(files) / 2):
        return "DUMPSTER_FIRE"
    if files_with_2plus >= 1:
        return "MESSY"
    return "LOOKS_GOOD"


def _build_summary(verdict: str, files: list[FileAssessment]) -> str:
    """Build a human-readable summary from the verdict and file assessments."""
    if not files:
        return "No source files referenced in issue — manual inspection needed."

    total_concerns = sum(len(f.concerns) for f in files)

    if verdict == "LOOKS_GOOD":
        return f"Assessed {len(files)} file(s) — no major concerns found."
    elif verdict == "MESSY":
        return f"Assessed {len(files)} file(s) — {total_concerns} concern(s) found. Proceed with caution."
    else:
        return f"Assessed {len(files)} file(s) — {total_concerns} concern(s) found. Consider a different issue."


def assess_issue(
    client: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
) -> SniffResult:
    """Assess code quality for files referenced in a GitHub issue.

    1. Fetch the issue and its comments
    2. Identify file paths mentioned in the text
    3. Assess each file for size, tests, churn, and nesting
    4. Compute overall verdict
    """
    # Fetch issue details
    issue = client.rest_get(f"/repos/{owner}/{repo}/issues/{issue_number}")
    issue_title = issue.get("title", f"Issue #{issue_number}")
    issue_body = issue.get("body", "") or ""

    # Fetch comments. /issues/{N}/comments returns a JSON array, but rest_get
    # is typed as -> dict for the common case; narrow to list here.
    raw_comments = client.rest_get(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")
    comments_data: list[dict[str, Any]] = raw_comments if isinstance(raw_comments, list) else []

    # Identify referenced files
    file_paths = identify_files(issue_body, comments_data)

    if not file_paths:
        return SniffResult(
            issue_number=issue_number,
            issue_title=issue_title,
            files=[],
            verdict="LOOKS_GOOD",
            summary="No source files referenced in issue — manual inspection needed.",
        )

    # Assess each file
    file_assessments = [_assess_file(client, owner, repo, path) for path in file_paths]

    verdict = _compute_verdict(file_assessments)
    summary = _build_summary(verdict, file_assessments)

    return SniffResult(
        issue_number=issue_number,
        issue_title=issue_title,
        files=file_assessments,
        verdict=verdict,
        summary=summary,
    )
