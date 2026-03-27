"""Tests for state.py."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from give_back.exceptions import StateCorruptError
from give_back.models import Assessment, SignalResult, Tier
from give_back.state import (
    _empty_state,
    get_cached_assessment,
    load_state,
    save_assessment,
    save_state,
)


@pytest.fixture
def state_dir(tmp_path):
    """Use a temp directory for state file."""
    state_file = tmp_path / "state.json"
    with patch("give_back.state.STATE_DIR", tmp_path), patch("give_back.state.STATE_FILE", state_file):
        yield tmp_path, state_file


class TestLoadState:
    def test_no_file_returns_empty(self, state_dir):
        state = load_state()
        assert state == _empty_state()
        assert state["version"] == 1

    def test_valid_file(self, state_dir):
        _, state_file = state_dir
        state_file.write_text(json.dumps({"version": 1, "assessments": {}, "skip_list": []}))
        state = load_state()
        assert state["version"] == 1

    def test_corrupt_json_raises_and_backs_up(self, state_dir):
        _, state_file = state_dir
        state_file.write_text("not json at all")
        with pytest.raises(StateCorruptError):
            load_state()
        assert state_file.with_suffix(".json.bak").exists()

    def test_missing_version_raises(self, state_dir):
        _, state_file = state_dir
        state_file.write_text(json.dumps({"assessments": {}}))
        with pytest.raises(StateCorruptError):
            load_state()


class TestSaveState:
    def test_creates_dir_and_file(self, state_dir):
        tmp, state_file = state_dir
        save_state(_empty_state())
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["version"] == 1

    def test_atomic_write(self, state_dir):
        """Verify no partial writes — file should always be valid JSON."""
        _, state_file = state_dir
        save_state({"version": 1, "assessments": {"a/b": {}}, "skip_list": []})
        data = json.loads(state_file.read_text())
        assert "a/b" in data["assessments"]


class TestSaveAssessment:
    def test_saves_and_retrieves(self, state_dir):
        now = datetime.now(timezone.utc).isoformat()
        assessment = Assessment(
            owner="pallets",
            repo="flask",
            overall_tier=Tier.GREEN,
            signals=[SignalResult(score=1.0, tier=Tier.GREEN, summary="MIT License")],
            gate_passed=True,
            incomplete=False,
            timestamp=now,
        )
        save_assessment(assessment)

        cached = get_cached_assessment("pallets", "flask")
        assert cached is not None
        assert cached["overall_tier"] == "green"

    def test_cache_expired(self, state_dir):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        assessment = Assessment(
            owner="pallets",
            repo="flask",
            overall_tier=Tier.GREEN,
            signals=[],
            gate_passed=True,
            incomplete=False,
            timestamp=old_time,
        )
        save_assessment(assessment)

        cached = get_cached_assessment("pallets", "flask")
        assert cached is None  # Expired

    def test_cache_fresh(self, state_dir):
        now = datetime.now(timezone.utc).isoformat()
        assessment = Assessment(
            owner="pallets",
            repo="flask",
            overall_tier=Tier.GREEN,
            signals=[],
            gate_passed=True,
            incomplete=False,
            timestamp=now,
        )
        save_assessment(assessment)

        cached = get_cached_assessment("pallets", "flask")
        assert cached is not None

    def test_nonexistent_repo_returns_none(self, state_dir):
        assert get_cached_assessment("no", "such") is None
