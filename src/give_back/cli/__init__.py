"""CLI entry point for give-back."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from give_back import __version__
from give_back.cli._shared import _parse_repo  # noqa: F401 — re-export for backward compatibility
from give_back.cli.assess import assess
from give_back.cli.audit import audit
from give_back.cli.calibrate import calibrate
from give_back.cli.check import check
from give_back.cli.conventions import conventions
from give_back.cli.deps import deps
from give_back.cli.discover import discover
from give_back.cli.prepare import prepare
from give_back.cli.skill import skill
from give_back.cli.skip import skip, unskip
from give_back.cli.sniff import sniff
from give_back.cli.status import status
from give_back.cli.submit import submit
from give_back.cli.triage import triage


def _stdout_isatty() -> bool:
    """Defensive isatty check — embedders may replace sys.stdout with
    wrappers that don't implement .isatty() or raise from it."""
    return getattr(sys.stdout, "isatty", lambda: False)()


def _stderr_isatty() -> bool:
    return getattr(sys.stderr, "isatty", lambda: False)()


def _check_skill_installed_hint() -> None:
    """Print a one-line advisory hint to stderr if the skill isn't installed.

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

    The hint is purely advisory UX for interactive humans. Operational warnings
    (e.g. corrupt workspace data in ``status.py``) remain unconditionally on
    stderr — they are signal, not advisory. See the "Machine-readable output"
    section in ``README.md`` for the full output contract.
    """
    pref = os.environ.get("GIVE_BACK_HINTS", "auto").lower()
    if pref == "never":
        return
    if pref == "auto" and not (_stdout_isatty() and _stderr_isatty()):
        return
    # pref == "always" OR (pref == "auto" AND both TTYs) — fall through

    skill_target = Path.home() / ".claude" / "skills" / "give-back" / "SKILL.md"
    if not skill_target.exists():
        from give_back.console import stderr_console

        stderr_console.print("[dim]Tip: run 'give-back skill install' to enable /give-back in Claude Code.[/dim]")


# Root CLI group
@click.group()
@click.version_option(version=__version__, prog_name="give-back")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Evaluate whether an open-source project is viable for outside contributions."""
    # Skip the hint when the user is running skill management commands —
    # they're already dealing with the skill install state, so it would just be noise.
    if ctx.invoked_subcommand != "skill":
        _check_skill_installed_hint()


# Register commands in original source order (preserves --help display order)
cli.add_command(assess)
cli.add_command(triage)
cli.add_command(sniff)
cli.add_command(conventions)
cli.add_command(deps)
cli.add_command(calibrate)
cli.add_command(skip)
cli.add_command(unskip)
cli.add_command(prepare)
cli.add_command(check)
cli.add_command(discover)
cli.add_command(submit)
cli.add_command(status)
cli.add_command(audit)
cli.add_command(skill)

__all__ = ["cli", "_parse_repo"]
