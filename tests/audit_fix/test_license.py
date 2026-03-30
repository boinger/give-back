"""Tests for audit_fix license picker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from give_back.audit_fix.license import _extract_slug_from_url, _fill_placeholders, pick_license


class TestSlugExtraction:
    def test_standard_url(self):
        assert _extract_slug_from_url("https://choosealicense.com/licenses/mit/") == "mit"

    def test_no_trailing_slash(self):
        assert _extract_slug_from_url("https://choosealicense.com/licenses/gpl-3.0") == "gpl-3.0"

    def test_invalid_url(self):
        assert _extract_slug_from_url("https://example.com/foo") is None

    def test_complex_slug(self):
        assert _extract_slug_from_url("https://choosealicense.com/licenses/bsd-2-clause/") == "bsd-2-clause"


class TestPlaceholderFill:
    def test_year_and_fullname(self):
        text = "Copyright [year] [fullname]"
        result = _fill_placeholders(text, "Test User")
        assert "Test User" in result
        assert "[year]" not in result
        assert "[fullname]" not in result

    def test_alternate_placeholders(self):
        text = "Copyright [yyyy] [name of copyright owner]"
        result = _fill_placeholders(text, "Jane Doe")
        assert "Jane Doe" in result
        assert "[yyyy]" not in result

    def test_no_placeholders(self):
        text = "This license has no placeholders."
        result = _fill_placeholders(text, "Nobody")
        assert result == text


class TestPickLicense:
    def test_pick_mit(self):
        client = MagicMock()
        client.rest_get.return_value = {"body": "MIT License\nCopyright [year] [fullname]"}

        with (
            patch("give_back.audit_fix.license.click.prompt", side_effect=["1", "Test User"]),
            patch("give_back.audit_fix.license.click.echo"),
        ):
            result = pick_license(client)

        assert result is not None
        content, fullname = result
        assert "MIT License" in content
        assert "Test User" in content
        assert fullname == "Test User"
        client.rest_get.assert_called_once_with("/licenses/mit")

    def test_pick_skip(self):
        client = MagicMock()
        with (
            patch("give_back.audit_fix.license.click.prompt", return_value="5"),
            patch("give_back.audit_fix.license.click.echo"),
        ):
            result = pick_license(client)
        assert result is None

    def test_api_failure_fallback(self):
        from give_back.exceptions import GiveBackError

        client = MagicMock()
        client.rest_get.side_effect = GiveBackError("API error")

        with (
            patch("give_back.audit_fix.license.click.prompt", return_value="1"),
            patch("give_back.audit_fix.license.click.echo"),
        ):
            result = pick_license(client)
        assert result is None

    def test_paste_url(self):
        client = MagicMock()
        client.rest_get.return_value = {"body": "GPL v3\nCopyright [year] [fullname]"}

        with (
            patch(
                "give_back.audit_fix.license.click.prompt",
                side_effect=["4", "https://choosealicense.com/licenses/gpl-3.0/", "Jane"],
            ),
            patch("give_back.audit_fix.license.click.echo"),
        ):
            result = pick_license(client)

        assert result is not None
        content, fullname = result
        assert "GPL v3" in content
        client.rest_get.assert_called_once_with("/licenses/gpl-3.0")

    def test_fullname_passed_in(self):
        """When fullname is provided, don't prompt for it."""
        client = MagicMock()
        client.rest_get.return_value = {"body": "MIT License\nCopyright [year] [fullname]"}

        with (
            patch("give_back.audit_fix.license.click.prompt", return_value="1"),
            patch("give_back.audit_fix.license.click.echo"),
        ):
            result = pick_license(client, fullname="Pre-filled")

        assert result is not None
        content, fullname = result
        assert "Pre-filled" in content
