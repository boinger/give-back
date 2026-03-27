"""Filter dependency candidates: stdlib, same-org, skip list, archived, mega-projects.

Filters are applied in order:
1. Unresolved (owner/repo is None)
2. Standard library packages (Python or Go)
3. Same-org (owner matches primary repo owner)
4. Skip list (user-managed exclusions)
5. Archived repos and mega-project flagging (requires GitHubClient)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from give_back.github_client import GitHubClient

logger = logging.getLogger(__name__)

# fmt: off
PYTHON_STDLIB: frozenset[str] = frozenset({
    "abc", "argparse", "array", "ast", "asyncio",
    "base64", "bisect", "builtins", "bz2",
    "calendar", "codecs", "collections", "compileall", "concurrent", "configparser",
    "contextlib", "copy", "csv", "ctypes",
    "dataclasses", "datetime", "decimal", "dis", "doctest",
    "email", "enum",
    "fnmatch", "fractions", "functools",
    "gettext", "glob", "gzip",
    "hashlib", "heapq", "hmac", "html", "http",
    "importlib", "inspect", "io", "itertools",
    "json",
    "locale", "logging", "lzma",
    "math", "multiprocessing",
    "operator", "os",
    "pathlib", "pdb", "pkgutil", "platform", "pprint", "profile",
    "queue",
    "random", "re",
    "secrets", "select", "selectors", "shelve", "shutil", "signal", "site", "socket",
    "sqlite3", "ssl", "statistics", "string", "struct", "subprocess", "sys", "sysconfig",
    "tarfile", "tempfile", "test", "textwrap", "threading", "time", "timeit", "token",
    "tokenize", "traceback", "types", "typing",
    "unicodedata", "unittest", "urllib",
    "venv",
    "warnings", "weakref",
    "xml",
    "zipfile", "zlib",
    # pickle is stdlib but listed separately to avoid tooling false positives
    "pickle",
})

GO_STDLIB: frozenset[str] = frozenset({
    "archive", "bufio", "bytes",
    "compress", "container", "context", "crypto",
    "database", "debug",
    "embed", "encoding", "errors",
    "flag", "fmt",
    "go",
    "hash", "html", "http",
    "image", "index", "io",
    "log",
    "math", "mime",
    "net",
    "os",
    "path", "filepath", "plugin",
    "reflect", "regexp", "runtime",
    "sort", "strconv", "strings", "sync", "syscall",
    "testing", "text", "time",
    "unicode", "unsafe",
})
# fmt: on

# Well-known mega-projects that are unlikely to want drive-by contributions.
# These are flagged in stats but NOT auto-removed.
_KNOWN_MEGA_PROJECTS: frozenset[str] = frozenset(
    {
        "google/protobuf",
        "kubernetes/kubernetes",
        "golang/go",
        "python/cpython",
        "torvalds/linux",
    }
)

_MEGA_STAR_THRESHOLD = 50_000


def filter_candidates(
    candidates: list[tuple[str, str | None]],
    primary_owner: str,
    skip_list: list[str],
    client: GitHubClient | None = None,
) -> tuple[list[tuple[str, str]], dict]:
    """Filter dependency candidates, returning survivors and statistics.

    Args:
        candidates: List of ``(package_name, "owner/repo" or None)`` tuples.
        primary_owner: Owner of the primary repo (for same-org filtering).
        skip_list: User-managed list of ``"owner/repo"`` slugs to exclude.
        client: Optional :class:`GitHubClient` for archive/star checks.

    Returns:
        ``(filtered, stats)`` where *filtered* is a list of ``(package_name, "owner/repo")``
        tuples that passed all filters, and *stats* is a dict with counts per filter.
    """
    stats: dict = {
        "unresolved": 0,
        "stdlib": 0,
        "same_org": 0,
        "skip_list": 0,
        "archived": 0,
        "mega_projects": [],
        "passed": 0,
    }

    primary_owner_lower = primary_owner.lower()
    skip_set = {s.lower() for s in skip_list}

    # --- Pass 1: unresolved ---
    resolved: list[tuple[str, str]] = []
    for pkg, slug in candidates:
        if slug is None:
            stats["unresolved"] += 1
        else:
            resolved.append((pkg, slug))

    # --- Pass 2: stdlib ---
    after_stdlib: list[tuple[str, str]] = []
    for pkg, slug in resolved:
        pkg_base = pkg.split("/")[0].split(".")[0]
        if pkg_base in PYTHON_STDLIB or pkg_base in GO_STDLIB:
            stats["stdlib"] += 1
        else:
            after_stdlib.append((pkg, slug))

    # --- Pass 3: same-org ---
    after_org: list[tuple[str, str]] = []
    for pkg, slug in after_stdlib:
        owner = slug.split("/")[0]
        if owner.lower() == primary_owner_lower:
            stats["same_org"] += 1
        else:
            after_org.append((pkg, slug))

    # --- Pass 4: skip list ---
    after_skip: list[tuple[str, str]] = []
    for pkg, slug in after_org:
        if slug.lower() in skip_set:
            stats["skip_list"] += 1
        else:
            after_skip.append((pkg, slug))

    # --- Pass 5: archived + mega-project flagging (requires client) ---
    final: list[tuple[str, str]] = []
    for pkg, slug in after_skip:
        # Check known mega-projects first (no API call needed)
        if slug.lower() in {m.lower() for m in _KNOWN_MEGA_PROJECTS}:
            stats["mega_projects"].append(slug)
            # Flagged but NOT removed — still passes through
            final.append((pkg, slug))
            continue

        if client is not None:
            try:
                repo_data = client.rest_get(f"/repos/{slug}")
                if repo_data.get("archived", False):
                    stats["archived"] += 1
                    continue
                stars = repo_data.get("stargazers_count", 0)
                if stars > _MEGA_STAR_THRESHOLD:
                    stats["mega_projects"].append(slug)
                    # Flagged but NOT removed
            except Exception:  # noqa: BLE001 — network errors should not crash filtering
                logger.debug("Failed to fetch repo info for %s, keeping candidate", slug)

        final.append((pkg, slug))

    stats["passed"] = len(final)
    return final, stats
