"""Template resolver: load templates from built-in defaults, local dir, or remote repo."""

from __future__ import annotations

import base64
from pathlib import Path

import click

from give_back.audit_fix.templates import (
    BUG_REPORT_YML,
    CODE_OF_CONDUCT,
    CONFIG_YML,
    FEATURE_REQUEST_YML,
    PR_TEMPLATE,
    SECURITY,
)
from give_back.exceptions import GiveBackError
from give_back.github_client import GitHubClient

_BUILTIN_TEMPLATES: dict[str, str] = {
    "CODE_OF_CONDUCT.md": CODE_OF_CONDUCT,
    "SECURITY.md": SECURITY,
    ".github/PULL_REQUEST_TEMPLATE.md": PR_TEMPLATE,
    ".github/ISSUE_TEMPLATE/bug_report.yml": BUG_REPORT_YML,
    ".github/ISSUE_TEMPLATE/feature_request.yml": FEATURE_REQUEST_YML,
    ".github/ISSUE_TEMPLATE/config.yml": CONFIG_YML,
}


class TemplateResolver:
    """Resolve template content from a custom source or fall back to built-ins.

    Three modes:
    - Built-in only (default): returns hardcoded template strings.
    - Local directory: reads files from a local path, falls back to built-in.
    - Remote repo: fetches files via GitHub Contents API, falls back to built-in.
    """

    def __init__(
        self,
        *,
        template_dir: Path | None = None,
        template_repo: str | None = None,
        client: GitHubClient | None = None,
    ) -> None:
        if template_dir and template_repo:
            raise ValueError("Cannot specify both --template-dir and --template-repo")
        self._template_dir = template_dir
        self._template_repo = template_repo
        self._client = client
        self._remote_cache: dict[str, str | None] = {}
        self._source_owner: str | None = None
        self._source_repo: str | None = None

        if template_repo:
            parts = template_repo.split("/")
            if len(parts) != 2:
                raise ValueError(f"Invalid template repo format: {template_repo!r} (expected owner/repo)")
            self._source_owner, self._source_repo = parts

    @property
    def is_custom(self) -> bool:
        return self._template_dir is not None or self._template_repo is not None

    @property
    def source_label(self) -> str:
        if self._template_dir:
            return f"local: {self._template_dir}"
        if self._template_repo:
            return f"repo: {self._template_repo}"
        return "built-in"

    def get(self, key: str, owner: str, repo: str) -> str:
        """Get template content for *key*, with {owner}/{repo} placeholders filled.

        Tries custom source first (if configured), falls back to built-in.
        """
        content = self._get_raw(key)

        # Replace source repo references with target repo for custom templates
        if self.is_custom and self._source_owner and self._source_repo:
            content = content.replace(self._source_owner, "{owner}")
            content = content.replace(self._source_repo, "{repo}")

        return content.format(owner=owner, repo=repo)

    def _get_raw(self, key: str) -> str:
        """Get raw template content (before placeholder substitution)."""
        if self._template_dir:
            return self._get_from_dir(key)
        if self._template_repo:
            return self._get_from_repo(key)
        return self._get_builtin(key)

    def _get_builtin(self, key: str) -> str:
        content = _BUILTIN_TEMPLATES.get(key)
        if content is None:
            raise KeyError(f"No built-in template for {key!r}")
        return content

    def _get_from_dir(self, key: str) -> str:
        """Read template from local directory, fall back to built-in."""
        if self._template_dir is None:
            raise ValueError("_get_from_dir called without template_dir set")
        path = self._template_dir / key
        if path.is_file():
            return path.read_text()
        return self._get_builtin(key)

    def _get_from_repo(self, key: str) -> str:
        """Fetch template from GitHub repo via Contents API, fall back to built-in."""
        if key in self._remote_cache:
            cached = self._remote_cache[key]
            if cached is not None:
                return cached
            return self._get_builtin(key)

        if self._client is None:
            raise ValueError("_get_from_repo called without client set")
        if self._source_owner is None or self._source_repo is None:
            raise ValueError("_get_from_repo called without template_repo configured")

        try:
            data = self._client.rest_get(f"/repos/{self._source_owner}/{self._source_repo}/contents/{key}")
            if isinstance(data, dict) and data.get("encoding") == "base64" and data.get("content"):
                content = base64.b64decode(data["content"]).decode("utf-8")
                self._remote_cache[key] = content
                return content
        except GiveBackError:
            click.echo(f"  [dim]Could not fetch {key} from {self._template_repo}, using built-in[/dim]")

        self._remote_cache[key] = None
        return self._get_builtin(key)
