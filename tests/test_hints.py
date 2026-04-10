"""Tests for give_back.hints — advisory-hint infrastructure."""

from __future__ import annotations

import io
from unittest.mock import patch

from rich.console import Console

from give_back.hints import emit_advisory


def _make_capture_console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200)
    return console, buf


class TestEmitAdvisory:
    """T1-T3: emit_advisory respects GIVE_BACK_HINTS and TTY state."""

    def test_auto_both_ttys_prints(self):
        """T1: GIVE_BACK_HINTS=auto (default) + both TTYs → message appears."""
        console, buf = _make_capture_console()

        with (
            patch("give_back.hints._stdout_isatty", return_value=True),
            patch("give_back.hints._stderr_isatty", return_value=True),
            patch("give_back.console.stderr_console", console),
            patch.dict("os.environ", {}, clear=False),
        ):
            # Remove GIVE_BACK_HINTS if set, to test default "auto"
            import os

            os.environ.pop("GIVE_BACK_HINTS", None)
            emit_advisory("test hint message")

        assert "test hint message" in buf.getvalue()

    def test_never_suppresses(self):
        """T2: GIVE_BACK_HINTS=never → no output regardless of TTY state."""
        console, buf = _make_capture_console()

        with (
            patch("give_back.hints._stdout_isatty", return_value=True),
            patch("give_back.hints._stderr_isatty", return_value=True),
            patch("give_back.console.stderr_console", console),
            patch.dict("os.environ", {"GIVE_BACK_HINTS": "never"}),
        ):
            emit_advisory("should not appear")

        assert buf.getvalue() == ""

    def test_auto_stdout_piped_suppresses(self):
        """T3: GIVE_BACK_HINTS=auto + stdout piped → no output."""
        console, buf = _make_capture_console()

        with (
            patch("give_back.hints._stdout_isatty", return_value=False),
            patch("give_back.hints._stderr_isatty", return_value=True),
            patch("give_back.console.stderr_console", console),
            patch.dict("os.environ", {}, clear=False),
        ):
            import os

            os.environ.pop("GIVE_BACK_HINTS", None)
            emit_advisory("should not appear")

        assert buf.getvalue() == ""
