"""Tests for deps/resolver.py package resolution."""

import socket
from unittest.mock import patch

import httpx
import pytest
import respx

from give_back.deps import resolver
from give_back.deps.resolver import (
    resolve_crates_io,
    resolve_go_module,
    resolve_npm,
    resolve_packages,
    resolve_pypi,
    resolve_rubygems,
)

# Capture references to the real functions at module load time, before any
# autouse fixture can replace them with mocks. SSRF-guard tests call these
# directly to bypass the default "every host is public" patching.
_REAL_IS_PUBLIC_HOST = resolver._is_public_host
_REAL_SAFE_GO_GET = resolver._safe_go_get


@pytest.fixture(autouse=True)
def _reset_resolver_state():
    """Reset module-level state between tests.

    Clears:
    - _go_meta_cache (prevents cross-test leakage of cached lookups)
    - shared httpx Client (prevents pool reuse across tests)
    - GIVE_BACK_ALLOW_PRIVATE_HOSTS cache
    """
    resolver._go_meta_cache.clear()
    resolver._clear_http_client()
    resolver._clear_allowlist()
    yield
    resolver._go_meta_cache.clear()
    resolver._clear_http_client()
    resolver._clear_allowlist()


@pytest.fixture(autouse=True)
def _bypass_ssrf_check_by_default():
    """By default, assume every host is public during testing.

    Respx mocks HTTP traffic but not DNS; fake hostnames like
    ``quirky.example.com`` would fail ``socket.getaddrinfo`` and be rejected
    by ``_is_public_host``. Tests that specifically exercise the SSRF guard
    override this by patching ``_is_public_host`` or ``socket.getaddrinfo``
    locally inside the test function.
    """
    with patch.object(resolver, "_is_public_host", return_value=True):
        yield


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
        respx.get("https://slow.example.com/pkg?go-get=1").mock(side_effect=httpx.TimeoutException("timed out"))
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
        respx.get("https://gone.example.com/pkg?go-get=1").mock(return_value=httpx.Response(404))
        assert resolve_go_module("gone.example.com/pkg") is None

    @respx.mock
    def test_deep_path_segment_stripping(self):
        """Deep paths strip to root module (k8s.io/api/core/v1 → k8s.io/api)."""
        # The full path 404s, but the root module path resolves
        respx.get("https://k8s.io/api/core/v1?go-get=1").mock(return_value=httpx.Response(404))
        respx.get("https://k8s.io/api/core?go-get=1").mock(return_value=httpx.Response(404))
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
        respx.get("https://example.com/pkg?go-get=1").mock(return_value=httpx.Response(200, text=html))
        assert resolve_go_module("example.com/pkg") == "right/repo"

    @respx.mock
    def test_mod_vcs_type_skipped(self):
        """Meta tags with VCS type 'mod' (proxy entries) are skipped."""
        html = (
            '<meta name="go-import" content="example.com/pkg mod https://proxy.golang.org">'
            '<meta name="go-import" content="example.com/pkg git https://github.com/real/repo">'
        )
        respx.get("https://example.com/pkg?go-get=1").mock(return_value=httpx.Response(200, text=html))
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


class TestResolveCratesIo:
    @respx.mock
    def test_crate_found(self):
        respx.get("https://crates.io/api/v1/crates/serde").mock(
            return_value=httpx.Response(
                200,
                json={"crate": {"repository": "https://github.com/serde-rs/serde"}},
            )
        )
        assert resolve_crates_io("serde") == "serde-rs/serde"

    @respx.mock
    def test_crate_not_found(self):
        respx.get("https://crates.io/api/v1/crates/nonexistent").mock(return_value=httpx.Response(404))
        assert resolve_crates_io("nonexistent") is None

    @respx.mock
    def test_crate_no_github(self):
        respx.get("https://crates.io/api/v1/crates/nope").mock(
            return_value=httpx.Response(
                200,
                json={"crate": {"repository": "https://gitlab.com/owner/nope"}},
            )
        )
        assert resolve_crates_io("nope") is None

    @respx.mock
    def test_crate_timeout(self):
        respx.get("https://crates.io/api/v1/crates/slow").mock(side_effect=httpx.TimeoutException("timed out"))
        assert resolve_crates_io("slow") is None


class TestResolveNpm:
    @respx.mock
    def test_npm_found_object_repo(self):
        respx.get("https://registry.npmjs.org/express").mock(
            return_value=httpx.Response(
                200,
                json={"repository": {"type": "git", "url": "git+https://github.com/expressjs/express.git"}},
            )
        )
        assert resolve_npm("express") == "expressjs/express"

    @respx.mock
    def test_npm_found_string_repo(self):
        respx.get("https://registry.npmjs.org/simple").mock(
            return_value=httpx.Response(
                200,
                json={"repository": "https://github.com/owner/simple"},
            )
        )
        assert resolve_npm("simple") == "owner/simple"

    @respx.mock
    def test_npm_not_found(self):
        respx.get("https://registry.npmjs.org/nonexistent").mock(return_value=httpx.Response(404))
        assert resolve_npm("nonexistent") is None

    @respx.mock
    def test_npm_no_github(self):
        respx.get("https://registry.npmjs.org/nope").mock(
            return_value=httpx.Response(
                200,
                json={"repository": {"url": "https://bitbucket.org/owner/nope"}},
            )
        )
        assert resolve_npm("nope") is None

    @respx.mock
    def test_npm_scoped_package(self):
        respx.get("https://registry.npmjs.org/@babel/core").mock(
            return_value=httpx.Response(
                200,
                json={"repository": {"url": "https://github.com/babel/babel.git"}},
            )
        )
        assert resolve_npm("@babel/core") == "babel/babel"


class TestResolveRubygems:
    @respx.mock
    def test_gem_found(self):
        respx.get("https://rubygems.org/api/v1/gems/rails.json").mock(
            return_value=httpx.Response(
                200,
                json={"source_code_uri": "https://github.com/rails/rails"},
            )
        )
        assert resolve_rubygems("rails") == "rails/rails"

    @respx.mock
    def test_gem_homepage_fallback(self):
        respx.get("https://rubygems.org/api/v1/gems/old-gem.json").mock(
            return_value=httpx.Response(
                200,
                json={"source_code_uri": None, "homepage_uri": "https://github.com/owner/old-gem"},
            )
        )
        assert resolve_rubygems("old-gem") == "owner/old-gem"

    @respx.mock
    def test_gem_not_found(self):
        respx.get("https://rubygems.org/api/v1/gems/nonexistent.json").mock(return_value=httpx.Response(404))
        assert resolve_rubygems("nonexistent") is None

    @respx.mock
    def test_gem_no_github(self):
        respx.get("https://rubygems.org/api/v1/gems/nope.json").mock(
            return_value=httpx.Response(
                200,
                json={"source_code_uri": "https://gitlab.com/owner/nope", "homepage_uri": "https://example.com"},
            )
        )
        assert resolve_rubygems("nope") is None


class TestSSRFGuard:
    """Coverage for _is_public_host, _safe_go_get, and the env-var allowlist.

    Overrides the module-level `_bypass_ssrf_check_by_default` autouse fixture
    with a no-op so the real guard runs. Each test patches
    `socket.getaddrinfo` to supply controlled IPs.
    """

    @pytest.fixture(autouse=True)
    def _bypass_ssrf_check_by_default(self):
        """Override: SSRF tests need the real _is_public_host to run."""
        yield

    def _make_addrinfo(self, ip: str):
        """Build a single addrinfo tuple matching socket.getaddrinfo's shape."""
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]

    def _multi_addrinfo(self, *ips: str):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in ips]

    def test_rejects_aws_metadata_ip(self):
        """Link-local AWS metadata address (169.254.169.254) is rejected."""
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=self._make_addrinfo("169.254.169.254")):
            assert real_is_public_host("aws-metadata.example") is False

    def test_rejects_private_ip(self):
        """RFC1918 10.0.0.1 is rejected."""
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=self._make_addrinfo("10.0.0.1")):
            assert real_is_public_host("internal.example") is False

    def test_rejects_loopback_ipv4(self):
        """127.0.0.1 is rejected."""
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=self._make_addrinfo("127.0.0.1")):
            assert real_is_public_host("localhost") is False

    def test_rejects_ipv6_loopback(self):
        """IPv6 ::1 is rejected via ipaddress.is_loopback."""
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        addrinfo = [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0))]
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=addrinfo):
            assert real_is_public_host("ip6-localhost") is False

    def test_rejects_multi_a_record_with_private(self):
        """DNS record with both public AND private IPs is rejected.

        This is the SSRF bypass pattern where an attacker publishes a record
        with multiple A values hoping the client picks the private one. Our
        guard iterates all results and fails closed if ANY is private.
        """
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        with patch(
            "give_back.deps.resolver.socket.getaddrinfo",
            return_value=self._multi_addrinfo("1.2.3.4", "10.0.0.1"),
        ):
            assert real_is_public_host("sneaky.example") is False

    def test_rejects_on_dns_failure(self):
        """DNS resolution failure means the host is rejected (fail-closed)."""
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        with patch("give_back.deps.resolver.socket.getaddrinfo", side_effect=socket.gaierror("no such host")):
            assert real_is_public_host("nonexistent.invalid") is False

    def test_accepts_public_ip(self):
        """Normal public IP is accepted."""
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=self._make_addrinfo("8.8.8.8")):
            assert real_is_public_host("dns.google") is True

    def test_allowlist_accepts_private_host(self, monkeypatch):
        """GIVE_BACK_ALLOW_PRIVATE_HOSTS opts specific hosts past the guard."""
        monkeypatch.setenv("GIVE_BACK_ALLOW_PRIVATE_HOSTS", "go.company.internal,gitlab.internal")
        resolver._clear_allowlist()  # force re-read of env var
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        # Even though the IP is private, the host is on the allowlist.
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=self._make_addrinfo("10.0.0.5")):
            assert real_is_public_host("go.company.internal") is True
            assert real_is_public_host("gitlab.internal") is True
        # But a different private host is still rejected.
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=self._make_addrinfo("10.0.0.6")):
            assert real_is_public_host("not-on-allowlist.internal") is False

    def test_allowlist_miss_emits_one_shot_warning(self, capsys):
        """First rejection of a host emits a stderr warning; second is silent."""
        resolver._clear_allowlist()
        real_is_public_host = _REAL_IS_PUBLIC_HOST
        with patch("give_back.deps.resolver.socket.getaddrinfo", return_value=self._make_addrinfo("10.0.0.5")):
            # First call — warns.
            real_is_public_host("internal.example")
            first_err = capsys.readouterr().err
            assert "GIVE_BACK_ALLOW_PRIVATE_HOSTS" in first_err
            assert "internal.example" in first_err
            # Second call — same host, no new warning.
            real_is_public_host("internal.example")
            second_err = capsys.readouterr().err
            assert second_err == ""

    @respx.mock
    def test_safe_go_get_rejects_redirect_to_private(self):
        """Redirect from a public host to a private IP is rejected mid-chain."""
        respx.get("https://public.example/pkg?go-get=1").mock(
            return_value=httpx.Response(302, headers={"location": "https://internal.example/pkg?go-get=1"})
        )

        # Public host passes first check; internal.example resolves to private.
        def fake_addrinfo(host, *args, **kwargs):
            if host == "public.example":
                return self._make_addrinfo("1.2.3.4")
            return self._make_addrinfo("10.0.0.5")

        with patch("give_back.deps.resolver.socket.getaddrinfo", side_effect=fake_addrinfo):
            assert _REAL_SAFE_GO_GET("public.example/pkg") is None

    @respx.mock
    def test_safe_go_get_max_redirects_cap(self):
        """_safe_go_get returns None after exceeding _GO_GET_MAX_REDIRECTS."""
        # Each URL redirects to the next; build a chain longer than the cap.
        chain = [f"https://public{i}.example/pkg?go-get=1" for i in range(10)]
        for i, url in enumerate(chain[:-1]):
            respx.get(url).mock(return_value=httpx.Response(302, headers={"location": chain[i + 1]}))
        respx.get(chain[-1]).mock(return_value=httpx.Response(200, text="<meta name='go-import' content='x'>"))

        with patch(
            "give_back.deps.resolver.socket.getaddrinfo",
            return_value=self._make_addrinfo("1.2.3.4"),
        ):
            assert _REAL_SAFE_GO_GET("public0.example/pkg") is None
