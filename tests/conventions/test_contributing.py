"""Tests for conventions/_contributing.py shared helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from give_back.conventions._contributing import iter_contributing_md


def test_iter_contributing_md_skips_unreadable(tmp_path: Path) -> None:
    """When a candidate raises OSError on read, the iterator continues to
    the next candidate instead of stopping.

    This covers the except OSError: continue branch in iter_contributing_md,
    which the transitive CLA/DCO tests can't exercise because they never
    trigger a file read error.

    Uses CONTRIBUTING.rst as the failing file to avoid case-insensitive
    filesystem collisions on macOS (where CONTRIBUTING.md and contributing.md
    resolve to the same inode).
    """
    # CONTRIBUTING.rst is unique (no .md twin), so case-insensitive filesystems
    # don't create aliasing. The failing_path is the .rst file; the passing
    # file is .github/CONTRIBUTING.md.
    (tmp_path / "CONTRIBUTING.rst").write_text("rst content should fail to read")
    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    (github_dir / "CONTRIBUTING.md").write_text("GITHUB FILE reads fine")

    original_read_text = Path.read_text
    failing_path = tmp_path / "CONTRIBUTING.rst"

    def fake_read_text(self, *args, **kwargs):
        if str(self) == str(failing_path):
            raise OSError("simulated read failure")
        return original_read_text(self, *args, **kwargs)

    with patch("pathlib.Path.read_text", fake_read_text):
        contents = list(iter_contributing_md(tmp_path))

    # The .rst file raised OSError → skipped. Only .github/CONTRIBUTING.md yielded.
    assert len(contents) == 1
    assert "github file" in contents[0]
