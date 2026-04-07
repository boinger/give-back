"""Tests for give_back.console._effective_width."""

from __future__ import annotations

import pytest

from give_back.console import _NON_TTY_FALLBACK_WIDTH, _effective_width


class TestEffectiveWidth:
    """Width policy for rich consoles used by give-back output."""

    def test_returns_none_when_stdout_is_tty(self, monkeypatch):
        """TTY path: return None so rich auto-detects from the terminal."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert _effective_width() is None

    def test_returns_none_when_stderr_is_tty(self, monkeypatch):
        """Stderr TTY path: return None so rich auto-detects."""
        monkeypatch.setattr("sys.stderr.isatty", lambda: True)
        assert _effective_width(is_stderr=True) is None

    def test_fallback_width_when_stdout_piped(self, monkeypatch):
        """Non-TTY path with no COLUMNS env: use the wide fallback, not rich's 80."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.delenv("COLUMNS", raising=False)
        assert _effective_width() == _NON_TTY_FALLBACK_WIDTH

    def test_honors_columns_env_when_piped(self, monkeypatch):
        """Non-TTY path with COLUMNS set: honour the caller's override."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.setenv("COLUMNS", "160")
        assert _effective_width() == 160

    def test_ignores_non_numeric_columns(self, monkeypatch):
        """Garbage $COLUMNS value should fall back rather than raise."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.setenv("COLUMNS", "not-a-number")
        assert _effective_width() == _NON_TTY_FALLBACK_WIDTH

    def test_is_stderr_selects_stderr_stream(self, monkeypatch):
        """is_stderr=True must check sys.stderr, not sys.stdout."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)  # would return None
        monkeypatch.setattr("sys.stderr.isatty", lambda: False)
        monkeypatch.delenv("COLUMNS", raising=False)
        assert _effective_width(is_stderr=True) == _NON_TTY_FALLBACK_WIDTH

    @pytest.mark.parametrize("columns_value", ["0", "1", "40", "300"])
    def test_accepts_any_positive_integer_columns(self, monkeypatch, columns_value):
        """Any digit string in COLUMNS is passed through verbatim."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        monkeypatch.setenv("COLUMNS", columns_value)
        assert _effective_width() == int(columns_value)
