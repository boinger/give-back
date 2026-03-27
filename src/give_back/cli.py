"""CLI entry point for give-back."""

import click

from give_back import __version__


@click.group()
@click.version_option(version=__version__, prog_name="give-back")
def cli() -> None:
    """Evaluate whether an open-source project is viable for outside contributions."""


@cli.command()
@click.argument("repo")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--no-cache", is_flag=True, help="Skip cached results, force fresh API calls.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed signal data and API call info.")
def assess(repo: str, json_output: bool, no_cache: bool, verbose: bool) -> None:
    """Assess a GitHub repository's viability for outside contributions.

    REPO can be 'owner/repo' or a full GitHub URL.
    """
    # TODO: implement in Step 6
    click.echo(f"Assessing {repo}... (not yet implemented)")
