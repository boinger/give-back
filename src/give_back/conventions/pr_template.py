"""Find and parse PR description templates in a repository."""

from __future__ import annotations

import re
from pathlib import Path

from give_back.conventions.models import PrTemplate

# Candidate paths in priority order.
_TEMPLATE_PATHS = [
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
    "pull_request_template.md",
]

# Directory that may contain multiple templates (first file wins).
_TEMPLATE_DIR = ".github/PULL_REQUEST_TEMPLATE"

_SECTION_RE = re.compile(r"^#{1,2}\s+(.+)", re.MULTILINE)


def _extract_sections(content: str) -> list[str]:
    """Extract section headers (lines starting with # or ##) from template content."""
    return _SECTION_RE.findall(content)


def find_pr_template(clone_dir: Path) -> PrTemplate | None:
    """Find a PR template in the cloned repo directory.

    Checks known paths in priority order, then falls back to checking the
    template directory. Returns None if no template is found.
    """
    # Check individual file paths first.
    for rel_path in _TEMPLATE_PATHS:
        candidate = clone_dir / rel_path
        if candidate.is_file():
            content = candidate.read_text(encoding="utf-8", errors="replace")
            return PrTemplate(
                path=rel_path,
                sections=_extract_sections(content),
                raw_content=content,
            )

    # Check the template directory (use first file found).
    template_dir = clone_dir / _TEMPLATE_DIR
    if template_dir.is_dir():
        for child in sorted(template_dir.iterdir()):
            if child.is_file():
                content = child.read_text(encoding="utf-8", errors="replace")
                rel_path = f"{_TEMPLATE_DIR}/{child.name}"
                return PrTemplate(
                    path=rel_path,
                    sections=_extract_sections(content),
                    raw_content=content,
                )

    return None
