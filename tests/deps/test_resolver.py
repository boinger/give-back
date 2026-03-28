"""Tests for deps/resolver.py package resolution."""

import httpx
import pytest
import respx

from give_back.deps import resolver
from give_back.deps.resolver import resolve_go_module, resolve_packages, resolve_pypi


@pytest.fixture(autouse=True)
def _clear_go_meta_cache():
    """Clear the module-level go-import cache between tests."""
    resolver._go_meta_cache.clear()
    yield
    resolver._go_meta_cache.clear()


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

    @respx.mock
    def test_go_gopkg_in_resolves(self):
        """gopkg.in modules resolve to GitHub via go-import meta tag."""
        respx.get("https://gopkg.in/yaml.v3?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="gopkg.in/yaml.v3 git https://github.com/go-yaml/yaml">',
            )
        )
        assert resolve_go_module("gopkg.in/yaml.v3") == "go-yaml/yaml"

    @respx.mock
    def test_go_k8s_io_resolves(self):
        """k8s.io modules resolve to GitHub via go-import meta tag."""
        respx.get("https://k8s.io/api?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="k8s.io/api git https://github.com/kubernetes/api">',
            )
        )
        assert resolve_go_module("k8s.io/api") == "kubernetes/api"

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

    @respx.mock
    def test_resolve_packages_go(self):
        """Batch resolution for Go modules (github.com direct, others via HTTP)."""
        respx.get("https://gopkg.in/yaml.v3?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="gopkg.in/yaml.v3 git https://github.com/go-yaml/yaml">',
            )
        )
        result = resolve_packages(
            ["github.com/gorilla/mux", "golang.org/x/net", "gopkg.in/yaml.v3"],
            "go",
        )
        assert result == [
            ("github.com/gorilla/mux", "gorilla/mux"),
            ("golang.org/x/net", "golang/net"),
            ("gopkg.in/yaml.v3", "go-yaml/yaml"),
        ]


class TestGoMetaResolution:
    """Tests for go-import meta tag resolution of non-GitHub Go module hosts."""

    @respx.mock
    def test_go_uber_org(self):
        """go.uber.org modules resolve via meta tag."""
        respx.get("https://go.uber.org/zap?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="go.uber.org/zap git https://github.com/uber-go/zap">',
            )
        )
        assert resolve_go_module("go.uber.org/zap") == "uber-go/zap"

    @respx.mock
    def test_sigs_k8s_io(self):
        """sigs.k8s.io modules resolve via meta tag."""
        respx.get("https://sigs.k8s.io/controller-runtime?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="sigs.k8s.io/controller-runtime git https://github.com/kubernetes-sigs/controller-runtime">',
            )
        )
        assert resolve_go_module("sigs.k8s.io/controller-runtime") == "kubernetes-sigs/controller-runtime"

    @respx.mock
    def test_timeout_returns_none(self):
        """Network timeout returns None gracefully."""
        respx.get("https://slow.example.com/pkg?go-get=1").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        assert resolve_go_module("slow.example.com/pkg") is None

    @respx.mock
    def test_non_github_vcs_returns_none(self):
        """Module pointing to Bitbucket (not GitHub) returns None."""
        respx.get("https://example.com/pkg?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="example.com/pkg git https://bitbucket.org/owner/pkg">',
            )
        )
        assert resolve_go_module("example.com/pkg") is None

    @respx.mock
    def test_invalid_html_returns_none(self):
        """Page without go-import meta tag returns None."""
        respx.get("https://notathing.example.com/pkg?go-get=1").mock(
            return_value=httpx.Response(200, text="<html><body>Not a Go module</body></html>")
        )
        assert resolve_go_module("notathing.example.com/pkg") is None

    @respx.mock
    def test_http_404_returns_none(self):
        """Server returning 404 returns None."""
        respx.get("https://gone.example.com/pkg?go-get=1").mock(
            return_value=httpx.Response(404)
        )
        assert resolve_go_module("gone.example.com/pkg") is None

    @respx.mock
    def test_deep_path_segment_stripping(self):
        """Deep paths strip to root module (k8s.io/api/core/v1 → k8s.io/api)."""
        # The full path 404s, but the root module path resolves
        respx.get("https://k8s.io/api/core/v1?go-get=1").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://k8s.io/api/core?go-get=1").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://k8s.io/api?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="k8s.io/api git https://github.com/kubernetes/api">',
            )
        )
        assert resolve_go_module("k8s.io/api/core/v1") == "kubernetes/api"

    @respx.mock
    def test_cache_hit_skips_http(self):
        """Second call for same prefix uses cache, no HTTP request."""
        route = respx.get("https://k8s.io/api?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="k8s.io/api git https://github.com/kubernetes/api">',
            )
        )
        # First call populates cache
        assert resolve_go_module("k8s.io/api") == "kubernetes/api"
        assert route.call_count == 1

        # Second call should hit cache, not HTTP
        assert resolve_go_module("k8s.io/api") == "kubernetes/api"
        assert route.call_count == 1  # still 1, no new request

    @respx.mock
    def test_cache_prefix_match(self):
        """Cache entry for prefix matches sub-paths too."""
        respx.get("https://k8s.io/api?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="k8s.io/api git https://github.com/kubernetes/api">',
            )
        )
        # Populate cache via root path
        assert resolve_go_module("k8s.io/api") == "kubernetes/api"
        # Sub-path should match cached prefix without HTTP
        assert resolve_go_module("k8s.io/api/core/v1") == "kubernetes/api"

    @respx.mock
    def test_multiple_meta_tags_correct_prefix(self):
        """Page with multiple go-import tags selects the matching prefix."""
        html = (
            '<meta name="go-import" content="example.com/other git https://github.com/wrong/repo">'
            '<meta name="go-import" content="example.com/pkg git https://github.com/right/repo">'
        )
        respx.get("https://example.com/pkg?go-get=1").mock(
            return_value=httpx.Response(200, text=html)
        )
        assert resolve_go_module("example.com/pkg") == "right/repo"

    @respx.mock
    def test_mod_vcs_type_skipped(self):
        """Meta tags with VCS type 'mod' (proxy entries) are skipped."""
        html = (
            '<meta name="go-import" content="example.com/pkg mod https://proxy.golang.org">'
            '<meta name="go-import" content="example.com/pkg git https://github.com/real/repo">'
        )
        respx.get("https://example.com/pkg?go-get=1").mock(
            return_value=httpx.Response(200, text=html)
        )
        assert resolve_go_module("example.com/pkg") == "real/repo"

    @respx.mock
    def test_mod_only_returns_none(self):
        """Page with only 'mod' type (no git) returns None."""
        respx.get("https://proxy-only.example.com/pkg?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text='<meta name="go-import" content="proxy-only.example.com/pkg mod https://proxy.golang.org">',
            )
        )
        assert resolve_go_module("proxy-only.example.com/pkg") is None

    @respx.mock
    def test_single_quote_attributes(self):
        """Meta tags with single-quoted attributes are parsed correctly."""
        respx.get("https://quirky.example.com/pkg?go-get=1").mock(
            return_value=httpx.Response(
                200,
                text="<meta name='go-import' content='quirky.example.com/pkg git https://github.com/owner/pkg'>",
            )
        )
        assert resolve_go_module("quirky.example.com/pkg") == "owner/pkg"
