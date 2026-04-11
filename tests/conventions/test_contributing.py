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
    # Content is yielded in ORIGINAL case (not lowercased) per the contract
    # update in 2026-04-11.
    assert len(contents) == 1
    assert "GITHUB FILE" in contents[0]


def test_iter_contributing_md_yields_original_content(tmp_path: Path) -> None:
    """Helper yields RAW content, not lowercased.

    Callers that need case-insensitive matching lowercase locally. Callers
    that need to preserve case (URL extraction, RFC 3986 path preservation)
    use the raw content directly. This test pins the contract after the
    2026-04-11 change that moved .lower() out of the helper.
    """
    mixed_case_content = (
        "# Contributing\n\n"
        "You must sign the Contributor License Agreement at "
        "https://cla.Example.io/SomeMixedCase/Path before submitting."
    )
    (tmp_path / "CONTRIBUTING.md").write_text(mixed_case_content)

    contents = list(iter_contributing_md(tmp_path))

    # On case-insensitive filesystems (macOS HFS+/APFS), CONTRIBUTING.md and
    # contributing.md alias to the same inode, so the iterator may yield the
    # same file content twice. Assert at least one yield and that every
    # yielded copy preserves case.
    assert len(contents) >= 1
    for content in contents:
        assert "Contributor License Agreement" in content
        assert "Example.io" in content
        assert "SomeMixedCase/Path" in content
