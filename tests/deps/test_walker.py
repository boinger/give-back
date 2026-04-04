"""Tests for deps/walker.py — the dependency walking orchestrator.

These are integration-style tests that mock at the HTTP layer with respx.
Parser, resolver, and filter logic have their own tests; these focus on
orchestration: detect → parse → resolve → filter → assess flow.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import httpx
import pytest
import respx

from give_back.deps.walker import NoManifestError, WalkResult, walk_deps
from give_back.github_client import GitHubClient


def _b64(text: str) -> str:
    """Encode text as base64 (matching GitHub contents API format)."""
    return base64.b64encode(text.encode()).decode()


# --- Fixtures ---

_PYPROJECT_CONTENT = """\
[project]
name = "myproject"
dependencies = [
    "click>=8.0",
    "httpx",
]
"""

_GOMOD_CONTENT = """\
module example.com/myorg/myproject

go 1.21

require (
    github.com/gorilla/mux v1.8.0
    github.com/sirupsen/logrus v1.9.0
)
"""

# Minimal healthy repo GraphQL response — metadata only (no PRs)
_GRAPHQL_METADATA_RESPONSE = {
    "data": {
        "repository": {
            "licenseInfo": {"spdxId": "MIT", "name": "MIT License", "key": "mit"},
            "labels": {"nodes": [{"name": "bug"}, {"name": "good first issue"}]},
            "defaultBranchRef": {"target": {"committedDate": "2026-03-20T10:00:00Z"}},
            "releases": {
                "nodes": [
                    {"createdAt": "2026-03-10T12:00:00Z", "tagName": "v1.0.0"},
                ]
            },
            "issues": {"totalCount": 10},
            "closedIssues": {"totalCount": 50},
        }
    }
}

# PR page response (returned by the paginated PR query)
_GRAPHQL_PR_PAGE_RESPONSE = {
    "data": {
        "repository": {
            "pullRequests": {
                "pageInfo": {"hasPreviousPage": False, "startCursor": None},
                "nodes": [
                    {
                        "number": 1,
                        "state": "MERGED",
                        "createdAt": "2026-03-01T10:00:00Z",
                        "mergedAt": "2026-03-02T10:00:00Z",
                        "closedAt": "2026-03-02T10:00:00Z",
                        "author": {"login": "external-dev"},
                        "authorAssociation": "NONE",
                        "comments": {
                            "nodes": [
                                {
                                    "createdAt": "2026-03-01T12:00:00Z",
                                    "author": {"login": "maintainer"},
                                }
                            ]
                        },
                        "reviews": {"nodes": []},
                    }
                ],
            },
        }
    }
}

_COMMUNITY_RESPONSE = {
    "health_percentage": 80,
    "files": {
        "contributing": None,
        "code_of_conduct": None,
        "license": {"name": "MIT License"},
    },
}

_RATE_LIMIT_HEADERS = {
    "X-RateLimit-Remaining": "4999",
    "X-RateLimit-Limit": "5000",
    "X-RateLimit-Reset": "9999999999",
}


_ALL_MANIFESTS = ("go.mod", "Cargo.toml", "pyproject.toml", "package.json", "Gemfile", "requirements.txt")


def _mock_no_manifests(owner: str, repo: str) -> None:
    """Mock 404 for all manifest files. Override specific ones after calling this."""
    for filename in _ALL_MANIFESTS:
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{filename}").mock(
            return_value=httpx.Response(404, headers=_RATE_LIMIT_HEADERS)
        )


def _mock_github_assessment(router: respx.MockRouter, owner: str, repo: str) -> None:
    """Set up respx routes for a full viability assessment of a repo."""
    # GraphQL
    router.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=_GRAPHQL_METADATA_RESPONSE, headers=_RATE_LIMIT_HEADERS)
    )

    # Community profile
    router.get(f"https://api.github.com/repos/{owner}/{repo}/community/profile").mock(
        return_value=httpx.Response(200, json=_COMMUNITY_RESPONSE, headers=_RATE_LIMIT_HEADERS)
    )

    # Search (AI policy)
    router.get("https://api.github.com/search/issues").mock(
        return_value=httpx.Response(200, json={"total_count": 0, "items": []}, headers=_RATE_LIMIT_HEADERS)
    )


class TestWalkPythonProject:
    @respx.mock
    def test_walk_pyproject(self):
        """Walk a Python project with pyproject.toml, resolving via PyPI."""
        # All manifests → 404 first, then override the one we want
        _mock_no_manifests("myorg", "myproject")

        # pyproject.toml → found (overrides the 404 mock)
        respx.get("https://api.github.com/repos/myorg/myproject/contents/pyproject.toml").mock(
            return_value=httpx.Response(
                200,
                json={"encoding": "base64", "content": _b64(_PYPROJECT_CONTENT)},
                headers=_RATE_LIMIT_HEADERS,
            )
        )

        # 3. PyPI resolution for click and httpx
        respx.get("https://pypi.org/pypi/click/json").mock(
            return_value=httpx.Response(
                200,
                json={"info": {"project_urls": {"Source": "https://github.com/pallets/click"}}},
            )
        )
        respx.get("https://pypi.org/pypi/httpx/json").mock(
            return_value=httpx.Response(
                200,
                json={"info": {"project_urls": {"Source": "https://github.com/encode/httpx"}}},
            )
        )

        # 4. Filter checks (repo info for archived/stars)
        for slug in ("pallets/click", "encode/httpx"):
            respx.get(f"https://api.github.com/repos/{slug}").mock(
                return_value=httpx.Response(
                    200,
                    json={"archived": False, "stargazers_count": 5000},
                    headers=_RATE_LIMIT_HEADERS,
                )
            )

        # 5. Assessment API calls for each dep: metadata + PR page per dep
        # Each assessment = 2 GraphQL calls (metadata + PR page), so 2 deps = 4 calls
        _meta = httpx.Response(200, json=_GRAPHQL_METADATA_RESPONSE, headers=_RATE_LIMIT_HEADERS)
        _prs = httpx.Response(200, json=_GRAPHQL_PR_PAGE_RESPONSE, headers=_RATE_LIMIT_HEADERS)
        respx.post("https://api.github.com/graphql").mock(side_effect=[_meta, _prs, _meta, _prs])

        for slug in ("pallets/click", "encode/httpx"):
            respx.get(f"https://api.github.com/repos/{slug}/community/profile").mock(
                return_value=httpx.Response(200, json=_COMMUNITY_RESPONSE, headers=_RATE_LIMIT_HEADERS)
            )

        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "items": []}, headers=_RATE_LIMIT_HEADERS)
        )

        # Run with patched state (no cache, empty skip list)
        with (
            patch("give_back.deps.walker.get_skip_list", return_value=[]),
            patch("give_back.deps.walker.get_cached_assessment", return_value=None),
            patch("give_back.deps.walker.save_assessment"),
        ):
            with GitHubClient(token="test-token") as client:
                result = walk_deps(client, "myorg", "myproject", limit=20)

        assert isinstance(result, WalkResult)
        assert result.ecosystem == "python"
        assert result.total_packages == 2
        assert result.resolved_count == 2
        # Both click and httpx are from different orgs than "myorg", so both pass
        assert len(result.results) == 2
        for dep in result.results:
            assert dep.assessment is not None
            assert not dep.from_cache


class TestWalkGoProject:
    @respx.mock
    def test_walk_gomod(self):
        """Walk a Go project with go.mod, resolving module paths directly."""
        # 1. go.mod → found
        respx.get("https://api.github.com/repos/myorg/myproject/contents/go.mod").mock(
            return_value=httpx.Response(
                200,
                json={"encoding": "base64", "content": _b64(_GOMOD_CONTENT)},
                headers=_RATE_LIMIT_HEADERS,
            )
        )

        # 2. Filter checks — both are different orgs from "myorg"
        for slug in ("gorilla/mux", "sirupsen/logrus"):
            respx.get(f"https://api.github.com/repos/{slug}").mock(
                return_value=httpx.Response(
                    200,
                    json={"archived": False, "stargazers_count": 15000},
                    headers=_RATE_LIMIT_HEADERS,
                )
            )

        # 3. Assessment for each dep (metadata + PR page per dep)
        _meta = httpx.Response(200, json=_GRAPHQL_METADATA_RESPONSE, headers=_RATE_LIMIT_HEADERS)
        _prs = httpx.Response(200, json=_GRAPHQL_PR_PAGE_RESPONSE, headers=_RATE_LIMIT_HEADERS)
        respx.post("https://api.github.com/graphql").mock(side_effect=[_meta, _prs, _meta, _prs])

        for slug in ("gorilla/mux", "sirupsen/logrus"):
            respx.get(f"https://api.github.com/repos/{slug}/community/profile").mock(
                return_value=httpx.Response(200, json=_COMMUNITY_RESPONSE, headers=_RATE_LIMIT_HEADERS)
            )

        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "items": []}, headers=_RATE_LIMIT_HEADERS)
        )

        with (
            patch("give_back.deps.walker.get_skip_list", return_value=[]),
            patch("give_back.deps.walker.get_cached_assessment", return_value=None),
            patch("give_back.deps.walker.save_assessment"),
        ):
            with GitHubClient(token="test-token") as client:
                result = walk_deps(client, "myorg", "myproject", limit=20)

        assert result.ecosystem == "go"
        assert result.total_packages == 2
        assert len(result.results) == 2


class TestNoManifestFound:
    @respx.mock
    def test_raises_on_no_manifest(self):
        """404 on all manifest files raises NoManifestError."""
        _mock_no_manifests("myorg", "empty-project")

        with GitHubClient(token="test-token") as client:
            with pytest.raises(NoManifestError, match="No supported manifest"):
                walk_deps(client, "myorg", "empty-project")


class TestRespectsLimit:
    @respx.mock
    def test_only_limit_assessed(self):
        """When more deps than limit, only 'limit' are assessed."""
        # pyproject with 5 deps
        pyproject = """\
[project]
name = "myproject"
dependencies = [
    "pkg-a",
    "pkg-b",
    "pkg-c",
    "pkg-d",
    "pkg-e",
]
"""
        _mock_no_manifests("myorg", "myproject")
        respx.get("https://api.github.com/repos/myorg/myproject/contents/pyproject.toml").mock(
            return_value=httpx.Response(
                200,
                json={"encoding": "base64", "content": _b64(pyproject)},
                headers=_RATE_LIMIT_HEADERS,
            )
        )

        # PyPI resolution — all resolve to different orgs
        for name in ("pkg-a", "pkg-b", "pkg-c", "pkg-d", "pkg-e"):
            respx.get(f"https://pypi.org/pypi/{name}/json").mock(
                return_value=httpx.Response(
                    200,
                    json={"info": {"project_urls": {"Source": f"https://github.com/ext-{name}/repo"}}},
                )
            )

        # Filter: repo info
        for name in ("pkg-a", "pkg-b", "pkg-c", "pkg-d", "pkg-e"):
            respx.get(f"https://api.github.com/repos/ext-{name}/repo").mock(
                return_value=httpx.Response(
                    200,
                    json={"archived": False, "stargazers_count": 100},
                    headers=_RATE_LIMIT_HEADERS,
                )
            )

        # Assessment — only 2 will be assessed (limit=2), each needs metadata + PR page
        _meta = httpx.Response(200, json=_GRAPHQL_METADATA_RESPONSE, headers=_RATE_LIMIT_HEADERS)
        _prs = httpx.Response(200, json=_GRAPHQL_PR_PAGE_RESPONSE, headers=_RATE_LIMIT_HEADERS)
        respx.post("https://api.github.com/graphql").mock(side_effect=[_meta, _prs, _meta, _prs])

        for name in ("pkg-a", "pkg-b"):
            respx.get(f"https://api.github.com/repos/ext-{name}/repo/community/profile").mock(
                return_value=httpx.Response(200, json=_COMMUNITY_RESPONSE, headers=_RATE_LIMIT_HEADERS)
            )

        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "items": []}, headers=_RATE_LIMIT_HEADERS)
        )

        with (
            patch("give_back.deps.walker.get_skip_list", return_value=[]),
            patch("give_back.deps.walker.get_cached_assessment", return_value=None),
            patch("give_back.deps.walker.save_assessment"),
        ):
            with GitHubClient(token="test-token") as client:
                result = walk_deps(client, "myorg", "myproject", limit=2)

        assert result.total_packages == 5
        assert len(result.results) == 2  # limit=2


class TestUsesCache:
    @respx.mock
    def test_cached_assessment_returned_without_api_calls(self):
        """Cached assessments are used without making assessment API calls."""
        _mock_no_manifests("myorg", "myproject")
        respx.get("https://api.github.com/repos/myorg/myproject/contents/pyproject.toml").mock(
            return_value=httpx.Response(
                200,
                json={"encoding": "base64", "content": _b64(_PYPROJECT_CONTENT)},
                headers=_RATE_LIMIT_HEADERS,
            )
        )

        # PyPI resolution
        respx.get("https://pypi.org/pypi/click/json").mock(
            return_value=httpx.Response(
                200,
                json={"info": {"project_urls": {"Source": "https://github.com/pallets/click"}}},
            )
        )
        respx.get("https://pypi.org/pypi/httpx/json").mock(
            return_value=httpx.Response(
                200,
                json={"info": {"project_urls": {"Source": "https://github.com/encode/httpx"}}},
            )
        )

        # Filter checks
        for slug in ("pallets/click", "encode/httpx"):
            respx.get(f"https://api.github.com/repos/{slug}").mock(
                return_value=httpx.Response(
                    200,
                    json={"archived": False, "stargazers_count": 5000},
                    headers=_RATE_LIMIT_HEADERS,
                )
            )

        # Cached assessment data
        cached_data = {
            "timestamp": "2026-03-26T10:00:00+00:00",
            "overall_tier": "green",
            "gate_passed": True,
            "incomplete": False,
            "signals": [
                {"score": 0.9, "tier": "green", "summary": "85% of external PRs merged"},
            ],
        }

        # NO graphql/community/search mocks — those should not be called
        with (
            patch("give_back.deps.walker.get_skip_list", return_value=[]),
            patch("give_back.deps.walker.get_cached_assessment", return_value=cached_data),
            patch("give_back.deps.walker.save_assessment"),
        ):
            with GitHubClient(token="test-token") as client:
                result = walk_deps(client, "myorg", "myproject", limit=20)

        assert len(result.results) == 2
        for dep in result.results:
            assert dep.from_cache is True
            assert dep.assessment is not None
            assert dep.assessment.overall_tier.value == "green"


class TestRequiresAuth:
    def test_deps_cli_requires_auth(self):
        """The deps CLI command refuses to run without authentication."""
        from click.testing import CliRunner

        from give_back.cli import cli

        runner = CliRunner()
        with patch("give_back.cli.deps.resolve_token", return_value=None):
            result = runner.invoke(cli, ["deps", "pallets/flask"])

        assert result.exit_code != 0
        assert "requires authentication" in result.output


class TestSkipCommand:
    def test_skip_adds_to_list(self, tmp_path):
        """The skip command calls add_to_skip_list."""
        from click.testing import CliRunner

        from give_back.cli import cli

        runner = CliRunner()
        # Patch at the module where the name is looked up (top-level import in cli.py)
        with patch("give_back.state.STATE_DIR", tmp_path), patch("give_back.state.STATE_FILE", tmp_path / "state.json"):
            result = runner.invoke(cli, ["skip", "google/protobuf"])

        assert result.exit_code == 0
        assert "Added google/protobuf to skip list" in result.output


class TestUnskipCommand:
    def test_unskip_removes_from_list(self, tmp_path):
        """The unskip command calls remove_from_skip_list."""

        from click.testing import CliRunner

        from give_back.cli import cli

        runner = CliRunner()
        # Pre-populate state with the slug in skip list
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"version": 1, "assessments": {}, "skip_list": ["google/protobuf"]}))

        with patch("give_back.state.STATE_DIR", tmp_path), patch("give_back.state.STATE_FILE", state_file):
            result = runner.invoke(cli, ["unskip", "google/protobuf"])

        assert result.exit_code == 0
        assert "Removed google/protobuf from skip list" in result.output
