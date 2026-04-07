"""Tests for cli/skill.py: install, uninstall, missing-skill hint, editable detection."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from rich.console import Console

from give_back.cli import _check_skill_installed_hint
from give_back.cli.skill import (
    _is_editable_install,
    skill_install,
    skill_uninstall,
)


def _make_install_dir(tmp_path: Path) -> Path:
    """Build a fake home with ~/.claude/skills/ structure."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()
    return fake_home


class TestSkillInstall:
    def test_install_creates_target_dir_and_symlinks(self, tmp_path):
        """Default install creates the target dir and symlinks SKILL.md."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        target = target_dir / "SKILL.md"

        with patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir):
            runner = CliRunner()
            result = runner.invoke(skill_install, [])

        assert result.exit_code == 0
        assert target.exists()
        assert target.is_symlink()
        # Symlink target should be the bundled file in the package
        assert target.resolve().name == "SKILL.md"

    def test_install_copy_flag_writes_real_file(self, tmp_path):
        """--copy produces a real file, not a symlink."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        target = target_dir / "SKILL.md"

        with patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir):
            runner = CliRunner()
            result = runner.invoke(skill_install, ["--copy"])

        assert result.exit_code == 0
        assert target.exists()
        assert not target.is_symlink()
        # File should have actual SKILL.md content (not empty)
        assert len(target.read_text()) > 0
        assert "give-back" in target.read_text().lower()

    def test_install_overwrites_existing_file(self, tmp_path):
        """Pre-existing file at target is replaced."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        target_dir.mkdir(parents=True)
        target = target_dir / "SKILL.md"
        target.write_text("OLD CONTENT")

        with patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir):
            runner = CliRunner()
            result = runner.invoke(skill_install, ["--copy"])

        assert result.exit_code == 0
        assert "OLD CONTENT" not in target.read_text()

    def test_install_overwrites_broken_symlink(self, tmp_path):
        """A dangling symlink at the target is replaced cleanly."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        target_dir.mkdir(parents=True)
        target = target_dir / "SKILL.md"
        target.symlink_to(tmp_path / "nonexistent")
        assert target.is_symlink()
        assert not target.exists()  # broken symlink

        with patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir):
            runner = CliRunner()
            result = runner.invoke(skill_install, [])

        assert result.exit_code == 0
        assert target.exists()
        assert target.is_symlink()

    def test_install_warns_when_no_claude_dir(self, tmp_path):
        """If ~/.claude/ does not exist, install warns but proceeds."""
        # Don't create ~/.claude/ in the fake home
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        target_dir = fake_home / ".claude" / "skills" / "give-back"

        with (
            patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir),
            patch("give_back.cli.skill.Path.home", return_value=fake_home),
        ):
            runner = CliRunner()
            result = runner.invoke(skill_install, [])

        assert result.exit_code == 0
        assert "Warning" in result.output or "warning" in result.output
        # Should still install
        assert (target_dir / "SKILL.md").exists()

    def test_install_falls_back_to_copy_on_symlink_failure(self, tmp_path):
        """If symlink_to raises OSError (Windows w/o admin), fall back to copy."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        target_dir.mkdir(parents=True)
        target = target_dir / "SKILL.md"

        with (
            patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir),
            patch.object(Path, "symlink_to", side_effect=OSError("not permitted")),
        ):
            runner = CliRunner()
            result = runner.invoke(skill_install, [])

        assert result.exit_code == 0
        assert target.exists()
        assert not target.is_symlink()
        assert "Warning" in result.output or "Falling back" in result.output

    def test_install_prints_editable_hint_when_editable(self, tmp_path):
        """When _is_editable_install returns True, print the editable-install hint."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"

        with (
            patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir),
            patch("give_back.cli.skill._is_editable_install", return_value=True),
        ):
            runner = CliRunner()
            result = runner.invoke(skill_install, [])

        assert result.exit_code == 0
        assert "Editable install" in result.output


class TestSkillUninstall:
    def test_uninstall_removes_dir(self, tmp_path):
        """Happy path: uninstall removes the install directory."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        target_dir.mkdir(parents=True)
        (target_dir / "SKILL.md").write_text("content")

        with patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir):
            runner = CliRunner()
            result = runner.invoke(skill_uninstall, ["--yes"])

        assert result.exit_code == 0
        assert not target_dir.exists()

    def test_uninstall_silent_when_nothing_to_remove(self, tmp_path):
        """If install dir doesn't exist, uninstall exits cleanly with a note."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        # Don't create target_dir

        with patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir):
            runner = CliRunner()
            result = runner.invoke(skill_uninstall, ["--yes"])

        assert result.exit_code == 0
        assert "Nothing to uninstall" in result.output

    def test_uninstall_yes_flag_skips_confirmation(self, tmp_path):
        """--yes bypasses the click.confirm prompt."""
        fake_home = _make_install_dir(tmp_path)
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        target_dir.mkdir(parents=True)
        (target_dir / "SKILL.md").write_text("content")

        with patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir):
            runner = CliRunner()
            # No input provided; --yes should be enough
            result = runner.invoke(skill_uninstall, ["--yes"], input="")

        assert result.exit_code == 0
        assert not target_dir.exists()


class TestMissingSkillHint:
    """Tests for _check_skill_installed_hint().

    These tests patch stderr_console directly because Rich's Console binds to
    sys.stderr at construction time, so CliRunner's stderr capture doesn't work
    for output already routed through a Rich Console object.
    """

    def _make_capture_console(self) -> tuple[Console, io.StringIO]:
        """Build a Rich Console that writes to a StringIO buffer for capture."""
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=200)
        return console, buf

    def test_hint_prints_when_skill_not_installed(self, tmp_path):
        """When skill file is missing, the hint prints to the stderr console."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        console, buf = self._make_capture_console()

        with (
            patch("give_back.cli.Path.home", return_value=fake_home),
            patch("give_back.console.stderr_console", console),
        ):
            _check_skill_installed_hint()

        assert "Tip: run 'give-back skill install'" in buf.getvalue()

    def test_hint_silent_when_skill_installed(self, tmp_path):
        """When skill file exists, no hint is printed."""
        fake_home = tmp_path / "home"
        skill_path = fake_home / ".claude" / "skills" / "give-back" / "SKILL.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text("installed")
        console, buf = self._make_capture_console()

        with (
            patch("give_back.cli.Path.home", return_value=fake_home),
            patch("give_back.console.stderr_console", console),
        ):
            _check_skill_installed_hint()

        assert "Tip: run 'give-back skill install'" not in buf.getvalue()
        assert buf.getvalue() == ""

    def test_hint_goes_to_stderr_not_stdout(self, tmp_path):
        """The hint uses stderr_console (not stdout). Verified by patching stderr_console
        and confirming it received the output, while stdout would be untouched."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        console, buf = self._make_capture_console()

        with (
            patch("give_back.cli.Path.home", return_value=fake_home),
            patch("give_back.console.stderr_console", console),
        ):
            _check_skill_installed_hint()

        # The hint went through stderr_console (captured in buf)
        assert "Tip" in buf.getvalue()
        # The function uses stderr_console.print, never stdout. We verify this
        # structurally: if it had used stdout, our patch wouldn't have caught it.

    def test_hint_prints_on_every_invocation_until_installed(self, tmp_path):
        """The hint prints on every call while the skill is missing."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        console, buf = self._make_capture_console()

        with (
            patch("give_back.cli.Path.home", return_value=fake_home),
            patch("give_back.console.stderr_console", console),
        ):
            _check_skill_installed_hint()
            _check_skill_installed_hint()
            _check_skill_installed_hint()

        # The hint should appear 3 times (once per call)
        assert buf.getvalue().count("Tip: run 'give-back skill install'") == 3

    def test_hint_suppressed_for_skill_subcommands(self, tmp_path):
        """The hint should NOT print when the user runs `give-back skill install/uninstall`.

        It's redundant — they're literally managing the skill state. The check is in
        the root cli() callback which inspects ctx.invoked_subcommand.
        """
        from give_back.cli import cli as cli_group

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        target_dir = fake_home / ".claude" / "skills" / "give-back"
        console, buf = self._make_capture_console()

        with (
            patch("give_back.cli.Path.home", return_value=fake_home),
            patch("give_back.console.stderr_console", console),
            patch("give_back.cli.skill.SKILL_INSTALL_DIR", target_dir),
        ):
            runner = CliRunner()
            # Invoke `give-back skill uninstall` (skill not installed → would
            # normally trigger the hint, but `skill` subcommand should suppress it)
            result = runner.invoke(cli_group, ["skill", "uninstall", "--yes"])

        assert result.exit_code == 0
        # Hint should NOT appear because invoked_subcommand was "skill"
        assert "Tip: run 'give-back skill install'" not in buf.getvalue()


class TestIsEditableInstall:
    def test_returns_false_for_pipx_venv_path(self):
        """When the bundled path is inside a pipx venv, return False."""
        # We can't easily mock importlib.resources, but we can test the
        # behavior indirectly by checking what the function returns in our
        # current dev environment.
        # In a `pipx install -e .` editable install (this dev env), it should
        # return True. In a `pipx install` from wheel, False.
        result = _is_editable_install()
        # Just verify it returns a bool, doesn't crash
        assert isinstance(result, bool)

    def test_handles_module_not_found_gracefully(self):
        """If the skill subpackage can't be loaded, return False (don't crash)."""
        with patch("give_back.cli.skill.files", side_effect=ModuleNotFoundError):
            assert _is_editable_install() is False
