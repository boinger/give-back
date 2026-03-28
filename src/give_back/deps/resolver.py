"""Resolve package names to GitHub owner/repo slugs.

Supports:
- PyPI packages: looks up project_urls via PyPI JSON API for GitHub links
- Go modules: parses github.com paths directly, handles golang.org/x special case,
  resolves non-GitHub hosts (gopkg.in, k8s.io, etc.) via go-import meta tags

No external dependencies beyond httpx (already in project deps).
"""

from __future__ import annotations

import re

import httpx

_PYPI_TIMEOUT = 10.0  # seconds

# Keys to check in PyPI project_urls, in priority order (case-insensitive)
_PYPI_URL_KEYS = ("source", "repository", "source code", "github", "homepage", "code")

_GITHUB_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/#?]+)")

# go-import meta tag: <meta name="go-import" content="prefix vcs repo-url">
# Handles both single and double quotes in attributes.
_GO_IMPORT_RE = re.compile(
    r"""<meta\s+name=["']go-import["']\s+content=["']([^"']+)["']""",
    re.IGNORECASE,
)
_GO_GET_TIMEOUT = 5.0

# Module-level cache: import-prefix → GitHub slug (or None for failed lookups).
# Session-scoped — lives for one CLI invocation.
_go_meta_cache: dict[str, str | None] = {}


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

    Resolution order (fast paths first, then HTTP fallback):
    1. ``github.com/foo/bar`` -> ``foo/bar`` (direct parse, no HTTP)
    2. ``golang.org/x/net`` -> ``golang/net`` (known mapping, no HTTP)
    3. Everything else -> fetch ``?go-get=1`` and parse go-import meta tag
    """
    # Fast path: github.com (no HTTP needed)
    if module_path.startswith("github.com/"):
        parts = module_path.split("/")
        if len(parts) >= 3:
            return f"{parts[1]}/{parts[2]}"
        return None

    # Fast path: golang.org/x (known mapping, no HTTP needed)
    if module_path.startswith("golang.org/x/"):
        parts = module_path.split("/")
        if len(parts) >= 3:
            return f"golang/{parts[2]}"
        return None

    # HTTP fallback: resolve via go-import meta tag
    return _resolve_go_via_meta(module_path)


def _resolve_go_via_meta(module_path: str) -> str | None:
    """Resolve a Go module path via the go-import HTML meta tag.

    Fetches ``https://{path}?go-get=1`` and parses the
    ``<meta name="go-import" content="{prefix} {vcs} {repo-url}">`` tag.
    Only extracts GitHub URLs from git VCS entries (skips "mod" proxy entries).

    Uses a module-level cache to avoid repeat HTTP lookups for the same host prefix.
    Caches both positive results (GitHub slug) and negative results (None).
    """
    # Check cache first (prefix match)
    for prefix, slug in _go_meta_cache.items():
        if module_path == prefix or module_path.startswith(prefix + "/"):
            return slug

    # Try progressively shorter paths until we get a valid go-import response
    parts = module_path.split("/")
    for end in range(len(parts), 1, -1):
        candidate = "/".join(parts[:end])
        try:
            resp = httpx.get(
                f"https://{candidate}?go-get=1",
                timeout=_GO_GET_TIMEOUT,
                follow_redirects=True,
            )
        except (httpx.HTTPError, httpx.TimeoutException):
            continue

        if resp.status_code != 200:
            continue

        # Find all go-import meta tags and match the right prefix
        for match in _GO_IMPORT_RE.finditer(resp.text):
            fields = match.group(1).split()
            if len(fields) < 3:
                continue
            import_prefix, vcs_type, repo_url = fields[0], fields[1], fields[2]
            # Only handle git VCS (skip "mod" proxy entries)
            if vcs_type != "git":
                continue
            # Check prefix matches our module path
            if module_path == import_prefix or module_path.startswith(import_prefix + "/"):
                slug = _extract_github_slug(repo_url)
                _go_meta_cache[import_prefix] = slug
                return slug

    # Cache negative result to avoid retrying failed hosts
    root = "/".join(parts[:min(len(parts), 3)])
    _go_meta_cache[root] = None
    return None


def resolve_crates_io(crate_name: str) -> str | None:
    """Resolve a Rust crate name to a GitHub owner/repo slug.

    Calls the crates.io API and inspects the ``repository`` field for a GitHub URL.
    """
    url = f"https://crates.io/api/v1/crates/{crate_name}"
    try:
        response = httpx.get(
            url,
            timeout=_PYPI_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "give-back (https://github.com/boinger/give-back)"},
        )
    except (httpx.TimeoutException, httpx.HTTPError):
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    repo_url = (data.get("crate") or {}).get("repository") or ""
    return _extract_github_slug(repo_url)


def resolve_npm(package_name: str) -> str | None:
    """Resolve an npm package name to a GitHub owner/repo slug.

    Calls the npm registry and inspects the ``repository`` field for a GitHub URL.
    Handles scoped packages (``@scope/name``).
    """
    url = f"https://registry.npmjs.org/{package_name}"
    try:
        response = httpx.get(url, timeout=_PYPI_TIMEOUT, follow_redirects=True)
    except (httpx.TimeoutException, httpx.HTTPError):
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    repo = data.get("repository") or {}
    if isinstance(repo, str):
        repo_url = repo
    elif isinstance(repo, dict):
        repo_url = repo.get("url", "")
    else:
        return None

    return _extract_github_slug(repo_url)


def resolve_rubygems(gem_name: str) -> str | None:
    """Resolve a Ruby gem name to a GitHub owner/repo slug.

    Calls the RubyGems API and inspects ``source_code_uri`` and ``homepage_uri``
    for a GitHub URL.
    """
    url = f"https://rubygems.org/api/v1/gems/{gem_name}.json"
    try:
        response = httpx.get(url, timeout=_PYPI_TIMEOUT, follow_redirects=True)
    except (httpx.TimeoutException, httpx.HTTPError):
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    # Check source_code_uri first, then homepage_uri
    for key in ("source_code_uri", "homepage_uri"):
        uri = data.get(key) or ""
        slug = _extract_github_slug(uri)
        if slug:
            return slug

    return None


_ECOSYSTEM_RESOLVERS = {
    "python": resolve_pypi,
    "go": resolve_go_module,
    "rust": resolve_crates_io,
    "node": resolve_npm,
    "ruby": resolve_rubygems,
}


def resolve_packages(packages: list[str], ecosystem: str) -> list[tuple[str, str | None]]:
    """Resolve a list of package names to GitHub slugs.

    Args:
        packages: List of package names.
        ecosystem: ``"python"``, ``"go"``, ``"rust"``, ``"node"``, or ``"ruby"``.

    Returns:
        List of ``(package_name, owner_repo_or_none)`` tuples.
    """
    resolver = _ECOSYSTEM_RESOLVERS.get(ecosystem, resolve_pypi)
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
