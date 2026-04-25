"""Shared helpers for CLI command modules."""

from __future__ import annotations

import re
import subprocess

import click

# Matches owner/repo or https://github.com/owner/repo (with optional trailing slash/path)
_GITHUB_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$")
_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")

# Matches GitHub remote URLs in both SSH and HTTPS forms, including HTTPS with embedded credentials.
# Captures owner and repo as separate groups. Used by detect_repo_from_cwd() and workspace.py.
_GITHUB_REMOTE_URL_RE = re.compile(
    r"^(?:git@github\.com:|https://(?:[^@/]+@)?github\.com/)([^/]+)/([^/.]+?)(?:\.git)?$"
)


def _parse_repo(repo: str) -> tuple[str, str]:
    """Parse a repo argument into (owner, repo) tuple.

    Accepts 'owner/repo' or 'https://github.com/owner/repo'.
    """
    # Try URL first
    m = _GITHUB_URL_RE.match(repo)
    if m:
        return m.group(1), m.group(2)

    # Try slug
    if _SLUG_RE.match(repo):
        owner, name = repo.split("/", 1)
        return owner, name

    raise click.BadParameter(
        f"Invalid repository: '{repo}'. Use 'owner/repo' or a GitHub URL.",
        param_hint="'REPO'",
    )


class DefaultGroup(click.Group):
    """Click Group with a default subcommand for unknown first tokens.

    Routes `mygroup unknownarg --opt` to a named default subcommand instead of
    failing with "No such command". Same pattern as click-default-group.

    Usage:
        @click.group(cls=DefaultGroup, default='repo', default_if_no_args=True)
        def mygroup(): ...

        @mygroup.command('repo')
        @click.argument('name')
        def myrepo(name): ...

    Now `mygroup foo` → `mygroup repo foo`, `mygroup` → `mygroup repo`, and
    `mygroup repo foo` → explicit.
    """

    ignore_unknown_options = True

    def __init__(self, *args: object, **kwargs: object) -> None:
        # The kwargs.pop calls return `object` per **kwargs typing; narrow to the
        # specific types we actually require for downstream str/bool operations.
        default_cmd = kwargs.pop("default", None)
        self.default_cmd_name: str | None = default_cmd if isinstance(default_cmd, str) else None
        self.default_if_no_args: bool = bool(kwargs.pop("default_if_no_args", False))
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args and self.default_if_no_args and self.default_cmd_name is not None:
            args.insert(0, self.default_cmd_name)
        return super().parse_args(ctx, args)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name not in self.commands and self.default_cmd_name is not None:
            # Unknown subcommand — stash it and route to the default
            ctx.arg0 = cmd_name  # type: ignore[attr-defined]
            cmd_name = self.default_cmd_name
        return super().get_command(ctx, cmd_name)

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        cmd_name, cmd, args = super().resolve_command(ctx, args)
        if hasattr(ctx, "arg0"):
            # Re-insert the originally-typed token as an arg to the default subcommand
            args.insert(0, ctx.arg0)
            cmd_name = cmd.name if cmd else cmd_name
        return cmd_name, cmd, args


def detect_repo_from_cwd() -> tuple[str, str] | None:
    """Auto-detect (owner, repo) from the current directory's `origin` remote.

    Returns (owner, repo) tuple if cwd is a git repo with a GitHub origin.
    Returns None if not in a git repo, no origin remote, or origin is not GitHub.

    Uses `origin` only. Users with give-back workspaces who want to audit the
    upstream repo should pass it explicitly as an argument.
    """
    # Check we're in a git repo first (gives clearer error path downstream)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None  # Not in a git repo

    # Get origin URL
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None  # No origin remote

    url = result.stdout.strip()
    m = _GITHUB_REMOTE_URL_RE.match(url)
    if m:
        return m.group(1), m.group(2)
    return None  # Origin is not a github.com URL
