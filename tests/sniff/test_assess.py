"""Tests for sniff/assess.py — heuristic code quality assessment."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from give_back.github_client import GitHubClient
from give_back.sniff.assess import _compute_max_indent_depth, _compute_verdict, assess_issue
from give_back.sniff.models import FileAssessment

_RATE_HEADERS = {
    "X-RateLimit-Remaining": "4999",
    "X-RateLimit-Limit": "5000",
    "X-RateLimit-Reset": "9999999999",
}


@pytest.fixture
def client():
    c = GitHubClient(token="fake")
    yield c
    c.close()


def _mock_issue(number: int = 42, title: str = "Fix the bug", body: str = "See `src/foo.py` for details"):
    """Return a mock issue JSON response."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": "open",
    }


def _encode_content(text: str) -> str:
    """Base64 encode text content like the GitHub contents API returns."""
    return base64.b64encode(text.encode()).decode()


def _small_file_content() -> str:
    """A small, clean file (under 500 lines, shallow nesting)."""
    lines = ["def hello():", "    print('hi')", ""] * 50
    return "\n".join(lines)


def _large_file_content(line_count: int = 600) -> str:
    """A large file with many lines."""
    lines = [f"    line_{i} = {i}" for i in range(line_count)]
    return "def big_function():\n" + "\n".join(lines)


def _deeply_nested_content() -> str:
    """A file with deep nesting (>6 levels at 4-space indent)."""
    lines = ["def outer():"]
    for i in range(1, 9):
        indent = "    " * i
        lines.append(f"{indent}if condition_{i}:")
    lines.append("    " * 9 + "pass")
    return "\n".join(lines)


def _huge_untested_content() -> str:
    """A >1000 line file."""
    lines = [f"line_{i} = {i}" for i in range(1100)]
    return "\n".join(lines)


# --- _compute_max_indent_depth tests ---


class TestComputeMaxIndentDepth:
    def test_no_indentation(self):
        assert _compute_max_indent_depth("x = 1\ny = 2\n", "foo.py") == 0

    def test_python_spaces(self):
        content = "def foo():\n    if True:\n        pass\n"
        assert _compute_max_indent_depth(content, "foo.py") == 2

    def test_js_two_space(self):
        content = "function foo() {\n  if (true) {\n    return;\n  }\n}\n"
        assert _compute_max_indent_depth(content, "foo.js") == 2

    def test_tabs(self):
        content = "def foo():\n\tif True:\n\t\tpass\n"
        assert _compute_max_indent_depth(content, "foo.py") == 2

    def test_empty_content(self):
        assert _compute_max_indent_depth("", "foo.py") == 0

    def test_deep_nesting(self):
        content = _deeply_nested_content()
        depth = _compute_max_indent_depth(content, "foo.py")
        assert depth >= 7


# --- _compute_verdict tests ---


class TestComputeVerdict:
    def test_looks_good_no_concerns(self):
        files = [FileAssessment(path="a.py", lines=100, recent_commits=2, has_tests=True, max_indent_depth=2)]
        assert _compute_verdict(files) == "LOOKS_GOOD"

    def test_looks_good_one_concern_each(self):
        files = [
            FileAssessment(
                path="a.py", lines=600, recent_commits=2, has_tests=True, max_indent_depth=2, concerns=["large file"]
            ),
            FileAssessment(
                path="b.py", lines=100, recent_commits=2, has_tests=False, max_indent_depth=2, concerns=["no tests"]
            ),
        ]
        assert _compute_verdict(files) == "LOOKS_GOOD"

    def test_messy_two_concerns(self):
        files = [
            FileAssessment(
                path="a.py",
                lines=600,
                recent_commits=2,
                has_tests=False,
                max_indent_depth=2,
                concerns=["large file", "no tests"],
            ),
        ]
        assert _compute_verdict(files) == "MESSY"

    def test_dumpster_fire_huge_untested(self):
        files = [
            FileAssessment(
                path="a.py",
                lines=1100,
                recent_commits=2,
                has_tests=False,
                max_indent_depth=2,
                concerns=["large file", "no tests"],
            ),
        ]
        assert _compute_verdict(files) == "DUMPSTER_FIRE"

    def test_dumpster_fire_majority_3plus_concerns(self):
        files = [
            FileAssessment(
                path="a.py",
                lines=600,
                recent_commits=15,
                has_tests=False,
                max_indent_depth=8,
                concerns=["large file", "no tests", "high churn"],
            ),
            FileAssessment(
                path="b.py",
                lines=700,
                recent_commits=12,
                has_tests=False,
                max_indent_depth=9,
                concerns=["large file", "no tests", "deep nesting"],
            ),
            FileAssessment(
                path="c.py",
                lines=50,
                recent_commits=1,
                has_tests=True,
                max_indent_depth=2,
                concerns=[],
            ),
        ]
        assert _compute_verdict(files) == "DUMPSTER_FIRE"

    def test_empty_files_list(self):
        assert _compute_verdict([]) == "LOOKS_GOOD"


# --- assess_issue integration tests ---


class TestAssessIssue:
    @respx.mock
    def test_looks_good(self, client):
        """Small file, has tests, low churn -> LOOKS_GOOD."""
        content = _small_file_content()
        encoded = _encode_content(content)

        # Mock issue
        respx.get("https://api.github.com/repos/test/repo/issues/42").mock(
            return_value=httpx.Response(200, json=_mock_issue(body="See `src/foo.py`"), headers=_RATE_HEADERS)
        )
        # Mock comments (empty)
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=httpx.Response(200, json=[], headers=_RATE_HEADERS)
        )
        # Mock file content
        respx.get("https://api.github.com/repos/test/repo/contents/src/foo.py").mock(
            return_value=httpx.Response(200, json={"content": encoded, "encoding": "base64"}, headers=_RATE_HEADERS)
        )
        # Mock test file exists
        respx.get("https://api.github.com/repos/test/repo/contents/tests/test_foo.py").mock(
            return_value=httpx.Response(200, json={"name": "test_foo.py"}, headers=_RATE_HEADERS)
        )
        # Mock commits (low churn)
        respx.get("https://api.github.com/repos/test/repo/commits").mock(
            return_value=httpx.Response(200, json=[{"sha": "abc"}], headers=_RATE_HEADERS)
        )

        result = assess_issue(client, "test", "repo", 42)
        assert result.verdict == "LOOKS_GOOD"
        assert len(result.files) == 1
        assert result.files[0].has_tests is True

    @respx.mock
    def test_messy(self, client):
        """Large file, no tests -> MESSY."""
        content = _large_file_content(600)
        encoded = _encode_content(content)

        respx.get("https://api.github.com/repos/test/repo/issues/42").mock(
            return_value=httpx.Response(200, json=_mock_issue(body="See `src/big.py`"), headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=httpx.Response(200, json=[], headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/src/big.py").mock(
            return_value=httpx.Response(200, json={"content": encoded, "encoding": "base64"}, headers=_RATE_HEADERS)
        )
        # No test files found
        respx.get("https://api.github.com/repos/test/repo/contents/tests/test_big.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/tests/src/test_big.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/test/test_big.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        # Low churn
        respx.get("https://api.github.com/repos/test/repo/commits").mock(
            return_value=httpx.Response(200, json=[{"sha": "abc"}], headers=_RATE_HEADERS)
        )

        result = assess_issue(client, "test", "repo", 42)
        assert result.verdict == "MESSY"
        assert any("large file" in c for c in result.files[0].concerns)
        assert any("no test" in c for c in result.files[0].concerns)

    @respx.mock
    def test_no_files_referenced(self, client):
        """Empty issue with no file references -> LOOKS_GOOD with manual inspection note."""
        respx.get("https://api.github.com/repos/test/repo/issues/42").mock(
            return_value=httpx.Response(
                200, json=_mock_issue(body="Something is broken but I'm not sure where"), headers=_RATE_HEADERS
            )
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=httpx.Response(200, json=[], headers=_RATE_HEADERS)
        )

        result = assess_issue(client, "test", "repo", 42)
        assert result.verdict == "LOOKS_GOOD"
        assert "manual inspection" in result.summary.lower()
        assert result.files == []

    @respx.mock
    def test_dumpster_fire(self, client):
        """Huge file (>1000 lines), no tests, deep nesting -> DUMPSTER_FIRE."""
        content = _huge_untested_content()
        encoded = _encode_content(content)

        respx.get("https://api.github.com/repos/test/repo/issues/42").mock(
            return_value=httpx.Response(200, json=_mock_issue(body="See `src/monster.py`"), headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/issues/42/comments").mock(
            return_value=httpx.Response(200, json=[], headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/src/monster.py").mock(
            return_value=httpx.Response(200, json={"content": encoded, "encoding": "base64"}, headers=_RATE_HEADERS)
        )
        # No test files
        respx.get("https://api.github.com/repos/test/repo/contents/tests/test_monster.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/tests/src/test_monster.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/test/test_monster.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        # High churn
        respx.get("https://api.github.com/repos/test/repo/commits").mock(
            return_value=httpx.Response(200, json=[{"sha": f"abc{i}"} for i in range(15)], headers=_RATE_HEADERS)
        )

        result = assess_issue(client, "test", "repo", 42)
        assert result.verdict == "DUMPSTER_FIRE"
        assert len(result.files) == 1
        assert result.files[0].lines > 1000
        assert result.files[0].has_tests is False
