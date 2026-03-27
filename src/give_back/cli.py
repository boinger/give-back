"""CLI entry point for give-back."""

from __future__ import annotations

import base64
import re
import sys

import click
from rich.console import Console

from give_back import __version__
from give_back.auth import resolve_token
from give_back.exceptions import (
    AuthenticationError,
    ForkError,
    GiveBackError,
    GraphQLError,
    RateLimitError,
    RepoNotFoundError,
    StateCorruptError,
    WorkspaceError,
)
from give_back.github_client import GitHubClient
from give_back.graphql.queries import VIABILITY_QUERY
from give_back.models import RepoData
from give_back.output import (
    print_assessment,
    print_assessment_json,
    print_cached_notice,
    print_check_results,
    print_conventions,
    print_conventions_json,
    print_prepare_json,
    print_sniff,
    print_sniff_json,
)
from give_back.signals import ALL_SIGNALS
from give_back.state import add_to_skip_list, get_cached_assessment, load_config, remove_from_skip_list, save_assessment

_console = Console(stderr=True)

# Matches owner/repo or https://github.com/owner/repo (with optional trailing slash/path)
_GITHUB_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$")
_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


def _parse_repo(repo: str) -> tuple[str, str]:
    """Parse a repo argument into (owner, repo) tuple.

    Accepts 'owner/repo' or 'https://github.com/owner/repo'.
    """
    # Try URL first
    m = _GITHUB_URL_RE.match(repo)
    if m:
        return m.group(1), m.group(2)

    # Try slug
    if _SLUG_RE.match(repo):
        owner, name = repo.split("/", 1)
        return owner, name

    raise click.BadParameter(
        f"Invalid repository: '{repo}'. Use 'owner/repo' or a GitHub URL.",
        param_hint="'REPO'",
    )


def _fetch_repo_data(client: GitHubClient, owner: str, repo: str, verbose: bool) -> RepoData:
    """Fetch all data needed for signal evaluation (4 API calls)."""
    if verbose:
        _console.print(f"  [dim]Fetching GraphQL data for {owner}/{repo}...[/dim]")

    # 1. GraphQL: repo metadata + PRs
    graphql_data = client.graphql(VIABILITY_QUERY, {"owner": owner, "repo": repo})

    if verbose:
        remaining = client._rate_remaining
        _console.print(f"  [dim]Rate limit remaining: {remaining}[/dim]")

    # 2. REST: community profile
    if verbose:
        _console.print("  [dim]Fetching community profile...[/dim]")

    try:
        community = client.rest_get(f"/repos/{owner}/{repo}/community/profile")
    except RepoNotFoundError:
        community = {}

    # 3. REST: CONTRIBUTING.md text (only if community profile found one)
    contributing_text = None
    contributing_info = community.get("files", {}).get("contributing") if community else None
    if contributing_info and contributing_info.get("url"):
        if verbose:
            _console.print("  [dim]Fetching CONTRIBUTING.md content...[/dim]")
        try:
            # The community profile gives us the HTML URL; we need the API URL.
            # Extract the path from html_url: https://github.com/owner/repo/blob/main/.github/CONTRIBUTING.md
            html_url = contributing_info.get("html_url", "")
            # Parse path after /blob/branch/
            path_match = re.search(r"/blob/[^/]+/(.+)$", html_url)
            if path_match:
                file_path = path_match.group(1)
                contents = client.rest_get(f"/repos/{owner}/{repo}/contents/{file_path}")
                if contents.get("encoding") == "base64" and contents.get("content"):
                    contributing_text = base64.b64decode(contents["content"]).decode("utf-8", errors="replace")
        except (RepoNotFoundError, GiveBackError, KeyError):
            pass  # Fall through with contributing_text = None

    # 4. REST: search for AI policy keywords (only if CONTRIBUTING.md doesn't have explicit policy)
    search = {}
    if _needs_ai_search(contributing_text):
        if verbose:
            _console.print("  [dim]Searching for AI policy discussions...[/dim]")
        try:
            search = client.search(f'repo:{owner}/{repo} "AI" OR "LLM" OR "copilot" OR "ChatGPT" OR "generated code"')
        except (RateLimitError, GiveBackError):
            search = {}

    return RepoData(
        owner=owner,
        repo=repo,
        graphql=graphql_data,
        community=community,
        contributing_text=contributing_text,
        search=search,
    )


def _needs_ai_search(contributing_text: str | None) -> bool:
    """Check if the AI policy signal needs the search API (CONTRIBUTING.md is silent on AI)."""
    if not contributing_text:
        return True

    text_lower = contributing_text.lower()
    # If CONTRIBUTING.md has explicit AI policy (ban, welcome, or disclosure), no search needed
    ban_keywords = [
        "no ai",
        "no llm",
        "no copilot",
        "no chatgpt",
        "ai-generated code is not accepted",
        "machine-generated",
    ]
    welcome_keywords = ["ai-assisted welcome", "copilot encouraged", "ai contributions accepted"]
    disclosure_keywords = ["disclose", "label ai", "ai-assisted must be noted"]

    for kw in ban_keywords + welcome_keywords + disclosure_keywords:
        if kw in text_lower:
            return False

    return True


@click.group()
@click.version_option(version=__version__, prog_name="give-back")
def cli() -> None:
    """Evaluate whether an open-source project is viable for outside contributions."""


@cli.command()
@click.argument("repo")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--no-cache", is_flag=True, help="Skip cached results, force fresh API calls.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed signal data and API call info.")
@click.option("--deps", is_flag=True, help="Also assess the project's dependencies for contribution opportunities.")
@click.option("--limit", default=20, help="Maximum number of dependencies to assess (with --deps).")
def assess(repo: str, json_output: bool, no_cache: bool, verbose: bool, deps: bool, limit: int) -> None:
    """Assess a GitHub repository's viability for outside contributions.

    REPO can be 'owner/repo' or a full GitHub URL.
    """
    from give_back.assess import run_assessment

    # Parse repo argument
    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    # Check cache (unless --no-cache)
    if not no_cache:
        cached = get_cached_assessment(owner, repo_name)
        if cached is not None:
            if verbose:
                print_cached_notice(owner, repo_name, cached.get("timestamp", "unknown"))
                _console.print("  [dim]Cache hit — use --no-cache to force fresh API calls[/dim]")
            # For now, just note the cache hit and proceed with fresh data
            # Full cache display would reconstruct the Assessment from cached data
            # TODO: reconstruct and display cached assessment without API calls

    # Resolve auth
    token = resolve_token()

    # Fetch data and run assessment
    try:
        with GitHubClient(token=token) as client:
            assessment = run_assessment(client, owner, repo_name, verbose)

            # Save to state
            try:
                save_assessment(assessment)
            except PermissionError:
                _console.print("[yellow]Warning:[/yellow] Cannot write state file. Continuing without cache.")
            except StateCorruptError:
                _console.print("[yellow]Warning:[/yellow] State file corrupted. Backed up and starting fresh.")
                from give_back.state import _empty_state, save_state

                try:
                    save_state(_empty_state())
                    save_assessment(assessment)
                except PermissionError:
                    pass

            # Output
            signal_names = [s.name for s in ALL_SIGNALS]
            signal_weights = [s.weight for s in ALL_SIGNALS]

            if json_output:
                print_assessment_json(assessment, signal_names)
            else:
                print_assessment(assessment, signal_names, signal_weights, verbose=verbose)

            # --deps: also walk dependencies
            if deps:
                if not client.authenticated:
                    _console.print(
                        "\n[red]Error:[/red] --deps requires authentication. Set GITHUB_TOKEN or run `gh auth login`."
                    )
                    sys.exit(1)

                from give_back.deps.walker import walk_deps
                from give_back.output import print_deps, print_deps_json

                try:
                    walk_result = walk_deps(client, owner, repo_name, limit=limit, verbose=verbose)
                    if json_output:
                        print_deps_json(walk_result)
                    else:
                        print_deps(walk_result, verbose=verbose)
                except GiveBackError as exc:
                    _console.print(f"\n[yellow]Warning:[/yellow] Dependency walking failed: {exc}")

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except GraphQLError as exc:
        _console.print(f"[red]Error:[/red] GitHub API error: {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # Exit codes: 0 = success, 1 = gate fail, 2 = incomplete (HIGH/GATE signal errored)
    if not assessment.gate_passed:
        sys.exit(1)
    if assessment.incomplete:
        sys.exit(2)


@cli.command()
@click.argument("repo")
@click.option("--label", default=None, help="Filter issues by label (e.g., 'good first issue').")
@click.option("--limit", default=20, help="Maximum number of candidates to show.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--verbose", "-v", is_flag=True, help="Show competition details and staleness info.")
def triage(repo: str, label: str | None, limit: int, json_output: bool, verbose: bool) -> None:
    """Find good starter issues for contribution.

    REPO can be 'owner/repo' or a full GitHub URL.
    Fetches open issues, checks for competing work, and ranks by contribution-friendliness.
    """
    from give_back.triage.compete import check_competition
    from give_back.triage.fetch import fetch_issues
    from give_back.triage.rank import rank_candidates

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            if verbose:
                _console.print(f"  [dim]Fetching open issues for {owner}/{repo_name}...[/dim]")

            candidates = fetch_issues(client, owner, repo_name, label_filter=label, limit=limit)

            if not candidates:
                _console.print(f"\n  No candidate issues found for {owner}/{repo_name}.")
                if label:
                    _console.print("  [dim]Try without --label, or use a different label.[/dim]")
                return

            if verbose:
                _console.print(f"  [dim]Checking for competing work on {len(candidates)} candidates...[/dim]")

            check_competition(client, owner, repo_name, candidates)
            ranked = rank_candidates(candidates, limit=limit)

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    from give_back.output import print_triage, print_triage_json

    if json_output:
        print_triage_json(ranked, owner, repo_name)
    else:
        print_triage(ranked, owner, repo_name, verbose=verbose)


@cli.command()
@click.argument("repo")
@click.argument("issue_number", type=int)
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
def sniff(repo: str, issue_number: int, json_output: bool) -> None:
    """Assess code quality for files referenced in a GitHub issue.

    REPO can be 'owner/repo' or a full GitHub URL. ISSUE_NUMBER is the issue to inspect.
    """
    from give_back.sniff.assess import assess_issue

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            result = assess_issue(client, owner, repo_name, issue_number)
    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Issue #{issue_number} not found in {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if json_output:
        print_sniff_json(result)
    else:
        print_sniff(result)


@cli.command()
@click.argument("repo")
@click.option("--issue", type=int, default=None, help="Issue number to include context in the brief.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON.")
@click.option("--keep-clone", is_flag=True, help="Keep the cloned repo after scanning.")
@click.option("--verbose", "-v", is_flag=True, help="Show detection details.")
def conventions(repo: str, issue: int | None, json_output: bool, keep_clone: bool, verbose: bool) -> None:
    """Scan a repository's contribution conventions and produce a brief.

    REPO can be 'owner/repo' or a full GitHub URL.
    Clones the repo to a temp directory, analyzes commit messages, PR templates,
    branch naming, test frameworks, merge strategy, code style, and DCO requirements.
    """
    from give_back.conventions.brief import scan_conventions
    from give_back.conventions.clone import CloneError

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            if verbose:
                _console.print(f"  [dim]Scanning conventions for {owner}/{repo_name}...[/dim]")

            brief = scan_conventions(
                client,
                owner,
                repo_name,
                issue_number=issue,
                keep_clone=keep_clone,
                verbose=verbose,
            )

            if json_output:
                print_conventions_json(brief)
            else:
                print_conventions(brief, verbose=verbose)

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except CloneError as exc:
        _console.print(f"[red]Error:[/red] Failed to clone repository: {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@cli.command()
@click.argument("repo")
@click.option("--limit", default=20, help="Maximum number of dependencies to assess.")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON instead of formatted table.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress and signal data.")
def deps(repo: str, limit: int, json_output: bool, verbose: bool) -> None:
    """Walk a project's dependencies and assess each for contribution viability.

    REPO can be 'owner/repo' or a full GitHub URL.
    Parses the project's manifest (go.mod, pyproject.toml, requirements.txt),
    resolves each dependency to a GitHub repo, and runs viability assessment.
    """
    from give_back.deps.walker import walk_deps
    from give_back.output import print_deps, print_deps_json

    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    token = resolve_token()
    if token is None:
        _console.print("[red]Error:[/red] `deps` requires authentication. Set GITHUB_TOKEN or run `gh auth login`.")
        sys.exit(1)

    try:
        with GitHubClient(token=token) as client:
            walk_result = walk_deps(client, owner, repo_name, limit=limit, verbose=verbose)
    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError:
        _console.print(f"[red]Error:[/red] Repository not found: {owner}/{repo_name}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except GiveBackError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if json_output:
        print_deps_json(walk_result)
    else:
        print_deps(walk_result, verbose=verbose)


@cli.command()
@click.argument("calibration_file", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed signal data for mismatches.")
def calibrate(calibration_file: str, verbose: bool) -> None:
    """Run scoring threshold calibration against a set of repos with known tiers.

    CALIBRATION_FILE is a YAML or JSON file mapping repos to expected tiers.

    YAML format:

        - repo: pallets/flask

          expected: green

    JSON format:

        [{"repo": "pallets/flask", "expected": "green"}]
    """
    from give_back.calibrate import load_calibration_file, run_calibration
    from give_back.output import print_calibration

    try:
        entries = load_calibration_file(calibration_file)
    except (ValueError, KeyError) as exc:
        _console.print(f"[red]Error:[/red] Invalid calibration file: {exc}")
        sys.exit(1)

    if not entries:
        _console.print("[red]Error:[/red] Calibration file contains no entries.")
        sys.exit(1)

    token = resolve_token()

    try:
        with GitHubClient(token=token) as client:
            _console.print(f"  Running calibration on {len(entries)} repos...")
            result = run_calibration(client, entries, verbose=verbose)

        print_calibration(result, verbose=verbose)

    except AuthenticationError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    except RepoNotFoundError as exc:
        _console.print(f"[red]Error:[/red] Repository not found: {exc}")
        sys.exit(1)
    except RateLimitError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@cli.command()
@click.argument("repo")
def skip(repo: str) -> None:
    """Add a repository to the skip list (excluded from dep-walking results).

    REPO should be 'owner/repo'.
    """
    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    slug = f"{owner}/{repo_name}"
    add_to_skip_list(slug)
    _console.print(f"Added {slug} to skip list.")


@cli.command()
@click.argument("repo")
def unskip(repo: str) -> None:
    """Remove a repository from the skip list.

    REPO should be 'owner/repo'.
    """
    try:
        owner, repo_name = _parse_repo(repo)
    except click.BadParameter as exc:
        _console.print(f"[red]Error:[/red] {exc.format_message()}")
        sys.exit(1)

    slug = f"{owner}/{repo_name}"
    remove_from_skip_list(slug)
    _console.print(f"Removed {slug} from skip list.")


@cli.command()
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

    from give_back.conventions.brief import scan_conventions
    from give_back.conventions.models import ContributionBrief
    from give_back.prepare.action_plan import generate_action_plan
    from give_back.prepare.brief_writer import write_brief
    from give_back.prepare.fork import ensure_fork
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

    # 4. Convention scan (unless --skip-conventions)
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

    # 5. Ensure fork exists
    try:
        fork_owner = ensure_fork(owner, repo_name)
    except ForkError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # 6. Generate branch name
    branch_name = generate_branch_name(
        brief.branch_convention,
        issue or 0,
        brief.issue_title or "contribution",
    )

    # 7. Set up workspace (clone, remotes, branch)
    try:
        workspace_path = setup_workspace(
            fork_owner=fork_owner,
            repo=repo_name,
            upstream_owner=owner,
            branch_name=branch_name,
            default_branch=brief.default_branch,
            workspace_dir=effective_workspace_dir,
        )
    except WorkspaceError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    # 8. Write brief
    try:
        write_brief(workspace_path, brief, issue, branch_name, owner)
    except OSError as exc:
        _console.print(f"[red]Error:[/red] Cannot write brief: {exc}")
        sys.exit(1)

    # 9. Generate and print action plan (or JSON output)
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
            subprocess.run(config.handoff_command, shell=True, cwd=workspace_path)  # noqa: S602
        except OSError as exc:
            _console.print(
                f"[yellow]Warning:[/yellow] Handoff command failed: {exc}. Workspace ready at {workspace_path}."
            )


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed check results.")
def check(verbose: bool) -> None:
    """Run pre-flight guardrail checks in a give-back workspace.

    Must be run from a directory prepared with `give-back prepare`.
    Reads .give-back/context.json to determine which checks apply.
    """
    import json
    import subprocess
    from pathlib import Path

    from give_back.guardrails import (
        check_base_branch_freshness,
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

    # 3. Gather current git state
    # Staged files
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=cwd,
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
    )
    commit_msg = result.stdout.strip() if result.returncode == 0 else ""

    # Commits behind upstream
    commits_behind = 0
    result = subprocess.run(
        ["git", "rev-list", "--count", f"HEAD..upstream/{default_branch}"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode == 0:
        try:
            commits_behind = int(result.stdout.strip())
        except ValueError:
            pass

    # 4. Run guardrails
    results: list = []

    results.append(check_staged_files_clean(staged_files))

    if staged_files or commit_msg:
        results.append(check_dco_signoff(commit_msg, dco_required))

    results.append(check_unrelated_changes(staged_files))

    results.append(check_base_branch_freshness(branch_name, f"upstream/{default_branch}", commits_behind))

    results.append(check_local_ci(ci_commands if ci_commands else None, ci_results=None))

    # 5. If auth is available, check for duplicate PRs
    token = resolve_token()
    if token is not None:
        try:
            with GitHubClient(token=token) as client:
                results.append(check_duplicate_pr(client, upstream_owner, repo_name, issue_number))
        except (AuthenticationError, RateLimitError, GiveBackError):
            pass  # Skip duplicate check if API fails

    # 6. Print results
    print_check_results(results, upstream_owner, repo_name, issue_number, verbose=verbose)
