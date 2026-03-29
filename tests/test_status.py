"""Tests for the status command: workspace scanning, PR refresh, review aggregation, output."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from give_back.exceptions import GiveBackError, RepoNotFoundError
from give_back.output.status import print_status, print_status_json
from give_back.status import (
    ArchivedContribution,
    ContributionStatus,
    _aggregate_review_state,
    _extract_pr_number,
    check_contributions,
    scan_workspaces,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    owner: str = "pallets",
    repo: str = "flask",
    issue_number: int = 5432,
    branch_name: str = "give-back/5432-fix-x",
    status: str = "pr_open",
    pr_url: str | None = "https://github.com/pallets/flask/pull/6789",
    pr_number: int | None = 6789,
    fork_owner: str | None = "jeff",
    previous_issues: list[dict] | None = None,
) -> dict:
    ctx: dict = {
        "upstream_owner": owner,
        "repo": repo,
        "issue_number": issue_number,
        "branch_name": branch_name,
        "status": status,
    }
    if pr_url is not None:
        ctx["pr_url"] = pr_url
    if pr_number is not None:
        ctx["pr_number"] = pr_number
    if fork_owner is not None:
        ctx["fork_owner"] = fork_owner
    if previous_issues is not None:
        ctx["previous_issues"] = previous_issues
    return ctx


def _write_context(tmp_path: Path, owner: str, repo: str, ctx: dict) -> Path:
    """Write a context.json under tmp_path/owner/repo/.give-back/."""
    workspace = tmp_path / owner / repo
    gb_dir = workspace / ".give-back"
    gb_dir.mkdir(parents=True, exist_ok=True)
    (gb_dir / "context.json").write_text(json.dumps(ctx))
    return workspace


# ---------------------------------------------------------------------------
# scan_workspaces
# ---------------------------------------------------------------------------


class TestScanWorkspaces:
    def test_found(self, tmp_path: Path) -> None:
        ctx = _make_context()
        _write_context(tmp_path, "pallets", "flask", ctx)
        results = scan_workspaces(tmp_path)
        assert len(results) == 1
        assert results[0][1]["upstream_owner"] == "pallets"

    def test_multiple_sorted(self, tmp_path: Path) -> None:
        _write_context(tmp_path, "encode", "httpx", _make_context(owner="encode", repo="httpx"))
        _write_context(tmp_path, "astral", "ruff", _make_context(owner="astral", repo="ruff"))
        results = scan_workspaces(tmp_path)
        assert len(results) == 2
        # Sorted by path: astral before encode
        assert results[0][1]["upstream_owner"] == "astral"
        assert results[1][1]["upstream_owner"] == "encode"

    def test_empty_dir(self, tmp_path: Path) -> None:
        results = scan_workspaces(tmp_path)
        assert results == []

    def test_missing_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        results = scan_workspaces(missing)
        assert results == []

    def test_corrupt_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        workspace = tmp_path / "bad" / "repo"
        gb_dir = workspace / ".give-back"
        gb_dir.mkdir(parents=True)
        (gb_dir / "context.json").write_text("{invalid json")

        results = scan_workspaces(tmp_path)
        assert results == []


# ---------------------------------------------------------------------------
# _extract_pr_number
# ---------------------------------------------------------------------------


class TestExtractPrNumber:
    def test_valid_url(self) -> None:
        assert _extract_pr_number("https://github.com/pallets/flask/pull/6789") == 6789

    def test_invalid_url(self) -> None:
        assert _extract_pr_number("https://github.com/pallets/flask/issues/6789") is None

    def test_empty_string(self) -> None:
        assert _extract_pr_number("") is None

    def test_none_like(self) -> None:
        assert _extract_pr_number("") is None


# ---------------------------------------------------------------------------
# _aggregate_review_state
# ---------------------------------------------------------------------------


class TestAggregateReviewState:
    def test_single_approved(self) -> None:
        reviews = [{"user": {"login": "alice"}, "state": "APPROVED"}]
        assert _aggregate_review_state(reviews) == "approved"

    def test_changes_requested(self) -> None:
        reviews = [{"user": {"login": "alice"}, "state": "CHANGES_REQUESTED"}]
        assert _aggregate_review_state(reviews) == "changes_requested"

    def test_reviewer_changes_mind(self) -> None:
        """Reviewer approves then requests changes — latest wins."""
        reviews = [
            {"user": {"login": "alice"}, "state": "APPROVED"},
            {"user": {"login": "alice"}, "state": "CHANGES_REQUESTED"},
        ]
        assert _aggregate_review_state(reviews) == "changes_requested"

    def test_reviewer_approves_after_changes(self) -> None:
        """Reviewer requests changes then approves — latest wins."""
        reviews = [
            {"user": {"login": "alice"}, "state": "CHANGES_REQUESTED"},
            {"user": {"login": "alice"}, "state": "APPROVED"},
        ]
        assert _aggregate_review_state(reviews) == "approved"

    def test_no_reviews(self) -> None:
        assert _aggregate_review_state([]) is None

    def test_commented_only(self) -> None:
        """COMMENTED reviews are not actionable."""
        reviews = [{"user": {"login": "alice"}, "state": "COMMENTED"}]
        assert _aggregate_review_state(reviews) is None

    def test_dismissed_excluded(self) -> None:
        """DISMISSED reviews are not actionable."""
        reviews = [
            {"user": {"login": "alice"}, "state": "APPROVED"},
            {"user": {"login": "bob"}, "state": "DISMISSED"},
        ]
        assert _aggregate_review_state(reviews) == "approved"

    def test_mixed_reviewers(self) -> None:
        """One approves, another requests changes — changes_requested wins."""
        reviews = [
            {"user": {"login": "alice"}, "state": "APPROVED"},
            {"user": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
        ]
        assert _aggregate_review_state(reviews) == "changes_requested"


# ---------------------------------------------------------------------------
# check_contributions
# ---------------------------------------------------------------------------


class TestCheckContributions:
    def test_with_client_open_pr(self, tmp_path: Path) -> None:
        ctx = _make_context(status="pr_open", pr_number=100, pr_url="https://github.com/pallets/flask/pull/100")
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True
        # PR data
        client.rest_get.side_effect = [
            {"state": "open", "merged_at": None},  # PR info
            [{"user": {"login": "alice"}, "state": "APPROVED"}],  # reviews
        ]

        contributions, archived = check_contributions(client, workspace_dir=tmp_path)
        assert len(contributions) == 1
        assert contributions[0].pr_state == "open"
        assert contributions[0].review_state == "approved"
        assert not contributions[0].stale
        assert not contributions[0].local

    def test_with_client_merged_pr(self, tmp_path: Path) -> None:
        ctx = _make_context(status="pr_open", pr_number=100, pr_url="https://github.com/pallets/flask/pull/100")
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True
        client.rest_get.side_effect = [
            {"state": "closed", "merged_at": "2026-03-20T12:00:00Z"},  # PR info
            [{"user": {"login": "alice"}, "state": "APPROVED"}],  # reviews
        ]

        contributions, _ = check_contributions(client, workspace_dir=tmp_path)
        assert contributions[0].pr_state == "merged"

    def test_with_client_closed_pr(self, tmp_path: Path) -> None:
        ctx = _make_context(status="pr_open", pr_number=100, pr_url="https://github.com/pallets/flask/pull/100")
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True
        client.rest_get.side_effect = [
            {"state": "closed", "merged_at": None},  # PR info
            [],  # no reviews
        ]

        contributions, _ = check_contributions(client, workspace_dir=tmp_path)
        assert contributions[0].pr_state == "closed"
        assert contributions[0].review_state is None

    def test_without_client_local_mode(self, tmp_path: Path) -> None:
        ctx = _make_context(status="pr_open")
        _write_context(tmp_path, "pallets", "flask", ctx)

        contributions, _ = check_contributions(None, workspace_dir=tmp_path)
        assert len(contributions) == 1
        assert contributions[0].local is True
        assert contributions[0].pr_state == "open"

    def test_api_failure_marks_stale(self, tmp_path: Path) -> None:
        ctx = _make_context(status="pr_open", pr_number=100, pr_url="https://github.com/pallets/flask/pull/100")
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True
        client.rest_get.side_effect = GiveBackError("API error")

        contributions, _ = check_contributions(client, workspace_dir=tmp_path)
        assert contributions[0].stale is True
        assert contributions[0].pr_state == "open"  # falls back to local status mapping

    def test_repo_not_found_sets_skip_reason(self, tmp_path: Path) -> None:
        ctx = _make_context(status="pr_open", pr_number=100, pr_url="https://github.com/pallets/flask/pull/100")
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True
        client.rest_get.side_effect = RepoNotFoundError("Not found")

        contributions, _ = check_contributions(client, workspace_dir=tmp_path)
        assert contributions[0].skip_reason == "PR or repo deleted"

    def test_find_pr_for_branch_integration(self, tmp_path: Path) -> None:
        """When no pr_number, try find_pr_for_branch."""
        ctx = _make_context(
            status="working",
            pr_url=None,
            pr_number=None,
            fork_owner="jeff",
            branch_name="give-back/5432-fix-x",
        )
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True

        mock_pr_info = MagicMock()
        mock_pr_info.pr_number = 999
        mock_pr_info.pr_url = "https://github.com/pallets/flask/pull/999"
        mock_pr_info.state = "open"

        with patch("give_back.status.find_pr_for_branch", return_value=mock_pr_info):
            contributions, _ = check_contributions(client, workspace_dir=tmp_path)

        assert contributions[0].pr_number == 999
        assert contributions[0].pr_state == "open"

    def test_archived_entries(self, tmp_path: Path) -> None:
        prev = [
            {
                "issue_number": 100,
                "branch_name": "give-back/100-old",
                "status": "merged",
                "pr_url": "https://github.com/pallets/flask/pull/200",
                "archived_at": "2026-03-15T00:00:00Z",
            }
        ]
        ctx = _make_context(previous_issues=prev)
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True
        client.rest_get.side_effect = [
            {"state": "open", "merged_at": None},
            [],
        ]

        _, archived = check_contributions(client, workspace_dir=tmp_path)
        assert len(archived) == 1
        assert archived[0].issue_number == 100
        assert archived[0].pr_url == "https://github.com/pallets/flask/pull/200"
        assert archived[0].status == "merged"

    def test_archived_entry_without_pr_url(self, tmp_path: Path) -> None:
        prev = [
            {
                "issue_number": 50,
                "status": "working",
                "archived_at": "2026-02-01T00:00:00Z",
            }
        ]
        ctx = _make_context(previous_issues=prev)
        _write_context(tmp_path, "pallets", "flask", ctx)

        contributions, archived = check_contributions(None, workspace_dir=tmp_path)
        assert len(archived) == 1
        assert archived[0].pr_url is None
        assert archived[0].status == "working"

    def test_uses_config_workspace_dir(self, tmp_path: Path) -> None:
        """When workspace_dir is None, loads from config."""
        ctx = _make_context()
        _write_context(tmp_path, "pallets", "flask", ctx)

        mock_config = MagicMock()
        mock_config.workspace_dir = str(tmp_path)

        with patch("give_back.status.load_config", return_value=mock_config):
            contributions, _ = check_contributions(None)

        assert len(contributions) == 1

    def test_extract_pr_number_from_url(self, tmp_path: Path) -> None:
        """When pr_number is not in context, extract from pr_url."""
        ctx = _make_context(pr_number=None, pr_url="https://github.com/pallets/flask/pull/42")
        _write_context(tmp_path, "pallets", "flask", ctx)

        client = MagicMock()
        client.has_rate_budget.return_value = True
        client.rest_get.side_effect = [
            {"state": "open", "merged_at": None},
            [],
        ]

        contributions, _ = check_contributions(client, workspace_dir=tmp_path)
        assert contributions[0].pr_number == 42


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _capture_console(fn, *args, **kwargs) -> str:
    """Capture rich console output to a string."""
    buf = StringIO()
    console = Console(file=buf, width=120, no_color=True)
    with patch("give_back.output.status._console", console):
        fn(*args, **kwargs)
    return buf.getvalue()


class TestPrintStatus:
    def test_table_rendering(self) -> None:
        contributions = [
            ContributionStatus(
                owner="pallets",
                repo="flask",
                issue_number=5432,
                branch_name="give-back/5432-fix-x",
                pr_url="https://github.com/pallets/flask/pull/6789",
                pr_number=6789,
                pr_state="open",
                review_state="changes_requested",
                workspace_path="/tmp/ws/pallets/flask",
            ),
        ]
        output = _capture_console(print_status, contributions, [])
        assert "pallets/flask" in output
        assert "#5432" in output
        assert "#6789" in output
        assert "open" in output
        assert "changes_requested" in output

    def test_empty_results(self) -> None:
        output = _capture_console(print_status, [], [])
        assert "No tracked contributions found" in output

    def test_stale_marker(self) -> None:
        contributions = [
            ContributionStatus(
                owner="pallets",
                repo="flask",
                issue_number=1,
                branch_name="fix",
                pr_state="open",
                stale=True,
            ),
        ]
        output = _capture_console(print_status, contributions, [])
        assert "(stale)" in output

    def test_local_marker(self) -> None:
        contributions = [
            ContributionStatus(
                owner="pallets",
                repo="flask",
                issue_number=1,
                branch_name="fix",
                pr_state="open",
                local=True,
            ),
        ]
        output = _capture_console(print_status, contributions, [])
        assert "(local)" in output

    def test_skip_reason_shown(self) -> None:
        contributions = [
            ContributionStatus(
                owner="pallets",
                repo="flask",
                issue_number=1,
                branch_name="fix",
                skip_reason="PR or repo deleted",
            ),
        ]
        output = _capture_console(print_status, contributions, [])
        assert "PR or repo deleted" in output

    def test_archived_footer(self) -> None:
        archived = [
            ArchivedContribution(
                owner="pallets",
                repo="flask",
                issue_number=100,
                pr_url="https://github.com/pallets/flask/pull/200",
                status="merged",
                archived_at="2026-03-15T00:00:00Z",
            ),
        ]
        output = _capture_console(print_status, [], archived)
        assert "1 archived contribution(s)" in output
        assert "--verbose" in output

    def test_verbose_shows_archived(self) -> None:
        archived = [
            ArchivedContribution(
                owner="pallets",
                repo="flask",
                issue_number=100,
                pr_url="https://github.com/pallets/flask/pull/200",
                status="merged",
                archived_at="2026-03-15T00:00:00Z",
            ),
        ]
        output = _capture_console(print_status, [], archived, verbose=True)
        assert "Archived:" in output
        assert "#100" in output
        assert "merged" in output
        assert "2026-03-15" in output


class TestPrintStatusJson:
    def test_json_structure(self, capsys: pytest.CaptureFixture[str]) -> None:
        contributions = [
            ContributionStatus(
                owner="pallets",
                repo="flask",
                issue_number=5432,
                branch_name="give-back/5432-fix-x",
                pr_url="https://github.com/pallets/flask/pull/6789",
                pr_number=6789,
                pr_state="open",
                review_state="approved",
                workspace_path="/tmp/ws",
            ),
        ]
        archived = [
            ArchivedContribution(
                owner="pallets",
                repo="flask",
                issue_number=100,
                pr_url=None,
                status="working",
                archived_at="2026-02-01T00:00:00Z",
            ),
        ]
        print_status_json(contributions, archived)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["contributions"]) == 1
        assert data["contributions"][0]["owner"] == "pallets"
        assert data["contributions"][0]["pr_state"] == "open"
        assert data["contributions"][0]["review_state"] == "approved"
        assert len(data["archived"]) == 1
        assert data["archived"][0]["pr_url"] is None

    def test_empty_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_status_json([], [])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["contributions"] == []
        assert data["archived"] == []
