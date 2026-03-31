"""CONTRIBUTING.md wizard: section selection → skeleton with TODO placeholders."""

from __future__ import annotations

import click

_SECTIONS = [
    (
        "Getting Started",
        """\
1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/REPO_NAME.git`
3. Install dependencies: *(describe how)*
4. Create a branch: `git checkout -b my-feature`""",
    ),
    (
        "Running Tests",
        """\
Run the test suite with:

```bash
# replace with your actual test command
make test
```""",
    ),
    (
        "Submitting Changes",
        """\
1. Push your branch to your fork
2. Open a pull request against `main`
3. Describe what your PR does and why
4. Reference any related issues""",
    ),
    (
        "Code Style",
        """\
This project uses *(describe linter/formatter)* for code formatting.
Run the formatter before submitting:

```bash
# replace with your actual format command
make lint
```""",
    ),
    (
        "Reporting Issues",
        """\
When reporting bugs, please include:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Version information""",
    ),
    (
        "Code of Conduct",
        """\
This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.""",
    ),
]


def _render_section(heading: str, body: str) -> str:
    return f"## {heading}\n\n{body}"


def run_wizard(has_coc: bool = True) -> str | None:
    """Interactive wizard that generates a CONTRIBUTING.md skeleton.

    *has_coc*: whether CODE_OF_CONDUCT.md exists (or was just created).
    If False, the "Code of Conduct" section is excluded.

    Returns the markdown content, or None if the user declines.
    """
    sections = [s for s in _SECTIONS if has_coc or s[0] != "Code of Conduct"]

    click.echo()
    click.echo("  CONTRIBUTING.md helps contributors understand your process.")
    click.echo("  Not required — lacking one doesn't mean you don't want contributors,")
    click.echo("  only that you don't feel the need for formal rules.")
    click.echo()
    click.echo("  Available sections:")
    for i, (heading, _body) in enumerate(sections, 1):
        click.echo(f"    {i}) {heading}")
    click.echo()

    choice = click.prompt(
        "  Include sections? [a]ll / [s]ome / [p]review / [n]one",
        type=click.Choice(["a", "s", "p", "n"], case_sensitive=False),
        default="a",
        show_choices=False,
    )

    if choice == "n":
        return None

    if choice == "p":
        for heading, body in sections:
            click.echo(f"\n  ── {heading} ──")
            for line in _render_section(heading, body).splitlines():
                click.echo(f"  │ {line}")
        click.echo()
        choice = click.prompt(
            "  Include sections? [a]ll / [s]ome / [n]one",
            type=click.Choice(["a", "s", "n"], case_sensitive=False),
            default="a",
            show_choices=False,
        )

    if choice == "n":
        return None

    if choice == "s":
        selected: list[tuple[str, str]] = []
        for heading, body in sections:
            while True:
                per_section = click.prompt(
                    f"  '{heading}': [y]es / [n]o / [p]review",
                    type=click.Choice(["y", "n", "p"], case_sensitive=False),
                    default="y",
                    show_choices=False,
                )
                if per_section == "p":
                    click.echo(f"\n  ── {heading} ──")
                    for line in _render_section(heading, body).splitlines():
                        click.echo(f"  │ {line}")
                    click.echo()
                    continue
                if per_section == "y":
                    selected.append((heading, body))
                break
    else:
        # choice == "a"
        selected = list(sections)

    if not selected:
        click.echo("  No sections selected. Skipping.")
        return None

    parts = ["# Contributing\n"]
    for heading, body in selected:
        parts.append(_render_section(heading, body))

    return "\n\n".join(parts) + "\n"
