"""Advisory hint infrastructure — TTY-gated, env-var-overridable stderr hints.

Advisory hints are purely UX for interactive humans. They are NOT operational
warnings. Operational warnings (e.g. corrupt workspace data in ``status.py``)
remain unconditionally on stderr — they are signal, not advisory.

See the "Machine-readable output" section in ``README.md`` for the full
output contract.
"""

from __future__ import annotations

import os
import sys


def _stdout_isatty() -> bool:
    """Defensive isatty check — embedders may replace sys.stdout with
    wrappers that don't implement .isatty() or raise from it."""
    return getattr(sys.stdout, "isatty", lambda: False)()


def _stderr_isatty() -> bool:
    return getattr(sys.stderr, "isatty", lambda: False)()


def emit_advisory(message: str) -> None:
    """Print an advisory hint to stderr, respecting ``GIVE_BACK_HINTS``.

    Hint visibility is controlled by the ``GIVE_BACK_HINTS`` env var:

    - ``always`` — force print regardless of stream state
    - ``never``  — force suppress
    - ``auto``   — (default) print only when BOTH stdout and stderr are TTYs

    The default ``auto`` behavior suppresses the hint whenever stdout OR stderr
    is not attached to a terminal, which covers:

    - JSON piping  (``cmd --json | jq``)           — stdout not TTY
    - Stderr redirect  (``cmd 2>err.log``)          — stderr not TTY
    - ``2>&1`` merging  (``cmd --json 2>&1 | jq``) — merged stream, both non-TTY
    - Subprocess capture  (``capture_output=True``) — both non-TTY
    - CI / pytest                                   — both non-TTY
    - Pipe to pager  (``cmd | less``)               — stdout not TTY
    """
    pref = os.environ.get("GIVE_BACK_HINTS", "auto").lower()
    if pref == "never":
        return
    if pref == "auto" and not (_stdout_isatty() and _stderr_isatty()):
        return

    from give_back.console import stderr_console

    stderr_console.print(message)
