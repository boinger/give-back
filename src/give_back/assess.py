"""Reusable viability assessment logic.

Extracted from cli.py so both the `assess` CLI command and the dependency
walker can call the same assessment pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console

from give_back.github_client import GitHubClient
from give_back.models import Assessment, SignalResult, Tier
from give_back.scoring import compute_tier
from give_back.signals import ALL_SIGNALS

_console = Console(stderr=True)


def run_assessment(client: GitHubClient, owner: str, repo: str, verbose: bool = False) -> Assessment:
    """Run the full viability assessment for a single repo.

    Fetches data, evaluates all signals, computes tier, and returns an Assessment.

    Raises:
        RepoNotFoundError: If the repository does not exist.
        GraphQLError: If a GraphQL error occurs.
        RateLimitError: If the rate limit is exceeded.
        GiveBackError: On other API errors.
    """
    from give_back.cli import _fetch_repo_data

    data = _fetch_repo_data(client, owner, repo, verbose)

    # Evaluate signals
    signal_results: list[tuple] = []
    successful_results: list[SignalResult] = []

    for signal_def in ALL_SIGNALS:
        try:
            result = signal_def.func(data)
            signal_results.append((signal_def.weight, result))
            successful_results.append(result)
        except Exception:
            signal_results.append((signal_def.weight, None))
            successful_results.append(SignalResult(score=0.0, tier=Tier.RED, summary="N/A — evaluation failed"))

    # Score
    tier, gate_passed, incomplete = compute_tier(signal_results)

    # Build assessment
    now = datetime.now(timezone.utc).isoformat()
    return Assessment(
        owner=owner,
        repo=repo,
        overall_tier=tier,
        signals=successful_results,
        gate_passed=gate_passed,
        incomplete=incomplete,
        timestamp=now,
    )
