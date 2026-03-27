"""Reusable viability assessment logic.

Extracted from cli.py so both the `assess` CLI command and the dependency
walker can call the same assessment pipeline.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from rich.console import Console

from give_back.exceptions import GiveBackError, RepoNotFoundError
from give_back.github_client import GitHubClient
from give_back.license_eval import LicenseEvaluation, evaluate_license_text
from give_back.models import Assessment, SignalResult, Tier
from give_back.reconcile import reconcile_merge_rate, should_reconcile
from give_back.scoring import compute_tier
from give_back.signals import ALL_SIGNALS

_console = Console(stderr=True)

# License file names to try, in order of preference
_LICENSE_FILENAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")


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

    # Score (first pass)
    tier, gate_passed, incomplete = compute_tier(signal_results)

    # Bias reconciliation: if PR merge rate looks suspiciously low but other signals
    # are healthy, investigate collaborator role transitions and re-score if warranted.
    signal_names = [s.name for s in ALL_SIGNALS]
    if should_reconcile(signal_results, signal_names):
        # Find the merge rate signal index
        for i, signal_def in enumerate(ALL_SIGNALS):
            if "merge" in signal_def.name.lower() and successful_results[i].score < 0.4:
                adjusted = reconcile_merge_rate(client, owner, repo, successful_results[i], verbose=verbose)
                if adjusted is not None:
                    successful_results[i] = adjusted
                    signal_results[i] = (signal_def.weight, adjusted)
                    # Re-score with adjusted signal
                    tier, gate_passed, incomplete = compute_tier(signal_results)
                break

    # LLM-assisted license classification: if a license signal needs human review,
    # try to fetch the LICENSE file and classify it with an LLM.
    _try_llm_license_classification(client, owner, repo, successful_results, verbose)

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


def _fetch_license_text(client: GitHubClient, owner: str, repo: str) -> str | None:
    """Try to fetch the LICENSE file content from the repository.

    Tries LICENSE, LICENSE.md, LICENSE.txt, COPYING in order.
    Returns the decoded text, or None if not found.
    """
    for filename in _LICENSE_FILENAMES:
        try:
            contents = client.rest_get(f"/repos/{owner}/{repo}/contents/{filename}")
            if contents.get("encoding") == "base64" and contents.get("content"):
                return base64.b64decode(contents["content"]).decode("utf-8", errors="replace")
        except (RepoNotFoundError, GiveBackError):
            continue
    return None


def _try_llm_license_classification(
    client: GitHubClient,
    owner: str,
    repo: str,
    results: list[SignalResult],
    verbose: bool,
) -> None:
    """Post-process: if a license signal needs human review, try LLM classification.

    Mutates the signal result in-place if classification succeeds.
    """
    for result in results:
        if not result.details.get("needs_human"):
            continue

        # Found a license signal that needs review
        if verbose:
            _console.print("  [dim]Fetching LICENSE file for LLM classification...[/dim]")

        license_text = _fetch_license_text(client, owner, repo)
        if license_text is None:
            if verbose:
                _console.print("  [dim]LICENSE file not found, skipping LLM classification.[/dim]")
            return

        if verbose:
            _console.print("  [dim]Sending license text to Claude for classification...[/dim]")

        result_from_llm = evaluate_license_text(license_text)
        if result_from_llm is None:
            if verbose:
                _console.print("  [dim]LLM classification unavailable (no API key or call failed).[/dim]")
            return

        _apply_llm_result(result, result_from_llm)
        if verbose:
            _console.print(
                f"  [dim]LLM says: {result_from_llm.classification} ({result_from_llm.confidence} confidence)[/dim]"
            )
        return  # Only process the first matching signal


def _apply_llm_result(result: SignalResult, llm_result: LicenseEvaluation) -> None:
    """Update a license SignalResult with LLM classification data."""
    license_url = result.details.get("license_url", "")
    llm_summary = f"{llm_result.classification} ({llm_result.summary}, {llm_result.confidence} confidence)"
    result.summary = f"Unrecognized — LLM says: {llm_summary}\n                          verify at {license_url}"
    result.details["llm_classification"] = {
        "classification": llm_result.classification,
        "summary": llm_result.summary,
        "oss_compatible": llm_result.oss_compatible,
        "confidence": llm_result.confidence,
        "details": llm_result.details,
    }
