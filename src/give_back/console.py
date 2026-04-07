"""Shared rich console instances.

stderr_console: for status messages, warnings, progress bars (never captured by pipes).
stdout_console: for command output (tables, JSON) — lives in output/_shared.py.

Both consoles use :func:`_effective_width` so that output rendered while
give-back is running as a subprocess (Claude Code, CI, ``| less``) doesn't
collapse into the 80-column rich default and truncate table columns.
"""

from __future__ import annotations

import os
import sys

from rich.console import Console

_NON_TTY_FALLBACK_WIDTH = 120


def _effective_width(*, is_stderr: bool = False) -> int | None:
    """Return the width to pass to a rich :class:`Console`.

    Returns ``None`` (rich auto-detects from the terminal) when the relevant
    stream is attached to a TTY. When the stream is piped — e.g. give-back
    invoked as a subprocess by Claude Code, a CI job, or ``| less`` — rich's
    default fallback is 80 columns, which squeezes table columns and wraps
    descriptions mid-word. In that case:

    * honour ``$COLUMNS`` if set (so callers retain control);
    * otherwise use :data:`_NON_TTY_FALLBACK_WIDTH` (120), wide enough for
      every table give-back prints without being obnoxious when piped to a
      narrow pager.
    """
    stream = sys.stderr if is_stderr else sys.stdout
    if stream.isatty():
        return None

    columns = os.environ.get("COLUMNS")
    if columns and columns.isdigit():
        return int(columns)

    return _NON_TTY_FALLBACK_WIDTH


stderr_console = Console(stderr=True, width=_effective_width(is_stderr=True))
