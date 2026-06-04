"""Tests for the assess CLI command — argument parsing and error paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from give_back.cli.assess import assess
from give_back.exceptions import GiveBackError


class TestAssessArgParsing:
    def test_invalid_repo_arg_exits_nonzero(self):
        """A garbage repo string is rejected by _parse_repo and exits 1."""
        runner = CliRunner()
        result = runner.invoke(assess, ["not_a_repo_format"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_repo_arg(self):
        """Click rejects missing required argument with usage error."""
        runner = CliRunner()
        result = runner.invoke(assess, [])
        assert result.exit_code == 2  # Click usage error
        assert "Missing argument" in result.output or "REPO" in result.output


class TestAssessAuthFlow:
    def test_no_token_warns_but_proceeds(self):
        """Without a token, resolve_token prints a warning to stderr — handler still runs."""
        runner = CliRunner()
        with (
            patch("give_back.auth.resolve_token", return_value=None),
            patch("give_back.cli.assess.get_cached_assessment", return_value=None),
            patch("give_back.assess.run_assessment", side_effect=RuntimeError("no network")),
        ):
            result = runner.invoke(assess, ["pallets/flask"])
        # Either an unhandled error or a graceful exit — but not exit 0 with no work
        assert result.exit_code != 0 or "Warning" in result.output


class TestAssessCachedPath:
    """Characterization tests for the cache-hit fast path (exit-code routing).

    Pinned before extracting the cached exits into a helper — see
    plans/PLAN-sloppylint-cleanup.md (these lines were previously uncovered).
    """

    def _invoke_cached(self, assessment, args=None):
        cached = {"timestamp": "2026-01-01T00:00:00Z"}
        runner = CliRunner()
        with (
            patch("give_back.cli.assess.get_cached_assessment", return_value=cached),
            patch("give_back.state.reconstruct_assessment", return_value=(assessment, ["Sig"])),
            patch("give_back.cli.assess.print_assessment") as mock_print,
            patch("give_back.cli.assess.print_assessment_json") as mock_print_json,
            patch("give_back.cli.assess.print_cached_notice"),
        ):
            result = runner.invoke(assess, ["pallets/flask", *(args or [])])
        return result, mock_print, mock_print_json

    def test_cached_gate_fail_exits_3(self):
        assessment = SimpleNamespace(gate_passed=False, incomplete=False)
        result, mock_print, _ = self._invoke_cached(assessment)
        assert result.exit_code == 3
        mock_print.assert_called_once()

    def test_cached_incomplete_exits_2(self):
        assessment = SimpleNamespace(gate_passed=True, incomplete=True)
        result, _, _ = self._invoke_cached(assessment)
        assert result.exit_code == 2

    def test_cached_pass_exits_0(self):
        assessment = SimpleNamespace(gate_passed=True, incomplete=False)
        result, mock_print, mock_print_json = self._invoke_cached(assessment)
        assert result.exit_code == 0
        mock_print.assert_called_once()
        mock_print_json.assert_not_called()

    def test_cached_json_flag_uses_json_printer(self):
        assessment = SimpleNamespace(gate_passed=True, incomplete=False)
        result, mock_print, mock_print_json = self._invoke_cached(assessment, args=["--json"])
        assert result.exit_code == 0
        mock_print_json.assert_called_once()
        mock_print.assert_not_called()


class TestAssessDepsEmit:
    """Characterization tests for the --deps emit block.

    Pinned before extracting the block into a helper — see
    plans/PLAN-sloppylint-cleanup.md (these lines were previously uncovered).
    """

    def _invoke_deps(self, args, authenticated=True, walk_error=None):
        assessment = SimpleNamespace(gate_passed=True, incomplete=False)
        walk_result = object()
        walk_kwargs = {"side_effect": walk_error} if walk_error else {"return_value": walk_result}

        runner = CliRunner()
        with (
            patch("give_back.cli.assess.get_cached_assessment", return_value=None),
            patch("give_back.cli.assess.resolve_token", return_value="tok"),
            patch("give_back.cli.assess.GitHubClient") as mock_client_cls,
            patch("give_back.assess.run_assessment", return_value=assessment),
            patch("give_back.cli.assess.save_assessment"),
            patch("give_back.cli.assess.print_assessment"),
            patch("give_back.cli.assess.print_assessment_json"),
            patch("give_back.deps.walker.walk_deps", **walk_kwargs) as mock_walk,
            patch("give_back.output.print_deps") as mock_print_deps,
            patch("give_back.output.print_deps_json") as mock_print_deps_json,
        ):
            client = mock_client_cls.return_value.__enter__.return_value
            client.authenticated = authenticated
            result = runner.invoke(assess, ["pallets/flask", "--deps", *args])
        return result, walk_result, mock_walk, mock_print_deps, mock_print_deps_json

    def test_deps_human_output(self):
        result, walk_result, mock_walk, mock_print_deps, mock_print_deps_json = self._invoke_deps([])
        assert result.exit_code == 0
        mock_walk.assert_called_once()
        mock_print_deps.assert_called_once()
        assert mock_print_deps.call_args[0][0] is walk_result
        mock_print_deps_json.assert_not_called()

    def test_deps_json_output(self):
        result, walk_result, _mock_walk, mock_print_deps, mock_print_deps_json = self._invoke_deps(["--json"])
        assert result.exit_code == 0
        mock_print_deps_json.assert_called_once()
        assert mock_print_deps_json.call_args[0][0] is walk_result
        mock_print_deps.assert_not_called()

    def test_deps_unauthenticated_exits_1(self):
        result, _wr, mock_walk, _mpd, _mpdj = self._invoke_deps([], authenticated=False)
        assert result.exit_code == 1
        assert "requires authentication" in result.output
        mock_walk.assert_not_called()

    def test_deps_walk_failure_warns_but_succeeds(self):
        result, _wr, _mw, mock_print_deps, _mpdj = self._invoke_deps([], walk_error=GiveBackError("walk failed"))
        assert result.exit_code == 0
        assert "Dependency walking failed" in result.output
        mock_print_deps.assert_not_called()
