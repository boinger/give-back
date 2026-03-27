"""LLM-assisted license evaluation for unrecognized licenses.

When the license gate returns YELLOW (unrecognized / NOASSERTION), fetches the
LICENSE file text and asks Claude to classify it. Purely additive — if the
Anthropic API key is missing or the call fails, the original signal is unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5-20251001"
_MAX_LICENSE_CHARS = 4000

_SYSTEM_PROMPT = (
    "You are a software license classifier. Analyze the given license text and respond "
    "with a JSON object containing: classification (one of: Permissive, Copyleft, "
    "Weak-Copyleft, Source-Available, Proprietary, Public-Domain, Unknown), summary "
    "(one-line description), oss_compatible (boolean — true if the license allows open "
    "source contribution), confidence (high/medium/low), details (2-3 sentence "
    "explanation). Respond ONLY with the JSON object, no other text."
)

# License file names to try, in order of preference
_LICENSE_FILENAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")


@dataclass
class LicenseEvaluation:
    """Result from LLM license classification."""

    classification: str
    """e.g., 'Permissive', 'Copyleft', 'Source-Available', 'Unknown'."""

    summary: str
    """One-line description."""

    oss_compatible: bool
    """Whether the license is compatible with OSS contribution."""

    confidence: str
    """'high', 'medium', or 'low'."""

    details: str
    """Longer explanation (2-3 sentences)."""


def evaluate_license_text(license_text: str) -> LicenseEvaluation | None:
    """Send license text to Claude API for classification.

    Returns None if ANTHROPIC_API_KEY is not set or the API call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    # Truncate to avoid excessive token usage
    truncated = license_text[:_MAX_LICENSE_CHARS]

    try:
        response = httpx.post(
            _ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": 512,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": truncated}],
            },
            timeout=15.0,
        )
        response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException):
        return None

    try:
        body = response.json()
        # Extract the text content from the Messages API response
        text = body["content"][0]["text"]
        parsed = json.loads(text)

        return LicenseEvaluation(
            classification=str(parsed["classification"]),
            summary=str(parsed["summary"]),
            oss_compatible=bool(parsed["oss_compatible"]),
            confidence=str(parsed["confidence"]),
            details=str(parsed["details"]),
        )
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
