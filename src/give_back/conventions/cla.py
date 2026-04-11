"""Detect Contributor License Agreement (CLA) requirements.

Checks four signals:
1. CLA config files in the repo (.clabot, cla.json, .github/workflows/cla*.yml)
2. Known CLA services referenced in CI config (CLA Assistant, EasyCLA)
3. Recent PR comments from CLA bots (via GitHub API)
4. CONTRIBUTING.md mentions of CLA systems (Apache ICLA, Google CLA)

Returns a CLAInfo dataclass with the system type and signing URL when derivable.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from give_back.conventions._contributing import iter_contributing_md
from give_back.conventions.models import CLAInfo
from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient

_log = logging.getLogger(__name__)

# Known CLA bot logins → system mapping
_BOT_TO_SYSTEM: dict[str, str] = {
    "claassistant": "cla-assistant",
    "claassistant[bot]": "cla-assistant",
    "linux-foundation-easycla": "easycla",
    "easycla": "easycla",
    "googlebot": "google",
    "google-cla": "google",
    "cla-checker": "unknown",
}

# CI patterns → system mapping
_CI_PATTERN_TO_SYSTEM: dict[str, str] = {
    "cla-assistant": "cla-assistant",
    "cla_assistant": "cla-assistant",
    "cla-bot": "unknown",
    "clabot": "cla-assistant",
    "contributor-assistant": "cla-assistant",
    "easycla": "easycla",
    "google-cla": "google",
}

# URL templates by system
_SIGNING_URLS: dict[str, str] = {
    "cla-assistant": "https://cla-assistant.io/{owner}/{repo}",
    "easycla": "https://easycla.lfx.linuxfoundation.org/",
    "google": "https://cla.developers.google.com/",
    "apache": "https://www.apache.org/licenses/contributor-agreements.html",
}

# EasyCLA bots embed signing URLs in their comments
_EASYCLA_URL_RE = re.compile(r"https://\S*easycla\S*")

# Generic CLA signing URLs in CONTRIBUTING.md. "cla" must be the leading
# subdomain component — the common pattern (cla.strapi.io,
# cla.developers.google.com, cla.openjsf.org). The terminator char class
# includes whitespace, closing markdown delimiters, and backtick so inline
# code `https://cla.example.io/sign` doesn't capture the trailing backtick.
# re.IGNORECASE lets the "cla." prefix match `HTTPS://CLA.EXAMPLE.IO` too
# (host is case-insensitive per RFC 3986) while the original-case path is
# preserved via the match's captured text.
_CLA_URL_RE = re.compile(r"https://cla\.[^\s)\]\"'`>]+", re.IGNORECASE)


def _extract_cla_url(original_content: str) -> str | None:
    """Scan CONTRIBUTING.md content for a generic CLA signing URL.

    Takes ORIGINAL (non-lowercased) content because URL paths are
    case-sensitive per RFC 3986 — lowercasing would mangle mixed-case
    path segments. Returns the first match or None.
    """
    match = _CLA_URL_RE.search(original_content)
    return match.group(0) if match else None


def _derive_signing_url(system: str, owner: str | None = None, repo: str | None = None) -> str | None:
    """Derive the signing URL for a given CLA system."""
    template = _SIGNING_URLS.get(system)
    if template is None:
        return None
    if "{owner}" in template and owner and repo:
        return template.format(owner=owner, repo=repo)
    return template


def _check_cla_files(clone_dir: Path) -> str | None:
    """Check for CLA config files in the repo. Returns the file found, or None."""
    candidates = [".clabot", "cla.json", ".cla.json", "CLA.md"]
    for name in candidates:
        if (clone_dir / name).is_file():
            return name
    return None


def _check_ci_for_cla(clone_dir: Path) -> tuple[str, str] | None:
    """Check CI workflows for CLA-related references.

    Returns (matched_pattern, workflow_filename) or None.
    """
    workflows_dir = clone_dir / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return None

    for workflow_file in workflows_dir.iterdir():
        if workflow_file.suffix not in (".yml", ".yaml") or not workflow_file.is_file():
            continue
        try:
            content = workflow_file.read_text(encoding="utf-8", errors="replace").lower()
            for pattern in _CI_PATTERN_TO_SYSTEM:
                if pattern in content:
                    return (pattern, workflow_file.name)
        except OSError:
            continue

    return None


def _check_pr_comments_for_cla(client: GitHubClient, owner: str, repo: str) -> tuple[str, str | None] | None:
    """Check recent merged PR comments for CLA bot activity.

    Returns (bot_login, extracted_url_or_None) or None if no bot found.
    """
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
                if login.lower() in _BOT_TO_SYSTEM:
                    # Try to extract signing URL from EasyCLA bot comments
                    extracted_url = None
                    if "easycla" in login.lower():
                        body = comment.get("body", "")
                        match = _EASYCLA_URL_RE.search(body)
                        if match:
                            extracted_url = match.group(0)
                    return (login, extracted_url)
        except (GiveBackError, httpx.HTTPError, OSError):
            _log.debug("Failed to fetch comments for PR #%s", pr_number)
            continue

    return None


def _check_contributing_for_cla(clone_dir: Path) -> tuple[str, str, str | None] | None:
    """Search CONTRIBUTING.md variants for CLA requirements.

    Returns (system, detection_source, extracted_url) or None.

    extracted_url is always None for system-specific matches (apache,
    google, easycla, cla-assistant) — callers use _derive_signing_url
    for those. extracted_url may be populated for the generic fallback
    when a CLA signing URL appears directly in the CONTRIBUTING.md body.
    """
    for original in iter_contributing_md(clone_dir):
        content = original.lower()

        # System-specific matches take priority over the generic fallback.
        if "apache" in content and ("icla" in content or "apache.org/licenses" in content):
            return ("apache", "contributing-md", None)
        if "google" in content and ("cla.developers.google.com" in content or "google cla" in content):
            return ("google", "contributing-md", None)
        if "easycla" in content or "lfx.linuxfoundation" in content:
            return ("easycla", "contributing-md", None)
        if "cla-assistant" in content:
            return ("cla-assistant", "contributing-md", None)

        # Generic fallback: canonical phrase match + optional URL extraction.
        # URL extraction runs against ORIGINAL content to preserve path case.
        if "contributor license agreement" in content:
            extracted_url = _extract_cla_url(original)
            return ("unknown", "contributing-md", extracted_url)

    return None


def detect_cla(
    clone_dir: Path,
    client: GitHubClient | None = None,
    owner: str | None = None,
    repo: str | None = None,
) -> CLAInfo:
    """Detect whether a CLA appears to be required and identify the system.

    Checks four signals (in priority order):
    1. CLA config files in the repo (.clabot, cla.json, CLA.md).
    2. CI workflows referencing CLA services.
    3. CONTRIBUTING.md mentions of known CLA systems.
    4. Recent PR comments from known CLA bots (requires client + owner/repo).

    Returns a CLAInfo with system type and signing URL when derivable.
    """
    # Signal 1: Config files
    config_file = _check_cla_files(clone_dir)
    if config_file is not None:
        # .clabot and cla.json are CLA Assistant config
        system = "cla-assistant" if config_file in (".clabot", "cla.json", ".cla.json") else "unknown"
        return CLAInfo(
            required=True,
            system=system,
            signing_url=_derive_signing_url(system, owner, repo),
            detection_source="config-file",
        )

    # Signal 2: CI workflows
    ci_result = _check_ci_for_cla(clone_dir)
    if ci_result is not None:
        pattern, _filename = ci_result
        system = _CI_PATTERN_TO_SYSTEM.get(pattern, "unknown")
        return CLAInfo(
            required=True,
            system=system,
            signing_url=_derive_signing_url(system, owner, repo),
            detection_source="ci-workflow",
        )

    # Signal 3: CONTRIBUTING.md
    contrib_result = _check_contributing_for_cla(clone_dir)
    if contrib_result is not None:
        system, source, extracted_url = contrib_result
        signing_url = extracted_url or _derive_signing_url(system, owner, repo)
        return CLAInfo(
            required=True,
            system=system,
            signing_url=signing_url,
            detection_source=source,
        )

    # Signal 4: PR comments (requires API access)
    if client is not None and owner is not None and repo is not None:
        pr_result = _check_pr_comments_for_cla(client, owner, repo)
        if pr_result is not None:
            bot_login, extracted_url = pr_result
            system = _BOT_TO_SYSTEM.get(bot_login.lower(), "unknown")
            signing_url = extracted_url or _derive_signing_url(system, owner, repo)
            return CLAInfo(
                required=True,
                system=system,
                signing_url=signing_url,
                detection_source="pr-comment",
            )

    return CLAInfo()  # required=False, system="unknown"
