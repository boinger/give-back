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
from give_back.models import Assessment, Config, SignalResult, Tier

STATE_DIR = Path.home() / ".give-back"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "config.yaml"


def atomic_write_text(path: Path, content: str) -> None:
    """Write *content* to *path* atomically via temp-file-then-rename.

    The temp file is created in the same directory as *path* so the rename
    is guaranteed atomic on POSIX. Parent directories must already exist.
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


_SCHEMA_VERSION = 1
_DEFAULT_CACHE_TTL_HOURS = 24


_MAX_AUDIT_HISTORY = 5


def _empty_state() -> dict:
    return {"version": _SCHEMA_VERSION, "assessments": {}, "skip_list": [], "audit_results": {}}


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
    atomic_write_text(STATE_FILE, json.dumps(state, indent=2))


def save_assessment(assessment: Assessment, signal_names: list[str] | None = None) -> None:
    """Save an assessment result to state, keyed by owner/repo.

    *signal_names* should match the order of ``assessment.signals``. When
    provided, each signal is stored with its name for stable reconstruction
    regardless of registry order changes.
    """
    try:
        state = load_state()
    except StateCorruptError:
        state = _empty_state()

    names = signal_names or [""] * len(assessment.signals)
    key = f"{assessment.owner}/{assessment.repo}"
    state["assessments"][key] = {
        "timestamp": assessment.timestamp,
        "overall_tier": assessment.overall_tier.value,
        "gate_passed": assessment.gate_passed,
        "incomplete": assessment.incomplete,
        "signals": [
            {
                "name": name,
                "tier": s.tier.value,
                "score": s.score,
                "summary": s.summary,
            }
            for name, s in zip(names, assessment.signals)
        ],
    }

    save_state(state)


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


def reconstruct_assessment(cached: dict, owner: str, repo: str) -> tuple[Assessment, list[str]]:
    """Rebuild an Assessment and signal names from the cached JSON format.

    Returns ``(assessment, signal_names)`` where *signal_names* are the names
    stored at cache time. If the cache predates named signals, names will be
    empty strings.

    Raises ValueError if the cached data is missing required fields.
    """
    try:
        tier = Tier(cached["overall_tier"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid cached tier: {exc}") from exc

    signals = []
    signal_names: list[str] = []
    for s in cached.get("signals", []):
        try:
            signal_tier = Tier(s["tier"])
        except (KeyError, ValueError):
            signal_tier = Tier.RED
        signals.append(
            SignalResult(
                score=float(s.get("score", 0.0)),
                tier=signal_tier,
                summary=s.get("summary", ""),
            )
        )
        signal_names.append(s.get("name", ""))

    assessment = Assessment(
        owner=owner,
        repo=repo,
        overall_tier=tier,
        signals=signals,
        gate_passed=cached.get("gate_passed", True),
        incomplete=cached.get("incomplete", False),
        timestamp=cached.get("timestamp", ""),
    )
    return assessment, signal_names


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


def save_audit_result(owner: str, repo: str, snapshot: dict) -> None:
    """Append an audit snapshot to the capped history for *owner/repo*.

    *snapshot* is a plain dict with at least ``timestamp`` and ``items`` keys.
    The list is kept to the most recent ``_MAX_AUDIT_HISTORY`` entries.
    """
    try:
        state = load_state()
    except StateCorruptError:
        state = _empty_state()

    audits = state.setdefault("audit_results", {})
    key = f"{owner}/{repo}"

    history = audits.get(key, [])
    # Handle legacy single-dict format (wrap in list)
    if isinstance(history, dict):
        history = [history]
    if not isinstance(history, list):
        history = []

    history.append(snapshot)
    audits[key] = history[-_MAX_AUDIT_HISTORY:]

    save_state(state)


def get_previous_audit(owner: str, repo: str) -> dict | None:
    """Return the most recent stored audit snapshot for *owner/repo*, or None."""
    try:
        state = load_state()
    except StateCorruptError:
        return None

    key = f"{owner}/{repo}"
    history = state.get("audit_results", {}).get(key)

    if history is None:
        return None

    # Handle legacy single-dict format
    if isinstance(history, dict):
        history = [history]
    if not isinstance(history, list) or not history:
        return None

    entry = history[-1]
    # Validate minimally: must be a dict with an "items" dict
    if not isinstance(entry, dict) or not isinstance(entry.get("items"), dict):
        return None

    return entry


def save_discover_cache(query_hash: str, query: str, repos: list[dict]) -> None:
    """Save search results to discover cache, keyed by query hash."""
    try:
        state = load_state()
    except StateCorruptError:
        state = _empty_state()

    cache = state.setdefault("discover_cache", {})
    cache[query_hash] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "repos": repos,
    }
    save_state(state)


def get_discover_cache(query_hash: str, max_age_hours: int = _DEFAULT_CACHE_TTL_HOURS) -> dict | None:
    """Return cached search results if fresh, else None."""
    try:
        state = load_state()
    except StateCorruptError:
        return None

    entry = state.get("discover_cache", {}).get(query_hash)
    if entry is None:
        return None

    cached_time = entry.get("timestamp", "")
    try:
        cached_dt = datetime.fromisoformat(cached_time)
        age = datetime.now(timezone.utc) - cached_dt
        if age.total_seconds() > max_age_hours * 3600:
            return None
    except (ValueError, TypeError):
        return None

    return entry


def _backup_corrupt_state() -> None:
    """Back up a corrupt state file before recreating."""
    if STATE_FILE.exists():
        backup = STATE_FILE.with_suffix(".json.bak")
        shutil.copy2(STATE_FILE, backup)


# --- Config management ---


def load_config() -> Config:
    """Load user config from ~/.give-back/config.yaml.

    Returns defaults if file doesn't exist or is invalid.
    Simple key-value parser — no PyYAML dependency.
    """
    if not CONFIG_FILE.exists():
        return Config()

    try:
        content = CONFIG_FILE.read_text()
        return _parse_config_yaml(content)
    except (ValueError, OSError) as exc:
        import sys

        print(f"Warning: Config file {CONFIG_FILE} invalid ({exc}), using defaults.", file=sys.stderr)
        return Config()


def _parse_config_yaml(content: str) -> Config:
    """Parse a minimal YAML config (two fields, one nested level).

    Supports:
      workspace_dir: ~/path
      handoff:
        command: "some command"
    """
    workspace_dir = Config.workspace_dir
    handoff_command = None

    in_handoff = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("workspace_dir:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                workspace_dir = value
            in_handoff = False

        elif stripped == "handoff:" or stripped.startswith("handoff:"):
            # Check if there's an inline value (shouldn't be, but handle it)
            after = stripped.split(":", 1)[1].strip()
            if after and after not in ("null", "~"):
                handoff_command = after.strip("\"'")
                in_handoff = False
            else:
                in_handoff = True

        elif in_handoff and stripped.startswith("command:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value and value not in ("null", "~"):
                handoff_command = value
            in_handoff = False

    return Config(workspace_dir=workspace_dir, handoff_command=handoff_command)
