"""CLI command: prepare."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.cli._shared import _parse_repo
from give_back.console import stderr_console as _console
from give_back.exceptions import (
    AuthenticationError,
    ForkError,
    GiveBackError,
    RateLimitError,
    RepoNotFoundError,
    WorkspaceError,
)
from give_back.github_client import GitHubClient
from give_back.output import print_prepare_json
from give_back.state import load_config


@click.command()
@click.argument("repo")
@click.option("--issue", type=int, default=None, help="Issue number to prepare a workspace for.")
@click.option("--dir", "workspace_dir", default=None, help="Custom workspace directory.")
@click.option("--skip-conventions", is_flag=True, help="Skip convention scan (faster, uses defaults).")
@click.option("--json", "json_output", is_flag=True, help="Output JSON instead of formatted text.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress.")
def prepare(
    repo: str, issue: int | None, workspace_dir: str | None, skip_conventions: bool, json_output: bool, verbose: bool
) -> None:
    """Prepare a contribution workspace: fork, clone, branch, and write brief.

    REPO can be 'owner/repo' or a full GitHub URL.
    Forks the repo (if needed), clones your fork, creates a branch from the
    upstream default branch, writes a contribution brief, and optionally hands
    off to your editor.
    """
    import subprocess
    from pathlib import Path

    from give_back.conventions.brief import scan_conventions
    from give_back.conventions.models import ContributionBrief
    from give_back.prepare.action_plan import generate_action_plan
    from give_back.prepare.brief_writer import write_brief
    from give_back.prepare.fork import ensure_fork
    from give_back.prepare.lifecycle import ResolveAction, read_workspace_context, resolve_old_workspace
    from give_back.prepare.workspace import generate_branch_name, setup_workspace

    # 1. Parse repo argument
    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    # 2. Resolve auth token — require authentication for fork/clone
    token = resolve_token()
    if token is None:
        _console.print("[red]Error:[/red] `prepare` requires authentication. Set GITHUB_TOKEN or run `gh auth login`.")
        sys.exit(1)

    # 3. Load config for workspace_dir default
    config = load_config()
    effective_workspace_dir = workspace_dir or config.workspace_dir

    # 4. Ensure fork exists (moved earlier — needed for lifecycle PR search)
    try:
        fork_owner, fork_repo = ensure_fork(owner, repo_name)
    except ForkError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # 5. Check for existing workspace and handle lifecycle
    clone_dir = Path(effective_workspace_dir).expanduser() / owner / repo_name
    old_context = read_workspace_context(clone_dir)
    previous_issues: list[dict] = []

    if old_context is not None:
        old_issue = old_context.get("issue_number")
        if old_issue is not None and old_issue != issue:
            # Different issue — resolve old workspace
            try:
                with GitHubClient(token=token) as client:
                    result = resolve_old_workspace(clone_dir, old_context, client, fork_owner)
            except GiveBackError:
                # API failure — try without PR detection
                result = resolve_old_workspace(clone_dir, old_context)

            if result.action == ResolveAction.BLOCK_UNPUSHED:
                _console.print(f"[red]Error:[/red] {result.message}")
                sys.exit(1)

            _console.print(f"  [dim]{result.message}[/dim]")
            previous_issues = old_context.get("previous_issues", [])
            if result.archived_entry:
                previous_issues.append(result.archived_entry)
        elif old_issue == issue:
            # Same issue — idempotent re-prepare, preserve history
            previous_issues = old_context.get("previous_issues", [])

    # 6. Convention scan (unless --skip-conventions)
    brief: ContributionBrief
    if skip_conventions:
        if verbose:
            _console.print("  [dim]Skipping convention scan (using defaults).[/dim]")
        brief = ContributionBrief(owner=owner, repo=repo_name, issue_number=issue)
        # Fetch default branch even when skipping conventions
        try:
            with GitHubClient(token=token) as client:
                repo_data = client.rest_get(f"/repos/{owner}/{repo_name}")
                brief.default_branch = repo_data.get("default_branch", "main")
                if issue is not None:
                    issue_data = client.rest_get(f"/repos/{owner}/{repo_name}/issues/{issue}")
                    brief.issue_title = issue_data.get("title")
        except (AuthenticationError, RepoNotFoundError, RateLimitError, GiveBackError) as exc:
            _console.print(f"[yellow]Warning:[/yellow] Could not fetch repo metadata: {exc}")
    else:
        if verbose:
            _console.print(f"  [dim]Scanning conventions for {owner}/{repo_name}...[/dim]")
        try:
            with GitHubClient(token=token) as client:
                brief = scan_conventions(
                    client,
                    owner,
                    repo_name,
                    issue_number=issue,
                    verbose=verbose,
                )
        except AuthenticationError as exc:
            _console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)
        except RepoNotFoundError:
            _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
            sys.exit(1)
        except RateLimitError as exc:
            _console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)

    # 7. Generate branch name
    branch_name = generate_branch_name(
        brief.branch_convention,
        issue or 0,
        brief.issue_title or "contribution",
    )

    # 8. Set up workspace (clone, remotes, branch)
    try:
        workspace_path = setup_workspace(
            fork_owner=fork_owner,
            fork_repo=fork_repo,
            repo=repo_name,
            upstream_owner=owner,
            branch_name=branch_name,
            default_branch=brief.default_branch,
            workspace_dir=effective_workspace_dir,
        )
    except WorkspaceError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # 9. Write brief (with lifecycle context)
    try:
        write_brief(
            workspace_path,
            brief,
            issue,
            branch_name,
            owner,
            fork_owner=fork_owner,
            previous_issues=previous_issues,
        )
    except OSError as exc:
        _console.print(f"[red]Error:[/red] Cannot write brief: {exc}")
        sys.exit(1)

    # 10. Generate and print action plan (or JSON output)
    action_plan_text = generate_action_plan(brief, workspace_path, branch_name, owner)

    if json_output:
        print_prepare_json(workspace_path, branch_name, brief, action_plan_text)
    else:
        _console.print()
        _console.print(action_plan_text)
        _console.print()

    # 10. Run handoff command if configured
    if config.handoff_command:
        if verbose:
            _console.print(f"  [dim]Running handoff: {config.handoff_command}[/dim]")
        try:
            subprocess.run(["sh", "-c", config.handoff_command], cwd=workspace_path)
        except OSError as exc:
            _console.print(
                f"[yellow]Warning:[/yellow] Handoff command failed: {exc}. Workspace ready at {workspace_path}."
            )
