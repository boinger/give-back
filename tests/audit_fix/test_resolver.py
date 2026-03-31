"""Tests for TemplateResolver: built-in, local dir, and remote repo modes."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from give_back.audit_fix.resolver import TemplateResolver


class TestBuiltinMode:
    def test_returns_builtin_with_placeholders_filled(self):
        resolver = TemplateResolver()
        content = resolver.get("CODE_OF_CONDUCT.md", "pallets", "flask")
        assert "Contributor Covenant" in content
        assert "pallets/flask" in content
        assert "{owner}" not in content

    def test_unknown_key_raises(self):
        resolver = TemplateResolver()
        with pytest.raises(KeyError):
            resolver.get("NONEXISTENT.md", "a", "b")

    def test_is_custom_false(self):
        resolver = TemplateResolver()
        assert resolver.is_custom is False

    def test_source_label(self):
        assert TemplateResolver().source_label == "built-in"


class TestLocalDirMode:
    def test_reads_from_dir(self, tmp_path):
        (tmp_path / "CODE_OF_CONDUCT.md").write_text("Custom CoC for {owner}/{repo}")
        resolver = TemplateResolver(template_dir=tmp_path)
        content = resolver.get("CODE_OF_CONDUCT.md", "pallets", "flask")
        assert content == "Custom CoC for pallets/flask"

    def test_falls_back_to_builtin(self, tmp_path):
        # Dir exists but doesn't have SECURITY.md
        resolver = TemplateResolver(template_dir=tmp_path)
        content = resolver.get("SECURITY.md", "pallets", "flask")
        assert "vulnerability" in content.lower()

    def test_nested_path(self, tmp_path):
        pr_dir = tmp_path / ".github"
        pr_dir.mkdir()
        (pr_dir / "PULL_REQUEST_TEMPLATE.md").write_text("Custom PR template for {owner}/{repo}")
        resolver = TemplateResolver(template_dir=tmp_path)
        content = resolver.get(".github/PULL_REQUEST_TEMPLATE.md", "test", "repo")
        assert content == "Custom PR template for test/repo"

    def test_is_custom_true(self, tmp_path):
        resolver = TemplateResolver(template_dir=tmp_path)
        assert resolver.is_custom is True

    def test_source_label(self, tmp_path):
        resolver = TemplateResolver(template_dir=tmp_path)
        assert str(tmp_path) in resolver.source_label


class TestRemoteRepoMode:
    def test_fetches_from_github(self):
        client = MagicMock()
        raw = "Remote CoC for {owner}/{repo}"
        client.rest_get.return_value = {
            "encoding": "base64",
            "content": base64.b64encode(raw.encode()).decode(),
        }
        resolver = TemplateResolver(template_repo="myorg/standards", client=client)
        content = resolver.get("CODE_OF_CONDUCT.md", "pallets", "flask")
        assert "pallets/flask" in content
        client.rest_get.assert_called_once_with("/repos/myorg/standards/contents/CODE_OF_CONDUCT.md")

    def test_replaces_source_repo_references(self):
        client = MagicMock()
        raw = "Report issues at https://github.com/myorg/standards/issues"
        client.rest_get.return_value = {
            "encoding": "base64",
            "content": base64.b64encode(raw.encode()).decode(),
        }
        resolver = TemplateResolver(template_repo="myorg/standards", client=client)
        content = resolver.get("SECURITY.md", "pallets", "flask")
        assert "pallets/flask" in content
        assert "myorg" not in content

    def test_falls_back_on_api_error(self):
        from give_back.exceptions import GiveBackError

        client = MagicMock()
        client.rest_get.side_effect = GiveBackError("not found")
        resolver = TemplateResolver(template_repo="myorg/standards", client=client)
        content = resolver.get("SECURITY.md", "pallets", "flask")
        # Should fall back to built-in
        assert "vulnerability" in content.lower()

    def test_caches_remote_results(self):
        client = MagicMock()
        raw = "Cached content"
        client.rest_get.return_value = {
            "encoding": "base64",
            "content": base64.b64encode(raw.encode()).decode(),
        }
        resolver = TemplateResolver(template_repo="myorg/standards", client=client)
        resolver.get("SECURITY.md", "a", "b")
        resolver.get("SECURITY.md", "c", "d")
        # Should only call API once
        assert client.rest_get.call_count == 1

    def test_is_custom_true(self):
        resolver = TemplateResolver(template_repo="myorg/standards", client=MagicMock())
        assert resolver.is_custom is True

    def test_invalid_repo_format(self):
        with pytest.raises(ValueError, match="expected owner/repo"):
            TemplateResolver(template_repo="just-a-name", client=MagicMock())


class TestMutualExclusion:
    def test_both_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Cannot specify both"):
            TemplateResolver(template_dir=tmp_path, template_repo="a/b", client=MagicMock())
