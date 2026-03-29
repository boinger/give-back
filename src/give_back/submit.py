"""Create a pull request from the current workspace using convention brief data.

Reads .give-back/context.json and brief.md to:
1. Determine the upstream repo, branch, and issue number
2. Apply conventions: commit format, DCO sign-off, PR template sections
3. Push the branch to the fork
4. Create the PR via gh CLI with the correct title, body, and labels

Requires gh CLI to be installed and authenticated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SubmitResult:
    """Result of a PR submission attempt."""

    pr_url: str | None = None
    pr_number: int | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.pr_url is not None


def submit_pr(
    workspace_dir: Path,
    *,
    title: str | None = None,
    draft: bool = False,
) -> SubmitResult:
    """Create a PR from the current workspace.

    Reads the .give-back/context.json for repo metadata and the
    contribution brief for conventions (DCO, commit format, PR template).

    If *title* is not provided, generates one from the issue title and
    branch name.

    Args:
        workspace_dir: Path to the workspace root (contains .give-back/).
        title: Optional PR title override.
        draft: If True, create as draft PR.

    Returns:
        SubmitResult with the PR URL on success, or error message on failure.
    """
    raise NotImplementedError("submit_pr is not yet implemented")
