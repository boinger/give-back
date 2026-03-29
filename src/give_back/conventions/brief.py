"""Assemble a ContributionBrief by orchestrating all convention detectors."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone

import httpx

from give_back.conventions.branches import analyze_branch_names
from give_back.conventions.cla import detect_cla
from give_back.conventions.clone import cloned_repo
from give_back.conventions.commits import analyze_commits
from give_back.conventions.dco import detect_dco
from give_back.conventions.merge_strategy import detect_merge_strategy
from give_back.conventions.models import (
    CommitFormat,
    ContributionBrief,
    ReviewInfo,
)
from give_back.conventions.pr_template import find_pr_template
from give_back.conventions.style import detect_style
from give_back.conventions.testing import detect_testing
from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient

_log = logging.getLogger(__name__)


def _fetch_review_info(client: GitHubClient, owner: str, repo: str) -> ReviewInfo:
    """Fetch typical reviewers from recent merged PRs.

    Looks at the last 5 merged PRs and collects unique reviewer logins.
    """
    reviewers: set[str] = set()
    required_checks: list[str] = []

    try:
        prs = client.rest_get(
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": "10",
            },
        )

        if not isinstance(prs, list):
            return ReviewInfo()

        merged_prs = [pr for pr in prs if pr.get("merged_at")][:5]

        for pr in merged_prs:
            pr_number = pr.get("number")
            if not pr_number:
                continue
            try:
                reviews = client.rest_get(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews")
                if isinstance(reviews, list):
                    for review in reviews:
                        user = review.get("user", {})
                        login = user.get("login")
                        if login:
                            reviewers.add(login)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("Failed to fetch reviews for PR #%s", pr_number)
                continue

    except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
        _log.debug("Failed to fetch PRs for review info")

    return ReviewInfo(
        required_checks=required_checks,
        typical_reviewers=sorted(reviewers),
    )


def _generate_notes(brief: ContributionBrief) -> list[str]:
    """Generate advisory notes based on scan findings."""
    notes: list[str] = []

    if brief.cla_required:
        notes.append("CLA (Contributor License Agreement) required — sign before your PR can be reviewed")

    if brief.dco_required:
        notes.append("DCO sign-off required (use `git commit -s`)")

    if brief.merge_strategy == "squash":
        notes.append("Uses squash merge — commit history will be flattened")
    elif brief.merge_strategy == "rebase":
        notes.append("Uses rebase merge — keep commits clean and atomic")

    if brief.pr_template is not None:
        notes.append("PR template found — fill out all required sections")
        # Check if template has a checklist
        if brief.pr_template.raw_content and "- [" in brief.pr_template.raw_content:
            notes.append(
                "PR template has a checklist — remove items that don't apply "
                "(don't leave them unchecked unless the template says otherwise)"
            )

    if brief.commit_format.style == "conventional":
        prefix = brief.commit_format.prefix_pattern or "type:"
        notes.append(f"Conventional commits expected (e.g., {prefix})")

    if brief.test_info.framework:
        cmd = brief.test_info.run_command or brief.test_info.framework
        notes.append(f"Run tests locally before submitting: {cmd}")

    if brief.style_info.linter:
        notes.append(f"Linter: {brief.style_info.linter} — run before submitting")

    return notes


def scan_conventions(
    client: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int | None = None,
    keep_clone: bool = False,
    verbose: bool = False,
) -> ContributionBrief:
    """Scan a repository's conventions and assemble a ContributionBrief.

    Clones the repo to a temp directory, runs all file-based detectors,
    then makes API calls for branch naming and review info.

    Args:
        client: Authenticated GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        issue_number: Optional issue number to include in the brief.
        keep_clone: If True, keep the cloned repo after scanning.
        verbose: If True, log detection details.

    Returns:
        A populated ContributionBrief.
    """
    brief = ContributionBrief(
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        generated_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
    )

    # Fetch issue title if issue_number provided.
    if issue_number is not None:
        try:
            issue_data = client.rest_get(f"/repos/{owner}/{repo}/issues/{issue_number}")
            brief.issue_title = issue_data.get("title")
        except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
            _log.debug("Failed to fetch issue #%s", issue_number)

    # Clone-based detectors.
    try:
        with cloned_repo(owner, repo, keep=keep_clone, depth=50) as clone_dir:
            if verbose:
                _log.info("Cloned %s/%s to %s", owner, repo, clone_dir)

            # Commit format
            try:
                brief.commit_format = analyze_commits(clone_dir)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("Commit analysis failed")
                brief.commit_format = CommitFormat(style="unknown")

            # Merge strategy
            try:
                brief.merge_strategy = detect_merge_strategy(clone_dir)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("Merge strategy detection failed")

            # PR template
            try:
                brief.pr_template = find_pr_template(clone_dir)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("PR template detection failed")

            # DCO
            try:
                brief.dco_required = detect_dco(clone_dir)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("DCO detection failed")

            # CLA
            try:
                brief.cla_required = detect_cla(clone_dir, client=client, owner=owner, repo=repo)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("CLA detection failed")

            # Testing
            try:
                brief.test_info = detect_testing(clone_dir)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("Test detection failed")

            # Style
            try:
                brief.style_info = detect_style(clone_dir)
            except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                _log.debug("Style detection failed")

    except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
        _log.debug("Clone failed for %s/%s", owner, repo)

    # API-based detectors (outside clone context).

    # Branch convention
    try:
        brief.branch_convention = analyze_branch_names(client, owner, repo)
    except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
        _log.debug("Branch analysis failed")

    # Default branch from API
    try:
        repo_data = client.rest_get(f"/repos/{owner}/{repo}")
        brief.default_branch = repo_data.get("default_branch", "main")
    except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
        _log.debug("Failed to fetch default branch")

    # Review info (optional)
    try:
        brief.review_info = _fetch_review_info(client, owner, repo)
    except (GiveBackError, httpx.HTTPError, OSError, subprocess.SubprocessError):
        _log.debug("Review info fetch failed")

    # Generate notes based on findings.
    brief.notes = _generate_notes(brief)

    return brief
