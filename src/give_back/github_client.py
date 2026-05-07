"""Thin httpx wrapper for GitHub REST + GraphQL API.

Handles:
- Authentication (Bearer token or unauthenticated)
- Adaptive rate limiting (sleeps when approaching limit)
- Retry with backoff (2x on timeout)
- GraphQL error detection (200 with errors key or repository: null)
- Separate search API rate limit (30/min)

Retry/throttle flow:
    request ──► check rate limit ──► execute
                    │                    │
                    ▼                    ▼
              sleep if <10%        success? ──► return
              remaining                │
                                  timeout? ──► retry (2x backoff)
                                       │
                                  401? ──► AuthenticationError
                                  403+rate? ──► RateLimitError (sleep+retry)
                                  404? ──► RepoNotFoundError
"""

from __future__ import annotations

import time
from typing import Any, cast

import httpx

from give_back.exceptions import (
    AuthenticationError,
    GitHubClientError,
    GitHubServerError,
    GraphQLError,
    RateLimitError,
    RepoNotFoundError,
)

_GITHUB_API_BASE = "https://api.github.com"
_GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Retry configuration
_MAX_RETRIES = 2
_INITIAL_BACKOFF = 1.0  # seconds

# Rate limit safety margin: sleep when remaining drops below this fraction of the limit
_RATE_LIMIT_SAFETY_FRACTION = 0.10


class GitHubClient:
    """Synchronous GitHub API client with rate limiting and retry logic."""

    def __init__(self, token: str | None = None) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.Client(
            base_url=_GITHUB_API_BASE,
            headers=headers,
            timeout=30.0,
        )
        self.authenticated = token is not None

        # Track rate limit state from response headers
        self._rate_remaining: int | None = None
        self._rate_limit: int | None = None
        self._rate_reset: int | None = None

        # Search API has a separate, tighter limit (30/min)
        self._search_remaining: int | None = None
        self._search_reset: int | None = None

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query. Returns the 'data' dict.

        Raises:
            GraphQLError: If the response contains an 'errors' key.
            RepoNotFoundError: If repository is null in the response.
            AuthenticationError: On 401.
            RateLimitError: On 403 with rate limit headers.
        """
        response = self._request_with_retry(
            "POST",
            _GITHUB_GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
        )
        body = response.json()

        # Check for GraphQL-level errors (HTTP 200 but errors present)
        if "errors" in body:
            messages = [e.get("message", "Unknown error") for e in body["errors"]]
            raise GraphQLError(f"GraphQL errors: {'; '.join(messages)}", errors=body["errors"])

        data: dict[str, Any] = body.get("data", {})

        # Check for null repository (repo not found or private)
        if "repository" in data and data["repository"] is None:
            raise RepoNotFoundError("Repository not found or is private")

        return data

    def rest_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a REST API endpoint. Returns parsed JSON.

        Raises:
            RepoNotFoundError: On 404.
            AuthenticationError: On 401.
            RateLimitError: On 403 with rate limit headers.
        """
        response = self._request_with_retry("GET", path, params=params)
        return cast(dict[str, Any], response.json())

    def rest_post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST to a REST API endpoint. Returns parsed JSON.

        Raises:
            AuthenticationError: On 401.
            RateLimitError: On 403 with rate limit headers.
        """
        response = self._request_with_retry("POST", path, json=json)
        return cast(dict[str, Any], response.json())

    def search(self, query: str) -> dict[str, Any]:
        """Execute a search API query. Returns parsed JSON.

        Uses the separate search rate limit tracking (30 req/min).
        """
        self._check_search_rate_limit()
        response = self._request_with_retry("GET", "/search/issues", params={"q": query, "per_page": 10})
        self._update_search_rate_limit(response)
        return cast(dict[str, Any], response.json())

    def search_repos(self, query: str, per_page: int = 30, sort: str = "stars") -> dict[str, Any]:
        """Search the repositories endpoint. Returns parsed JSON.

        Uses the separate search rate limit tracking (30 req/min).
        """
        self._check_search_rate_limit()
        response = self._request_with_retry(
            "GET", "/search/repositories", params={"q": query, "per_page": per_page, "sort": sort}
        )
        self._update_search_rate_limit(response)
        return cast(dict[str, Any], response.json())

    def has_rate_budget(self, calls: int) -> bool:
        """Check if enough core API budget remains for *calls* requests."""
        if self._rate_remaining is None:
            return True  # Unknown budget, optimistic
        return self._rate_remaining >= calls

    @property
    def rate_remaining(self) -> int | None:
        """Current core API rate-limit remaining, or None if unknown."""
        return self._rate_remaining

    def check_rate_limit(self) -> dict[str, Any]:
        """Return current rate limit status from the API."""
        response = self._client.get("/rate_limit")
        return cast(dict[str, Any], response.json())

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- Internal ---

    def _request_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Execute an HTTP request with retry on timeout and rate limit handling.

        ``**kwargs`` is typed as ``Any`` because they pass through to
        ``httpx.Client.request``, which is overloaded with a complex union of
        per-parameter types (json, params, headers, cookies, auth, follow_redirects,
        timeout). Narrowing here would require enumerating all of them.
        """
        self._check_rate_limit()

        backoff = _INITIAL_BACKOFF

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.request(method, url, **kwargs)

                self._update_rate_limit(response)
                self._handle_error_status(response)
                return response

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise

            except RateLimitError as exc:
                if exc.reset_at and attempt < _MAX_RETRIES:
                    wait = max(0, exc.reset_at - int(time.time())) + 1
                    time.sleep(min(wait, 120))  # Cap at 120s to guard against clock skew
                else:
                    raise

        # Every terminal path in the loop above either returns or raises.
        # This line is unreachable; keep it as an explicit error in case a
        # future refactor adds a branch that forgets to raise.
        raise RuntimeError("unreachable: retry loop exited without return or raise")

    def _handle_error_status(self, response: httpx.Response) -> None:
        """Raise appropriate exceptions for HTTP error status codes."""
        if response.status_code == 401:
            raise AuthenticationError("GitHub API authentication failed. Check your GITHUB_TOKEN.")

        if response.status_code == 403:
            # Check if this is a rate limit error
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) == 0:
                reset_at = int(response.headers.get("X-RateLimit-Reset", "0"))
                raise RateLimitError("GitHub API rate limit exceeded.", reset_at=reset_at)
            # 403 without rate limit headers — some other permission issue
            raise AuthenticationError(f"GitHub API access denied: {response.text[:200]}")

        if response.status_code == 404:
            raise RepoNotFoundError(f"Not found: {response.url}")

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            # Distinct name so mypy doesn't carry the int inference from the 403 branch above.
            retry_reset_at: int | None = int(time.time()) + int(retry_after) if retry_after else None
            raise RateLimitError("GitHub API rate limit exceeded (429).", reset_at=retry_reset_at)

        # Split remaining error codes: 5xx = retryable server error, other 4xx = client error.
        if 500 <= response.status_code < 600:
            raise GitHubServerError(
                f"GitHub API {response.status_code} for {response.url}: {response.text[:200]}",
                status_code=response.status_code,
            )

        if response.status_code >= 400:
            raise GitHubClientError(
                f"GitHub API {response.status_code} for {response.url}: {response.text[:200]}",
                status_code=response.status_code,
            )

    def _update_rate_limit(self, response: httpx.Response) -> None:
        """Update core rate limit tracking from response headers.

        GitHub tracks several rate-limit buckets independently (core, search,
        graphql, integration_manifest, ...) and identifies which bucket a
        response belongs to via ``X-RateLimit-Resource``. Because
        ``_request_with_retry`` runs for every request — including
        ``/search/*`` — we must ignore responses from other buckets here, or
        search responses will poison the core counter consulted by
        :meth:`has_rate_budget`.
        """
        resource = response.headers.get("X-RateLimit-Resource")
        if resource is not None and resource != "core":
            return

        remaining = response.headers.get("X-RateLimit-Remaining")
        limit = response.headers.get("X-RateLimit-Limit")
        reset = response.headers.get("X-RateLimit-Reset")

        if remaining is not None:
            self._rate_remaining = int(remaining)
        if limit is not None:
            self._rate_limit = int(limit)
        if reset is not None:
            self._rate_reset = int(reset)

    def _update_search_rate_limit(self, response: httpx.Response) -> None:
        """Update search-specific rate limit tracking.

        Mirror of :meth:`_update_rate_limit`: only accept headers when the
        response is explicitly from the ``search`` bucket, so a stray core
        response cannot clobber the search counter.
        """
        resource = response.headers.get("X-RateLimit-Resource")
        if resource is not None and resource != "search":
            return

        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")

        if remaining is not None:
            self._search_remaining = int(remaining)
        if reset is not None:
            self._search_reset = int(reset)

    def _check_rate_limit(self) -> None:
        """Sleep if approaching the rate limit."""
        if self._rate_remaining is not None and self._rate_limit is not None:
            threshold = int(self._rate_limit * _RATE_LIMIT_SAFETY_FRACTION)
            if self._rate_remaining <= threshold and self._rate_reset:
                wait = max(0, self._rate_reset - int(time.time())) + 1
                time.sleep(min(wait, 60))

    def _check_search_rate_limit(self) -> None:
        """Sleep if approaching the search rate limit (30/min, separate from core limit)."""
        if self._search_remaining is not None and self._search_remaining <= 2 and self._search_reset:
            wait = max(0, self._search_reset - int(time.time())) + 1
            time.sleep(min(wait, 60))
