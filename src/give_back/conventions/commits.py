"""Analyze commit message conventions from git log."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from give_back.conventions.models import CommitFormat

# Conventional commit prefixes (with optional scope).
_CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|chore|docs|refactor|test|ci|build|perf|style)(\(.+?\))?!?:\s",
)

# Common imperative-mood verbs that start commit messages.
_IMPERATIVE_VERBS = frozenset(
    {
        "Add",
        "Allow",
        "Apply",
        "Avoid",
        "Bump",
        "Change",
        "Clean",
        "Close",
        "Convert",
        "Create",
        "Delete",
        "Deprecate",
        "Disable",
        "Drop",
        "Enable",
        "Ensure",
        "Exclude",
        "Extract",
        "Fix",
        "Handle",
        "Ignore",
        "Implement",
        "Improve",
        "Include",
        "Increase",
        "Introduce",
        "Make",
        "Merge",
        "Migrate",
        "Move",
        "Prevent",
        "Reduce",
        "Refactor",
        "Remove",
        "Rename",
        "Replace",
        "Resolve",
        "Restore",
        "Return",
        "Revert",
        "Run",
        "Set",
        "Simplify",
        "Skip",
        "Sort",
        "Split",
        "Stop",
        "Support",
        "Switch",
        "Update",
        "Upgrade",
        "Use",
        "Validate",
    }
)

_IMPERATIVE_RE = re.compile(r"^(" + "|".join(sorted(_IMPERATIVE_VERBS)) + r")\b")


def _classify_message(msg: str) -> str:
    """Classify a single commit message as 'conventional', 'imperative', or 'other'."""
    if _CONVENTIONAL_RE.match(msg):
        return "conventional"
    if _IMPERATIVE_RE.match(msg):
        return "imperative"
    return "other"


def _pick_examples(messages: list[str], max_examples: int = 5) -> list[str]:
    """Pick diverse example messages (up to max_examples).

    Tries to include at least one from each detected category, then fills
    the rest from the most common category.
    """
    if not messages:
        return []

    by_category: dict[str, list[str]] = {"conventional": [], "imperative": [], "other": []}
    for msg in messages:
        by_category[_classify_message(msg)].append(msg)

    examples: list[str] = []
    seen: set[str] = set()

    # One from each non-empty category first.
    for category in ("conventional", "imperative", "other"):
        for msg in by_category[category]:
            if msg not in seen:
                examples.append(msg)
                seen.add(msg)
                break

    # Fill remaining from all messages, preserving order.
    for msg in messages:
        if len(examples) >= max_examples:
            break
        if msg not in seen:
            examples.append(msg)
            seen.add(msg)

    return examples[:max_examples]


def _most_common_prefix(messages: list[str]) -> str | None:
    """Return the most common conventional-commit prefix, or None."""
    counts: dict[str, int] = {}
    for msg in messages:
        m = _CONVENTIONAL_RE.match(msg)
        if m:
            prefix = m.group(1) + ":"
            counts[prefix] = counts.get(prefix, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def analyze_commits(clone_dir: Path) -> CommitFormat:
    """Analyze recent commit messages to detect the commit style convention.

    Runs ``git log --format="%s" -20`` in *clone_dir* and classifies the
    overall style as conventional / imperative / mixed / unknown.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--format=%s", "-20"],
            capture_output=True,
            text=True,
            cwd=clone_dir,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return CommitFormat(style="unknown")

    if result.returncode != 0:
        return CommitFormat(style="unknown")

    messages = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]

    if len(messages) < 5:
        return CommitFormat(
            style="unknown",
            examples=_pick_examples(messages, max_examples=min(len(messages), 5)),
        )

    conventional_count = 0
    imperative_count = 0
    for msg in messages:
        cat = _classify_message(msg)
        if cat == "conventional":
            conventional_count += 1
        elif cat == "imperative":
            imperative_count += 1

    total = len(messages)
    majority = total * 0.6

    if conventional_count >= majority:
        style = "conventional"
    elif imperative_count >= majority:
        style = "imperative"
    elif conventional_count > 0 and imperative_count > 0:
        style = "mixed"
    else:
        style = "unknown"

    prefix_pattern = _most_common_prefix(messages) if style == "conventional" else None

    return CommitFormat(
        style=style,
        examples=_pick_examples(messages),
        prefix_pattern=prefix_pattern,
    )
