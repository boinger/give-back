"""Tests for conventions/testing.py — test framework and CI detection."""

from __future__ import annotations

import json
from pathlib import Path

from give_back.conventions.testing import detect_testing


class TestFrameworkDetection:
    def test_python_pytest(self, tmp_path: Path) -> None:
        """pyproject.toml with [tool.pytest] + tests/ dir -> framework='pytest'."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("def test_it(): pass\n")

        result = detect_testing(tmp_path)

        assert result.framework == "pytest"

    def test_python_pytest_ini(self, tmp_path: Path) -> None:
        """pytest.ini present -> framework='pytest'."""
        (tmp_path / "pytest.ini").write_text("[pytest]\n")

        result = detect_testing(tmp_path)

        assert result.framework == "pytest"

    def test_python_setup_cfg_pytest(self, tmp_path: Path) -> None:
        """setup.cfg with [tool:pytest] -> framework='pytest'."""
        (tmp_path / "setup.cfg").write_text("[tool:pytest]\ntestpaths = tests\n")

        result = detect_testing(tmp_path)

        assert result.framework == "pytest"

    def test_python_unittest(self, tmp_path: Path) -> None:
        """Test files that import unittest -> framework='unittest'."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("import unittest\n\nclass TestFoo(unittest.TestCase): pass\n")

        result = detect_testing(tmp_path)

        assert result.framework == "unittest"

    def test_go_testing(self, tmp_path: Path) -> None:
        """*_test.go files present -> framework='go test'."""
        (tmp_path / "main.go").write_text("package main\n")
        (tmp_path / "main_test.go").write_text("package main\n")

        result = detect_testing(tmp_path)

        assert result.framework == "go test"

    def test_js_jest(self, tmp_path: Path) -> None:
        """package.json with jest in test script -> framework='jest'."""
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest --coverage"}}))

        result = detect_testing(tmp_path)

        assert result.framework == "jest"

    def test_js_vitest(self, tmp_path: Path) -> None:
        """package.json with vitest in test script -> framework='vitest'."""
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))

        result = detect_testing(tmp_path)

        assert result.framework == "vitest"

    def test_js_mocha(self, tmp_path: Path) -> None:
        """package.json with mocha in test script -> framework='mocha'."""
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "mocha"}}))

        result = detect_testing(tmp_path)

        assert result.framework == "mocha"

    def test_rust_cargo(self, tmp_path: Path) -> None:
        """Cargo.toml + #[test] in source -> framework='cargo test'."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "foo"\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "lib.rs").write_text("#[cfg(test)]\nmod tests {\n    #[test]\n    fn it_works() {}\n}\n")

        result = detect_testing(tmp_path)

        assert result.framework == "cargo test"

    def test_no_tests_found(self, tmp_path: Path) -> None:
        """Empty dir -> all None."""
        result = detect_testing(tmp_path)

        assert result.framework is None
        assert result.test_dir is None
        assert result.ci_config is None
        assert result.run_command is None


class TestTestDirDetection:
    def test_test_dir_detected(self, tmp_path: Path) -> None:
        """tests/ dir exists -> test_dir='tests/'."""
        (tmp_path / "tests").mkdir()

        result = detect_testing(tmp_path)

        assert result.test_dir == "tests/"

    def test_test_singular_dir(self, tmp_path: Path) -> None:
        """test/ dir exists -> test_dir='test/'."""
        (tmp_path / "test").mkdir()

        result = detect_testing(tmp_path)

        assert result.test_dir == "test/"

    def test_spec_dir(self, tmp_path: Path) -> None:
        """spec/ dir exists -> test_dir='spec/'."""
        (tmp_path / "spec").mkdir()

        result = detect_testing(tmp_path)

        assert result.test_dir == "spec/"

    def test_src_tests_dir(self, tmp_path: Path) -> None:
        """src/tests/ dir exists -> test_dir='src/tests/'."""
        (tmp_path / "src" / "tests").mkdir(parents=True)

        result = detect_testing(tmp_path)

        assert result.test_dir == "src/tests/"


class TestCiDetection:
    def test_github_actions_ci(self, tmp_path: Path) -> None:
        """.github/workflows/ dir exists -> ci_config='GitHub Actions'."""
        (tmp_path / ".github" / "workflows").mkdir(parents=True)

        result = detect_testing(tmp_path)

        assert result.ci_config == "GitHub Actions"

    def test_travis_ci(self, tmp_path: Path) -> None:
        """.travis.yml exists -> ci_config='Travis CI'."""
        (tmp_path / ".travis.yml").write_text("language: python\n")

        result = detect_testing(tmp_path)

        assert result.ci_config == "Travis CI"

    def test_circleci(self, tmp_path: Path) -> None:
        """.circleci/ dir exists -> ci_config='CircleCI'."""
        (tmp_path / ".circleci").mkdir()

        result = detect_testing(tmp_path)

        assert result.ci_config == "CircleCI"

    def test_jenkins(self, tmp_path: Path) -> None:
        """Jenkinsfile exists -> ci_config='Jenkins'."""
        (tmp_path / "Jenkinsfile").write_text("pipeline {}\n")

        result = detect_testing(tmp_path)

        assert result.ci_config == "Jenkins"

    def test_azure_pipelines(self, tmp_path: Path) -> None:
        """azure-pipelines.yml exists -> ci_config='Azure Pipelines'."""
        (tmp_path / "azure-pipelines.yml").write_text("trigger:\n  - main\n")

        result = detect_testing(tmp_path)

        assert result.ci_config == "Azure Pipelines"


class TestRunCommand:
    def test_makefile_test_target(self, tmp_path: Path) -> None:
        """Makefile with test: target -> run_command='make test'."""
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")

        result = detect_testing(tmp_path)

        assert result.run_command == "make test"

    def test_makefile_phony_test(self, tmp_path: Path) -> None:
        """Makefile with .PHONY: test -> run_command='make test'."""
        (tmp_path / "Makefile").write_text(".PHONY: clean test\n\ntest:\n\tpytest\n")
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")

        result = detect_testing(tmp_path)

        assert result.run_command == "make test"

    def test_pytest_run_command(self, tmp_path: Path) -> None:
        """pytest framework without Makefile -> run_command='pytest'."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")

        result = detect_testing(tmp_path)

        assert result.run_command == "pytest"

    def test_go_run_command(self, tmp_path: Path) -> None:
        """go test framework -> run_command='go test ./...'."""
        (tmp_path / "main_test.go").write_text("package main\n")

        result = detect_testing(tmp_path)

        assert result.run_command == "go test ./..."

    def test_jest_run_command(self, tmp_path: Path) -> None:
        """jest framework -> run_command='npm test'."""
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))

        result = detect_testing(tmp_path)

        assert result.run_command == "npm test"

    def test_cargo_run_command(self, tmp_path: Path) -> None:
        """cargo test framework -> run_command='cargo test'."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "foo"\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "lib.rs").write_text("#[test]\nfn it_works() {}\n")

        result = detect_testing(tmp_path)

        assert result.run_command == "cargo test"
