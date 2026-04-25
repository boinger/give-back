"""CLI command: check."""

from __future__ import annotations

import sys

import click

from give_back.auth import resolve_token
from give_back.console import stderr_console as _console
from give_back.conventions.models import CLAInfo
from give_back.exceptions import (
    AuthenticationError,
    GiveBackError,
    RateLimitError,
)
from give_back.github_client import GitHubClient
from give_back.output import print_check_results
from give_back.state import atomic_write_text


@click.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed check results.")
@click.option("--ack", "acknowledge", default=None, help="Acknowledge a guardrail (e.g., 'cla').")
def check(verbose: bool, acknowledge: str | None) -> None:
    """Run pre-flight guardrail checks in a give-back workspace.

    Must be run from a directory prepared with `give-back prepare`.
    Reads .give-back/context.json to determine which checks apply.

    Use --ack cla to acknowledge that you've signed the project's CLA.
    """
    import json
    import subprocess
    from pathlib import Path

    from give_back.guardrails import (
        check_base_branch_freshness,
        check_cla_signed,
        check_dco_signoff,
        check_duplicate_pr,
        check_local_ci,
        check_staged_files_clean,
        check_unrelated_changes,
    )

    cwd = Path.cwd()
    context_file = cwd / ".give-back" / "context.json"

    # 1. Check we're in a workspace
    if not context_file.exists():
        _console.print("[red]Error:[/red] Not in a give-back workspace. Run `give-back prepare` first.")
        sys.exit(1)

    # 2. Parse context.json
    try:
        context = json.loads(context_file.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        _console.print(f"[red]Error:[/red] Cannot read brief — re-run `give-back prepare`. ({exc})")
        sys.exit(1)

    upstream_owner = context.get("upstream_owner", "")
    repo_name = context.get("repo", "")
    issue_number = context.get("issue_number")
    branch_name = context.get("branch_name", "")
    default_branch = context.get("default_branch", "main")
    dco_required = context.get("dco_required", False)
    ci_commands = context.get("ci_commands", [])

    # Reconstruct CLAInfo from context.json fields
    cla_info = CLAInfo(
        required=context.get("cla_required", False),
        system=context.get("cla_system") or "unknown",
        signing_url=context.get("cla_signing_url"),
    )
    cla_acknowledged = context.get("cla_acknowledged", False)

    # Handle --ack cla
    if acknowledge == "cla":
        if not cla_info.required:
            _console.print("  No CLA required in this workspace — nothing to acknowledge.")
            sys.exit(0)
        context["cla_acknowledged"] = True
        atomic_write_text(context_file, json.dumps(context, indent=2))
        cla_acknowledged = True
        _console.print("  [green]CLA acknowledged.[/green] Running checks...")
        _console.print()
    elif acknowledge is not None:
        _console.print(f"[red]Error:[/red] Unknown guardrail to acknowledge: {acknowledge!r}")
        _console.print("  Supported: 'cla'")
        sys.exit(1)

    # 3. Gather current git state
    # Staged files
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )
    staged_files = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            # Staged files have a non-space first character
            if line and line[0] not in (" ", "?"):
                staged_files.append(line[3:])

    # Last commit message
    result = subprocess.run(
        ["git", "log", "--format=%B", "-1"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )
    commit_msg = result.stdout.strip() if result.returncode == 0 else ""

    # Commits behind upstream
    commits_behind = 0
    result = subprocess.run(
        ["git", "rev-list", "--count", f"HEAD..upstream/{default_branch}"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
    )
    if result.returncode == 0:
        try:
            commits_behind = int(result.stdout.strip())
        except ValueError:
            pass

    # 4. Run guardrails
    results: list = []

    results.append(check_staged_files_clean(staged_files))
    results.append(check_cla_signed(cla_info, acknowledged=cla_acknowledged))

    if staged_files or commit_msg:
        results.append(check_dco_signoff(commit_msg, dco_required))

    results.append(check_unrelated_changes(staged_files))

    results.append(check_base_branch_freshness(branch_name, f"upstream/{default_branch}", commits_behind))

    results.append(check_local_ci(ci_commands if ci_commands else None, ci_results=None))

    # 5. If auth is available, check for duplicate PRs and detect PR status
    token = resolve_token()
    if token is not None:
        try:
            with GitHubClient(token=token) as client:
                results.append(check_duplicate_pr(client, upstream_owner, repo_name, issue_number))

                # 5.5 PR detection — check if a PR exists for this branch
                if branch_name:
                    from give_back.guardrails import Severity
                    from give_back.prepare.lifecycle import (
                        find_pr_for_branch,
                        parse_fork_owner_from_remote,
                        update_context_status,
                    )

                    fork_owner = context.get("fork_owner")
                    if not fork_owner:
                        fork_owner = parse_fork_owner_from_remote(cwd)

                    if fork_owner:
                        pr_info = find_pr_for_branch(client, upstream_owner, repo_name, fork_owner, branch_name)
                        if pr_info:
                            status = "merged" if pr_info.state == "merged" else "pr_open"
                            update_context_status(cwd, status, pr_info.pr_url, pr_info.pr_number)
                            from give_back.guardrails import GuardrailResult

                            results.append(
                                GuardrailResult(
                                    name="pr_status",
                                    severity=Severity.INFO,
                                    passed=True,
                                    message=f"PR #{pr_info.pr_number} ({pr_info.state}): {pr_info.pr_url}",
                                )
                            )
        except (AuthenticationError, RateLimitError, GiveBackError):
            pass  # Skip API checks if they fail

    # 6. Print results
    print_check_results(results, upstream_owner, repo_name, issue_number, verbose=verbose)
