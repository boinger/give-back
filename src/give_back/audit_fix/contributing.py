"""CONTRIBUTING.md wizard: section checklist → skeleton with TODO placeholders."""

from __future__ import annotations

import click

_SECTIONS = [
    (
        "1",
        "Getting started",
        "Getting Started",
        "Describe dev environment setup, prerequisites, and how to clone/install.",
    ),
    ("2", "Running tests", "Running Tests", "Which command runs the test suite? Any setup needed first?"),
    (
        "3",
        "Submitting changes",
        "Submitting Changes",
        "Describe the PR process: branch naming, commit style, review expectations.",
    ),
    ("4", "Code style", "Code Style", "Which linter/formatter? Any style rules beyond what the tooling enforces?"),
    (
        "5",
        "Issue reporting",
        "Reporting Issues",
        "What makes a good bug report? What information should reporters include?",
    ),
    ("6", "Code of conduct", "Code of Conduct", "Reference your CODE_OF_CONDUCT.md or describe expected behavior."),
]

_DEFAULT_SECTIONS = "1,2,3"


def run_wizard() -> str | None:
    """Interactive wizard that generates a CONTRIBUTING.md skeleton.

    Returns the markdown content, or None if the user declines.
    """
    click.echo()
    click.echo("  CONTRIBUTING.md helps contributors understand your process.")
    click.echo("  Not required — lacking one doesn't mean you don't want contributors,")
    click.echo("  only that you don't feel the need for formal rules.")
    click.echo()

    if not click.confirm("  Create CONTRIBUTING.md?", default=True):
        return None

    click.echo()
    click.echo("  Which sections to include?")
    for num, label, _heading, _desc in _SECTIONS:
        click.echo(f"    {num}) {label}")
    click.echo()

    raw = click.prompt("  Include sections (comma-separated)", default=_DEFAULT_SECTIONS).strip()

    chosen_nums = {s.strip() for s in raw.split(",")}
    selected = [(heading, desc) for num, _label, heading, desc in _SECTIONS if num in chosen_nums]

    if not selected:
        click.echo("  No sections selected. Skipping.")
        return None

    lines = ["# Contributing\n"]
    for heading, desc in selected:
        lines.append(f"\n## {heading}\n")
        lines.append(f"\n<!-- TODO: {desc} -->\n")

    return "\n".join(lines) + "\n"
