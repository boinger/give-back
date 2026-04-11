"""Shared helper for reading CONTRIBUTING.md.

Both CLA and DCO detection need to locate and read CONTRIBUTING.md from the
same set of candidate paths. This helper centralizes the file-enumeration so
the two detectors stay in sync when a new candidate path is added.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

_CANDIDATES = (
    "CONTRIBUTING.md",
    "contributing.md",
    "CONTRIBUTING.rst",
    ".github/CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
)


def iter_contributing_md(clone_dir: Path) -> Iterator[str]:
    """Yield lowercased content of each CONTRIBUTING.md variant found.

    Skips candidates that raise OSError on read and continues to the next.
    Yields nothing if no candidate file exists or all reads fail.

    Callers typically iterate until their pattern matches, then break:

        for content in iter_contributing_md(clone_dir):
            if "developer certificate of origin" in content:
                return True
        return False
    """
    for name in _CANDIDATES:
        path = clone_dir / name
        if path.is_file():
            try:
                yield path.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
