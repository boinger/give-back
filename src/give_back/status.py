"""Track the status of your open contributions across repos.

Scans workspace directories for .give-back/context.json files,
checks GitHub for PR status (open, reviewed, merged, closed),
updates local context, and reports a summary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from give_back.console import stderr_console
from give_back.exceptions import GiveBackError, RepoNotFoundError
from give_back.github_client import GitHubClient
from give_back.prepare.lifecycle import (
    find_pr_for_branch,
    parse_fork_owner_from_remote,
    update_context_status,
)
from give_back.state import load_config


@dataclass
class ContributionStatus:
    """Status of a single contribution (one issue/PR in one repo)."""

    owner: str
    repo: str
    issue_number: int | None
    branch_name: str
    pr_url: str | None = None
    pr_number: int | None = None
    pr_state: str | None = None
    """One of: 'open', 'closed', 'merged', or None if no PR exists."""
    review_state: str | None = None
    """One of: 'approved', 'changes_requested', 'pending', or None."""
    workspace_path: str | None = None
    stale: bool = False
    """True if API refresh failed and we fell back to cached state."""
    local: bool = False
    """True if no client was available (unauthenticated mode)."""
    skip_reason: str | None = None
    """Shown instead of status when the contribution can't be checked."""


@dataclass
class ArchivedContribution:
    """A previously-active contribution that was archived during workspace reuse."""

    owner: str
    repo: str
    issue_number: int | None
    pr_url: str | None
    status: str
    archived_at: str


_PR_URL_RE = re.compile(r"https://github\.com/[^/]+/[^/]+/pull/(\d+)$")


def scan_workspaces(workspace_dir: Path) -> list[tuple[Path, dict]]:
    """Glob workspace_dir/*/*/.give-back/context.json and parse each.

    Returns a list of (workspace_path, context_dict) sorted by path.
    Skips corrupt JSON with a warning to stderr.
    """
    results: list[tuple[Path, dict]] = []
    if not workspace_dir.is_dir():
        return results

    for context_file in sorted(workspace_dir.glob("*/*/.give-back/context.json")):
        try:
            ctx = json.loads(context_file.read_text())
            # workspace_path is the repo clone dir (two levels up from context.json)
            workspace_path = context_file.parent.parent
            results.append((workspace_path, ctx))
        except json.JSONDecodeError:
            stderr_console.print(f"[yellow]Warning:[/yellow] Corrupt context.json at {context_file}, skipping.")
        except OSError as exc:
            stderr_console.print(f"[yellow]Warning:[/yellow] Cannot read {context_file}: {exc}")

    return results


def _extract_pr_number(pr_url: str) -> int | None:
    """Parse a PR number from a GitHub PR URL like https://github.com/owner/repo/pull/123."""
    if not pr_url:
        return None
    match = _PR_URL_RE.match(pr_url)
    if match:
        return int(match.group(1))
    return None


def _refresh_pr_state(client: GitHubClient, owner: str, repo: str, pr_number: int) -> tuple[str, str | None]:
    """Fetch current PR state and review state from the GitHub API.

    Returns (pr_state, review_state) where pr_state is one of 'open', 'closed', 'merged'.
    """
    pr_data = client.rest_get(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    # Determine PR state
    if pr_data.get("merged_at"):
        pr_state = "merged"
    elif pr_data.get("state") == "open":
        pr_state = "open"
    else:
        pr_state = "closed"

    # Fetch reviews
    reviews = client.rest_get(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews")
    review_state = _aggregate_review_state(reviews if isinstance(reviews, list) else [])

    return pr_state, review_state


def _aggregate_review_state(reviews: list[dict]) -> str | None:
    """Aggregate review verdicts: track latest state per reviewer.

    Only APPROVED and CHANGES_REQUESTED count. DISMISSED and COMMENTED are ignored.
    Returns 'changes_requested', 'approved', 'pending', or None (no actionable reviews).
    """
    latest_per_reviewer: dict[str, str] = {}
    for review in reviews:
        user = review.get("user")
        if not user:
            continue
        login = user.get("login", "")
        state = review.get("state", "")
        if state in ("APPROVED", "CHANGES_REQUESTED"):
            latest_per_reviewer[login] = state

    if not latest_per_reviewer:
        return None

    if any(s == "CHANGES_REQUESTED" for s in latest_per_reviewer.values()):
        return "changes_requested"
    if any(s == "APPROVED" for s in latest_per_reviewer.values()):
        return "approved"
    return "pending"


# Status mapping from context.json status to display status
_STATUS_MAP = {
    "working": "working",
    "pr_open": "open",
    "merged": "merged",
    "closed": "closed",
    "abandoned": "closed",
}


@dataclass
class _RefreshResult:
    """Intermediate result from refreshing one workspace's PR state."""

    pr_state: str | None = None
    review_state: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    stale: bool = False
    local: bool = False
    skip_reason: str | None = None


def _refresh_workspace_pr_state(
    client: GitHubClient | None,
    path: Path,
    *,
    owner: str,
    repo: str,
    branch_name: str,
    local_status: str,
    pr_url: str | None,
    pr_number: int | None,
    fork_owner_hint: str | None,
) -> _RefreshResult:
    """Determine current PR state for one workspace.

    May update context.json as a side effect when the PR state changes
    or a new PR is discovered for the branch.
    """
    result = _RefreshResult(pr_url=pr_url, pr_number=pr_number)

    if client is None:
        result.local = True
        result.pr_state = _STATUS_MAP.get(local_status)
        return result

    if not client.has_rate_budget(2):
        result.stale = True
        result.pr_state = _STATUS_MAP.get(local_status)
        return result

    if pr_number:
        try:
            pr_state, review_state = _refresh_pr_state(client, owner, repo, pr_number)
        except RepoNotFoundError:
            result.skip_reason = "PR or repo deleted"
            result.pr_state = _STATUS_MAP.get(local_status)
            return result
        except (GiveBackError, httpx.HTTPError):
            result.stale = True
            result.pr_state = _STATUS_MAP.get(local_status)
            return result
        result.pr_state = pr_state
        result.review_state = review_state
        new_ctx_status = _pr_state_to_context_status(pr_state)
        if new_ctx_status != local_status:
            update_context_status(path, new_ctx_status, pr_url=pr_url, pr_number=pr_number)
        return result

    if branch_name:
        fork_owner = fork_owner_hint or parse_fork_owner_from_remote(path)
        if not (fork_owner and owner and repo):
            result.pr_state = _STATUS_MAP.get(local_status)
            return result
        try:
            pr_info = find_pr_for_branch(client, owner, repo, fork_owner, branch_name)
        except (GiveBackError, httpx.HTTPError):
            result.stale = True
            result.pr_state = _STATUS_MAP.get(local_status)
            return result
        if pr_info is None:
            result.pr_state = _STATUS_MAP.get(local_status)
            return result
        result.pr_number = pr_info.pr_number
        result.pr_url = pr_info.pr_url
        result.pr_state = pr_info.state
        new_ctx_status = _pr_state_to_context_status(pr_info.state)
        update_context_status(path, new_ctx_status, pr_url=pr_info.pr_url, pr_number=pr_info.pr_number)
        return result

    result.pr_state = _STATUS_MAP.get(local_status)
    return result


def check_contributions(
    client: GitHubClient | None,
    workspace_dir: Path | None = None,
) -> tuple[list[ContributionStatus], list[ArchivedContribution]]:
    """Check the status of all tracked contributions.

    Scans workspace contexts, optionally refreshes PR state from the GitHub API,
    and returns current + archived contributions.

    When client is None, returns local state only (all contributions marked local=True).
    """
    if workspace_dir is None:
        config = load_config()
        workspace_dir = Path(config.workspace_dir).expanduser()
    else:
        workspace_dir = workspace_dir.expanduser()

    workspaces = scan_workspaces(workspace_dir)

    contributions: list[ContributionStatus] = []
    archived: list[ArchivedContribution] = []

    for path, ctx in workspaces:
        try:
            owner = ctx.get("upstream_owner", "")
            repo = ctx.get("repo", "")
            issue_number = ctx.get("issue_number")
            branch_name = ctx.get("branch_name", "")
            local_status = ctx.get("status", "working")
            pr_url = ctx.get("pr_url")
            pr_number = ctx.get("pr_number") or _extract_pr_number(pr_url or "")

            refresh = _refresh_workspace_pr_state(
                client,
                path,
                owner=owner,
                repo=repo,
                branch_name=branch_name,
                local_status=local_status,
                pr_url=pr_url,
                pr_number=pr_number,
                fork_owner_hint=ctx.get("fork_owner"),
            )

            contributions.append(
                ContributionStatus(
                    owner=owner,
                    repo=repo,
                    issue_number=issue_number,
                    branch_name=branch_name,
                    pr_url=refresh.pr_url,
                    pr_number=refresh.pr_number,
                    pr_state=refresh.pr_state,
                    review_state=refresh.review_state,
                    workspace_path=str(path),
                    stale=refresh.stale,
                    local=refresh.local,
                    skip_reason=refresh.skip_reason,
                )
            )

            for prev in ctx.get("previous_issues", []):
                archived.append(
                    ArchivedContribution(
                        owner=owner,
                        repo=repo,
                        issue_number=prev.get("issue_number"),
                        pr_url=prev.get("pr_url"),
                        status=prev.get("status", "unknown"),
                        archived_at=prev.get("archived_at", ""),
                    )
                )

        except (KeyError, TypeError, ValueError) as exc:
            stderr_console.print(f"[yellow]Warning:[/yellow] Error processing {path}: {exc}")
            continue

    return contributions, archived


def _pr_state_to_context_status(pr_state: str) -> str:
    """Map a PR state from the API to the context.json status field."""
    if pr_state == "open":
        return "pr_open"
    if pr_state == "merged":
        return "merged"
    if pr_state == "closed":
        return "closed"
    return "working"
