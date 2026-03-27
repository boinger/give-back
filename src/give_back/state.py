"""State file management for give-back.

Location: ~/.give-back/state.json
Atomic writes via write-to-temp-then-rename to prevent corruption from Ctrl+C.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from give_back.exceptions import StateCorruptError
from give_back.models import Assessment

STATE_DIR = Path.home() / ".give-back"
STATE_FILE = STATE_DIR / "state.json"

_SCHEMA_VERSION = 1
_DEFAULT_CACHE_TTL_HOURS = 24


def _empty_state() -> dict:
    return {"version": _SCHEMA_VERSION, "assessments": {}, "skip_list": []}


def load_state() -> dict:
    """Load state file. Returns empty state if file doesn't exist.

    Raises StateCorruptError if file exists but is invalid, after backing up.
    """
    if not STATE_FILE.exists():
        return _empty_state()

    try:
        data = json.loads(STATE_FILE.read_text())
        if not isinstance(data, dict) or "version" not in data:
            raise StateCorruptError("State file missing version field")
        return data
    except json.JSONDecodeError as exc:
        _backup_corrupt_state()
        raise StateCorruptError(f"State file contains invalid JSON: {exc}") from exc


def save_state(state: dict) -> None:
    """Save state to disk atomically (write to temp, then rename).

    Silently creates ~/.give-back/ if it doesn't exist.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Write to temp file in the same directory (same filesystem for atomic rename)
    fd, tmp_path = tempfile.mkstemp(dir=STATE_DIR, suffix=".tmp", prefix="state-")
    try:
        with open(fd, "w") as f:
            json.dump(state, f, indent=2)
        # Atomic rename
        Path(tmp_path).replace(STATE_FILE)
    except BaseException:
        # Clean up temp file on any failure
        Path(tmp_path).unlink(missing_ok=True)
        raise


def save_assessment(assessment: Assessment) -> None:
    """Save an assessment result to state, keyed by owner/repo."""
    try:
        state = load_state()
    except StateCorruptError:
        state = _empty_state()

    key = f"{assessment.owner}/{assessment.repo}"
    state["assessments"][key] = {
        "timestamp": assessment.timestamp,
        "overall_tier": assessment.overall_tier.value,
        "gate_passed": assessment.gate_passed,
        "incomplete": assessment.incomplete,
        "signals": [
            {
                "name": s.summary,
                "tier": s.tier.value,
                "score": s.score,
                "summary": s.summary,
            }
            for s in assessment.signals
        ],
    }

    try:
        save_state(state)
    except PermissionError:
        pass  # CLI layer handles the warning


def get_cached_assessment(owner: str, repo: str, max_age_hours: int = _DEFAULT_CACHE_TTL_HOURS) -> dict | None:
    """Return cached assessment if fresh enough, else None."""
    try:
        state = load_state()
    except StateCorruptError:
        return None

    key = f"{owner}/{repo}"
    entry = state.get("assessments", {}).get(key)
    if entry is None:
        return None

    # Check freshness
    try:
        cached_time = datetime.fromisoformat(entry["timestamp"])
        now = datetime.now(timezone.utc)
        age_hours = (now - cached_time).total_seconds() / 3600
        if age_hours > max_age_hours:
            return None
    except (KeyError, ValueError):
        return None

    return entry


def add_to_skip_list(slug: str) -> None:
    """Add an owner/repo slug to the skip list (deduplicated, case-preserved)."""
    try:
        state = load_state()
    except StateCorruptError:
        state = _empty_state()

    existing = state.setdefault("skip_list", [])
    # Deduplicate case-insensitively
    if slug.lower() not in {s.lower() for s in existing}:
        existing.append(slug)
        save_state(state)


def remove_from_skip_list(slug: str) -> None:
    """Remove an owner/repo slug from the skip list (case-insensitive match)."""
    try:
        state = load_state()
    except StateCorruptError:
        state = _empty_state()

    existing = state.setdefault("skip_list", [])
    state["skip_list"] = [s for s in existing if s.lower() != slug.lower()]
    save_state(state)


def get_skip_list() -> list[str]:
    """Return the current skip list."""
    try:
        state = load_state()
    except StateCorruptError:
        return []

    return state.get("skip_list", [])


def _backup_corrupt_state() -> None:
    """Back up a corrupt state file before recreating."""
    if STATE_FILE.exists():
        backup = STATE_FILE.with_suffix(".json.bak")
        shutil.copy2(STATE_FILE, backup)
