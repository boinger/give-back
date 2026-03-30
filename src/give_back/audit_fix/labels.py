"""Label creation via GitHub REST API."""

from __future__ import annotations

import click

from give_back.exceptions import AuthenticationError, GiveBackError, RateLimitError
from give_back.github_client import GitHubClient

_LABEL_COLORS = {
    "good first issue": "7057ff",
    "help wanted": "008672",
}

_LABEL_DESCRIPTIONS = {
    "good first issue": "Good for newcomers",
    "help wanted": "Extra attention is needed",
}


def create_labels(client: GitHubClient, owner: str, repo: str, missing: list[str]) -> list[str]:
    """Create missing contribution-friendly labels via GitHub REST API.

    Returns the names of labels successfully created. Treats "already exists"
    as success. Handles auth/rate-limit errors gracefully.
    """
    if not missing:
        return []

    if not client.authenticated:
        click.echo("  [labels] Skipped — no auth token (labels require write access)")
        return []

    created: list[str] = []
    for name in missing:
        color = _LABEL_COLORS.get(name, "ededed")
        description = _LABEL_DESCRIPTIONS.get(name, "")

        try:
            result = client.rest_post(
                f"/repos/{owner}/{repo}/labels",
                json={"name": name, "color": color, "description": description},
            )
            # GitHub returns the created label object on success,
            # or a validation error dict on 422 (already exists).
            if isinstance(result, dict) and "name" in result:
                created.append(name)
            elif isinstance(result, dict) and result.get("message") == "Validation Failed":
                # Label already exists — treat as success
                created.append(name)
            else:
                click.echo(f"  [labels] Unexpected response creating '{name}': {str(result)[:100]}")
        except AuthenticationError:
            click.echo("  [labels] Skipped — authentication failed (need repo write access)")
            return created
        except RateLimitError:
            click.echo("  [labels] Skipped — rate limit exceeded")
            return created
        except GiveBackError as exc:
            click.echo(f"  [labels] Failed to create '{name}': {exc}")

    return created
