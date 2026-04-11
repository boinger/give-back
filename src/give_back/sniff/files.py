"""File identification and fetching for code quality sniff.

Parses issue bodies and comments for file path references, fetches file contents
via the GitHub REST contents API, and checks for corresponding test files.
"""

from __future__ import annotations

import base64
import os
import re
from urllib.parse import quote

from give_back.exceptions import RepoNotFoundError
from give_back.github_client import GitHubClient

# Known source file extensions
_KNOWN_EXTENSIONS = frozenset(
    {
        ".py",
        ".go",
        ".rs",
        ".js",
        ".ts",
        ".rb",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".jsx",
        ".tsx",
        ".cs",
        ".swift",
        ".kt",
        ".scala",
        ".lua",
        ".php",
        ".rst",
        ".md",
        ".yml",
        ".yaml",
        ".toml",
        ".json",
        ".cfg",
        ".ini",
    }
)

# Regex for explicit file paths: word-boundary delimited, must contain / and end in known extension.
# Matches paths like src/foo/bar.py, lib/something.rs, cmd/main.go
_EXPLICIT_PATH_RE = re.compile(
    r"(?:^|[\s`\"'(])"  # preceded by whitespace, backtick, quote, or paren
    r"((?:[a-zA-Z0-9_./-]+/)+[a-zA-Z0-9_.-]+\.[a-zA-Z]{1,4})"  # path with at least one /
    r"(?=[`\"'):\s,]|$)",  # followed by delimiter or end
    re.MULTILINE,
)

# Python stack trace: File "src/foo.py", line 42
_PYTHON_TRACE_RE = re.compile(
    r'File "([^"]+)"',
)

# Go / Rust stack trace: at src/foo.go:42  or  src/main.rs:10:5
_GO_TRACE_RE = re.compile(
    r"(?:at\s+)((?:[a-zA-Z0-9_./-]+/)+[a-zA-Z0-9_.-]+\.[a-zA-Z]{1,4}):\d+",
)

# Node.js stack trace: at Object.<anonymous> (src/foo.js:10:5) or (src/foo.ts:10)
_NODE_TRACE_RE = re.compile(
    r"\(((?:[a-zA-Z0-9_./-]+/)+[a-zA-Z0-9_.-]+\.[a-zA-Z]{1,4}):\d+(?::\d+)?\)",
)


def _has_known_extension(path: str) -> bool:
    """Check if a path ends with a known source file extension."""
    _, ext = os.path.splitext(path)
    return ext.lower() in _KNOWN_EXTENSIONS


def _is_url(path: str) -> bool:
    """Reject things that look like URLs rather than file paths."""
    return path.startswith(("http://", "https://", "ftp://"))


def identify_files(issue_body: str, comments: list[dict]) -> list[str]:
    """Extract file paths from issue body and comment bodies.

    Parses for:
    - Explicit file paths (src/foo/bar.py)
    - Python stack traces (File "src/foo.py", line 42)
    - Go/Rust traces (at src/main.go:42)
    - Node.js traces (at Object.<anonymous> (src/foo.js:10:5))

    Returns a deduplicated list of paths that contain a '/' and end in a known extension.
    """
    texts = [issue_body or ""]
    for comment in comments:
        body = comment.get("body", "")
        if body:
            texts.append(body)

    all_text = "\n".join(texts)
    found: list[str] = []

    # Extract from all patterns
    for pattern in (_EXPLICIT_PATH_RE, _PYTHON_TRACE_RE, _GO_TRACE_RE, _NODE_TRACE_RE):
        for match in pattern.finditer(all_text):
            path = match.group(1)
            found.append(path)

    # Filter and deduplicate
    seen: set[str] = set()
    result: list[str] = []
    for path in found:
        if _is_url(path):
            continue
        if "/" not in path:
            continue
        if not _has_known_extension(path):
            continue
        if path not in seen:
            seen.add(path)
            result.append(path)

    return result


def fetch_file_content(client: GitHubClient, owner: str, repo: str, path: str) -> tuple[str, int]:
    """Fetch a file's content via the REST contents API.

    Returns (content, line_count). On 404, returns ("", 0).
    """
    try:
        # URL-injection hardening: issue bodies are user-controlled and the path
        # regex permits chars that are URL-syntactic (?, #, %). quote(safe='/')
        # preserves path separators but escapes the injection surface. Does NOT
        # address path traversal — `..` passes through, but the GitHub contents
        # API resolves paths server-side inside the repo root so traversal is
        # unexploitable against this endpoint.
        data = client.rest_get(f"/repos/{owner}/{repo}/contents/{quote(path, safe='/')}")
    except RepoNotFoundError:
        return ("", 0)

    content_b64 = data.get("content", "")
    if not content_b64 or data.get("encoding") != "base64":
        return ("", 0)

    content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return (content, line_count)


def check_test_file(client: GitHubClient, owner: str, repo: str, source_path: str) -> bool:
    """Check if a test file exists for the given source file.

    Heuristics by language:
    - Python: src/foo/bar.py -> tests/test_bar.py, tests/foo/test_bar.py, test/test_bar.py
    - Go: lib/foo.go -> lib/foo_test.go
    - General: check tests/test_<name>.<ext> and test/test_<name>.<ext>
    """
    _, ext = os.path.splitext(source_path)
    basename = os.path.basename(source_path)
    name_no_ext = os.path.splitext(basename)[0]
    dirpath = os.path.dirname(source_path)

    candidates: list[str] = []

    if ext == ".go":
        # Go convention: test file lives alongside source
        candidates.append(os.path.join(dirpath, f"{name_no_ext}_test.go"))
    elif ext == ".py":
        candidates.append(f"tests/test_{name_no_ext}.py")
        if dirpath:
            candidates.append(f"tests/{dirpath}/test_{name_no_ext}.py")
        candidates.append(f"test/test_{name_no_ext}.py")
    else:
        # Generic: try tests/ and test/ directories
        candidates.append(f"tests/test_{name_no_ext}{ext}")
        candidates.append(f"test/test_{name_no_ext}{ext}")

    for candidate in candidates:
        try:
            # URL-injection hardening — see fetch_file_content for the threat model.
            client.rest_get(f"/repos/{owner}/{repo}/contents/{quote(candidate, safe='/')}")
            return True
        except RepoNotFoundError:
            continue

    return False


def get_recent_commits(client: GitHubClient, owner: str, repo: str, path: str, limit: int = 5) -> int:
    """Return the count of recent commits touching a file.

    Fetches up to `limit` commits via the commits API with path filter.
    Returns the count of commits returned (0 to limit).
    """
    try:
        data = client.rest_get(
            f"/repos/{owner}/{repo}/commits",
            params={"path": path, "per_page": str(limit)},
        )
    except RepoNotFoundError:
        return 0

    if isinstance(data, list):
        return len(data)
    return 0
