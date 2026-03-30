"""Tests for audit_fix label creation via REST API."""

from __future__ import annotations

from unittest.mock import MagicMock

from give_back.audit_fix.labels import create_labels
from give_back.exceptions import AuthenticationError, RateLimitError


class TestCreateLabels:
    def _make_client(self, authenticated: bool = True) -> MagicMock:
        client = MagicMock()
        client.authenticated = authenticated
        return client

    def test_create_both(self):
        client = self._make_client()
        client.rest_post.return_value = {"name": "good first issue", "color": "7057ff"}

        result = create_labels(client, "test", "repo", ["good first issue", "help wanted"])
        assert len(result) == 2
        assert client.rest_post.call_count == 2

    def test_already_exists_422(self):
        """GitHub returns validation error when label already exists."""
        client = self._make_client()
        client.rest_post.return_value = {
            "message": "Validation Failed",
            "errors": [{"resource": "Label", "code": "already_exists", "field": "name"}],
        }

        result = create_labels(client, "test", "repo", ["good first issue"])
        assert result == ["good first issue"]

    def test_no_auth_skips(self):
        client = self._make_client(authenticated=False)
        result = create_labels(client, "test", "repo", ["good first issue"])
        assert result == []

    def test_auth_failure_returns_partial(self):
        client = self._make_client()
        # First call succeeds, second raises auth error
        client.rest_post.side_effect = [
            {"name": "good first issue"},
            AuthenticationError("no write access"),
        ]

        result = create_labels(client, "test", "repo", ["good first issue", "help wanted"])
        assert result == ["good first issue"]

    def test_rate_limit_returns_partial(self):
        client = self._make_client()
        client.rest_post.side_effect = [
            {"name": "good first issue"},
            RateLimitError("limit exceeded", reset_at=9999999),
        ]

        result = create_labels(client, "test", "repo", ["good first issue", "help wanted"])
        assert result == ["good first issue"]

    def test_empty_missing_list(self):
        client = self._make_client()
        result = create_labels(client, "test", "repo", [])
        assert result == []
        client.rest_post.assert_not_called()
