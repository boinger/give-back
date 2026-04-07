"""CLI command group: skill install/uninstall.

Manages the give-back Claude Code skill at ~/.claude/skills/give-back/.

Symlinks the bundled SKILL.md by default (drift-proof for both editable and
wheel installs). Use --copy for read-only filesystems or audit-friendly installs.
"""

from __future__ import annotations

import shutil
import sys
from importlib.resources import as_file, files
from pathlib import Path

import click

from give_back.console import stderr_console as _console

# Canonical install location (matches Claude Code's skill discovery path)
SKILL_INSTALL_DIR = Path.home() / ".claude" / "skills" / "give-back"


def _is_editable_install() -> bool:
    """Detect whether give-back is installed via `pipx install -e` (editable).

    Editable installs resolve package data to the source repo path. Wheel installs
    resolve to the pipx venv's site-packages.
    """
    try:
        bundled = files("give_back.skill").joinpath("SKILL.md")
        with as_file(bundled) as path:
            return ".local/pipx/venvs" not in str(path)
    except (ModuleNotFoundError, FileNotFoundError):
        return False


def _resolve_bundled_skill_path() -> Path:
    """Get the path to the bundled SKILL.md file.

    For editable installs this is the source repo. For wheel installs this is
    the pipx venv's site-packages location. Either way it's a real file path
    (not a zipped resource).
    """
    bundled = files("give_back.skill").joinpath("SKILL.md")
    with as_file(bundled) as path:
        return Path(path)


@click.group()
def skill() -> None:
    """Manage the give-back Claude Code skill installation."""


@skill.command("install")
@click.option(
    "--copy",
    "force_copy",
    is_flag=True,
    help="Copy the skill file instead of symlinking. Use for read-only filesystems.",
)
def skill_install(force_copy: bool) -> None:
    """Install the give-back Claude Code skill to ~/.claude/skills/give-back/.

    By default, symlinks the bundled skill file from the package. Symlinks are
    drift-proof: the installed file IS the bundled file. Pass --copy to write a
    plain copy instead (useful for read-only filesystems or audit-friendly
    installs).
    """
    # Warn if ~/.claude/ doesn't exist (Claude Code may not be installed)
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        _console.print(
            "[yellow]Warning:[/yellow] ~/.claude/ does not exist. Is Claude Code installed? Installing anyway."
        )

    SKILL_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    target = SKILL_INSTALL_DIR / "SKILL.md"

    bundled_path = _resolve_bundled_skill_path()

    # Remove any existing target (file or broken symlink)
    if target.exists() or target.is_symlink():
        target.unlink()

    if force_copy:
        shutil.copy2(bundled_path, target)
        _console.print(f"  [green]✓[/green] Copied skill to {target}")
    else:
        try:
            target.symlink_to(bundled_path)
            _console.print(f"  [green]✓[/green] Symlinked skill to {target}")
            if _is_editable_install():
                _console.print(
                    "  [dim]Editable install detected. Edits to src/give_back/skill/SKILL.md are live.[/dim]"
                )
        except OSError as exc:
            # Symlink failed (Windows without admin, or weird filesystem).
            # Fall back to copy with a warning.
            _console.print(
                f"[yellow]Warning:[/yellow] Could not create symlink ({exc}). "
                "Falling back to copy. Use --copy to suppress this warning."
            )
            shutil.copy2(bundled_path, target)

    _console.print("  [dim]If Claude Code is already running, start a new session to pick up the skill.[/dim]")


@skill.command("uninstall")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def skill_uninstall(yes: bool) -> None:
    """Remove the give-back Claude Code skill from ~/.claude/skills/give-back/."""
    if not SKILL_INSTALL_DIR.exists():
        _console.print(f"  [dim]Nothing to uninstall: {SKILL_INSTALL_DIR} does not exist.[/dim]")
        return

    if not yes and sys.stdin.isatty():
        if not click.confirm(f"Remove {SKILL_INSTALL_DIR}?", default=True):
            _console.print("  Aborted.")
            return

    shutil.rmtree(SKILL_INSTALL_DIR)
    _console.print(f"  [green]✓[/green] Removed {SKILL_INSTALL_DIR}")
