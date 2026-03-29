"""Detect Contributor License Agreement (CLA) requirements.

Checks three signals:
1. CLA config files in the repo (.clabot, cla.json, .github/workflows/cla*.yml)
2. Known CLA services referenced in CI config (CLA Assistant, EasyCLA)
3. Recent PR comments from CLA bots (via GitHub API)
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient

_log = logging.getLogger(__name__)

# Known CLA bot logins
_CLA_BOT_LOGINS = frozenset(
    {
        "CLAassistant",
        "linux-foundation-easycla",
        "googlebot",
        "google-cla",
        "cla-checker",
        "CLAassistant[bot]",
        "easycla",
    }
)

# Strings in CI config that indicate CLA enforcement
_CLA_CI_PATTERNS = (
    "cla-assistant",
    "cla_assistant",
    "cla-bot",
    "clabot",
    "contributor-assistant",
    "easycla",
    "google-cla",
)


def _check_cla_files(clone_dir: Path) -> str | None:
    """Check for CLA config files in the repo. Returns the file found, or None."""
    candidates = [
        ".clabot",
        "cla.json",
        ".cla.json",
        "CLA.md",
    ]
    for name in candidates:
        if (clone_dir / name).is_file():
            return name
    return None


def _check_ci_for_cla(clone_dir: Path) -> str | None:
    """Check CI workflows for CLA-related references. Returns the pattern found, or None."""
    workflows_dir = clone_dir / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return None

    for workflow_file in workflows_dir.iterdir():
        if workflow_file.suffix not in (".yml", ".yaml") or not workflow_file.is_file():
            continue
        try:
            content = workflow_file.read_text(encoding="utf-8", errors="replace").lower()
            for pattern in _CLA_CI_PATTERNS:
                if pattern in content:
                    return f"{workflow_file.name}: {pattern}"
        except OSError:
            continue

    return None


def _check_pr_comments_for_cla(client: GitHubClient, owner: str, repo: str) -> str | None:
    """Check recent merged PR comments for CLA bot activity. Returns the bot login, or None."""
    try:
        prs = client.rest_get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": "5"},
        )
    except (GiveBackError, httpx.HTTPError, OSError):
        _log.debug("Failed to fetch PRs for CLA check")
        return None

    if not isinstance(prs, list):
        return None

    merged_prs = [pr for pr in prs if pr.get("merged_at")][:3]

    for pr in merged_prs:
        pr_number = pr.get("number")
        if not pr_number:
            continue
        try:
            comments = client.rest_get(f"/repos/{owner}/{repo}/issues/{pr_number}/comments")
            if not isinstance(comments, list):
                continue
            for comment in comments:
                login = (comment.get("user") or {}).get("login", "")
                if login.lower() in {b.lower() for b in _CLA_BOT_LOGINS}:
                    return login
        except (GiveBackError, httpx.HTTPError, OSError):
            _log.debug("Failed to fetch comments for PR #%s", pr_number)
            continue

    return None


def detect_cla(
    clone_dir: Path,
    client: GitHubClient | None = None,
    owner: str | None = None,
    repo: str | None = None,
) -> bool:
    """Detect whether a CLA appears to be required.

    Checks three signals:
    1. CLA config files in the repo (.clabot, cla.json, CLA.md).
    2. CI workflows referencing CLA services.
    3. Recent PR comments from known CLA bots (requires client + owner/repo).

    Returns True if any signal indicates CLA is required.
    """
    if _check_cla_files(clone_dir) is not None:
        return True

    if _check_ci_for_cla(clone_dir) is not None:
        return True

    if client is not None and owner is not None and repo is not None:
        if _check_pr_comments_for_cla(client, owner, repo) is not None:
            return True

    return False
