"""Tests for deps/parser.py manifest parsing."""

from pathlib import Path

from give_back.deps.parser import (
    parse_cargo_toml,
    parse_gemfile,
    parse_gomod,
    parse_package_json,
    parse_pyproject,
    parse_requirements_txt,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "manifests"


class TestGoMod:
    def test_parse_fixture(self):
        content = (FIXTURES / "go.mod").read_text()
        modules = parse_gomod(content)
        assert "github.com/gorilla/mux" in modules
        assert "github.com/sirupsen/logrus" in modules
        assert "golang.org/x/net" in modules
        assert "github.com/stretchr/testify" in modules  # indirect still included
        assert "github.com/spf13/cobra" in modules  # single-line require

    def test_skips_local_replaces(self):
        content = (FIXTURES / "go.mod").read_text()
        modules = parse_gomod(content)
        assert "github.com/example/localmod" not in modules
        assert "github.com/example/othermod" not in modules

    def test_empty(self):
        assert parse_gomod("") == []

    def test_no_require_block(self):
        assert parse_gomod("module github.com/foo/bar\n\ngo 1.21\n") == []

    def test_multiline_require(self):
        content = """
require (
    github.com/foo/bar v1.0.0
    github.com/baz/qux v2.0.0
)
"""
        modules = parse_gomod(content)
        assert modules == ["github.com/foo/bar", "github.com/baz/qux"]

    def test_comments_in_require(self):
        content = """
require (
    // This is a comment
    github.com/foo/bar v1.0.0
)
"""
        modules = parse_gomod(content)
        assert modules == ["github.com/foo/bar"]


class TestPyproject:
    def test_pep621_fixture(self):
        content = (FIXTURES / "pyproject_pep621.toml").read_text()
        packages = parse_pyproject(content)
        assert "click" in packages
        assert "httpx" in packages
        assert "rich" in packages
        assert "some-package" in packages

    def test_poetry_fixture(self):
        content = (FIXTURES / "pyproject_poetry.toml").read_text()
        packages = parse_pyproject(content)
        assert "click" in packages
        assert "httpx" in packages
        assert "rich" in packages
        assert "python" not in packages  # filtered out

    def test_pep621_strips_extras(self):
        content = (FIXTURES / "pyproject_pep621.toml").read_text()
        packages = parse_pyproject(content)
        # "rich[jupyter]>=13.0" should become "rich"
        assert "rich" in packages
        assert not any("[" in p for p in packages)

    def test_empty(self):
        assert parse_pyproject("") == []

    def test_invalid_toml(self):
        assert parse_pyproject("not valid toml {{}}") == []

    def test_no_dependencies_key(self):
        content = '[project]\nname = "foo"\n'
        assert parse_pyproject(content) == []

    def test_pep621_preferred_over_poetry(self):
        """If both PEP 621 and Poetry deps exist, PEP 621 wins."""
        content = """
[project]
dependencies = ["click>=8.1"]

[tool.poetry.dependencies]
httpx = ">=0.27"
"""
        packages = parse_pyproject(content)
        assert packages == ["click"]


class TestRequirementsTxt:
    def test_basic(self):
        content = "click>=8.1\nhttpx>=0.27\nrich\n"
        packages = parse_requirements_txt(content)
        assert packages == ["click", "httpx", "rich"]

    def test_skips_comments(self):
        content = "# comment\nclick\n"
        assert parse_requirements_txt(content) == ["click"]

    def test_skips_blank_lines(self):
        content = "click\n\nhttpx\n"
        assert parse_requirements_txt(content) == ["click", "httpx"]

    def test_skips_options(self):
        content = "-r other.txt\n-e .\n--index-url https://...\nclick\n"
        assert parse_requirements_txt(content) == ["click"]

    def test_skips_urls(self):
        content = "https://example.com/package.tar.gz\ngit+https://github.com/foo/bar.git\nclick\n"
        assert parse_requirements_txt(content) == ["click"]

    def test_empty(self):
        assert parse_requirements_txt("") == []

    def test_version_constraints(self):
        content = "click>=8.1\nhttpx==0.27.0\nrich~=13.0\n"
        packages = parse_requirements_txt(content)
        assert packages == ["click", "httpx", "rich"]


class TestCargoToml:
    def test_basic_dependencies(self):
        content = '[dependencies]\nserde = "1.0"\ntokio = { version = "1", features = ["full"] }\n'
        crates = parse_cargo_toml(content)
        assert "serde" in crates
        assert "tokio" in crates

    def test_dev_dependencies(self):
        content = '[dev-dependencies]\ncriterion = "0.5"\n'
        crates = parse_cargo_toml(content)
        assert "criterion" in crates

    def test_skips_path_only(self):
        content = '[dependencies]\nmy-local = { path = "../my-local" }\nremote = "1.0"\n'
        crates = parse_cargo_toml(content)
        assert "remote" in crates
        assert "my-local" not in crates

    def test_keeps_path_with_version(self):
        content = '[dependencies]\nmy-crate = { path = "../my-crate", version = "1.0" }\n'
        crates = parse_cargo_toml(content)
        assert "my-crate" in crates

    def test_empty(self):
        assert parse_cargo_toml("") == []

    def test_invalid_toml(self):
        assert parse_cargo_toml("not valid {{}}") == []


class TestPackageJson:
    def test_basic_dependencies(self):
        content = '{"dependencies": {"react": "^18.0", "lodash": "^4.17"}}'
        packages = parse_package_json(content)
        assert "react" in packages
        assert "lodash" in packages

    def test_dev_dependencies(self):
        content = '{"devDependencies": {"jest": "^29.0", "typescript": "^5.0"}}'
        packages = parse_package_json(content)
        assert "jest" in packages
        assert "typescript" in packages

    def test_both_dep_types(self):
        content = '{"dependencies": {"express": "^4.0"}, "devDependencies": {"mocha": "^10.0"}}'
        packages = parse_package_json(content)
        assert "express" in packages
        assert "mocha" in packages

    def test_scoped_packages(self):
        content = '{"dependencies": {"@types/node": "^20.0", "@babel/core": "^7.0"}}'
        packages = parse_package_json(content)
        assert "@types/node" in packages
        assert "@babel/core" in packages

    def test_skips_file_references(self):
        content = '{"dependencies": {"local-pkg": "file:../local", "remote": "^1.0"}}'
        packages = parse_package_json(content)
        assert "remote" in packages
        assert "local-pkg" not in packages

    def test_empty(self):
        assert parse_package_json("") == []

    def test_invalid_json(self):
        assert parse_package_json("not json {") == []

    def test_no_dependencies(self):
        assert parse_package_json('{"name": "foo"}') == []


class TestGemfile:
    def test_basic_gems(self):
        content = "gem 'rails', '~> 7.0'\ngem 'pg'\n"
        gems = parse_gemfile(content)
        assert "rails" in gems
        assert "pg" in gems

    def test_double_quotes(self):
        content = 'gem "sidekiq"\n'
        gems = parse_gemfile(content)
        assert "sidekiq" in gems

    def test_skips_comments(self):
        content = "# gem 'old'\ngem 'new'\n"
        gems = parse_gemfile(content)
        assert "new" in gems
        assert "old" not in gems

    def test_skips_path_gems(self):
        content = "gem 'local', path: '../local'\ngem 'remote'\n"
        gems = parse_gemfile(content)
        assert "remote" in gems
        assert "local" not in gems

    def test_skips_path_hashrocket(self):
        content = "gem 'local', :path => '../local'\ngem 'remote'\n"
        gems = parse_gemfile(content)
        assert "remote" in gems
        assert "local" not in gems

    def test_empty(self):
        assert parse_gemfile("") == []
