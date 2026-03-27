"""Terminal output formatting for give-back assessments.

Produces a rich table with signal breakdown and a natural-language summary.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from give_back.conventions.models import ContributionBrief
from give_back.models import Assessment, SignalWeight, Tier
from give_back.sniff.models import SniffResult
from give_back.triage.models import Competition, IssueCandidate

if TYPE_CHECKING:
    from give_back.calibrate import CalibrationResult
    from give_back.deps.walker import WalkResult

_console = Console()

_TIER_COLORS = {
    Tier.GREEN: "green",
    Tier.YELLOW: "yellow",
    Tier.RED: "red",
}

_TIER_LABELS = {
    Tier.GREEN: "GREEN — Viable for outside contributions",
    Tier.YELLOW: "YELLOW — Mixed signals, proceed with caution",
    Tier.RED: "RED — Not viable for outside contributions",
}

_WEIGHT_LABELS = {
    SignalWeight.GATE: "GATE",
    SignalWeight.HIGH: "HIGH",
    SignalWeight.MEDIUM: "MED",
    SignalWeight.LOW: "LOW",
}


def print_assessment(
    assessment: Assessment,
    signal_names: list[str],
    signal_weights: list[SignalWeight],
    verbose: bool = False,
) -> None:
    """Print a formatted assessment to the terminal."""
    color = _TIER_COLORS[assessment.overall_tier]

    # Header
    _console.print()
    _console.print(f"  Repository: [bold]{assessment.owner}/{assessment.repo}[/bold]")

    tier_label = _TIER_LABELS[assessment.overall_tier]
    _console.print(f"  Overall:    [{color} bold]{tier_label}[/{color} bold]")

    if assessment.incomplete:
        _console.print("  [yellow]Note: Incomplete assessment — some signals failed to evaluate[/yellow]")

    _console.print()

    # Natural-language summary
    summary = _build_summary(assessment, signal_names)
    _console.print(f"  {summary}")
    _console.print()

    # Signal table
    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("Signal", min_width=25)
    table.add_column("Weight", justify="center", min_width=6)
    table.add_column("Tier", justify="center", min_width=8)
    table.add_column("Finding", min_width=40)

    for name, weight, result in zip(signal_names, signal_weights, assessment.signals):
        weight_label = _WEIGHT_LABELS.get(weight, str(weight.value))

        if result.skip:
            tier_display = "—"
            tier_color = "dim"
            finding = f"[dim]{result.summary}[/dim]"
        else:
            tier_color = _TIER_COLORS.get(result.tier, "white")
            tier_display = result.tier.value.upper()
            if weight == SignalWeight.GATE:
                if result.score < 0:
                    tier_display = "FAIL"
                elif result.details.get("needs_human"):
                    tier_display = "REVIEW"
                else:
                    tier_display = "PASS"
            finding = result.summary
            if result.low_sample:
                finding += " [dim](low sample)[/dim]"

        table.add_row(
            name,
            weight_label,
            f"[{tier_color}]{tier_display}[/{tier_color}]",
            finding,
        )

    _console.print(table)
    _console.print()

    # Verbose details
    if verbose:
        _print_verbose_details(assessment, signal_names)


def print_assessment_json(assessment: Assessment, signal_names: list[str]) -> None:
    """Print assessment as JSON to stdout."""
    data = {
        "owner": assessment.owner,
        "repo": assessment.repo,
        "overall_tier": assessment.overall_tier.value,
        "gate_passed": assessment.gate_passed,
        "incomplete": assessment.incomplete,
        "timestamp": assessment.timestamp,
        "signals": [
            {
                "name": name,
                "score": r.score,
                "tier": r.tier.value,
                "summary": r.summary,
                "low_sample": r.low_sample,
                "details": r.details,
            }
            for name, r in zip(signal_names, assessment.signals)
        ],
    }
    print(json.dumps(data, indent=2))


def print_cached_notice(owner: str, repo: str, timestamp: str) -> None:
    """Print a notice that cached results are being used."""
    _console.print(f"  [dim]Using cached assessment from {timestamp}. Use --no-cache to refresh.[/dim]")


def _build_summary(assessment: Assessment, signal_names: list[str]) -> str:
    """Build a natural-language summary paragraph from signal results."""
    parts = []

    for name, result in zip(signal_names, assessment.signals):
        # Only include interesting findings in the summary
        if "merge" in name.lower() and result.score >= 0:
            parts.append(result.summary)
        elif "response" in name.lower() and result.tier != Tier.RED:
            parts.append(f"{result.summary} median response time")
        elif "ghost" in name.lower() and result.score < 1.0:
            parts.append(result.summary)
        elif "ai policy" in name.lower() and result.score < 1.0:
            parts.append(f"AI policy: {result.summary.lower()}")

    if not parts:
        if assessment.overall_tier == Tier.GREEN:
            return "This project shows strong signals for accepting outside contributions."
        elif assessment.overall_tier == Tier.YELLOW:
            return "This project shows mixed signals for outside contributions."
        else:
            return "This project does not appear to accept outside contributions."

    return ". ".join(parts) + "."


def _print_verbose_details(assessment: Assessment, signal_names: list[str]) -> None:
    """Print detailed signal data for --verbose mode."""
    _console.print("  [bold]Detailed signal data:[/bold]")
    for name, result in zip(signal_names, assessment.signals):
        if result.details:
            _console.print(f"    [dim]{name}:[/dim]")
            for key, value in result.details.items():
                _console.print(f"      {key}: {value}")

        # Collaborator bias warning
        collaborator_count = result.details.get("collaborator_pr_count", 0)
        if collaborator_count > 0 and "merge" in name.lower():
            _console.print(
                f"      [yellow]Note: {collaborator_count} PR(s) from current collaborators "
                f"may have been external contributions. authorAssociation reflects "
                f"current role, not role at PR time.[/yellow]"
            )
    _console.print()


# --- Triage output ---

_COMPETITION_COLORS = {
    Competition.NONE: "green",
    Competition.LOW: "yellow",
    Competition.HIGH: "red",
}


def print_triage(candidates: list[IssueCandidate], owner: str, repo: str, verbose: bool = False) -> None:
    """Print a ranked triage table to the terminal."""
    _console.print()
    _console.print(f"  Found [bold]{len(candidates)}[/bold] candidate issues for {owner}/{repo}")
    _console.print()

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Issue", justify="right", min_width=6)
    table.add_column("Scope", justify="center", min_width=5)
    table.add_column("Clarity", justify="center", min_width=7)
    table.add_column("Competition", justify="center", min_width=11)
    table.add_column("Title", min_width=40)

    for i, c in enumerate(candidates, 1):
        comp_color = _COMPETITION_COLORS.get(c.competition, "white")
        comp_text = c.competition.value
        if verbose and c.competition_detail:
            comp_text += f"\n[dim]({c.competition_detail})[/dim]"

        title = c.title
        if c.priority_labels:
            label_str = ", ".join(c.priority_labels)
            title += f"\n[dim][{label_str}][/dim]"
        if verbose and c.staleness_risk:
            title += "\n[yellow](stale — >1yr old, no recent activity)[/yellow]"

        table.add_row(
            str(i),
            f"#{c.number}",
            c.scope.value,
            c.clarity.value,
            f"[{comp_color}]{comp_text}[/{comp_color}]",
            title,
        )

    _console.print(table)
    _console.print()
    _console.print(f"  Use [bold]give-back sniff {owner}/{repo} <ISSUE_NUMBER>[/bold] to inspect code quality.")
    _console.print()


def print_triage_json(candidates: list[IssueCandidate], owner: str, repo: str) -> None:
    """Print triage results as JSON to stdout."""
    data = {
        "owner": owner,
        "repo": repo,
        "candidates": [
            {
                "number": c.number,
                "title": c.title,
                "url": c.url,
                "labels": c.labels,
                "priority_labels": c.priority_labels,
                "scope": c.scope.value,
                "clarity": c.clarity.value,
                "competition": c.competition.value,
                "competition_detail": c.competition_detail,
                "staleness_risk": c.staleness_risk,
                "comment_count": c.comment_count,
            }
            for c in candidates
        ],
    }
    print(json.dumps(data, indent=2))


# --- Sniff output ---

_VERDICT_COLORS = {
    "LOOKS_GOOD": "green",
    "MESSY": "yellow",
    "DUMPSTER_FIRE": "red",
}

_VERDICT_LABELS = {
    "LOOKS_GOOD": "LOOKS GOOD",
    "MESSY": "MESSY",
    "DUMPSTER_FIRE": "DUMPSTER FIRE",
}


def print_sniff(result: SniffResult) -> None:
    """Print a formatted sniff assessment to the terminal."""
    color = _VERDICT_COLORS.get(result.verdict, "white")
    verdict_label = _VERDICT_LABELS.get(result.verdict, result.verdict)

    _console.print()
    _console.print(f"  Issue #{result.issue_number}: [bold]{result.issue_title}[/bold]")
    _console.print()

    if result.files:
        _console.print("  Referenced files:")
        for fa in result.files:
            test_status = "has tests" if fa.has_tests else "[yellow]no test file[/yellow]"
            _console.print(f"    {fa.path}  — {fa.lines} lines, {fa.recent_commits} recent commits, {test_status}")
            if fa.concerns:
                for concern in fa.concerns:
                    _console.print(f"      [dim]- {concern}[/dim]")
        _console.print()
    else:
        _console.print("  [dim]No source files referenced in issue.[/dim]")
        _console.print()

    _console.print(f"  Assessment: [{color} bold]{verdict_label}[/{color} bold]")
    _console.print(f"    {result.summary}")
    _console.print()

    if result.verdict == "LOOKS_GOOD":
        _console.print("  Next: `give-back conventions <repo>` to understand contribution style.")
    elif result.verdict == "MESSY":
        _console.print("  [yellow]Proceed with caution — or try another issue.[/yellow]")
    else:
        _console.print("  [red]Recommend skipping this issue — try another one.[/red]")
    _console.print()


def print_sniff_json(result: SniffResult) -> None:
    """Print sniff assessment as JSON to stdout."""
    data = {
        "issue_number": result.issue_number,
        "issue_title": result.issue_title,
        "verdict": result.verdict,
        "summary": result.summary,
        "files": [
            {
                "path": fa.path,
                "lines": fa.lines,
                "recent_commits": fa.recent_commits,
                "has_tests": fa.has_tests,
                "max_indent_depth": fa.max_indent_depth,
                "concerns": fa.concerns,
            }
            for fa in result.files
        ],
    }
    print(json.dumps(data, indent=2))


# --- Deps output ---


def print_deps(walk_result: WalkResult, verbose: bool = False) -> None:
    """Print dependency assessment summary table."""
    stats = walk_result.filter_stats
    filtered_total = (
        stats.get("stdlib", 0) + stats.get("same_org", 0) + stats.get("skip_list", 0) + stats.get("archived", 0)
    )

    _console.print()
    _console.print(
        f"  Dependency assessment for [bold]{walk_result.primary_owner}/{walk_result.primary_repo}[/bold] "
        f"({walk_result.resolved_count} deps resolved, {filtered_total} filtered)"
    )
    _console.print()

    if not walk_result.results:
        _console.print("  [dim]No dependencies to assess after filtering.[/dim]")
        _print_deps_footer(walk_result)
        return

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", min_width=3)
    table.add_column("Repository", min_width=25)
    table.add_column("Tier", justify="center", min_width=8)
    table.add_column("Merge Rate", justify="center", min_width=10)
    table.add_column("Response", justify="center", min_width=9)
    table.add_column("Notes", min_width=15)

    for i, dep in enumerate(walk_result.results, 1):
        slug = f"{dep.owner}/{dep.repo}"

        if dep.assessment is None:
            table.add_row(str(i), slug, "[dim]—[/dim]", "[dim]—[/dim]", "[dim]—[/dim]", "[dim]assessment failed[/dim]")
            continue

        tier = dep.assessment.overall_tier
        tier_color = _TIER_COLORS.get(tier, "white")
        tier_label = tier.value.upper()

        merge_rate = _extract_signal_detail(dep.assessment, "merged", "merge_rate")
        response_time = _extract_signal_detail(dep.assessment, "first response", "median_hours")

        notes_parts = []
        if dep.from_cache:
            notes_parts.append("cached")
        low_sample_signals = [s for s in dep.assessment.signals if s.low_sample]
        if low_sample_signals:
            notes_parts.append("low sample")
        notes = ", ".join(notes_parts)

        table.add_row(
            str(i),
            slug,
            f"[{tier_color}]{tier_label}[/{tier_color}]",
            merge_rate,
            response_time,
            notes if notes else "",
        )

    _console.print(table)
    _print_deps_footer(walk_result)


def _print_deps_footer(walk_result: WalkResult) -> None:
    """Print filter summary and unresolvable count below the deps table."""
    stats = walk_result.filter_stats

    filter_parts = []
    if stats.get("stdlib", 0):
        filter_parts.append(f"{stats['stdlib']} stdlib")
    if stats.get("same_org", 0):
        filter_parts.append(f"{stats['same_org']} same-org")
    if stats.get("skip_list", 0):
        filter_parts.append(f"{stats['skip_list']} in skip list")
    if stats.get("archived", 0):
        filter_parts.append(f"{stats['archived']} archived")

    _console.print()
    if filter_parts:
        total_filtered = sum(stats.get(k, 0) for k in ("stdlib", "same_org", "skip_list", "archived"))
        _console.print(f"  {total_filtered} deps filtered: {', '.join(filter_parts)}")

    unresolved = stats.get("unresolved", 0)
    if unresolved:
        _console.print(f"  {unresolved} deps unresolvable (no GitHub URL found)")

    mega = stats.get("mega_projects", [])
    if mega:
        _console.print(f"  [dim]Mega-projects (>50k stars): {', '.join(mega)}[/dim]")

    _console.print()


def _extract_signal_detail(assessment: Assessment, keyword: str, detail_key: str) -> str:
    """Extract a specific metric from assessment signals for table display."""
    for signal in assessment.signals:
        if keyword in signal.summary.lower():
            # Try to get from details dict
            value = signal.details.get(detail_key)
            if value is not None:
                if detail_key == "merge_rate":
                    return f"{value:.0%}" if isinstance(value, float) else str(value)
                if detail_key == "median_hours":
                    if isinstance(value, (int, float)):
                        if value < 1:
                            return f"{value * 60:.0f}m"
                        if value < 48:
                            return f"{value:.0f}h"
                        return f"{value / 24:.0f}d"
                return str(value)

            # Fallback: try to extract from summary text
            return signal.summary[:20] if signal.summary else "—"

    return "—"


def print_deps_json(walk_result: WalkResult) -> None:
    """Print dependency walk results as JSON to stdout."""
    data = {
        "primary_owner": walk_result.primary_owner,
        "primary_repo": walk_result.primary_repo,
        "ecosystem": walk_result.ecosystem,
        "total_packages": walk_result.total_packages,
        "resolved_count": walk_result.resolved_count,
        "filter_stats": walk_result.filter_stats,
        "results": [
            {
                "package_name": dep.package_name,
                "owner": dep.owner,
                "repo": dep.repo,
                "from_cache": dep.from_cache,
                "assessment": {
                    "overall_tier": dep.assessment.overall_tier.value,
                    "gate_passed": dep.assessment.gate_passed,
                    "incomplete": dep.assessment.incomplete,
                    "timestamp": dep.assessment.timestamp,
                }
                if dep.assessment
                else None,
            }
            for dep in walk_result.results
        ],
    }
    print(json.dumps(data, indent=2))


# --- Calibration output ---


def print_calibration(result: CalibrationResult, verbose: bool = False) -> None:
    """Print calibration results: confusion matrix, accuracy, mismatches, suggestions."""
    from give_back.models import Tier

    tiers = [Tier.GREEN, Tier.YELLOW, Tier.RED]
    pct = (result.correct / result.total * 100) if result.total > 0 else 0.0

    _console.print()
    _console.print(f"  [bold]Calibration results ({result.total} repos):[/bold]")
    _console.print()

    # Confusion matrix
    _console.print("  [bold]Confusion Matrix:[/bold]")
    _console.print("                Predicted")

    # Header row
    header = "             "
    for t in tiers:
        header += f" {t.value.upper():>6}"
    _console.print(f"  {header}")

    # Data rows
    for expected in tiers:
        label = f"Expected {expected.value.upper():>6}"
        row = f"  {label}"
        for actual in tiers:
            count = result.matrix[expected][actual]
            row += f" {count:>6}"
        _console.print(row)

    _console.print()
    _console.print(f"  Accuracy: {result.correct}/{result.total} ({pct:.1f}%)")
    _console.print()

    if not result.mismatches:
        _console.print("  [green]All repos matched expected tiers.[/green]")
        _console.print()
        return

    # Mismatches
    _console.print("  [bold]Mismatches:[/bold]")
    for m in result.mismatches:
        _console.print(
            f"    {m.repo}: expected [bold]{m.expected.value.upper()}[/bold], got [bold]{m.actual.value.upper()}[/bold]"
        )
        _console.print(f"      (weighted avg: {m.weighted_avg:.2f})")
        if verbose and m.signal_summaries:
            for name, summary in m.signal_summaries.items():
                _console.print(f"        {name}: {summary}")

    _console.print()

    # Threshold suggestions
    green_t, yellow_t = result.current_thresholds
    _console.print(f"  Current thresholds: GREEN >= {green_t}, YELLOW >= {yellow_t}")

    if result.suggested_thresholds:
        new_green, new_yellow = result.suggested_thresholds
        _console.print(f"  Suggested thresholds: GREEN >= {new_green}, YELLOW >= {new_yellow}")
        _console.print()
        _console.print("  [dim]To apply: update TIER_GREEN_THRESHOLD / TIER_YELLOW_THRESHOLD in models.py[/dim]")
    else:
        _console.print("  [dim]No threshold adjustment could improve accuracy for these mismatches.[/dim]")

    _console.print()


# --- Conventions output ---


def print_conventions(brief: ContributionBrief, verbose: bool = False) -> None:
    """Print a formatted contribution brief to the terminal."""
    _console.print()
    title = f"Contribution Brief for {brief.owner}/{brief.repo}"
    _console.print(f"  [bold]{title}[/bold]")
    _console.print(f"  {'=' * len(title)}")
    _console.print()

    _console.print(f"  Project: [bold]{brief.owner}/{brief.repo}[/bold]")
    if brief.issue_number is not None:
        issue_title_str = f' — "{brief.issue_title}"' if brief.issue_title else ""
        _console.print(f"  Issue: #{brief.issue_number}{issue_title_str}")
    _console.print(f"  Generated: {brief.generated_at}")
    _console.print(f"  Default branch: {brief.default_branch}")
    _console.print()

    # Commit format
    cf = brief.commit_format
    style_display = cf.style
    if cf.prefix_pattern:
        style_display += f" (prefix: {cf.prefix_pattern})"
    _console.print(f"  [bold]Commit format:[/bold] {style_display}")
    if cf.examples:
        _console.print("    [dim]Examples from recent merges:[/dim]")
        for ex in cf.examples[:5]:
            _console.print(f'      [dim]"{ex}"[/dim]')
    _console.print()

    # PR template
    if brief.pr_template is not None:
        _console.print(f"  [bold]PR template:[/bold] Yes ({brief.pr_template.path})")
        if brief.pr_template.sections:
            sections_str = ", ".join(brief.pr_template.sections)
            _console.print(f"    Sections: {sections_str}")
    else:
        _console.print("  [bold]PR template:[/bold] None found")
    _console.print()

    # Branch convention
    bc = brief.branch_convention
    _console.print(f"  [bold]Branch convention:[/bold] {bc.pattern}")
    if bc.examples:
        examples_str = ", ".join(bc.examples[:5])
        _console.print(f"    [dim]Examples: {examples_str}[/dim]")
    _console.print()

    # Tests
    ti = brief.test_info
    if ti.framework:
        ci_str = f", CI runs on PR via {ti.ci_config}" if ti.ci_config else ""
        _console.print(f"  [bold]Tests:[/bold] {ti.framework}{ci_str}")
        if ti.test_dir:
            _console.print(f"    Test directory: {ti.test_dir}")
        if ti.run_command:
            _console.print(f"    Run locally: {ti.run_command}")
    else:
        _console.print("  [bold]Tests:[/bold] No framework detected")
    _console.print()

    # Merge strategy
    _console.print(f"  [bold]Merge strategy:[/bold] {brief.merge_strategy}")
    _console.print()

    # Code style
    si = brief.style_info
    if si.linter or si.formatter:
        _console.print("  [bold]Code style:[/bold]")
        if si.linter:
            config_str = f" ({si.config_file})" if si.config_file else ""
            _console.print(f"    Linter: {si.linter}{config_str}")
        if si.formatter:
            _console.print(f"    Formatter: {si.formatter}")
        if si.line_length:
            _console.print(f"    Line length: {si.line_length}")
    else:
        _console.print("  [bold]Code style:[/bold] No linter/formatter detected")
    _console.print()

    # DCO
    dco_str = "[yellow]Required[/yellow]" if brief.dco_required else "Not required"
    _console.print(f"  [bold]DCO/Sign-off:[/bold] {dco_str}")
    _console.print()

    # Review process
    ri = brief.review_info
    if ri.required_checks or ri.typical_reviewers:
        _console.print("  [bold]Review process:[/bold]")
        if ri.required_checks:
            checks_str = ", ".join(ri.required_checks)
            _console.print(f"    Required CI checks: {checks_str}")
        if ri.typical_reviewers:
            reviewers_str = ", ".join(ri.typical_reviewers)
            _console.print(f"    Typical reviewers: {reviewers_str}")
    else:
        _console.print("  [bold]Review process:[/bold] No data available")
    _console.print()

    # Notes
    if brief.notes:
        _console.print("  [bold]Notes:[/bold]")
        for note in brief.notes:
            _console.print(f"    - {note}")
        _console.print()

    if verbose:
        _print_conventions_verbose(brief)


def _print_conventions_verbose(brief: ContributionBrief) -> None:
    """Print additional verbose details for the contribution brief."""
    _console.print("  [bold]Verbose details:[/bold]")

    if brief.pr_template and brief.pr_template.raw_content:
        _console.print("    [dim]PR template content (first 500 chars):[/dim]")
        content_preview = brief.pr_template.raw_content[:500]
        for line in content_preview.splitlines():
            _console.print(f"      [dim]{line}[/dim]")

    _console.print()


def print_conventions_json(brief: ContributionBrief) -> None:
    """Print the ContributionBrief as JSON to stdout."""
    from dataclasses import asdict

    data = asdict(brief)
    print(json.dumps(data, indent=2))
