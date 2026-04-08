"""Contract guard: status.py operational warnings stay on stderr unconditionally.

The hint-vs-warning distinction codified in README.md's "Machine-readable
output" section:

- **Hints** are advisory UX for interactive humans. TTY-gated via
  `_check_skill_installed_hint` so they never leak into captured output.
- **Warnings** are operational signal. They must print to stderr *always*,
  regardless of TTY state, because callers consuming the output (log
  aggregators, audit scripts, oncall dashboards) depend on knowing when
  data is corrupt or unreadable.

This test pins that distinction so a future "fix" that gates all
stderr_console output on isatty would fail loudly.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from rich.console import Console

from give_back.status import scan_workspaces


class TestStatusWarningsContract:
    """Warnings from scan_workspaces() must reach stderr even in non-TTY
    contexts. They are operational signal, not advisory UX."""

    def _make_capture_console(self) -> tuple[Console, io.StringIO]:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=200)
        return console, buf

    def test_corrupt_context_warning_prints_under_non_tty(self, tmp_path):
        """A corrupt context.json must trigger the warning on stderr even
        when stdout is non-TTY (e.g. under `status --json | jq` or
        `status --json 2>&1`)."""
        workspace = tmp_path / "ws"
        (workspace / "pallets" / "flask" / ".give-back").mkdir(parents=True)
        corrupt = workspace / "pallets" / "flask" / ".give-back" / "context.json"
        corrupt.write_text("{ not valid json }")

        console, buf = self._make_capture_console()

        # Patch stderr_console in status.py's namespace — the module imports it
        # at load time, so patching 'give_back.console.stderr_console' alone
        # wouldn't affect the already-bound reference.
        with patch("give_back.status.stderr_console", console):
            results = scan_workspaces(workspace)

        # Corrupt file was skipped, but the warning DID print to stderr.
        assert results == []
        assert "Corrupt context.json" in buf.getvalue()
        assert "Warning" in buf.getvalue()

    def test_unreadable_context_warning_prints_under_non_tty(self, tmp_path):
        """An OSError while reading a context.json must trigger the
        warning on stderr regardless of TTY state."""
        workspace = tmp_path / "ws"
        ctx_dir = workspace / "pallets" / "flask" / ".give-back"
        ctx_dir.mkdir(parents=True)
        # Create the context.json path as a directory to force an OSError on read
        (ctx_dir / "context.json").mkdir()

        console, buf = self._make_capture_console()

        with patch("give_back.status.stderr_console", console):
            results = scan_workspaces(workspace)

        assert results == []
        assert "Cannot read" in buf.getvalue()
        assert "Warning" in buf.getvalue()
