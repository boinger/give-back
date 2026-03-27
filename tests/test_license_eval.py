"""Tests for LLM-assisted license evaluation."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from give_back.license_eval import LicenseEvaluation, evaluate_license_text

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def _make_anthropic_response(classification_data: dict) -> dict:
    """Build a mock Anthropic Messages API response body."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": json.dumps(classification_data)}],
        "model": "claude-haiku-4-5-20251001",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


_PERMISSIVE_RESPONSE = _make_anthropic_response(
    {
        "classification": "Permissive",
        "summary": "Apache-style permissive license",
        "oss_compatible": True,
        "confidence": "high",
        "details": "This license allows free use, modification, and distribution. "
        "It includes a patent grant and requires attribution. "
        "Fully compatible with open source contribution.",
    }
)

_COPYLEFT_RESPONSE = _make_anthropic_response(
    {
        "classification": "Copyleft",
        "summary": "GPL-like copyleft license",
        "oss_compatible": True,
        "confidence": "high",
        "details": "This is a strong copyleft license requiring derivative works to use "
        "the same license. Contributions are welcome but must remain open source. "
        "Similar to GPL v3.",
    }
)


class TestEvaluatePermissive:
    @respx.mock
    def test_returns_permissive_classification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        respx.post(_ANTHROPIC_API_URL).mock(return_value=httpx.Response(200, json=_PERMISSIVE_RESPONSE))

        result = evaluate_license_text("Apache License Version 2.0 ...")

        assert result is not None
        assert isinstance(result, LicenseEvaluation)
        assert result.classification == "Permissive"
        assert result.summary == "Apache-style permissive license"
        assert result.oss_compatible is True
        assert result.confidence == "high"
        assert "patent grant" in result.details


class TestEvaluateCopyleft:
    @respx.mock
    def test_returns_copyleft_classification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        respx.post(_ANTHROPIC_API_URL).mock(return_value=httpx.Response(200, json=_COPYLEFT_RESPONSE))

        result = evaluate_license_text("GNU General Public License ...")

        assert result is not None
        assert result.classification == "Copyleft"
        assert result.oss_compatible is True
        assert result.confidence == "high"


class TestNoApiKey:
    def test_returns_none_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = evaluate_license_text("Some license text")

        assert result is None


class TestApiError:
    @respx.mock
    def test_returns_none_on_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        respx.post(_ANTHROPIC_API_URL).mock(return_value=httpx.Response(500, json={"error": "Internal error"}))

        result = evaluate_license_text("Some license text")

        assert result is None

    @respx.mock
    def test_returns_none_on_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
        respx.post(_ANTHROPIC_API_URL).mock(return_value=httpx.Response(401, json={"error": "Invalid API key"}))

        result = evaluate_license_text("Some license text")

        assert result is None

    @respx.mock
    def test_returns_none_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        respx.post(_ANTHROPIC_API_URL).mock(side_effect=httpx.ConnectTimeout("Connection timed out"))

        result = evaluate_license_text("Some license text")

        assert result is None


class TestInvalidJsonResponse:
    @respx.mock
    def test_returns_none_on_non_json_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        bad_response = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "I cannot classify this license."}],
            "model": "claude-haiku-4-5-20251001",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
        respx.post(_ANTHROPIC_API_URL).mock(return_value=httpx.Response(200, json=bad_response))

        result = evaluate_license_text("Some license text")

        assert result is None

    @respx.mock
    def test_returns_none_on_missing_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        incomplete_response = _make_anthropic_response({"classification": "Permissive"})
        respx.post(_ANTHROPIC_API_URL).mock(return_value=httpx.Response(200, json=incomplete_response))

        result = evaluate_license_text("Some license text")

        assert result is None

    @respx.mock
    def test_returns_none_on_empty_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        empty_content_response = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": "claude-haiku-4-5-20251001",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 0},
        }
        respx.post(_ANTHROPIC_API_URL).mock(return_value=httpx.Response(200, json=empty_content_response))

        result = evaluate_license_text("Some license text")

        assert result is None


class TestTruncatesLongText:
    @respx.mock
    def test_truncates_to_4000_chars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")

        captured_request = {}

        def capture_request(request: httpx.Request) -> httpx.Response:
            captured_request["body"] = json.loads(request.content)
            return httpx.Response(200, json=_PERMISSIVE_RESPONSE)

        respx.post(_ANTHROPIC_API_URL).mock(side_effect=capture_request)

        long_text = "A" * 10000
        result = evaluate_license_text(long_text)

        assert result is not None
        # Verify the message content was truncated
        sent_content = captured_request["body"]["messages"][0]["content"]
        assert len(sent_content) == 4000

    @respx.mock
    def test_short_text_not_truncated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")

        captured_request = {}

        def capture_request(request: httpx.Request) -> httpx.Response:
            captured_request["body"] = json.loads(request.content)
            return httpx.Response(200, json=_PERMISSIVE_RESPONSE)

        respx.post(_ANTHROPIC_API_URL).mock(side_effect=capture_request)

        short_text = "MIT License, Copyright 2024"
        result = evaluate_license_text(short_text)

        assert result is not None
        sent_content = captured_request["body"]["messages"][0]["content"]
        assert sent_content == short_text
