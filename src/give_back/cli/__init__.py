"""CLI entry point for give-back."""

from __future__ import annotations

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
from give_back.cli.skip import skip, unskip
from give_back.cli.sniff import sniff
from give_back.cli.status import status
from give_back.cli.submit import submit
from give_back.cli.triage import triage


# Root CLI group
@click.group()
@click.version_option(version=__version__, prog_name="give-back")
def cli() -> None:
    """Evaluate whether an open-source project is viable for outside contributions."""


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

__all__ = ["cli", "_parse_repo"]
