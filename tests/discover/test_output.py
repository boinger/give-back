"""Tests for the discover output table.

Regression coverage for the width/truncation fix: the hard-coded
``description[:60]`` slice chopped long descriptions mid-word. The table now
delegates wrapping to rich via ``max_width`` + ``overflow="fold"``, so full
descriptions must survive all the way to the rendered output.
"""

from __future__ import annotations

import re
from io import StringIO

from rich.console import Console

import give_back.output.discover as discover_mod
from give_back.discover.search import DiscoverResult, DiscoverSummary
from give_back.models import Tier
from give_back.output.discover import print_discover

# ANSI escape sequences rich emits for colour/styling.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _capture(summary: DiscoverSummary, *, width: int = 120) -> str:
    """Render ``print_discover`` to a string at the given width."""
    buf = StringIO()
    test_console = Console(file=buf, width=width, force_terminal=True)
    original = discover_mod._console
    discover_mod._console = test_console
    try:
        print_discover(summary)
    finally:
        discover_mod._console = original
    return _strip_ansi(buf.getvalue())


def _summary(description: str) -> DiscoverSummary:
    """Build a minimal DiscoverSummary with one result that has *description*."""
    return DiscoverSummary(
        query="test",
        total_searched=1,
        assessed_count=1,
        cache_hits=0,
        results=[
            DiscoverResult(
                owner="acme",
                repo="widget",
                description=description,
                stars=1234,
                language="python",
                topics=["tools"],
                open_issue_count=42,
                good_first_issue_count=5,
                tier=Tier.GREEN,
            )
        ],
    )


class TestDiscoverDescriptionWrapping:
    def test_long_description_not_chopped_at_60_chars(self):
        """Regression: the old ``[:60]`` slice truncated descriptions mid-word.

        With ``description[:60]`` this 71-char string became
        ``"SigNoz is an open-source observability platform native to Op"`` —
        "OpenTelemetry" reduced to the bare stub "Op". The fix delegates
        wrapping to rich, so the full final word must survive into the
        rendered output (possibly wrapped across lines).
        """
        description = "SigNoz is an open-source observability platform native to OpenTelemetry"
        output = _capture(_summary(description))

        assert "OpenTelemetry" in output, f"expected full word 'OpenTelemetry' in:\n{output}"

    def test_short_description_renders_verbatim(self):
        """A short description must appear in full with no wrapping artefacts."""
        output = _capture(_summary("Short and sweet."))
        assert "Short and sweet." in output

    def test_empty_description_renders_without_error(self):
        """Empty/None descriptions should not blow up the table."""
        output = _capture(_summary(""))
        # Row headers still render.
        assert "acme/widget" in output
        assert "GREEN" in output
