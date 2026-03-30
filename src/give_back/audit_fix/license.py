"""License quick-pick: fetch from GitHub Licenses API, fill placeholders."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import click

from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient

_LICENSE_OPTIONS = [
    ("1", "MIT", "mit"),
    ("2", "BSD 2-Clause", "bsd-2-clause"),
    ("3", "Apache 2.0", "apache-2.0"),
]

_CHOOSEALICENSE_PATTERN = re.compile(r"choosealicense\.com/licenses/([a-z0-9._-]+)")


def _extract_slug_from_url(url: str) -> str | None:
    """Extract the SPDX slug from a choosealicense.com URL."""
    m = _CHOOSEALICENSE_PATTERN.search(url.lower().rstrip("/"))
    return m.group(1) if m else None


def _fetch_license_text(client: GitHubClient, slug: str) -> str | None:
    """Fetch license body text from GitHub Licenses API. Returns None on failure."""
    try:
        data = client.rest_get(f"/licenses/{slug}")
        return data.get("body")
    except GiveBackError:
        return None


def _fill_placeholders(text: str, fullname: str) -> str:
    """Replace common license placeholders with actual values."""
    year = str(datetime.now(timezone.utc).year)
    result = text
    result = result.replace("[year]", year)
    result = result.replace("[yyyy]", year)
    result = result.replace("[fullname]", fullname)
    result = result.replace("[name of copyright owner]", fullname)
    result = result.replace("[owner]", fullname)
    return result


def pick_license(client: GitHubClient, fullname: str | None = None) -> tuple[str, str] | None:
    """Interactive license picker. Returns (content, fullname) or None if skipped."""
    click.echo()
    click.echo("  No LICENSE file found.")
    click.echo()
    click.echo("  Choose a license:")
    for num, label, _slug in _LICENSE_OPTIONS:
        click.echo(f"    {num}) {label}")
    click.echo("    4) Other — choose from https://choosealicense.com, paste the URL")
    click.echo("    5) Skip")
    click.echo()

    choice = click.prompt("  Choice", type=str, default="5").strip()

    slug: str | None = None
    if choice in ("1", "2", "3"):
        slug = _LICENSE_OPTIONS[int(choice) - 1][2]
    elif choice == "4":
        url = click.prompt("  Paste the choosealicense.com URL").strip()
        slug = _extract_slug_from_url(url)
        if not slug:
            click.echo("  Could not parse license from that URL. Visit https://choosealicense.com manually.")
            return None
    elif choice == "5":
        return None
    else:
        click.echo("  Invalid choice. Skipping license.")
        return None

    body = _fetch_license_text(client, slug)
    if not body:
        click.echo(f"  Could not fetch license '{slug}' from GitHub. Visit https://choosealicense.com manually.")
        return None

    if fullname is None:
        fullname = click.prompt("  Copyright holder name", type=str).strip()

    content = _fill_placeholders(body, fullname)
    return content, fullname
