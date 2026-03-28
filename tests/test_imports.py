"""Smoke tests for import resolution — no circular imports."""


def test_assess_imports_cleanly():
    from give_back.assess import run_assessment

    assert callable(run_assessment)


def test_cli_imports_cleanly():
    from give_back.cli import cli

    assert callable(cli)


def test_both_import_without_circular_dependency():
    """Importing assess then cli (or vice versa) must not cause ImportError."""
    from give_back.assess import run_assessment
    from give_back.cli import cli

    assert callable(run_assessment)
    assert callable(cli)
