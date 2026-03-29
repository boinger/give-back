"""Conventions brief output: rich formatting + JSON."""

from __future__ import annotations

import json

from give_back.conventions.models import ContributionBrief
from give_back.output._shared import _console


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
