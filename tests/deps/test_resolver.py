"""Tests for deps/resolver.py package resolution."""

import httpx
import respx

from give_back.deps.resolver import resolve_go_module, resolve_packages, resolve_pypi


class TestResolvePyPI:
    @respx.mock
    def test_pypi_found(self):
        """Source key with GitHub URL resolves to owner/repo."""
        respx.get("https://pypi.org/pypi/click/json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "info": {
                        "project_urls": {
                            "Source": "https://github.com/pallets/click",
                            "Documentation": "https://click.palletsprojects.com",
                        }
                    }
                },
            )
        )
        assert resolve_pypi("click") == "pallets/click"

    @respx.mock
    def test_pypi_homepage_fallback(self):
        """Homepage with GitHub URL resolves when no Source key exists."""
        respx.get("https://pypi.org/pypi/some-pkg/json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "info": {
                        "project_urls": {
                            "Homepage": "https://github.com/owner/some-pkg",
                        }
                    }
                },
            )
        )
        assert resolve_pypi("some-pkg") == "owner/some-pkg"

    @respx.mock
    def test_pypi_no_github(self):
        """project_urls with no GitHub URLs returns None."""
        respx.get("https://pypi.org/pypi/nope/json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "info": {
                        "project_urls": {
                            "Homepage": "https://example.com/nope",
                            "Documentation": "https://docs.example.com",
                        }
                    }
                },
            )
        )
        assert resolve_pypi("nope") is None

    @respx.mock
    def test_pypi_not_found(self):
        """404 from PyPI returns None."""
        respx.get("https://pypi.org/pypi/nonexistent/json").mock(return_value=httpx.Response(404))
        assert resolve_pypi("nonexistent") is None

    @respx.mock
    def test_pypi_timeout(self):
        """Timeout from PyPI returns None."""
        respx.get("https://pypi.org/pypi/slow-pkg/json").mock(side_effect=httpx.TimeoutException("timed out"))
        assert resolve_pypi("slow-pkg") is None

    @respx.mock
    def test_pypi_strips_git_suffix(self):
        """GitHub URL ending in .git is cleaned up."""
        respx.get("https://pypi.org/pypi/dirty/json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "info": {
                        "project_urls": {
                            "Repository": "https://github.com/owner/dirty.git",
                        }
                    }
                },
            )
        )
        assert resolve_pypi("dirty") == "owner/dirty"

    @respx.mock
    def test_pypi_null_project_urls(self):
        """project_urls being null returns None."""
        respx.get("https://pypi.org/pypi/null-urls/json").mock(
            return_value=httpx.Response(
                200,
                json={"info": {"project_urls": None}},
            )
        )
        assert resolve_pypi("null-urls") is None

    @respx.mock
    def test_pypi_case_insensitive_keys(self):
        """project_urls key matching is case-insensitive."""
        respx.get("https://pypi.org/pypi/cased/json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "info": {
                        "project_urls": {
                            "SOURCE CODE": "https://github.com/owner/cased",
                        }
                    }
                },
            )
        )
        assert resolve_pypi("cased") == "owner/cased"


class TestResolveGoModule:
    def test_go_github_path(self):
        """Standard github.com module path resolves to owner/repo."""
        assert resolve_go_module("github.com/gorilla/mux") == "gorilla/mux"

    def test_go_versioned(self):
        """Version suffix is stripped."""
        assert resolve_go_module("github.com/foo/bar/v2") == "foo/bar"

    def test_go_subpackage(self):
        """Sub-package path is stripped to owner/repo."""
        assert resolve_go_module("github.com/foo/bar/pkg/sub") == "foo/bar"

    def test_go_golang_x(self):
        """golang.org/x modules resolve to golang org."""
        assert resolve_go_module("golang.org/x/net") == "golang/net"

    def test_go_non_github(self):
        """Non-GitHub hosts return None."""
        assert resolve_go_module("gopkg.in/yaml.v3") is None

    def test_go_k8s_io(self):
        """k8s.io modules return None (non-GitHub host)."""
        assert resolve_go_module("k8s.io/api") is None

    def test_go_incomplete_github_path(self):
        """github.com with only owner (no repo) returns None."""
        assert resolve_go_module("github.com/foo") is None


class TestResolvePackages:
    @respx.mock
    def test_resolve_packages_python(self):
        """Batch resolution for Python packages."""
        respx.get("https://pypi.org/pypi/click/json").mock(
            return_value=httpx.Response(
                200,
                json={"info": {"project_urls": {"Source": "https://github.com/pallets/click"}}},
            )
        )
        respx.get("https://pypi.org/pypi/unknown/json").mock(return_value=httpx.Response(404))
        result = resolve_packages(["click", "unknown"], "python")
        assert result == [("click", "pallets/click"), ("unknown", None)]

    def test_resolve_packages_go(self):
        """Batch resolution for Go modules (no API calls needed)."""
        result = resolve_packages(
            ["github.com/gorilla/mux", "golang.org/x/net", "gopkg.in/yaml.v3"],
            "go",
        )
        assert result == [
            ("github.com/gorilla/mux", "gorilla/mux"),
            ("golang.org/x/net", "golang/net"),
            ("gopkg.in/yaml.v3", None),
        ]
