"""Contract tests for the `--json` output guarantee.

Pins the production contract documented in README.md's "Machine-readable
output (`--json`)" section: under `--json`, stdout is strictly a JSON
document. The skill-install hint is TTY-gated so that piping, `2>&1`
merges, subprocess capture, and CI all produce clean stdout.

The unit tests exercise the gate logic directly. The subprocess test is
the only faithful reproduction of the real-world failure mode (shell
`2>&1` / `subprocess.run(stderr=STDOUT)`) — in-process simulation via
CliRunner doesn't work because Click's stream wrappers and Rich's stderr
binding make stream merging unreliable to simulate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest


class TestJsonContractUnit:
    """Unit-level: the hint gate short-circuits before stderr_console is ever
    called, so stdout stays clean for machine consumers."""

    def test_hint_short_circuits_when_stdout_not_tty(self, tmp_path, capsys):
        """Calling _check_skill_installed_hint() when stdout is non-TTY
        produces zero stdout and zero stderr output (the gate returns before
        any print happens)."""
        from unittest.mock import patch

        from give_back.cli import _check_skill_installed_hint

        fake_home = tmp_path / "home"
        fake_home.mkdir()

        with (
            patch("give_back.cli.Path.home", return_value=fake_home),
            patch("give_back.hints._stdout_isatty", return_value=False),
            patch("give_back.hints._stderr_isatty", return_value=True),
        ):
            _check_skill_installed_hint()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestJsonContractIntegration:
    """End-to-end subprocess tests that reproduce the real `2>&1` failure
    mode the gate is designed to fix.

    Target command: `give-back status --json --dir <empty-tmp-dir>`.
    Chosen because:
    - `prepare` is destructive (creates workspace, clones, may fork) and has
      no `--dry-run`.
    - `assess` and `audit` both make real GitHub API calls. Flaky.
    - `check` doesn't support `--json`.
    - `status --json` reads only local workspace state. With `--dir` pointed
      at an empty tmp directory, it iterates zero context.json files, makes
      zero API calls, and returns a deterministic empty JSON payload.

    Env setup:
    - `GITHUB_TOKEN=fake-test-token` so resolve_token() returns cleanly and
      the "No auth token" warning is suppressed. The client is constructed
      but never used (empty workspace, no API calls).
    - `HOME=<tmp_path>` so the skill-install marker check sees no skill file
      and the hint path is actually triggered (the thing the gate must
      suppress).
    """

    def _run_status(self, tmp_path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        workspace = tmp_path / "empty_workspace"
        workspace.mkdir()
        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "GITHUB_TOKEN": "fake-test-token",
        }
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "give_back", "status", "--json", "--dir", str(workspace)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            timeout=10,
        )

    def test_status_json_clean_under_stderr_merge(self, tmp_path):
        """Default behavior (GIVE_BACK_HINTS=auto implicit): under `2>&1`,
        stdout is parseable JSON — no hint leakage, no warnings (empty
        workspace)."""
        result = self._run_status(tmp_path)

        assert result.returncode == 0, f"exit {result.returncode}: {result.stdout!r}"
        # The merged stdout+stderr must parse as JSON — no 'Tip:' prefix,
        # no non-JSON lines.
        data = json.loads(result.stdout)
        # Empty workspace → empty contributions and archived lists.
        assert data == {"contributions": [], "archived": []}

    def test_status_json_clean_with_hints_never(self, tmp_path):
        """GIVE_BACK_HINTS=never is belt-and-braces: even if someone
        somehow lands on a TTY path, the hint is suppressed. Stdout is
        still clean JSON."""
        result = self._run_status(tmp_path, extra_env={"GIVE_BACK_HINTS": "never"})

        assert result.returncode == 0, f"exit {result.returncode}: {result.stdout!r}"
        data = json.loads(result.stdout)
        assert data == {"contributions": [], "archived": []}

    def test_status_json_polluted_with_hints_always(self, tmp_path):
        """GIVE_BACK_HINTS=always is the user-opted-in override: the hint
        prints regardless of TTY, so under `2>&1` it pollutes stdout and
        json.loads fails. This test pins that trade-off so the override
        semantics can't silently change.

        Users who set GIVE_BACK_HINTS=always are explicitly choosing
        'always show me the nag' over 'always keep stdout clean'.
        """
        result = self._run_status(tmp_path, extra_env={"GIVE_BACK_HINTS": "always"})

        assert result.returncode == 0, f"exit {result.returncode}: {result.stdout!r}"
        # The hint line is present, so json.loads on the full blob fails.
        assert "Tip: run 'give-back skill install'" in result.stdout
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)

        # But the JSON payload itself is still valid — the gate only gates the
        # hint, not the JSON output. A caller who strips the hint line gets
        # clean JSON back.
        lines = result.stdout.split("\n", 1)
        remainder = lines[1] if len(lines) > 1 else ""
        data = json.loads(remainder)
        assert data == {"contributions": [], "archived": []}


class TestAssessJsonCacheNotice:
    """The cache notice in `give-back assess` must go to stderr, not stdout.

    Otherwise ``assess <repo> --json | jq`` breaks on the second run within
    the cache TTL: the dim "Using cached assessment from ..." line lands
    above the JSON payload and `json.loads(stdout)` fails.

    Unit-level pins the function-level contract; subprocess test pins the
    end-to-end behavior the way real callers experience it.
    """

    def test_print_cached_notice_writes_to_stderr_not_stdout(self, capsys):
        """``print_cached_notice`` must emit to stderr so stdout stays clean
        for ``--json`` consumers."""
        from give_back.output.assess import print_cached_notice

        print_cached_notice("fake", "repo", "2026-04-25T12:00:00+00:00")

        captured = capsys.readouterr()
        assert captured.out == "", f"stdout must be empty, got: {captured.out!r}"
        assert "Using cached assessment" in captured.err
        assert "2026-04-25T12:00:00+00:00" in captured.err

    def _write_cached_state(self, tmp_path, owner: str, repo: str) -> None:
        """Hand-roll a state.json with one fresh cached assessment.

        Schema is pinned to ``state.save_assessment``'s output (state.py:80).
        Hand-rolling rather than calling save_assessment from the test process
        because state.STATE_DIR is computed from Path.home() at import time,
        so monkey-patching after import has no effect; writing the file
        directly is more explicit.
        """
        state_dir = tmp_path / ".give-back"
        state_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        state = {
            "version": 1,
            "assessments": {
                f"{owner}/{repo}": {
                    "timestamp": now,
                    "overall_tier": "green",
                    "gate_passed": True,
                    "incomplete": False,
                    "signals": [],
                }
            },
            "skip_list": [],
            "audit_results": {},
        }
        (state_dir / "state.json").write_text(json.dumps(state))

    def _run_assess(self, tmp_path, owner: str, repo: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "GITHUB_TOKEN": "fake-test-token",
        }
        return subprocess.run(
            [sys.executable, "-m", "give_back", "assess", f"{owner}/{repo}", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=10,
        )

    def test_assess_json_cache_hit_clean_stdout(self, tmp_path):
        """`assess <repo> --json` against a cached repo: stdout is clean JSON,
        cache notice lands on stderr."""
        self._write_cached_state(tmp_path, "fake", "repo")

        result = self._run_assess(tmp_path, "fake", "repo")

        assert result.returncode == 0, f"exit {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"

        # Stdout: strictly JSON, parseable.
        data = json.loads(result.stdout)
        assert data["owner"] == "fake"
        assert data["repo"] == "repo"
        assert data["overall_tier"] == "green"

        # Stderr: cache notice was emitted (proves it ran, just to the right stream).
        assert "Using cached assessment" in result.stderr

    def test_assess_json_cache_hit_2to1_merge_contains_both(self, tmp_path):
        """Under `2>&1` merge, the merged stream contains BOTH the cache
        notice AND the JSON payload — caller's documented trade-off when they
        merge streams.

        This test exists to pin the contract the README documents: warnings/
        notices on stderr will pollute a merged stream. That's the caller's
        choice, not a bug.
        """
        self._write_cached_state(tmp_path, "fake", "repo")

        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "GITHUB_TOKEN": "fake-test-token",
        }
        merged = subprocess.run(
            [sys.executable, "-m", "give_back", "assess", "fake/repo", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            timeout=10,
        )

        assert merged.returncode == 0, f"exit {merged.returncode}: {merged.stdout!r}"
        # Merged stream has both: notice line + JSON payload.
        assert "Using cached assessment" in merged.stdout
        assert '"owner": "fake"' in merged.stdout
        # As documented, json.loads on the merged blob fails.
        with pytest.raises(json.JSONDecodeError):
            json.loads(merged.stdout)
