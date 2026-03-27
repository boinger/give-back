"""Resolve package names to GitHub owner/repo slugs.

Supports:
- PyPI packages: looks up project_urls via PyPI JSON API for GitHub links
- Go modules: parses github.com paths directly, handles golang.org/x special case

No external dependencies beyond httpx (already in project deps).
"""

from __future__ import annotations

import re

import httpx

_PYPI_TIMEOUT = 10.0  # seconds

# Keys to check in PyPI project_urls, in priority order (case-insensitive)
_PYPI_URL_KEYS = ("source", "repository", "source code", "github", "homepage", "code")

_GITHUB_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/#?]+)")


def resolve_pypi(package_name: str) -> str | None:
    """Resolve a PyPI package name to a GitHub owner/repo slug.

    Calls the PyPI JSON API and inspects ``info.project_urls`` for GitHub URLs.
    Returns ``"owner/repo"`` or ``None`` if no GitHub URL is found.
    """
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = httpx.get(url, timeout=_PYPI_TIMEOUT, follow_redirects=True)
    except httpx.TimeoutException:
        return None
    except httpx.HTTPError:
        return None

    if response.status_code == 404:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    project_urls: dict[str, str] = data.get("info", {}).get("project_urls") or {}

    # Build a lowercase-key lookup for priority matching
    urls_lower = {k.lower(): v for k, v in project_urls.items()}

    for key in _PYPI_URL_KEYS:
        url_value = urls_lower.get(key)
        if url_value:
            slug = _extract_github_slug(url_value)
            if slug:
                return slug

    # Fallback: check ALL project_urls values for any GitHub URL
    for url_value in project_urls.values():
        slug = _extract_github_slug(url_value)
        if slug:
            return slug

    return None


def resolve_go_module(module_path: str) -> str | None:
    """Resolve a Go module path to a GitHub owner/repo slug.

    Handles:
    - ``github.com/foo/bar`` -> ``foo/bar``
    - ``github.com/foo/bar/v2`` -> ``foo/bar`` (strip version suffix)
    - ``github.com/foo/bar/pkg/sub`` -> ``foo/bar`` (strip sub-packages)
    - ``golang.org/x/net`` -> ``golang/net``
    - Non-GitHub hosts -> ``None``
    """
    # golang.org/x special case
    if module_path.startswith("golang.org/x/"):
        parts = module_path.split("/")
        if len(parts) >= 3:
            return f"golang/{parts[2]}"
        return None

    # GitHub paths
    if module_path.startswith("github.com/"):
        parts = module_path.split("/")
        if len(parts) >= 3:
            return f"{parts[1]}/{parts[2]}"
        return None

    # Non-GitHub hosts (gopkg.in, k8s.io, etc.) — skip for v1
    return None


def resolve_packages(packages: list[str], ecosystem: str) -> list[tuple[str, str | None]]:
    """Resolve a list of package names to GitHub slugs.

    Args:
        packages: List of package names (PyPI names or Go module paths).
        ecosystem: ``"python"`` or ``"go"``.

    Returns:
        List of ``(package_name, owner_repo_or_none)`` tuples.
    """
    resolver = resolve_pypi if ecosystem == "python" else resolve_go_module
    return [(pkg, resolver(pkg)) for pkg in packages]


def _extract_github_slug(url: str) -> str | None:
    """Extract ``owner/repo`` from a GitHub URL, or return None."""
    match = _GITHUB_REPO_RE.search(url)
    if match:
        owner = match.group(1)
        repo = match.group(2)
        # Strip common suffixes like .git
        repo = repo.removesuffix(".git")
        return f"{owner}/{repo}"
    return None
