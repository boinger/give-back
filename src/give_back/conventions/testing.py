"""Detect test framework, CI config, test directories, and run commands."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from give_back.conventions.models import CITestInfo


def _detect_framework(clone_dir: Path) -> str | None:
    """Detect the test framework from config files and directory structure."""
    # Python: pytest
    pyproject = clone_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            if "tool" in data and "pytest" in data["tool"]:
                return "pytest"
        except (tomllib.TOMLDecodeError, OSError):
            pass

    if (clone_dir / "pytest.ini").exists():
        return "pytest"

    setup_cfg = clone_dir / "setup.cfg"
    if setup_cfg.exists():
        try:
            content = setup_cfg.read_text(encoding="utf-8")
            if "[tool:pytest]" in content:
                return "pytest"
        except OSError:
            pass

    # Python: check tests/ dir for test files (default pytest), then unittest imports
    test_dirs = ["tests", "test"]
    for td in test_dirs:
        td_path = clone_dir / td
        if td_path.is_dir():
            test_files = list(td_path.glob("test_*.py"))
            if test_files:
                # Check if any import unittest
                for tf in test_files[:5]:
                    try:
                        content = tf.read_text(encoding="utf-8")
                        if "import unittest" in content:
                            return "unittest"
                    except OSError:
                        continue
                return "pytest"

    # Go: *_test.go files
    if list(clone_dir.rglob("*_test.go")):
        return "go test"

    # JS/TS: package.json scripts
    package_json = clone_dir / "package.json"
    if package_json.exists():
        try:
            import json

            data = json.loads(package_json.read_text(encoding="utf-8"))
            test_script = data.get("scripts", {}).get("test", "")
            if "vitest" in test_script:
                return "vitest"
            if "jest" in test_script:
                return "jest"
            if "mocha" in test_script:
                return "mocha"
        except (json.JSONDecodeError, OSError):
            pass

    # Rust: Cargo.toml + #[test] in source files
    if (clone_dir / "Cargo.toml").exists():
        for rs_file in clone_dir.rglob("*.rs"):
            try:
                content = rs_file.read_text(encoding="utf-8")
                if "#[test]" in content:
                    return "cargo test"
            except OSError:
                continue

    return None


def _detect_test_dir(clone_dir: Path) -> str | None:
    """Find the test directory."""
    candidates = ["tests/", "test/", "spec/", "src/test/", "src/tests/"]
    for candidate in candidates:
        if (clone_dir / candidate.rstrip("/")).is_dir():
            return candidate

    # Go: tests are co-located, no separate directory
    if list(clone_dir.rglob("*_test.go")):
        return None

    return None


def _detect_ci(clone_dir: Path) -> str | None:
    """Detect CI configuration."""
    if (clone_dir / ".github" / "workflows").is_dir():
        return "GitHub Actions"

    if (clone_dir / ".travis.yml").exists():
        return "Travis CI"

    if (clone_dir / ".circleci").is_dir():
        return "CircleCI"

    if (clone_dir / "Jenkinsfile").exists():
        return "Jenkins"

    if (clone_dir / "azure-pipelines.yml").exists():
        return "Azure Pipelines"

    return None


def _makefile_has_test_target(clone_dir: Path) -> bool:
    """Check if a Makefile has a test target."""
    makefile = clone_dir / "Makefile"
    if not makefile.exists():
        return False
    try:
        content = makefile.read_text(encoding="utf-8")
        # Match lines like "test:" or ".PHONY: ... test ..."
        for line in content.splitlines():
            if re.match(r"^test\s*:", line):
                return True
            if re.match(r"^\.PHONY\s*:.*\btest\b", line):
                return True
    except OSError:
        pass
    return False


def _infer_run_command(framework: str | None, has_makefile_test: bool) -> str | None:
    """Infer the run command from the framework and Makefile presence."""
    if has_makefile_test:
        return "make test"

    if framework == "pytest":
        return "pytest"
    if framework == "unittest":
        return "python -m pytest"
    if framework == "go test":
        return "go test ./..."
    if framework in ("jest", "mocha", "vitest"):
        return "npm test"
    if framework == "cargo test":
        return "cargo test"

    return None


def detect_testing(clone_dir: Path) -> CITestInfo:
    """Detect test framework, test directory, CI config, and run command.

    Inspects the cloned repo at *clone_dir* for test configuration files,
    directory structure, CI configs, and Makefile targets.
    """
    framework = _detect_framework(clone_dir)
    test_dir = _detect_test_dir(clone_dir)
    ci_config = _detect_ci(clone_dir)
    has_makefile_test = _makefile_has_test_target(clone_dir)
    run_command = _infer_run_command(framework, has_makefile_test)

    return CITestInfo(
        framework=framework,
        test_dir=test_dir,
        ci_config=ci_config,
        run_command=run_command,
    )
