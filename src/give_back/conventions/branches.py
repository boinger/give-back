"""Analyze branch naming conventions from recent merged PRs."""

from __future__ import annotations

import re

import httpx

from give_back.conventions.models import BranchConvention
from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient

# Branch names that indicate a fork's default branch (not a feature branch).
_DEFAULT_BRANCH_NAMES = frozenset({"main", "master", "develop", "dev"})

# Matches "type/description" format: fix/broken-login, feature/add-auth, docs/update-readme
_TYPE_SLASH_RE = re.compile(
    r"^(feat|feature|fix|bugfix|hotfix|docs|doc|chore|refactor|test|tests|ci|build|perf|style|release|dependabot)/"
)

# Matches issue-linked branches: 42-fix-login, issue-42, gh-42, GH-42-desc
_ISSUE_RE = re.compile(r"(^|\b)(issue|gh|#)?-?(\d{2,})", re.IGNORECASE)


def _classify_branch(name: str) -> str:
    """Classify a single branch name as 'type/description', 'issue-description', or 'other'."""
    if _TYPE_SLASH_RE.match(name):
        return "type/description"
    if _ISSUE_RE.search(name):
        return "issue-description"
    return "other"


def analyze_branch_names(client: GitHubClient, owner: str, repo: str) -> BranchConvention:
    """Analyze branch naming patterns from recent merged PRs.

    Fetches up to 20 recently-updated closed PRs via REST, filters to merged
    ones, and classifies their source branch names.
    """
    try:
        response = client.rest_get(
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": "20",
            },
        )
    except (GiveBackError, httpx.HTTPError, OSError):
        return BranchConvention(pattern="unknown")

    # rest_get returns parsed JSON; for this endpoint it's a list.
    prs: list[dict] = response if isinstance(response, list) else []

    # Filter to merged PRs and extract branch names, skipping fork default branches.
    branch_names: list[str] = []
    for pr in prs:
        if not pr.get("merged_at"):
            continue
        head = pr.get("head", {})
        ref = head.get("ref", "")
        if ref and ref not in _DEFAULT_BRANCH_NAMES:
            branch_names.append(ref)

    if len(branch_names) < 3:
        return BranchConvention(
            pattern="unknown",
            examples=branch_names[:5],
        )

    # Classify each branch name.
    counts: dict[str, int] = {"type/description": 0, "issue-description": 0, "other": 0}
    for name in branch_names:
        counts[_classify_branch(name)] += 1

    total = len(branch_names)
    majority = total * 0.5

    if counts["type/description"] >= majority:
        pattern = "type/description"
    elif counts["issue-description"] >= majority:
        pattern = "issue-description"
    else:
        pattern = "mixed"

    return BranchConvention(
        pattern=pattern,
        examples=branch_names[:5],
    )
