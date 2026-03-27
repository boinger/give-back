"""Tests for guardrails.py pre-flight contribution checks."""

import httpx
import respx

from give_back.github_client import GitHubClient
from give_back.guardrails import (
    Severity,
    check_base_branch_freshness,
    check_dco_signoff,
    check_duplicate_pr,
    check_local_ci,
    check_pr_targets_correct_branch,
    check_staged_files_clean,
    check_unrelated_changes,
    run_pre_commit_checks,
    run_pre_pr_checks,
    run_pre_push_checks,
)


class TestStagedFilesClean:
    def test_clean(self):
        result = check_staged_files_clean(["src/main.py", "tests/test_main.py"])
        assert result.passed is True

    def test_claude_md_blocked(self):
        result = check_staged_files_clean(["src/main.py", "CLAUDE.md"])
        assert result.passed is False
        assert result.severity == Severity.BLOCK
        assert "CLAUDE.md" in result.message

    def test_claude_dir_blocked(self):
        result = check_staged_files_clean([".claude/settings.json", "src/main.py"])
        assert result.passed is False

    def test_give_back_dir_blocked(self):
        result = check_staged_files_clean([".give-back/state.json"])
        assert result.passed is False

    def test_agents_dir_blocked(self):
        result = check_staged_files_clean([".agents/skills/foo/SKILL.md"])
        assert result.passed is False

    def test_gemini_md_blocked(self):
        result = check_staged_files_clean(["GEMINI.md"])
        assert result.passed is False

    def test_empty_list(self):
        result = check_staged_files_clean([])
        assert result.passed is True


class TestDcoSignoff:
    def test_not_required(self):
        result = check_dco_signoff("fix: something", dco_required=False)
        assert result.passed is True
        assert result.severity == Severity.INFO

    def test_required_and_present(self):
        msg = "fix: something\n\nSigned-off-by: Jeff Vier <jeff@example.com>"
        result = check_dco_signoff(msg, dco_required=True)
        assert result.passed is True

    def test_required_and_missing(self):
        result = check_dco_signoff("fix: something", dco_required=True)
        assert result.passed is False
        assert result.severity == Severity.BLOCK
        assert "sign-off" in result.message.lower()

    def test_required_missing_with_hint(self):
        result = check_dco_signoff(
            "fix: something",
            dco_required=True,
            author_name="Jeff",
            author_email="jeff@example.com",
        )
        assert result.passed is False
        assert "Jeff" in result.message
        assert "jeff@example.com" in result.message


class TestUnrelatedChanges:
    def test_focused_changes(self):
        result = check_unrelated_changes(["src/foo.py", "src/bar.py"])
        assert result.passed is True

    def test_too_many_directories(self):
        files = [f"dir{i}/file.py" for i in range(10)]
        result = check_unrelated_changes(files)
        assert result.passed is False
        assert result.severity == Severity.WARN

    def test_unexpected_dirs_with_expected_paths(self):
        result = check_unrelated_changes(
            staged_files=["src/fix.py", "docs/readme.md", "config/other.yaml", "vendor/thing.go"],
            expected_paths=["src/fix.py"],
        )
        assert result.passed is False
        assert "outside the expected scope" in result.message

    def test_expected_paths_match(self):
        result = check_unrelated_changes(
            staged_files=["src/fix.py", "src/helper.py"],
            expected_paths=["src/target.py"],
        )
        assert result.passed is True  # same directory

    def test_empty(self):
        result = check_unrelated_changes([])
        assert result.passed is True


class TestLocalCi:
    def test_no_ci_commands(self):
        result = check_local_ci(ci_commands=None)
        assert result.passed is True

    def test_ci_not_run(self):
        result = check_local_ci(ci_commands=["make test", "make lint"], ci_results=None)
        assert result.passed is False
        assert result.severity == Severity.BLOCK
        assert "not run locally" in result.message

    def test_ci_passed(self):
        result = check_local_ci(
            ci_commands=["make test"],
            ci_results=[("make test", 0)],
        )
        assert result.passed is True

    def test_ci_failed(self):
        result = check_local_ci(
            ci_commands=["make test", "make lint"],
            ci_results=[("make test", 0), ("make lint", 1)],
        )
        assert result.passed is False
        assert "make lint" in result.message


class TestBaseBranchFreshness:
    def test_up_to_date(self):
        result = check_base_branch_freshness("fix/thing", "main", 0)
        assert result.passed is True

    def test_slightly_behind(self):
        result = check_base_branch_freshness("fix/thing", "main", 3)
        assert result.passed is True
        assert result.severity == Severity.INFO

    def test_significantly_behind(self):
        result = check_base_branch_freshness("fix/thing", "main", 20)
        assert result.passed is False
        assert "20 commits behind" in result.message


class TestDuplicatePr:
    @respx.mock
    def test_no_duplicates(self):
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={"total_count": 0, "items": []},
                headers={"X-RateLimit-Remaining": "29", "X-RateLimit-Limit": "30", "X-RateLimit-Reset": "9999999"},
            )
        )
        with GitHubClient(token="fake") as client:
            result = check_duplicate_pr(client, "owner", "repo", issue_number=42)
        assert result.passed is True

    @respx.mock
    def test_duplicate_found(self):
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={"total_count": 1, "items": [{"number": 99, "title": "Fix issue #42"}]},
                headers={"X-RateLimit-Remaining": "29", "X-RateLimit-Limit": "30", "X-RateLimit-Reset": "9999999"},
            )
        )
        with GitHubClient(token="fake") as client:
            result = check_duplicate_pr(client, "owner", "repo", issue_number=42)
        assert result.passed is False
        assert result.severity == Severity.BLOCK
        assert "#99" in result.message

    def test_no_issue_or_keywords(self):
        with GitHubClient(token="fake") as client:
            result = check_duplicate_pr(client, "owner", "repo")
        assert result.passed is True  # can't check without search terms


class TestPrTargetBranch:
    def test_correct(self):
        result = check_pr_targets_correct_branch("main", "main")
        assert result.passed is True

    def test_wrong(self):
        result = check_pr_targets_correct_branch("main", "develop")
        assert result.passed is False
        assert result.severity == Severity.BLOCK
        assert "develop" in result.message


class TestRunners:
    def test_pre_commit_runs_all(self):
        results = run_pre_commit_checks(
            staged_files=["src/main.py"],
            commit_message="fix: thing",
            dco_required=False,
        )
        assert len(results) == 3
        assert all(r.passed for r in results)

    def test_pre_push_runs_all(self):
        results = run_pre_push_checks(
            local_branch="fix/thing",
            base_branch="main",
            commits_behind=0,
            ci_commands=["make test"],
            ci_results=[("make test", 0)],
        )
        assert len(results) == 2
        assert all(r.passed for r in results)

    @respx.mock
    def test_pre_pr_runs_all(self):
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={"total_count": 0, "items": []},
                headers={"X-RateLimit-Remaining": "29", "X-RateLimit-Limit": "30", "X-RateLimit-Reset": "9999999"},
            )
        )
        with GitHubClient(token="fake") as client:
            results = run_pre_pr_checks(
                client=client,
                owner="owner",
                repo="repo",
                target_branch="main",
                expected_branch="main",
                issue_number=42,
            )
        assert len(results) == 2
        assert all(r.passed for r in results)
