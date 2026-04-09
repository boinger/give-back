"""Resolve package names to GitHub owner/repo slugs.

Supports:
- PyPI packages: looks up project_urls via PyPI JSON API for GitHub links
- Go modules: parses github.com paths directly, handles golang.org/x special case,
  resolves non-GitHub hosts (gopkg.in, k8s.io, etc.) via go-import meta tags

No external dependencies beyond httpx (already in project deps).
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlsplit

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
_GO_GET_MAX_REDIRECTS = 5

# Module-level cache: import-prefix → GitHub slug (or None for failed lookups).
# Session-scoped — lives for one CLI invocation.
_go_meta_cache: dict[str, str | None] = {}

# Shared httpx Client for non-go resolvers (PyPI / crates / npm / rubygems).
# Lazily initialized so tests can reset cleanly via _clear_http_client().
_http_client: httpx.Client | None = None

# Parsed GIVE_BACK_ALLOW_PRIVATE_HOSTS env var (cached per process).
_ALLOWED_PRIVATE_HOSTS: frozenset[str] | None = None

# Hosts we've already warned about for this process. Prevents log spam when
# a single go.sum references the same private host multiple times.
_allowlist_miss_warned: set[str] = set()


def _get_client() -> httpx.Client:
    """Return the shared httpx.Client, creating it lazily on first use.

    Used by the non-go resolvers (PyPI / crates / npm / rubygems) to pool
    TCP+TLS connections across calls. resolve_go_module does NOT use this
    client — it routes through _safe_go_get() which disables redirects and
    re-validates the host on every hop.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(
            timeout=_PYPI_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "give-back (https://github.com/boinger/give-back)"},
        )
    return _http_client


def _clear_http_client() -> None:
    """Test teardown helper — close and reset the shared client."""
    global _http_client
    if _http_client is not None:
        _http_client.close()
        _http_client = None


def _get_allowed_private_hosts() -> frozenset[str]:
    """Read GIVE_BACK_ALLOW_PRIVATE_HOSTS and cache the result.

    Format: comma-separated list of hostnames, e.g.
    ``go.company.internal,gitlab.internal``. Matching is case-insensitive
    and exact (no subdomain wildcards — users list each host they need).
    """
    global _ALLOWED_PRIVATE_HOSTS
    if _ALLOWED_PRIVATE_HOSTS is None:
        raw = os.environ.get("GIVE_BACK_ALLOW_PRIVATE_HOSTS", "")
        _ALLOWED_PRIVATE_HOSTS = frozenset(h.strip().lower() for h in raw.split(",") if h.strip())
    return _ALLOWED_PRIVATE_HOSTS


def _clear_allowlist() -> None:
    """Test teardown helper — reset the cached allowlist and warn-set."""
    global _ALLOWED_PRIVATE_HOSTS
    _ALLOWED_PRIVATE_HOSTS = None
    _allowlist_miss_warned.clear()


def _warn_allowlist_miss(host: str) -> None:
    """Emit a one-shot stderr warning the first time *host* is rejected.

    Prevents silent failure when an enterprise user running an internal Go
    module server hasn't set GIVE_BACK_ALLOW_PRIVATE_HOSTS yet — they see
    the reason their host was skipped and the exact env var to set.
    """
    if host in _allowlist_miss_warned:
        return
    _allowlist_miss_warned.add(host)
    from give_back.console import stderr_console

    stderr_console.print(
        f"[yellow]Warning:[/yellow] skipped private/internal host "
        f"[bold]{host}[/bold] during Go module resolution. "
        f"To allow it, set [bold]GIVE_BACK_ALLOW_PRIVATE_HOSTS={host}[/bold] "
        f"(comma-separated for multiple hosts)."
    )


def _is_public_host(host: str) -> bool:
    """Return True if *host* is safe to fetch.

    Returns True when EITHER:
      - The host is explicitly allowlisted via GIVE_BACK_ALLOW_PRIVATE_HOSTS, OR
      - Every resolved IP for *host* is a public address.

    Fails closed: on resolution error, unknown host, or empty host, returns False.
    Emits a one-shot stderr warning the first time a private host is rejected
    without being on the allowlist, so enterprise users see why their
    internal server was skipped.

    Multi-A-record guard: iterates ALL getaddrinfo entries and returns False
    if ANY is private. This blocks the SSRF bypass where an attacker publishes
    a DNS record with both a public and a private IP.
    """
    if not host:
        return False

    # Enterprise escape hatch: explicit per-host opt-in.
    if host.lower() in _get_allowed_private_hosts():
        return True

    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False

    has_any_private = False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            has_any_private = True

    if has_any_private:
        _warn_allowlist_miss(host)
        return False
    return True


def _safe_go_get(candidate: str) -> httpx.Response | None:
    """Fetch ``https://{candidate}?go-get=1`` with SSRF protection.

    Manual redirect handling: follow up to _GO_GET_MAX_REDIRECTS hops and
    re-validate the host on every one. Returns None if any step targets a
    non-public host, if the redirect chain exceeds the cap, or on any HTTP
    error. Callers should treat None identically to the existing "continue"
    path (try the next prefix candidate).

    NOTE: this deliberately does NOT use the shared _get_client() — that
    client has follow_redirects=True which would bypass the per-hop host check.
    """
    url = f"https://{candidate}?go-get=1"
    for _ in range(_GO_GET_MAX_REDIRECTS + 1):
        host = urlsplit(url).hostname or ""
        if not _is_public_host(host):
            return None
        try:
            resp = httpx.get(url, timeout=_GO_GET_TIMEOUT, follow_redirects=False)
        except (httpx.HTTPError, httpx.TimeoutException):
            return None
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location")
            if not location:
                return None
            # Resolve relative Location against the current URL.
            url = str(httpx.URL(url).join(location))
            continue
        return resp
    # Redirect chain exceeded the cap.
    return None


def resolve_pypi(package_name: str) -> str | None:
    """Resolve a PyPI package name to a GitHub owner/repo slug.

    Calls the PyPI JSON API and inspects ``info.project_urls`` for GitHub URLs.
    Returns ``"owner/repo"`` or ``None`` if no GitHub URL is found.
    """
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = _get_client().get(url)
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

    # Try progressively shorter paths until we get a valid go-import response.
    # _safe_go_get handles SSRF protection (per-hop host validation + manual
    # redirect loop with _GO_GET_MAX_REDIRECTS cap). None = skip this candidate.
    parts = module_path.split("/")
    for end in range(len(parts), 1, -1):
        candidate = "/".join(parts[:end])
        resp = _safe_go_get(candidate)
        if resp is None:
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
    root = "/".join(parts[: min(len(parts), 3)])
    _go_meta_cache[root] = None
    return None


def resolve_crates_io(crate_name: str) -> str | None:
    """Resolve a Rust crate name to a GitHub owner/repo slug.

    Calls the crates.io API and inspects the ``repository`` field for a GitHub URL.
    """
    url = f"https://crates.io/api/v1/crates/{crate_name}"
    try:
        # Shared client already sets the give-back User-Agent that crates.io requires.
        response = _get_client().get(url)
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
        response = _get_client().get(url)
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
        response = _get_client().get(url)
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
