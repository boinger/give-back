"""Tests for state.py."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from give_back.exceptions import StateCorruptError
from give_back.models import Assessment, SignalResult, Tier
from give_back.state import (
    _empty_state,
    _parse_config_yaml,
    add_to_skip_list,
    get_cached_assessment,
    get_skip_list,
    load_config,
    load_state,
    reconstruct_assessment,
    remove_from_skip_list,
    save_assessment,
    save_state,
)


@pytest.fixture
def state_dir(tmp_path):
    """Use a temp directory for state file and config."""
    state_file = tmp_path / "state.json"
    config_file = tmp_path / "config.yaml"
    with (
        patch("give_back.state.STATE_DIR", tmp_path),
        patch("give_back.state.STATE_FILE", state_file),
        patch("give_back.state.CONFIG_FILE", config_file),
    ):
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


class TestSkipList:
    def test_add_to_skip_list(self, state_dir):
        add_to_skip_list("google/protobuf")
        assert "google/protobuf" in get_skip_list()

    def test_add_deduplicates_case_insensitive(self, state_dir):
        add_to_skip_list("google/protobuf")
        add_to_skip_list("Google/Protobuf")
        add_to_skip_list("google/protobuf")
        assert len(get_skip_list()) == 1

    def test_remove_from_skip_list(self, state_dir):
        add_to_skip_list("google/protobuf")
        add_to_skip_list("encode/httpx")
        remove_from_skip_list("google/protobuf")
        skip = get_skip_list()
        assert "google/protobuf" not in skip
        assert "encode/httpx" in skip

    def test_remove_case_insensitive(self, state_dir):
        add_to_skip_list("Google/Protobuf")
        remove_from_skip_list("google/protobuf")
        assert len(get_skip_list()) == 0

    def test_get_skip_list_empty(self, state_dir):
        assert get_skip_list() == []

    def test_get_skip_list_after_corrupt_state(self, state_dir):
        _, state_file = state_dir
        state_file.write_text("not json")
        # get_skip_list handles StateCorruptError gracefully
        assert get_skip_list() == []

    def test_add_after_corrupt_state(self, state_dir):
        _, state_file = state_dir
        state_file.write_text("not json")
        # add_to_skip_list handles StateCorruptError by recreating state
        add_to_skip_list("encode/httpx")
        assert "encode/httpx" in get_skip_list()


class TestParseConfigYaml:
    def test_valid_config(self):
        content = 'workspace_dir: ~/my-workspaces\nhandoff:\n  command: "code ."'
        config = _parse_config_yaml(content)
        assert config.workspace_dir == "~/my-workspaces"
        assert config.handoff_command == "code ."

    def test_comments_and_blank_lines(self):
        content = "# A comment\n\nworkspace_dir: ~/ws\n\n# another comment\n"
        config = _parse_config_yaml(content)
        assert config.workspace_dir == "~/ws"
        assert config.handoff_command is None

    def test_empty_content(self):
        config = _parse_config_yaml("")
        assert config.workspace_dir == "~/give-back-workspaces"
        assert config.handoff_command is None

    def test_only_handoff(self):
        content = 'handoff:\n  command: "cursor ."'
        config = _parse_config_yaml(content)
        assert config.handoff_command == "cursor ."

    def test_inline_handoff_value(self):
        content = 'handoff: "code ."'
        config = _parse_config_yaml(content)
        assert config.handoff_command == "code ."


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, state_dir):
        config = load_config()
        assert config.workspace_dir == "~/give-back-workspaces"
        assert config.handoff_command is None

    def test_valid_file(self, state_dir):
        tmp, _ = state_dir
        config_file = tmp / "config.yaml"
        config_file.write_text('workspace_dir: ~/ws\nhandoff:\n  command: "code ."')
        with patch("give_back.state.CONFIG_FILE", config_file):
            config = load_config()
        assert config.workspace_dir == "~/ws"
        assert config.handoff_command == "code ."


class TestReconstructAssessment:
    def test_round_trip(self, state_dir):
        """Save an assessment, retrieve cached, reconstruct, and compare."""
        now = datetime.now(timezone.utc).isoformat()
        original = Assessment(
            owner="pallets",
            repo="flask",
            overall_tier=Tier.GREEN,
            signals=[
                SignalResult(score=1.0, tier=Tier.GREEN, summary="MIT License"),
                SignalResult(score=0.8, tier=Tier.GREEN, summary="82% merge rate"),
            ],
            gate_passed=True,
            incomplete=False,
            timestamp=now,
        )
        save_assessment(original, signal_names=["License", "PR Merge Rate"])
        cached = get_cached_assessment("pallets", "flask")
        assert cached is not None

        rebuilt, names = reconstruct_assessment(cached, "pallets", "flask")
        assert rebuilt.overall_tier == original.overall_tier
        assert rebuilt.gate_passed == original.gate_passed
        assert rebuilt.incomplete == original.incomplete
        assert len(rebuilt.signals) == len(original.signals)
        assert rebuilt.signals[0].score == original.signals[0].score
        assert rebuilt.signals[0].tier == original.signals[0].tier
        assert names == ["License", "PR Merge Rate"]

    def test_reconstruct_without_names_returns_empty(self, state_dir):
        """Old caches without signal names still reconstruct with empty name strings."""
        now = datetime.now(timezone.utc).isoformat()
        original = Assessment(
            owner="pallets",
            repo="flask",
            overall_tier=Tier.GREEN,
            signals=[SignalResult(score=0.9, tier=Tier.GREEN, summary="OK")],
            gate_passed=True,
            incomplete=False,
            timestamp=now,
        )
        # Save without names (simulates old cache format)
        save_assessment(original)
        cached = get_cached_assessment("pallets", "flask")
        assert cached is not None

        _, names = reconstruct_assessment(cached, "pallets", "flask")
        assert names == [""]

    def test_invalid_tier_raises(self):
        cached = {"overall_tier": "invalid", "signals": []}
        with pytest.raises(ValueError):
            reconstruct_assessment(cached, "a", "b")

    def test_missing_tier_raises(self):
        cached = {"signals": []}
        with pytest.raises(ValueError):
            reconstruct_assessment(cached, "a", "b")
