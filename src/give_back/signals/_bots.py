"""Bot account detection for signal evaluation.

Used by time_to_response and ghost_closing to filter out automated
responses that don't represent real maintainer engagement.
"""

from __future__ import annotations

_BOT_SUFFIXES = ("[bot]", "-bot")
_KNOWN_BOTS = frozenset({
    "dependabot",
    "renovate",
    "codecov",
    "stale",
    "CLAassistant",
    "allcontributors",
    "netlify",
    "vercel",
    "sonarcloud",
    "codeclimate",
    "snyk-bot",
    "imgbot",
    "greenkeeper",
    "depfu",
    "mergify",
    "kodiakhq",
    "gitguardian",
})


def is_bot(login: str | None) -> bool:
    """Return True if the login looks like a bot account."""
    if not login:
        return False
    lower = login.lower()
    if lower in _KNOWN_BOTS:
        return True
    return any(lower.endswith(suffix) for suffix in _BOT_SUFFIXES)
