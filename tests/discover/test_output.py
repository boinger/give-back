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


def _capture(summary: DiscoverSummary, *, width: int = 120, limit: int = 10) -> str:
    """Render ``print_discover`` to a string at the given width."""
    buf = StringIO()
    test_console = Console(file=buf, width=width, force_terminal=True)
    original = discover_mod._console
    discover_mod._console = test_console
    try:
        print_discover(summary, limit=limit)
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


class TestDiscoverSummaryLine:
    """T10-T11: summary line reflects label gate status."""

    def test_gate_active_mentions_labels(self):
        """T10: label_gate_active=True → summary includes label names."""
        summary = _summary("A repo")
        # Default label_gate_active is True
        output = _capture(summary)
        assert "good first issue" in output or "help wanted" in output

    def test_gate_inactive_says_no_label_gate(self):
        """T11: label_gate_active=False → summary says 'no label gate'."""
        summary = _summary("A repo")
        summary.label_gate_active = False
        output = _capture(summary)
        assert "no label gate" in output


class TestDiscoverSparseHint:
    """T12-T13: sparse-result advisory hint."""

    def test_sparse_gate_active_hint_fires(self):
        """T12: sparse results + gate active → emit_advisory is called."""
        summary = DiscoverSummary(
            query="q",
            total_searched=2,
            assessed_count=2,
            results=[
                DiscoverResult(
                    owner="a",
                    repo="b",
                    description="d",
                    stars=100,
                    language="Go",
                    topics=[],
                    open_issue_count=10,
                    good_first_issue_count=0,
                    tier=Tier.GREEN,
                ),
            ],
            label_gate_active=True,
        )
        from unittest.mock import patch

        with patch("give_back.output.discover.emit_advisory") as mock_hint:
            _capture(summary, limit=10)

        mock_hint.assert_called_once()
        call_msg = mock_hint.call_args[0][0]
        assert "give-back assess" in call_msg
        assert "--any-issues" in call_msg

    def test_sparse_gate_inactive_no_hint(self):
        """T13: sparse results + gate inactive → no hint."""
        summary = DiscoverSummary(
            query="q",
            total_searched=2,
            assessed_count=2,
            results=[
                DiscoverResult(
                    owner="a",
                    repo="b",
                    description="d",
                    stars=100,
                    language="Go",
                    topics=[],
                    open_issue_count=10,
                    good_first_issue_count=0,
                    tier=Tier.GREEN,
                ),
            ],
            label_gate_active=False,
        )
        from unittest.mock import patch

        with patch("give_back.output.discover.emit_advisory") as mock_hint:
            _capture(summary, limit=10)

        mock_hint.assert_not_called()


class TestDiscoverJsonOutput:
    """T14: JSON output includes label_gate_active."""

    def test_json_includes_label_gate_active(self):
        """T14: print_discover_json includes label_gate_active field."""
        import json

        from give_back.output.discover import print_discover_json

        summary = DiscoverSummary(
            query="q",
            total_searched=1,
            assessed_count=1,
            results=[],
            label_gate_active=True,
        )

        from unittest.mock import patch

        with patch("builtins.print") as mock_print:
            print_discover_json(summary)

        printed_json = mock_print.call_args[0][0]
        data = json.loads(printed_json)
        assert "label_gate_active" in data
        assert data["label_gate_active"] is True

    def test_json_label_gate_false(self):
        from give_back.output.discover import print_discover_json as _print_json

        summary = DiscoverSummary(
            query="q",
            total_searched=1,
            assessed_count=1,
            results=[],
            label_gate_active=False,
        )

        import json
        from unittest.mock import patch

        with patch("builtins.print") as mock_print:
            _print_json(summary)

        data = json.loads(mock_print.call_args[0][0])
        assert data["label_gate_active"] is False


def _make_result(owner: str, repo: str = "r", tier: Tier = Tier.GREEN) -> DiscoverResult:
    return DiscoverResult(
        owner=owner,
        repo=repo,
        description="desc",
        stars=100,
        language="Go",
        topics=[],
        open_issue_count=10,
        good_first_issue_count=0,
        tier=tier,
    )


class TestFallbackTable:
    """T10-T12 (fallback): fallback table rendering and hint suppression."""

    def test_fallback_table_rendered_with_continuous_numbering(self):
        """T10: fallback_results non-empty → second table with numbering from primary."""
        summary = DiscoverSummary(
            query="q",
            total_searched=10,
            assessed_count=5,
            results=[_make_result("primary", "r1"), _make_result("primary", "r2")],
            fallback_results=[_make_result("fallback", "r3"), _make_result("fallback", "r4")],
            fallback_triggered=True,
            label_gate_active=True,
        )
        output = _capture(summary, limit=10)
        assert "Also found" in output
        # Continuous numbering: primary has 1,2 — fallback should have 3,4
        # Check that repo names appear in the output
        assert "fallback/r3" in output
        assert "fallback/r4" in output

    def test_no_fallback_table_when_empty(self):
        """T11: fallback_results empty → no second table."""
        summary = DiscoverSummary(
            query="q",
            total_searched=2,
            assessed_count=2,
            results=[_make_result("primary", "r1")],
            fallback_results=[],
            fallback_triggered=False,
            label_gate_active=True,
        )
        output = _capture(summary, limit=10)
        assert "Also found" not in output

    def test_hint_suppressed_when_fallback_has_results(self):
        """T12: Sparse hint suppressed when fallback_results is non-empty."""
        summary = DiscoverSummary(
            query="q",
            total_searched=2,
            assessed_count=2,
            results=[_make_result("primary", "r1")],
            fallback_results=[_make_result("fallback", "r2")],
            fallback_triggered=True,
            label_gate_active=True,
        )
        from unittest.mock import patch

        with patch("give_back.output.discover.emit_advisory") as mock_hint:
            _capture(summary, limit=10)

        mock_hint.assert_not_called()


class TestFallbackJsonOutput:
    """T13-T14: JSON fallback fields."""

    def test_json_includes_fallback_when_triggered(self):
        """T13: JSON includes fallback fields when fallback_triggered=True."""
        import json

        from give_back.output.discover import print_discover_json

        summary = DiscoverSummary(
            query="q",
            total_searched=5,
            assessed_count=3,
            results=[_make_result("primary")],
            fallback_results=[_make_result("fallback")],
            fallback_triggered=True,
        )
        from unittest.mock import patch

        with patch("builtins.print") as mock_print:
            print_discover_json(summary)

        data = json.loads(mock_print.call_args[0][0])
        assert data["fallback_triggered"] is True
        assert len(data["fallback_results"]) == 1
        assert data["fallback_results"][0]["owner"] == "fallback"

    def test_json_omits_fallback_when_not_triggered(self):
        """T14: JSON omits fallback fields when fallback_triggered=False."""
        import json

        from give_back.output.discover import print_discover_json

        summary = DiscoverSummary(
            query="q",
            total_searched=5,
            assessed_count=3,
            results=[_make_result("primary")],
            fallback_triggered=False,
        )
        from unittest.mock import patch

        with patch("builtins.print") as mock_print:
            print_discover_json(summary)

        data = json.loads(mock_print.call_args[0][0])
        assert "fallback_triggered" not in data
        assert "fallback_results" not in data
