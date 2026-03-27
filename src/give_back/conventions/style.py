"""Detect code style tooling: linters, formatters, line length."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from give_back.conventions.models import StyleInfo


def _detect_linter(clone_dir: Path) -> tuple[str | None, str | None]:
    """Detect linter and its config file. Returns (linter_name, config_file)."""
    # Python: ruff
    ruff_toml = clone_dir / "ruff.toml"
    if ruff_toml.exists():
        return "ruff", "ruff.toml"

    pyproject = clone_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            tool = data.get("tool", {})
            if "ruff" in tool:
                return "ruff", "pyproject.toml"
            if "pylint" in tool:
                return "pylint", "pyproject.toml"
        except (tomllib.TOMLDecodeError, OSError):
            pass

    # Python: flake8
    if (clone_dir / ".flake8").exists():
        return "flake8", ".flake8"

    setup_cfg = clone_dir / "setup.cfg"
    if setup_cfg.exists():
        try:
            content = setup_cfg.read_text(encoding="utf-8")
            if "[flake8]" in content:
                return "flake8", "setup.cfg"
        except OSError:
            pass

    # Go: golangci-lint
    for name in (".golangci.yml", ".golangci.yaml"):
        if (clone_dir / name).exists():
            return "golangci-lint", name

    # JS/TS: eslint
    for pattern in ("eslintrc", "eslint.config"):
        for f in clone_dir.glob(f".{pattern}*") if "eslintrc" in pattern else clone_dir.glob(f"{pattern}*"):
            return "eslint", f.name

    # Rust: clippy
    if (clone_dir / "clippy.toml").exists():
        return "clippy", "clippy.toml"

    return None, None


def _detect_formatter(clone_dir: Path, linter: str | None) -> str | None:
    """Detect code formatter."""
    # Python: ruff format
    if linter == "ruff":
        pyproject = clone_dir / "pyproject.toml"
        ruff_toml = clone_dir / "ruff.toml"

        for cfg_path in (ruff_toml, pyproject):
            if cfg_path.exists():
                try:
                    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
                    # ruff.toml: [format] section at top level
                    # pyproject.toml: [tool.ruff.format]
                    if cfg_path.name == "pyproject.toml":
                        ruff_section = data.get("tool", {}).get("ruff", {})
                    else:
                        ruff_section = data
                    if "format" in ruff_section:
                        return "ruff format"
                except (tomllib.TOMLDecodeError, OSError):
                    pass

    # Python: black
    pyproject = clone_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            if "black" in data.get("tool", {}):
                return "black"
        except (tomllib.TOMLDecodeError, OSError):
            pass

    # Go: always gofmt
    if list(clone_dir.rglob("*.go")):
        return "gofmt"

    # JS/TS: prettier
    for f in clone_dir.glob(".prettierrc*"):
        return "prettier"
    for f in clone_dir.glob("prettier.config.*"):
        return "prettier"

    # Rust: rustfmt
    if (clone_dir / "rustfmt.toml").exists():
        return "rustfmt"

    return None


def _extract_line_length(clone_dir: Path, linter: str | None, config_file: str | None) -> int | None:
    """Extract line length from linter/formatter config if available."""
    if not config_file:
        return None

    cfg_path = clone_dir / config_file

    if not cfg_path.exists():
        return None

    # TOML-based configs (ruff.toml, pyproject.toml)
    if config_file in ("ruff.toml", "pyproject.toml"):
        try:
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
            if config_file == "pyproject.toml":
                # Check [tool.ruff] or [tool.black]
                tool = data.get("tool", {})
                for section_name in ("ruff", "black"):
                    section = tool.get(section_name, {})
                    if "line-length" in section:
                        return int(section["line-length"])
                    if "line_length" in section:
                        return int(section["line_length"])
            else:
                # ruff.toml: top-level line-length
                if "line-length" in data:
                    return int(data["line-length"])
                if "line_length" in data:
                    return int(data["line_length"])
        except (tomllib.TOMLDecodeError, OSError, ValueError, TypeError):
            pass

    # INI-style configs (.flake8, setup.cfg)
    if config_file in (".flake8", "setup.cfg"):
        try:
            content = cfg_path.read_text(encoding="utf-8")
            match = re.search(r"max[_-]line[_-]length\s*=\s*(\d+)", content)
            if match:
                return int(match.group(1))
        except OSError:
            pass

    # golangci-lint YAML: check for lll linter config
    if config_file in (".golangci.yml", ".golangci.yaml"):
        try:
            content = cfg_path.read_text(encoding="utf-8")
            # Simple regex for line-length in lll config
            match = re.search(r"line-length\s*:\s*(\d+)", content)
            if match:
                return int(match.group(1))
        except OSError:
            pass

    return None


def _check_editorconfig(clone_dir: Path) -> dict[str, str | int | None]:
    """Extract indent style and size from .editorconfig if present."""
    editorconfig = clone_dir / ".editorconfig"
    if not editorconfig.exists():
        return {}

    result: dict[str, str | int | None] = {}
    try:
        content = editorconfig.read_text(encoding="utf-8")
        indent_style_match = re.search(r"indent_style\s*=\s*(\w+)", content)
        if indent_style_match:
            result["indent_style"] = indent_style_match.group(1)
        indent_size_match = re.search(r"indent_size\s*=\s*(\d+)", content)
        if indent_size_match:
            result["indent_size"] = int(indent_size_match.group(1))
    except OSError:
        pass

    return result


def detect_style(clone_dir: Path) -> StyleInfo:
    """Detect code style tooling from config files in the cloned repo.

    Checks for linters, formatters, line length configuration, and
    .editorconfig settings.
    """
    linter, config_file = _detect_linter(clone_dir)
    formatter = _detect_formatter(clone_dir, linter)
    line_length = _extract_line_length(clone_dir, linter, config_file)

    # Also check .editorconfig (results stored but not yet surfaced in StyleInfo)
    _check_editorconfig(clone_dir)

    return StyleInfo(
        linter=linter,
        formatter=formatter,
        config_file=config_file,
        line_length=line_length,
    )
