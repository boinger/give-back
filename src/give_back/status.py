"""Track the status of your open contributions across repos.

Scans the state file for repos you've prepared workspaces for,
checks GitHub for PR status (open, reviewed, merged, closed),
and reports a summary.
"""

from __future__ import annotations

from dataclasses import dataclass

from give_back.github_client import GitHubClient


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


def check_contributions(
    client: GitHubClient,
) -> list[ContributionStatus]:
    """Check the status of all tracked contributions.

    Reads workspace contexts from the state file and checks each
    repo for PR status and review state via the GitHub API.

    Returns a list of ContributionStatus, one per tracked workspace.
    """
    raise NotImplementedError("check_contributions is not yet implemented")
