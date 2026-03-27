"""Tests for sniff/files.py — file path extraction and fetching."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from give_back.github_client import GitHubClient
from give_back.sniff.files import (
    check_test_file,
    fetch_file_content,
    get_recent_commits,
    identify_files,
)

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


# --- identify_files tests ---


class TestIdentifyFiles:
    def test_extract_python_path(self):
        body = "File `src/foo.py` has a bug"
        result = identify_files(body, [])
        assert result == ["src/foo.py"]

    def test_extract_stack_trace(self):
        body = 'Traceback:\n  File "src/give_back/cli.py", line 42, in main\n    do_stuff()'
        result = identify_files(body, [])
        assert "src/give_back/cli.py" in result

    def test_extract_go_path(self):
        body = "panic at src/main.go:42"
        result = identify_files(body, [])
        assert "src/main.go" in result

    def test_extract_node_trace(self):
        body = "Error\n    at Object.<anonymous> (src/index.js:10:5)"
        result = identify_files(body, [])
        assert "src/index.js" in result

    def test_no_paths_found(self):
        body = "this is just text with no file references"
        result = identify_files(body, [])
        assert result == []

    def test_dedup(self):
        body = "See `src/foo.py` and also `src/foo.py` again"
        result = identify_files(body, [])
        assert result == ["src/foo.py"]

    def test_ignores_non_file_paths(self):
        body = "use http://example.com/foo/bar.py for reference"
        result = identify_files(body, [])
        assert result == []

    def test_extracts_from_comments(self):
        body = "Bug report"
        comments = [
            {"body": "I traced this to `src/utils/helper.py`"},
            {"body": "Also affects `lib/core/engine.rs`"},
        ]
        result = identify_files(body, comments)
        assert "src/utils/helper.py" in result
        assert "lib/core/engine.rs" in result

    def test_rejects_paths_without_slash(self):
        body = "The file main.py is broken"
        result = identify_files(body, [])
        assert result == []

    def test_multiple_patterns_in_one_body(self):
        body = 'See `src/foo.py` for the source.\nTraceback:\n  File "src/bar.py", line 10\nAlso at src/baz.go:55'
        result = identify_files(body, [])
        assert "src/foo.py" in result
        assert "src/bar.py" in result
        assert "src/baz.go" in result


# --- fetch_file_content tests ---


class TestFetchFileContent:
    @respx.mock
    def test_fetches_and_decodes(self, client):
        content = "line1\nline2\nline3\n"
        encoded = base64.b64encode(content.encode()).decode()
        respx.get("https://api.github.com/repos/test/repo/contents/src/foo.py").mock(
            return_value=httpx.Response(
                200,
                json={"content": encoded, "encoding": "base64"},
                headers=_RATE_HEADERS,
            )
        )
        text, lines = fetch_file_content(client, "test", "repo", "src/foo.py")
        assert text == content
        assert lines == 3

    @respx.mock
    def test_404_returns_empty(self, client):
        respx.get("https://api.github.com/repos/test/repo/contents/nonexistent.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        text, lines = fetch_file_content(client, "test", "repo", "nonexistent.py")
        assert text == ""
        assert lines == 0


# --- check_test_file tests ---


class TestCheckTestFile:
    @respx.mock
    def test_python_test_found(self, client):
        respx.get("https://api.github.com/repos/test/repo/contents/tests/test_bar.py").mock(
            return_value=httpx.Response(200, json={"name": "test_bar.py"}, headers=_RATE_HEADERS)
        )
        assert check_test_file(client, "test", "repo", "src/bar.py") is True

    @respx.mock
    def test_python_test_not_found(self, client):
        respx.get("https://api.github.com/repos/test/repo/contents/tests/test_bar.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/tests/src/test_bar.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        respx.get("https://api.github.com/repos/test/repo/contents/test/test_bar.py").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        assert check_test_file(client, "test", "repo", "src/bar.py") is False

    @respx.mock
    def test_go_test_found(self, client):
        respx.get("https://api.github.com/repos/test/repo/contents/lib/foo_test.go").mock(
            return_value=httpx.Response(200, json={"name": "foo_test.go"}, headers=_RATE_HEADERS)
        )
        assert check_test_file(client, "test", "repo", "lib/foo.go") is True

    @respx.mock
    def test_go_test_not_found(self, client):
        respx.get("https://api.github.com/repos/test/repo/contents/lib/foo_test.go").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        assert check_test_file(client, "test", "repo", "lib/foo.go") is False


# --- get_recent_commits tests ---


class TestGetRecentCommits:
    @respx.mock
    def test_returns_commit_count(self, client):
        commits = [{"sha": f"abc{i}"} for i in range(3)]
        respx.get("https://api.github.com/repos/test/repo/commits").mock(
            return_value=httpx.Response(200, json=commits, headers=_RATE_HEADERS)
        )
        count = get_recent_commits(client, "test", "repo", "src/foo.py", limit=5)
        assert count == 3

    @respx.mock
    def test_404_returns_zero(self, client):
        respx.get("https://api.github.com/repos/test/repo/commits").mock(
            return_value=httpx.Response(404, headers=_RATE_HEADERS)
        )
        count = get_recent_commits(client, "test", "repo", "nonexistent.py")
        assert count == 0
