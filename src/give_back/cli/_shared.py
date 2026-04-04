"""Shared helpers for CLI command modules."""

from __future__ import annotations

import re

import click

# Matches owner/repo or https://github.com/owner/repo (with optional trailing slash/path)
_GITHUB_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$")
_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


def _parse_repo(repo: str) -> tuple[str, str]:
    """Parse a repo argument into (owner, repo) tuple.

    Accepts 'owner/repo' or 'https://github.com/owner/repo'.
    """
    # Try URL first
    m = _GITHUB_URL_RE.match(repo)
    if m:
        return m.group(1), m.group(2)

    # Try slug
    if _SLUG_RE.match(repo):
        owner, name = repo.split("/", 1)
        return owner, name

    raise click.BadParameter(
        f"Invalid repository: '{repo}'. Use 'owner/repo' or a GitHub URL.",
        param_hint="'REPO'",
    )
