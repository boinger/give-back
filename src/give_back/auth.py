"""GitHub token resolution.

Priority order:
1. GITHUB_TOKEN environment variable
2. `gh auth token` subprocess call
3. None (unauthenticated — prints prominent warning)
"""

from __future__ import annotations

import os
import subprocess

from give_back.console import stderr_console as _console


def resolve_token() -> str | None:
    """Resolve a GitHub token from environment or gh CLI.

    Returns the token string, or None if no token is available.
    When returning None, prints a prominent warning about rate limits.
    """
    # 1. Check environment variable
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    # 2. Try gh CLI
    token = _try_gh_auth_token()
    if token:
        return token

    # 3. No token available — warn aggressively
    _console.print(
        "\n[bold yellow]Warning:[/bold yellow] No GitHub token found.\n"
        "Unauthenticated requests are limited to [bold]60/hour[/bold] and will likely\n"
        "hit rate limits before completing a single assessment.\n"
        "Set [bold]GITHUB_TOKEN[/bold] or run [bold]gh auth login[/bold].\n",
    )
    return None


def _try_gh_auth_token() -> str | None:
    """Attempt to get a token from the gh CLI. Returns None on any failure."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        # gh is not installed
        pass
    except subprocess.TimeoutExpired:
        pass
    except subprocess.CalledProcessError:
        pass
    return None
