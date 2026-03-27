"""Tests for conventions/branches.py branch naming analysis."""

import httpx
import respx

from give_back.conventions.branches import analyze_branch_names
from give_back.github_client import GitHubClient

_RATE_HEADERS = {
    "X-RateLimit-Remaining": "4999",
    "X-RateLimit-Limit": "5000",
    "X-RateLimit-Reset": "9999999",
}


def _make_pr(ref: str, merged: bool = True, fork: bool = False) -> dict:
    """Build a minimal PR payload."""
    pr: dict = {
        "number": 1,
        "title": f"PR for {ref}",
        "merged_at": "2026-03-25T12:00:00Z" if merged else None,
        "head": {
            "ref": ref,
            "repo": {"full_name": "other/repo" if fork else "test/repo"},
        },
    }
    return pr


@respx.mock
def test_type_description_pattern() -> None:
    """PRs with type/description branches produce the type/description pattern."""
    prs = [
        _make_pr("fix/broken-login"),
        _make_pr("feat/add-auth"),
        _make_pr("docs/update-readme"),
        _make_pr("chore/bump-deps"),
    ]
    respx.get("https://api.github.com/repos/test/repo/pulls").mock(
        return_value=httpx.Response(200, json=prs, headers=_RATE_HEADERS)
    )

    client = GitHubClient(token="fake")
    result = analyze_branch_names(client, "test", "repo")

    assert result.pattern == "type/description"
    assert len(result.examples) > 0
    assert "fix/broken-login" in result.examples


@respx.mock
def test_issue_pattern() -> None:
    """PRs with issue-linked branches produce the issue-description pattern."""
    prs = [
        _make_pr("42-fix-login"),
        _make_pr("gh-99-add-feature"),
        _make_pr("issue-55-update"),
        _make_pr("123-refactor"),
    ]
    respx.get("https://api.github.com/repos/test/repo/pulls").mock(
        return_value=httpx.Response(200, json=prs, headers=_RATE_HEADERS)
    )

    client = GitHubClient(token="fake")
    result = analyze_branch_names(client, "test", "repo")

    assert result.pattern == "issue-description"
    assert len(result.examples) > 0


@respx.mock
def test_mixed_pattern() -> None:
    """No clear majority pattern returns mixed."""
    prs = [
        _make_pr("fix/broken-login"),
        _make_pr("42-fix-login"),
        _make_pr("random-branch-name"),
        _make_pr("another-random"),
    ]
    respx.get("https://api.github.com/repos/test/repo/pulls").mock(
        return_value=httpx.Response(200, json=prs, headers=_RATE_HEADERS)
    )

    client = GitHubClient(token="fake")
    result = analyze_branch_names(client, "test", "repo")

    assert result.pattern == "mixed"


@respx.mock
def test_few_prs() -> None:
    """Fewer than 3 merged PRs returns unknown."""
    prs = [
        _make_pr("fix/thing"),
        _make_pr("not-merged", merged=False),
    ]
    respx.get("https://api.github.com/repos/test/repo/pulls").mock(
        return_value=httpx.Response(200, json=prs, headers=_RATE_HEADERS)
    )

    client = GitHubClient(token="fake")
    result = analyze_branch_names(client, "test", "repo")

    assert result.pattern == "unknown"


@respx.mock
def test_skips_fork_branches() -> None:
    """Branches named 'main' or 'master' (from forks) are skipped."""
    prs = [
        _make_pr("main", fork=True),
        _make_pr("master", fork=True),
        _make_pr("fix/actual-work"),
        _make_pr("feat/another"),
    ]
    respx.get("https://api.github.com/repos/test/repo/pulls").mock(
        return_value=httpx.Response(200, json=prs, headers=_RATE_HEADERS)
    )

    client = GitHubClient(token="fake")
    result = analyze_branch_names(client, "test", "repo")

    # Only 2 valid branches — below threshold.
    assert result.pattern == "unknown"
    assert "main" not in result.examples
    assert "master" not in result.examples


@respx.mock
def test_api_error_returns_unknown() -> None:
    """API errors return unknown pattern gracefully."""
    respx.get("https://api.github.com/repos/test/repo/pulls").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"}, headers=_RATE_HEADERS)
    )

    client = GitHubClient(token="fake")
    result = analyze_branch_names(client, "test", "repo")

    assert result.pattern == "unknown"
