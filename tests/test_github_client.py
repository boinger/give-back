"""Tests for github_client.py."""

import httpx
import pytest
import respx

from give_back.exceptions import (
    AuthenticationError,
    GiveBackError,
    GraphQLError,
    RateLimitError,
    RepoNotFoundError,
)
from give_back.github_client import GitHubClient


@pytest.fixture
def client():
    c = GitHubClient(token="fake-token")
    yield c
    c.close()


@pytest.fixture
def unauth_client():
    c = GitHubClient(token=None)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Eliminate real time.sleep() calls in retry/rate-limit paths."""
    monkeypatch.setattr("give_back.github_client.time.sleep", lambda _: None)


class TestGraphQL:
    @respx.mock
    def test_successful_query(self, client):
        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"repository": {"name": "flask"}}},
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = client.graphql("query { repository { name } }")
        assert result["repository"]["name"] == "flask"

    @respx.mock
    def test_graphql_errors_in_response(self, client):
        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(
                200,
                json={"errors": [{"message": "Field 'foo' not found"}]},
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        with pytest.raises(GraphQLError, match="Field 'foo' not found"):
            client.graphql("query { foo }")

    @respx.mock
    def test_repository_null_raises_not_found(self, client):
        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"repository": None}},
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        with pytest.raises(RepoNotFoundError):
            client.graphql("query { repository { name } }")

    @respx.mock
    def test_401_raises_auth_error(self, client):
        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"})
        )
        with pytest.raises(AuthenticationError):
            client.graphql("query { viewer { login } }")

    @respx.mock
    def test_403_rate_limit_raises(self, client):
        respx.post("https://api.github.com/graphql").mock(
            return_value=httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        with pytest.raises(RateLimitError):
            client.graphql("query { viewer { login } }")


class TestRestGet:
    @respx.mock
    def test_successful_get(self, client):
        respx.get("https://api.github.com/repos/pallets/flask/community/profile").mock(
            return_value=httpx.Response(
                200,
                json={"health_percentage": 100},
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = client.rest_get("/repos/pallets/flask/community/profile")
        assert result["health_percentage"] == 100

    @respx.mock
    def test_404_raises_not_found(self, client):
        respx.get("https://api.github.com/repos/nonexistent/repo").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        with pytest.raises(RepoNotFoundError):
            client.rest_get("/repos/nonexistent/repo")

    @respx.mock
    def test_429_raises_rate_limit(self, client):
        respx.get("https://api.github.com/repos/test/repo").mock(
            return_value=httpx.Response(
                429,
                json={"message": "rate limit"},
                headers={"Retry-After": "30"},
            )
        )
        with pytest.raises(RateLimitError):
            client.rest_get("/repos/test/repo")


class TestSearch:
    @respx.mock
    def test_successful_search(self, client):
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={"total_count": 3, "items": []},
                headers={"X-RateLimit-Remaining": "29", "X-RateLimit-Limit": "30", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = client.search("repo:pallets/flask AI")
        assert result["total_count"] == 3


class TestRetry:
    @respx.mock
    def test_timeout_retries(self, client):
        route = respx.post("https://api.github.com/graphql")
        route.side_effect = [
            httpx.TimeoutException("timeout"),
            httpx.Response(
                200,
                json={"data": {"repository": {"name": "flask"}}},
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            ),
        ]
        result = client.graphql("query { repository { name } }")
        assert result["repository"]["name"] == "flask"
        assert route.call_count == 2

    @respx.mock
    def test_timeout_exhausted(self, client):
        respx.post("https://api.github.com/graphql").mock(side_effect=httpx.TimeoutException("timeout"))
        with pytest.raises(httpx.TimeoutException):
            client.graphql("query { repository { name } }")


class TestUnhandledStatusCodes:
    """Verify that HTTP status codes not explicitly handled (500, 502, 422) raise GiveBackError."""

    @respx.mock
    def test_500_raises_giveback_error(self, client):
        respx.get("https://api.github.com/repos/test/repo").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(GiveBackError, match="500"):
            client.rest_get("/repos/test/repo")

    @respx.mock
    def test_502_raises_giveback_error(self, client):
        respx.get("https://api.github.com/repos/test/repo").mock(return_value=httpx.Response(502, text="Bad Gateway"))
        with pytest.raises(GiveBackError, match="502"):
            client.rest_get("/repos/test/repo")

    @respx.mock
    def test_422_raises_giveback_error(self, client):
        respx.get("https://api.github.com/repos/test/repo").mock(
            return_value=httpx.Response(422, json={"message": "Validation Failed"})
        )
        with pytest.raises(GiveBackError, match="422"):
            client.rest_get("/repos/test/repo")

    @respx.mock
    def test_error_message_includes_url(self, client):
        respx.get("https://api.github.com/repos/test/repo").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(GiveBackError, match="repos/test/repo"):
            client.rest_get("/repos/test/repo")

    @respx.mock
    def test_200_not_affected(self, client):
        """Regression: 2xx responses must not raise."""
        respx.get("https://api.github.com/repos/test/repo").mock(
            return_value=httpx.Response(
                200,
                json={"name": "repo"},
                headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Limit": "5000", "X-RateLimit-Reset": "9999999"},
            )
        )
        result = client.rest_get("/repos/test/repo")
        assert result["name"] == "repo"


class TestClientAuth:
    def test_authenticated_flag(self):
        c = GitHubClient(token="test")
        assert c.authenticated is True
        c.close()

    def test_unauthenticated_flag(self):
        c = GitHubClient(token=None)
        assert c.authenticated is False
        c.close()

    def test_context_manager(self):
        with GitHubClient(token="test") as c:
            assert c.authenticated is True
