"""Maintainer self-assessment: checklist of community health signals.

Checks community health files, templates, labels, and viability signals,
producing a pass/fail checklist with actionable recommendations for each
failing item. Runs entirely via API (no clone required unless --conventions).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from give_back.assess import evaluate_signals, fetch_repo_data
from give_back.conventions.brief import scan_conventions
from give_back.exceptions import GiveBackError, RepoNotFoundError
from give_back.github_client import GitHubClient
from give_back.models import RepoData, Tier

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AuditItem:
    """Single audit checklist item."""

    name: str
    """e.g. 'license', 'contributing', 'pr_template'."""

    category: str
    """Grouping key: 'community_health', 'templates', 'labels', 'signals', 'conventions'."""

    passed: bool
    message: str
    """Human-readable status."""

    recommendation: str | None = None
    """What to do if failing (None if passing)."""


@dataclass
class AuditReport:
    """Full audit results."""

    owner: str
    repo: str
    items: list[AuditItem] = field(default_factory=list)
    health_percentage: int | None = None
    signal_tier: Tier | None = None


# ---------------------------------------------------------------------------
# Community health file checks (read from community profile dict)
# ---------------------------------------------------------------------------

_COMMUNITY_CHECKS: list[tuple[str, str, str, str]] = [
    # (name, files_key, pass_message, recommendation)
    ("license", "license", "LICENSE present", "Add a LICENSE file → https://choosealicense.com/"),
    ("readme", "readme", "README present", "Add a README.md describing what the project does and how to use it."),
    (
        "contributing",
        "contributing",
        "CONTRIBUTING.md present",
        "Add a CONTRIBUTING.md with setup instructions and PR guidelines.",
    ),
    (
        "code_of_conduct",
        "code_of_conduct",
        "CODE_OF_CONDUCT present",
        "Add a CODE_OF_CONDUCT.md → https://www.contributor-covenant.org/version/2/1/code_of_conduct.md",
    ),
]


def _check_community_file(community: dict, name: str, files_key: str, pass_msg: str, recommendation: str) -> AuditItem:
    """Check whether a community health file exists."""
    file_info = community.get("files", {}).get(files_key)
    if file_info is not None:
        return AuditItem(name=name, category="community_health", passed=True, message=pass_msg)
    return AuditItem(
        name=name,
        category="community_health",
        passed=False,
        message=f"{name.replace('_', ' ').upper()} missing",
        recommendation=recommendation,
    )


def _check_security(client: GitHubClient, owner: str, repo: str) -> AuditItem:
    """Check whether a SECURITY policy exists via REST contents API.

    The community profile API does not surface SECURITY.md, so we check
    the file directly.
    """
    for path in ("SECURITY.md", ".github/SECURITY.md"):
        try:
            client.rest_get(f"/repos/{owner}/{repo}/contents/{path}")
            return AuditItem(
                name="security", category="community_health", passed=True, message="SECURITY policy present"
            )
        except RepoNotFoundError:
            continue
        except (GiveBackError, httpx.HTTPStatusError):
            break
    return AuditItem(
        name="security",
        category="community_health",
        passed=False,
        message="SECURITY policy missing",
        recommendation=(
            "Add a SECURITY.md. Enable GitHub private vulnerability reporting"
            f" → https://github.com/{owner}/{repo}/security/advisories/new"
        ),
    )


# ---------------------------------------------------------------------------
# Template checks (REST contents API)
# ---------------------------------------------------------------------------

_PR_TEMPLATE_PATHS = (
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
    "pull_request_template.md",
)


def _check_pr_template(client: GitHubClient, owner: str, repo: str) -> AuditItem:
    """Check whether a PR template exists (tries several common paths)."""
    for path in _PR_TEMPLATE_PATHS:
        try:
            client.rest_get(f"/repos/{owner}/{repo}/contents/{path}")
            return AuditItem(name="pr_template", category="templates", passed=True, message="PR template present")
        except RepoNotFoundError:
            continue  # File not found at this path, try next
        except (GiveBackError, httpx.HTTPStatusError):
            break  # Other API error, stop trying
    return AuditItem(
        name="pr_template",
        category="templates",
        passed=False,
        message="PR template missing",
        recommendation="Add .github/PULL_REQUEST_TEMPLATE.md with summary and test plan sections.",
    )


def _check_issue_templates(client: GitHubClient, owner: str, repo: str) -> AuditItem:
    """Check whether issue templates exist (directory check)."""
    try:
        result = client.rest_get(f"/repos/{owner}/{repo}/contents/.github/ISSUE_TEMPLATE")
        # If we get here, the directory exists (API returns array of files)
        if isinstance(result, list) and len(result) > 0:
            return AuditItem(
                name="issue_templates",
                category="templates",
                passed=True,
                message=f"Issue templates present ({len(result)} templates)",
            )
        return AuditItem(
            name="issue_templates",
            category="templates",
            passed=True,
            message="Issue template directory present",
        )
    except RepoNotFoundError:
        pass  # Directory not found
    except (GiveBackError, httpx.HTTPStatusError):
        pass  # Other API error
    return AuditItem(
        name="issue_templates",
        category="templates",
        passed=False,
        message="Issue templates missing",
        recommendation="Add .github/ISSUE_TEMPLATE/ with YAML issue forms for bugs and feature requests.",
    )


# ---------------------------------------------------------------------------
# Label check
# ---------------------------------------------------------------------------

_CONTRIBUTION_LABELS = {"good first issue", "good-first-issue", "help wanted", "help-wanted"}


def _check_labels(label_names: list[str]) -> AuditItem:
    """Check for contribution-friendly labels."""
    lower_names = {n.lower() for n in label_names}
    found = _CONTRIBUTION_LABELS & lower_names
    if found:
        display = ", ".join(sorted(found))
        return AuditItem(name="labels", category="labels", passed=True, message=f"Labels: {display}")
    return AuditItem(
        name="labels",
        category="labels",
        passed=False,
        message="No contribution-friendly labels",
        recommendation="Create 'good first issue' and 'help wanted' labels to guide new contributors.",
    )


# ---------------------------------------------------------------------------
# Signal wrapping (Assessment → AuditItems)
# ---------------------------------------------------------------------------

_SIGNAL_RECOMMENDATIONS: dict[str, str] = {
    "External PR merge rate": "{score:.0%} merge rate. Consider whether closed PRs could be guided to merge.",
    "Ghost-closing rate": "{score:.0%} of external PRs closed without feedback. Reply before closing.",
    "Time-to-first-response": "Median response time could be improved. Aim for <24h.",
    "Contribution process": "Contribution friction detected. Consider reducing CLA/DCO requirements.",
    "AI policy": "No AI policy found. State your position in CONTRIBUTING.md.",
    "Staleness": "Project activity is low. Active projects attract more contributors.",
}

_SIGNAL_PASS_THRESHOLD = 0.6


def _wrap_signals(assessment_signals: list, signal_names: list[str]) -> list[AuditItem]:
    """Convert signal results to AuditItems with maintainer-facing recommendations."""
    items: list[AuditItem] = []
    for name, result in zip(signal_names, assessment_signals):
        if result.skip:
            continue

        passed = result.score >= _SIGNAL_PASS_THRESHOLD
        recommendation = None

        if not passed and name in _SIGNAL_RECOMMENDATIONS:
            recommendation = _SIGNAL_RECOMMENDATIONS[name].format(score=result.score)
        elif not passed:
            recommendation = f"{name}: {result.summary}"

        items.append(
            AuditItem(
                name=name.lower().replace(" ", "_"),
                category="signals",
                passed=passed,
                message=result.summary,
                recommendation=recommendation,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Convention wrapping (informational, not pass/fail)
# ---------------------------------------------------------------------------


def _wrap_conventions(brief) -> list[AuditItem]:
    """Convert convention scan results to informational AuditItems."""
    items: list[AuditItem] = []

    if brief.commit_format:
        style = brief.commit_format.style if hasattr(brief.commit_format, "style") else "unknown"
        items.append(
            AuditItem(name="commit_format", category="conventions", passed=True, message=f"Commit format: {style}")
        )

    if brief.merge_strategy:
        strategy = brief.merge_strategy if isinstance(brief.merge_strategy, str) else str(brief.merge_strategy)
        items.append(
            AuditItem(name="merge_strategy", category="conventions", passed=True, message=f"Merge strategy: {strategy}")
        )

    if brief.style_info and brief.style_info.linter:
        linter = brief.style_info.linter
        items.append(AuditItem(name="code_style", category="conventions", passed=True, message=f"Code style: {linter}"))

    if brief.test_info and brief.test_info.framework:
        framework = brief.test_info.framework
        items.append(
            AuditItem(
                name="test_framework", category="conventions", passed=True, message=f"Test framework: {framework}"
            )
        )

    if brief.test_info and brief.test_info.ci_config:
        items.append(
            AuditItem(name="ci", category="conventions", passed=True, message=f"CI: {brief.test_info.ci_config}")
        )

    return items


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_audit(
    client: GitHubClient,
    owner: str,
    repo: str,
    *,
    verbose: bool = False,
    conventions: bool = False,
) -> AuditReport:
    """Run a full maintainer audit on a repository.

    Fetches data once, runs community health checks, template checks, label
    checks, and signal evaluation. Optionally scans conventions (requires clone).

    Returns an AuditReport with all items.
    """
    report = AuditReport(owner=owner, repo=repo)

    # Fetch all data (one set of API calls)
    data: RepoData = fetch_repo_data(client, owner, repo, verbose)
    community = data.community

    # GitHub health percentage
    report.health_percentage = community.get("health_percentage")

    # Community health file checks
    for name, files_key, pass_msg, recommendation in _COMMUNITY_CHECKS:
        report.items.append(_check_community_file(community, name, files_key, pass_msg, recommendation))
    report.items.append(_check_security(client, owner, repo))

    # Template checks (REST contents API — repo is validated by fetch_repo_data)
    report.items.append(_check_pr_template(client, owner, repo))
    report.items.append(_check_issue_templates(client, owner, repo))

    # Label check (from GraphQL labels data)
    labels_data = (data.graphql.get("repository") or {}).get("labels", {}).get("nodes", [])
    label_names = [label.get("name", "") for label in labels_data]
    report.items.append(_check_labels(label_names))

    # Signal evaluation (reuse assess pipeline)
    assessment = evaluate_signals(data, client, verbose)
    report.signal_tier = assessment.overall_tier
    report.items.extend(_wrap_signals(assessment.signals, assessment.signal_names))

    # Convention scan (opt-in, requires clone)
    if conventions:
        try:
            brief = scan_conventions(client, owner, repo, verbose=verbose)
            report.items.extend(_wrap_conventions(brief))
        except GiveBackError:
            report.items.append(
                AuditItem(
                    name="conventions",
                    category="conventions",
                    passed=False,
                    message="Convention scan failed",
                    recommendation="Try running `give-back conventions` separately for details.",
                )
            )

    return report
