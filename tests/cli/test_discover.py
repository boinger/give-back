"""CLI-layer tests for the discover command.

T15-T18: test the --auto-fallback flag tri-state resolution,
interactive loop shown_count tracking, and JSON opt-in behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from give_back.cli.discover import discover
from give_back.discover.search import DiscoverResult, DiscoverSummary
from give_back.models import Tier


def _make_result(owner: str, repo: str = "r") -> DiscoverResult:
    return DiscoverResult(
        owner=owner,
        repo=repo,
        description="desc",
        stars=100,
        language="Go",
        topics=[],
        open_issue_count=10,
        good_first_issue_count=0,
        tier=Tier.GREEN,
    )


def _sparse_summary_with_fallback() -> DiscoverSummary:
    """Summary with 2 gated + 3 fallback repos (sparse, fallback fired)."""
    return DiscoverSummary(
        query="q",
        total_searched=2,
        assessed_count=5,
        results=[_make_result("gated", "r1"), _make_result("gated", "r2")],
        fallback_results=[
            _make_result("fallback", "r3"),
            _make_result("fallback", "r4"),
            _make_result("fallback", "r5"),
        ],
        fallback_triggered=True,
        label_gate_active=True,
    )


def _sparse_summary_no_fallback() -> DiscoverSummary:
    """Summary with 2 gated repos, no fallback (auto_fallback was False)."""
    return DiscoverSummary(
        query="q",
        total_searched=2,
        assessed_count=2,
        results=[_make_result("gated", "r1"), _make_result("gated", "r2")],
        fallback_triggered=False,
        label_gate_active=True,
    )


class TestAutoFallbackTriState:
    """T15-T17: tri-state --auto-fallback resolution."""

    @patch("give_back.cli.discover.resolve_token", return_value="fake")
    @patch("give_back.cli.discover.GitHubClient")
    @patch("give_back.discover.search.discover_repos")
    def test_default_terminal_enables_fallback(self, mock_discover, mock_client_cls, mock_token):
        """T15: Default terminal invocation → auto_fallback=True passed to discover_repos."""
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_discover.return_value = _sparse_summary_with_fallback()

        runner = CliRunner()
        result = runner.invoke(discover, ["--topic", "test", "--limit", "10"])

        assert result.exit_code == 0
        call_kwargs = mock_discover.call_args[1]
        assert call_kwargs["auto_fallback"] is True

    @patch("give_back.cli.discover.resolve_token", return_value="fake")
    @patch("give_back.cli.discover.GitHubClient")
    @patch("give_back.discover.search.discover_repos")
    def test_no_auto_fallback_disables(self, mock_discover, mock_client_cls, mock_token):
        """T16: --no-auto-fallback → auto_fallback=False."""
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_discover.return_value = _sparse_summary_no_fallback()

        runner = CliRunner()
        result = runner.invoke(discover, ["--topic", "test", "--no-auto-fallback"])

        assert result.exit_code == 0
        call_kwargs = mock_discover.call_args[1]
        assert call_kwargs["auto_fallback"] is False

    @patch("give_back.cli.discover.resolve_token", return_value="fake")
    @patch("give_back.cli.discover.GitHubClient")
    @patch("give_back.discover.search.discover_repos")
    def test_json_default_disables_fallback(self, mock_discover, mock_client_cls, mock_token):
        """T17: --json without --auto-fallback → auto_fallback=False."""
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_discover.return_value = _sparse_summary_no_fallback()

        runner = CliRunner()
        result = runner.invoke(discover, ["--topic", "test", "--json"])

        assert result.exit_code == 0
        call_kwargs = mock_discover.call_args[1]
        assert call_kwargs["auto_fallback"] is False

    @patch("give_back.cli.discover.resolve_token", return_value="fake")
    @patch("give_back.cli.discover.GitHubClient")
    @patch("give_back.discover.search.discover_repos")
    def test_json_with_explicit_auto_fallback(self, mock_discover, mock_client_cls, mock_token):
        """--json --auto-fallback → auto_fallback=True (explicit override)."""
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_discover.return_value = _sparse_summary_with_fallback()

        runner = CliRunner()
        result = runner.invoke(discover, ["--topic", "test", "--json", "--auto-fallback"])

        assert result.exit_code == 0
        call_kwargs = mock_discover.call_args[1]
        assert call_kwargs["auto_fallback"] is True


class TestInteractiveLoopWithFallback:
    """T18: Interactive loop tracks shown_count across both pools."""

    @patch("give_back.cli.discover.sys")
    @patch("give_back.cli.discover.resolve_token", return_value="fake")
    @patch("give_back.cli.discover.GitHubClient")
    @patch("give_back.discover.search.discover_repos")
    def test_shown_count_includes_fallback(self, mock_discover, mock_client_cls, mock_token, mock_sys):
        """T18: After first batch with fallback, shown_count = primary + fallback."""
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        # Make sys.stdin.isatty() return True so the interactive loop fires
        mock_sys.stdin.isatty.return_value = True
        mock_sys.exit.side_effect = SystemExit

        first_summary = DiscoverSummary(
            query="q",
            total_searched=20,
            assessed_count=5,
            results=[_make_result("gated", f"r{i}") for i in range(3)],
            fallback_results=[_make_result("fb", f"r{i}") for i in range(7)],
            fallback_triggered=True,
            label_gate_active=True,
        )
        # Second call returns more results (limit increased)
        second_summary = DiscoverSummary(
            query="q",
            total_searched=20,
            assessed_count=8,
            results=[_make_result("gated", f"r{i}") for i in range(3)],
            fallback_results=[_make_result("fb", f"r{i}") for i in range(12)],
            fallback_triggered=True,
            label_gate_active=True,
        )
        mock_discover.side_effect = [first_summary, second_summary]

        runner = CliRunner()
        # Simulate: first display, then "yes" to confirm, then "no" to stop
        result = runner.invoke(
            discover,
            ["--topic", "test", "--interactive", "--limit", "10"],
            input="y\nn\n",
        )

        assert result.exit_code == 0
        assert len(mock_discover.call_args_list) >= 2, (
            f"Expected 2+ discover_repos calls, got {len(mock_discover.call_args_list)}"
        )
        # The second call should have limit = shown_count(10) + batch_size(5) = 15
        second_call_kwargs = mock_discover.call_args_list[1][1]
        assert second_call_kwargs["limit"] == 15  # 10 shown + 5 batch
