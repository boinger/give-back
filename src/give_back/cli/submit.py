"""CLI command: submit."""

from __future__ import annotations

import sys

import click

from give_back.console import stderr_console as _console


@click.command()
@click.option("--title", default=None, help="PR title (auto-generated from issue if omitted).")
@click.option("--draft", is_flag=True, help="Create as draft PR.")
@click.option("--edit", is_flag=True, help="Open editor for the PR body before submitting.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show submission details.")
def submit(title: str | None, draft: bool, edit: bool, json_output: bool, verbose: bool) -> None:
    """Create a pull request from the current workspace.

    Must be run from inside a give-back workspace (created by `prepare`).
    Reads the contribution brief to apply correct conventions: commit format,
    DCO sign-off, and PR template sections.

    Examples:

        cd ~/give-back-workspaces/pallets/flask
        give-back submit

        give-back submit --title "Fix type annotation in request handler" --draft
    """
    from pathlib import Path

    from give_back.output import print_submit_json, print_submit_success
    from give_back.submit import submit_pr

    cwd = Path.cwd()
    context_file = cwd / ".give-back" / "context.json"

    if not context_file.exists():
        _console.print(
            "[red]Error:[/red] Not in a give-back workspace. Run from a directory created by `give-back prepare`."
        )
        sys.exit(1)

    result = submit_pr(cwd, title=title, draft=draft, edit=edit)

    if json_output:
        print_submit_json(result)
    else:
        print_submit_success(result)

    if not result.success:
        sys.exit(1)
