"""Dependency walker orchestrator: detect ecosystem, parse, resolve, filter, assess.

Ties together parser, resolver, and filter modules to walk a project's dependencies
and run viability assessments on each candidate.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import Progress

from give_back.deps.filter import filter_candidates
from give_back.deps.parser import (
    parse_cargo_toml,
    parse_gemfile,
    parse_gomod,
    parse_package_json,
    parse_pyproject,
    parse_requirements_txt,
)
from give_back.deps.resolver import resolve_packages
from give_back.exceptions import GiveBackError, RepoNotFoundError
from give_back.github_client import GitHubClient
from give_back.models import Assessment
from give_back.state import get_cached_assessment, get_skip_list, save_assessment

logger = logging.getLogger(__name__)

_console = Console(stderr=True)


@dataclass
class DepResult:
    """Assessment result for a single dependency."""

    package_name: str
    owner: str
    repo: str
    assessment: Assessment | None  # None if assessment failed
    from_cache: bool


@dataclass
class WalkResult:
    """Complete result from walking a project's dependencies."""

    primary_owner: str
    primary_repo: str
    ecosystem: str  # "python", "go", "rust", "node", or "ruby"
    results: list[DepResult] = field(default_factory=list)
    filter_stats: dict = field(default_factory=dict)
    total_packages: int = 0  # before filtering
    resolved_count: int = 0  # successfully resolved to GitHub


class NoManifestError(GiveBackError):
    """No supported manifest file found in the repository."""


def walk_deps(
    client: GitHubClient,
    owner: str,
    repo: str,
    limit: int = 20,
    verbose: bool = False,
) -> WalkResult:
    """Walk a project's dependencies and assess each for contribution viability.

    Flow:
        1. Detect ecosystem (go.mod → pyproject.toml → requirements.txt)
        2. Fetch and parse manifest
        3. Resolve package names to GitHub repos
        4. Filter (stdlib, same-org, skip list, archived)
        5. Assess each candidate (up to limit), using cache when available

    Args:
        client: Authenticated GitHubClient.
        owner: Repository owner.
        repo: Repository name.
        limit: Maximum number of dependencies to assess.
        verbose: Show detailed progress.

    Returns:
        WalkResult with assessed dependencies and statistics.

    Raises:
        NoManifestError: If no supported manifest file is found.
        RepoNotFoundError: If the repository does not exist.
    """
    # Step 1: Detect ecosystem and fetch manifest
    ecosystem, packages = _detect_and_parse(client, owner, repo, verbose)

    total_packages = len(packages)

    if not packages:
        return WalkResult(
            primary_owner=owner,
            primary_repo=repo,
            ecosystem=ecosystem,
            total_packages=0,
            resolved_count=0,
        )

    # Step 2: Resolve packages to GitHub repos
    if verbose:
        _console.print(f"  [dim]Resolving {len(packages)} packages to GitHub repos...[/dim]")

    resolved = resolve_packages(packages, ecosystem)
    resolved_count = sum(1 for _, slug in resolved if slug is not None)

    # Step 3: Filter
    skip_list = get_skip_list()
    filtered, filter_stats = filter_candidates(resolved, owner, skip_list, client=client)

    if verbose:
        _console.print(
            f"  [dim]{resolved_count} resolved, {filter_stats['passed']} candidates "
            f"after filtering ({filter_stats['stdlib']} stdlib, "
            f"{filter_stats['same_org']} same-org, "
            f"{filter_stats['skip_list']} skipped, "
            f"{filter_stats['archived']} archived)[/dim]"
        )

    # Step 4: Assess each candidate (up to limit)
    candidates_to_assess = filtered[:limit]
    results: list[DepResult] = []

    with Progress(console=_console, transient=True) as progress:
        task = progress.add_task("Assessing dependencies...", total=len(candidates_to_assess))

        for pkg_name, slug in candidates_to_assess:
            dep_owner, dep_repo = slug.split("/", 1)
            progress.update(task, description=f"Assessing {slug}...")

            # Check cache first
            cached = get_cached_assessment(dep_owner, dep_repo)
            if cached is not None:
                # Build a minimal Assessment from cached data
                assessment = _assessment_from_cache(dep_owner, dep_repo, cached)
                results.append(
                    DepResult(
                        package_name=pkg_name,
                        owner=dep_owner,
                        repo=dep_repo,
                        assessment=assessment,
                        from_cache=True,
                    )
                )
                progress.advance(task)
                continue

            # Run full assessment
            try:
                from give_back.assess import run_assessment

                assessment = run_assessment(client, dep_owner, dep_repo, verbose=False)

                # Cache the result
                try:
                    save_assessment(assessment)
                except (PermissionError, GiveBackError):
                    pass

                results.append(
                    DepResult(
                        package_name=pkg_name,
                        owner=dep_owner,
                        repo=dep_repo,
                        assessment=assessment,
                        from_cache=False,
                    )
                )
            except (RepoNotFoundError, GiveBackError) as exc:
                logger.debug("Assessment failed for %s: %s", slug, exc)
                results.append(
                    DepResult(
                        package_name=pkg_name,
                        owner=dep_owner,
                        repo=dep_repo,
                        assessment=None,
                        from_cache=False,
                    )
                )

            progress.advance(task)

    return WalkResult(
        primary_owner=owner,
        primary_repo=repo,
        ecosystem=ecosystem,
        results=results,
        filter_stats=filter_stats,
        total_packages=total_packages,
        resolved_count=resolved_count,
    )


def _detect_and_parse(client: GitHubClient, owner: str, repo: str, verbose: bool) -> tuple[str, list[str]]:
    """Detect ecosystem and parse the manifest file.

    Returns (ecosystem, list_of_package_names).
    Raises NoManifestError if no supported manifest is found.
    """
    # Detection order: language-specific lockfiles first, then generic manifests.
    manifests: list[tuple[str, str, str]] = [
        ("go.mod", "go", "Go"),
        ("Cargo.toml", "rust", "Rust"),
        ("pyproject.toml", "python", "Python"),
        ("package.json", "node", "Node.js"),
        ("Gemfile", "ruby", "Ruby"),
        ("requirements.txt", "python", "Python"),
    ]

    parsers = {
        "go.mod": parse_gomod,
        "Cargo.toml": parse_cargo_toml,
        "pyproject.toml": parse_pyproject,
        "package.json": parse_package_json,
        "Gemfile": parse_gemfile,
        "requirements.txt": parse_requirements_txt,
    }

    for filename, ecosystem, label in manifests:
        content = _try_fetch_file(client, owner, repo, filename)
        if content is not None:
            if verbose:
                _console.print(f"  [dim]Found {filename} — {label} project[/dim]")
            return ecosystem, parsers[filename](content)

    raise NoManifestError(
        f"No supported manifest file found in {owner}/{repo}. "
        "Looked for: go.mod, Cargo.toml, pyproject.toml, package.json, Gemfile, requirements.txt"
    )


def _try_fetch_file(client: GitHubClient, owner: str, repo: str, path: str) -> str | None:
    """Fetch a file from the repo via the contents API. Returns decoded text or None."""
    try:
        data = client.rest_get(f"/repos/{owner}/{repo}/contents/{path}")
        if data.get("encoding") == "base64" and data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except RepoNotFoundError:
        return None
    except GiveBackError:
        return None
    return None


def _assessment_from_cache(owner: str, repo: str, cached: dict) -> Assessment:
    """Build a minimal Assessment from cached state data."""
    from give_back.models import SignalResult, Tier

    tier_str = cached.get("overall_tier", "red")
    try:
        tier = Tier(tier_str)
    except ValueError:
        tier = Tier.RED

    # Reconstruct minimal signal results from cached data
    signals = []
    for s in cached.get("signals", []):
        try:
            s_tier = Tier(s.get("tier", "red"))
        except ValueError:
            s_tier = Tier.RED
        signals.append(
            SignalResult(
                score=s.get("score", 0.0),
                tier=s_tier,
                summary=s.get("summary", ""),
            )
        )

    return Assessment(
        owner=owner,
        repo=repo,
        overall_tier=tier,
        signals=signals,
        gate_passed=cached.get("gate_passed", False),
        incomplete=cached.get("incomplete", True),
        timestamp=cached.get("timestamp", ""),
    )
