"""Tests for output.py terminal and JSON formatting."""

from __future__ import annotations

import json
import re
from io import StringIO

from rich.console import Console

from give_back.conventions.models import (
    BranchConvention,
    CITestInfo,
    CommitFormat,
    ContributionBrief,
    PrTemplate,
    ReviewInfo,
    StyleInfo,
)
from give_back.deps.walker import DepResult, WalkResult
from give_back.guardrails import GuardrailResult, Severity
from give_back.models import Assessment, SignalResult, SignalWeight, Tier
from give_back.output import (
    _extract_signal_detail,
    print_assessment,
    print_assessment_json,
    print_check_results,
    print_conventions,
    print_conventions_json,
    print_deps,
    print_deps_json,
    print_prepare_json,
    print_sniff,
    print_sniff_json,
    print_triage,
    print_triage_json,
)
from give_back.output.assess import _build_summary
from give_back.sniff.models import FileAssessment, SniffResult
from give_back.triage.models import Clarity, Competition, IssueCandidate, Scope

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _signal(
    score: float = 0.8,
    tier: Tier = Tier.GREEN,
    summary: str = "82% of external PRs merged",
    details: dict | None = None,
    low_sample: bool = False,
    skip: bool = False,
) -> SignalResult:
    return SignalResult(
        score=score,
        tier=tier,
        summary=summary,
        details=details or {},
        low_sample=low_sample,
        skip=skip,
    )


def _assessment(
    owner: str = "pallets",
    repo: str = "flask",
    tier: Tier = Tier.GREEN,
    signals: list[SignalResult] | None = None,
    gate_passed: bool = True,
    incomplete: bool = False,
    timestamp: str = "2025-06-01T00:00:00Z",
) -> Assessment:
    if signals is None:
        signals = [
            _signal(score=0.85, summary="82% of external PRs merged", details={"merge_rate": 0.82}),
            _signal(score=0.7, summary="4h first response time", tier=Tier.GREEN, details={"median_hours": 4.0}),
            _signal(score=0.3, tier=Tier.RED, summary="Ghost town — 2 contributors"),
        ]
    return Assessment(
        owner=owner,
        repo=repo,
        overall_tier=tier,
        signals=signals,
        gate_passed=gate_passed,
        incomplete=incomplete,
        timestamp=timestamp,
    )


def _issue(
    number: int = 1234,
    title: str = "Fix typo in README",
    url: str = "https://github.com/pallets/flask/issues/1234",
    labels: list[str] | None = None,
    scope: Scope = Scope.SMALL,
    clarity: Clarity = Clarity.HIGH,
    competition: Competition = Competition.NONE,
    competition_detail: str | None = None,
    staleness_risk: bool = False,
    comment_count: int = 3,
    priority_labels: list[str] | None = None,
) -> IssueCandidate:
    return IssueCandidate(
        number=number,
        title=title,
        url=url,
        labels=labels or ["good first issue"],
        scope=scope,
        clarity=clarity,
        competition=competition,
        competition_detail=competition_detail,
        staleness_risk=staleness_risk,
        comment_count=comment_count,
        priority_labels=priority_labels or [],
    )


def _sniff_result(
    verdict: str = "LOOKS_GOOD",
    files: list[FileAssessment] | None = None,
) -> SniffResult:
    if files is None:
        files = [
            FileAssessment(
                path="src/app.py",
                lines=120,
                recent_commits=5,
                has_tests=True,
                max_indent_depth=4,
                concerns=[],
            ),
        ]
    return SniffResult(
        issue_number=42,
        issue_title="Fix login bug",
        files=files,
        verdict=verdict,
        summary="Code is well-structured and has tests.",
    )


def _brief(
    owner: str = "pallets",
    repo: str = "flask",
    issue_number: int | None = 99,
    issue_title: str | None = "Add feature X",
) -> ContributionBrief:
    return ContributionBrief(
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        issue_title=issue_title,
        generated_at="2025-06-01T00:00:00Z",
        commit_format=CommitFormat(style="conventional", examples=["feat: add login", "fix: crash on save"]),
        pr_template=PrTemplate(path=".github/PULL_REQUEST_TEMPLATE.md", sections=["Summary", "Test plan"]),
        branch_convention=BranchConvention(pattern="type/description", examples=["fix/login-crash"]),
        test_info=CITestInfo(framework="pytest", test_dir="tests/", ci_config=".github/workflows/ci.yml"),
        merge_strategy="squash",
        style_info=StyleInfo(linter="ruff", formatter="black", config_file="pyproject.toml", line_length=120),
        dco_required=False,
        review_info=ReviewInfo(required_checks=["ci/test"], typical_reviewers=["maintainer1"]),
        notes=["CLA not required"],
        default_branch="main",
    )


def _walk_result(
    results: list[DepResult] | None = None,
) -> WalkResult:
    if results is None:
        results = [
            DepResult(
                package_name="requests",
                owner="psf",
                repo="requests",
                assessment=_assessment(owner="psf", repo="requests"),
                from_cache=True,
            ),
            DepResult(
                package_name="click",
                owner="pallets",
                repo="click",
                assessment=None,
                from_cache=False,
            ),
        ]
    return WalkResult(
        primary_owner="pallets",
        primary_repo="flask",
        ecosystem="python",
        results=results,
        filter_stats={"stdlib": 5, "same_org": 2, "unresolved": 1},
        total_packages=20,
        resolved_count=12,
    )


SIGNAL_NAMES = ["Merge rate", "First response time", "Ghost town"]
SIGNAL_WEIGHTS = [SignalWeight.HIGH, SignalWeight.MEDIUM, SignalWeight.LOW]


# ---------------------------------------------------------------------------
# JSON output tests
# ---------------------------------------------------------------------------


class TestPrintAssessmentJson:
    def test_structure(self, capsys):
        assessment = _assessment()
        print_assessment_json(assessment, SIGNAL_NAMES)
        data = json.loads(capsys.readouterr().out)

        assert data["owner"] == "pallets"
        assert data["repo"] == "flask"
        assert data["overall_tier"] == "green"
        assert data["gate_passed"] is True
        assert data["incomplete"] is False
        assert data["timestamp"] == "2025-06-01T00:00:00Z"
        assert len(data["signals"]) == 3

    def test_signal_fields(self, capsys):
        assessment = _assessment()
        print_assessment_json(assessment, SIGNAL_NAMES)
        data = json.loads(capsys.readouterr().out)
        sig = data["signals"][0]

        assert sig["name"] == "Merge rate"
        assert sig["score"] == 0.85
        assert sig["tier"] == "green"
        assert sig["summary"] == "82% of external PRs merged"
        assert "low_sample" in sig
        assert "details" in sig

    def test_empty_signals(self, capsys):
        assessment = _assessment(signals=[])
        print_assessment_json(assessment, [])
        data = json.loads(capsys.readouterr().out)
        assert data["signals"] == []

    def test_low_sample_flag(self, capsys):
        assessment = _assessment(signals=[_signal(low_sample=True)])
        print_assessment_json(assessment, ["Test signal"])
        data = json.loads(capsys.readouterr().out)
        assert data["signals"][0]["low_sample"] is True

    def test_incomplete_assessment(self, capsys):
        assessment = _assessment(incomplete=True, tier=Tier.YELLOW)
        print_assessment_json(assessment, SIGNAL_NAMES)
        data = json.loads(capsys.readouterr().out)
        assert data["incomplete"] is True
        assert data["overall_tier"] == "yellow"


class TestPrintTriageJson:
    def test_structure(self, capsys):
        candidates = [_issue(), _issue(number=5678, title="Improve docs")]
        print_triage_json(candidates, "pallets", "flask")
        data = json.loads(capsys.readouterr().out)

        assert data["owner"] == "pallets"
        assert data["repo"] == "flask"
        assert len(data["candidates"]) == 2

    def test_candidate_fields(self, capsys):
        candidates = [
            _issue(
                competition=Competition.LOW,
                competition_detail="PR #5410 stale 8 months",
                staleness_risk=True,
            )
        ]
        print_triage_json(candidates, "pallets", "flask")
        data = json.loads(capsys.readouterr().out)
        c = data["candidates"][0]

        assert c["number"] == 1234
        assert c["title"] == "Fix typo in README"
        assert c["scope"] == "S"
        assert c["clarity"] == "HIGH"
        assert c["competition"] == "Low"
        assert c["competition_detail"] == "PR #5410 stale 8 months"
        assert c["staleness_risk"] is True
        assert c["comment_count"] == 3

    def test_empty_candidates(self, capsys):
        print_triage_json([], "pallets", "flask")
        data = json.loads(capsys.readouterr().out)
        assert data["candidates"] == []


class TestPrintSniffJson:
    def test_structure(self, capsys):
        result = _sniff_result()
        print_sniff_json(result)
        data = json.loads(capsys.readouterr().out)

        assert data["issue_number"] == 42
        assert data["issue_title"] == "Fix login bug"
        assert data["verdict"] == "LOOKS_GOOD"
        assert data["summary"] == "Code is well-structured and has tests."
        assert len(data["files"]) == 1

    def test_file_fields(self, capsys):
        result = _sniff_result()
        print_sniff_json(result)
        data = json.loads(capsys.readouterr().out)
        f = data["files"][0]

        assert f["path"] == "src/app.py"
        assert f["lines"] == 120
        assert f["recent_commits"] == 5
        assert f["has_tests"] is True
        assert f["max_indent_depth"] == 4
        assert f["concerns"] == []

    def test_no_files(self, capsys):
        result = _sniff_result(files=[])
        print_sniff_json(result)
        data = json.loads(capsys.readouterr().out)
        assert data["files"] == []

    def test_file_with_concerns(self, capsys):
        fa = FileAssessment(
            path="big.py",
            lines=2000,
            recent_commits=0,
            has_tests=False,
            max_indent_depth=8,
            concerns=["Very large file", "Deep nesting"],
        )
        result = _sniff_result(verdict="DUMPSTER_FIRE", files=[fa])
        print_sniff_json(result)
        data = json.loads(capsys.readouterr().out)
        assert data["verdict"] == "DUMPSTER_FIRE"
        assert data["files"][0]["concerns"] == ["Very large file", "Deep nesting"]


class TestPrintConventionsJson:
    def test_structure(self, capsys):
        brief = _brief()
        print_conventions_json(brief)
        data = json.loads(capsys.readouterr().out)

        assert data["owner"] == "pallets"
        assert data["repo"] == "flask"
        assert data["issue_number"] == 99
        assert data["commit_format"]["style"] == "conventional"
        assert data["merge_strategy"] == "squash"
        assert data["default_branch"] == "main"

    def test_no_issue(self, capsys):
        brief = _brief(issue_number=None, issue_title=None)
        print_conventions_json(brief)
        data = json.loads(capsys.readouterr().out)
        assert data["issue_number"] is None
        assert data["issue_title"] is None

    def test_pr_template_sections(self, capsys):
        brief = _brief()
        print_conventions_json(brief)
        data = json.loads(capsys.readouterr().out)
        assert data["pr_template"]["sections"] == ["Summary", "Test plan"]


class TestPrintDepsJson:
    def test_structure(self, capsys):
        wr = _walk_result()
        print_deps_json(wr)
        data = json.loads(capsys.readouterr().out)

        assert data["primary_owner"] == "pallets"
        assert data["primary_repo"] == "flask"
        assert data["ecosystem"] == "python"
        assert data["total_packages"] == 20
        assert data["resolved_count"] == 12
        assert len(data["results"]) == 2

    def test_dep_with_assessment(self, capsys):
        wr = _walk_result()
        print_deps_json(wr)
        data = json.loads(capsys.readouterr().out)
        dep = data["results"][0]

        assert dep["package_name"] == "requests"
        assert dep["owner"] == "psf"
        assert dep["from_cache"] is True
        assert dep["assessment"]["overall_tier"] == "green"
        assert dep["assessment"]["gate_passed"] is True

    def test_dep_with_none_assessment(self, capsys):
        wr = _walk_result()
        print_deps_json(wr)
        data = json.loads(capsys.readouterr().out)
        dep = data["results"][1]

        assert dep["package_name"] == "click"
        assert dep["assessment"] is None

    def test_empty_results(self, capsys):
        wr = _walk_result(results=[])
        print_deps_json(wr)
        data = json.loads(capsys.readouterr().out)
        assert data["results"] == []


class TestPrintPrepareJson:
    def test_structure(self, capsys):
        brief = _brief()
        print_prepare_json("/tmp/workspace", "fix/issue-99", brief, "1. Read code\n2. Fix bug")
        data = json.loads(capsys.readouterr().out)

        assert data["workspace_path"] == "/tmp/workspace"
        assert data["branch_name"] == "fix/issue-99"
        assert data["upstream_owner"] == "pallets"
        assert data["repo"] == "flask"
        assert data["issue_number"] == 99
        assert data["action_plan"] == "1. Read code\n2. Fix bug"
        assert data["default_branch"] == "main"


# ---------------------------------------------------------------------------
# Rich table rendering tests
# ---------------------------------------------------------------------------


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences so plain-text assertions work."""
    return _ANSI_RE.sub("", text)


def _capture(func, *args, **kwargs) -> str:
    """Capture rich console output by temporarily replacing the module-level console.

    Returns plain text with ANSI codes stripped so assertions don't break on
    rich markup splitting tokens like ``#99`` into ``#\\x1b[1;36m99``.
    """
    import give_back.output._shared as shared
    import give_back.output.assess as assess_mod
    import give_back.output.check as check_mod
    import give_back.output.conventions as conv_mod
    import give_back.output.deps as deps_mod
    import give_back.output.sniff as sniff_mod
    import give_back.output.triage as triage_mod

    buf = StringIO()
    test_console = Console(file=buf, width=120, force_terminal=True)
    modules = [shared, assess_mod, check_mod, conv_mod, deps_mod, sniff_mod, triage_mod]
    originals = [m._console for m in modules]
    for m in modules:
        m._console = test_console
    try:
        func(*args, **kwargs)
    finally:
        for m, orig in zip(modules, originals):
            m._console = orig
    return _strip_ansi(buf.getvalue())


class TestPrintAssessmentRich:
    def test_contains_repo_name(self):
        output = _capture(print_assessment, _assessment(), SIGNAL_NAMES, SIGNAL_WEIGHTS)
        assert "pallets/flask" in output

    def test_contains_tier_label(self):
        output = _capture(print_assessment, _assessment(), SIGNAL_NAMES, SIGNAL_WEIGHTS)
        assert "GREEN" in output

    def test_contains_signal_names(self):
        output = _capture(print_assessment, _assessment(), SIGNAL_NAMES, SIGNAL_WEIGHTS)
        assert "Merge rate" in output
        assert "First response time" in output

    def test_incomplete_notice(self):
        output = _capture(print_assessment, _assessment(incomplete=True), SIGNAL_NAMES, SIGNAL_WEIGHTS)
        assert "Incomplete" in output

    def test_red_tier(self):
        output = _capture(print_assessment, _assessment(tier=Tier.RED), SIGNAL_NAMES, SIGNAL_WEIGHTS)
        assert "RED" in output

    def test_skipped_signal(self):
        signals = [_signal(skip=True, score=0.0, tier=Tier.RED, summary="No data")]
        assessment = _assessment(signals=signals)
        output = _capture(print_assessment, assessment, ["AI policy"], [SignalWeight.LOW])
        # Skipped signals show a dash instead of a tier
        assert "No data" in output

    def test_low_sample_annotation(self):
        signals = [_signal(low_sample=True)]
        assessment = _assessment(signals=signals)
        output = _capture(print_assessment, assessment, ["Merge rate"], [SignalWeight.HIGH])
        assert "low sample" in output

    def test_gate_pass_display(self):
        signals = [_signal(score=1.0, tier=Tier.GREEN, summary="External PRs accepted")]
        assessment = _assessment(signals=signals)
        output = _capture(print_assessment, assessment, ["PR policy"], [SignalWeight.GATE])
        assert "PASS" in output

    def test_gate_fail_display(self):
        signals = [_signal(score=-1.0, tier=Tier.RED, summary="Archived repo")]
        assessment = _assessment(signals=signals, gate_passed=False, tier=Tier.RED)
        output = _capture(print_assessment, assessment, ["Archived"], [SignalWeight.GATE])
        assert "FAIL" in output


class TestPrintTriageRich:
    def test_contains_candidate_info(self):
        output = _capture(print_triage, [_issue()], "pallets", "flask")
        assert "#1234" in output
        assert "Fix typo in README" in output

    def test_empty_candidates(self):
        output = _capture(print_triage, [], "pallets", "flask")
        assert "0" in output

    def test_competition_shown(self):
        output = _capture(
            print_triage,
            [_issue(competition=Competition.HIGH, competition_detail="Active PR")],
            "pallets",
            "flask",
        )
        assert "High" in output


class TestPrintSniffRich:
    def test_looks_good_verdict(self):
        output = _capture(print_sniff, _sniff_result(verdict="LOOKS_GOOD"))
        assert "LOOKS GOOD" in output

    def test_dumpster_fire_verdict(self):
        output = _capture(print_sniff, _sniff_result(verdict="DUMPSTER_FIRE"))
        assert "DUMPSTER FIRE" in output

    def test_no_files_message(self):
        output = _capture(print_sniff, _sniff_result(files=[]))
        assert "No source files" in output

    def test_file_details_shown(self):
        output = _capture(print_sniff, _sniff_result())
        assert "src/app.py" in output
        assert "120 lines" in output
        assert "has tests" in output


class TestPrintConventionsRich:
    def test_contains_repo_name(self):
        output = _capture(print_conventions, _brief())
        assert "pallets/flask" in output

    def test_commit_format(self):
        output = _capture(print_conventions, _brief())
        assert "conventional" in output

    def test_pr_template_shown(self):
        output = _capture(print_conventions, _brief())
        assert "PULL_REQUEST_TEMPLATE" in output

    def test_no_pr_template(self):
        brief = _brief()
        brief.pr_template = None
        output = _capture(print_conventions, brief)
        assert "None found" in output

    def test_issue_shown(self):
        output = _capture(print_conventions, _brief())
        assert "#99" in output
        assert "Add feature X" in output

    def test_no_issue(self):
        output = _capture(print_conventions, _brief(issue_number=None))
        # Issue line should not appear
        assert "#None" not in output


class TestPrintDepsRich:
    def test_contains_repo_info(self):
        output = _capture(print_deps, _walk_result())
        assert "pallets/flask" in output

    def test_empty_results(self):
        output = _capture(print_deps, _walk_result(results=[]))
        assert "No dependencies" in output

    def test_filter_stats_shown(self):
        output = _capture(print_deps, _walk_result())
        assert "stdlib" in output


class TestPrintCheckResults:
    def test_all_passed(self):
        results = [
            GuardrailResult(name="clean", severity=Severity.INFO, passed=True, message="No artifacts staged"),
            GuardrailResult(name="lint", severity=Severity.WARN, passed=True, message="Linter passes"),
        ]
        output = _capture(print_check_results, results, "pallets", "flask", issue_number=99)
        assert "All checks passed" in output
        assert "#99" in output

    def test_block_shown(self):
        results = [
            GuardrailResult(
                name="big-file",
                severity=Severity.BLOCK,
                passed=False,
                message="Large file committed",
            ),
        ]
        output = _capture(print_check_results, results, "pallets", "flask", issue_number=None)
        assert "Large file committed" in output
        assert "blocker" in output

    def test_warn_shown(self):
        results = [
            GuardrailResult(
                name="lint",
                severity=Severity.WARN,
                passed=False,
                message="Lint warnings found",
            ),
        ]
        output = _capture(print_check_results, results, "pallets", "flask", issue_number=None)
        assert "warning" in output


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_green_default(self):
        assessment = _assessment(signals=[_signal(score=0.9, summary="All good")])
        result = _build_summary(assessment, ["Something unrelated"])
        assert "strong signals" in result

    def test_red_default(self):
        assessment = _assessment(tier=Tier.RED, signals=[_signal(score=0.1, tier=Tier.RED, summary="Bad")])
        result = _build_summary(assessment, ["Something unrelated"])
        assert "does not appear" in result

    def test_merge_signal_included(self):
        signals = [_signal(score=0.8, summary="82% merged")]
        assessment = _assessment(signals=signals)
        result = _build_summary(assessment, ["Merged PR rate"])
        assert "82% merged" in result


class TestExtractSignalDetail:
    def test_merge_rate_formatting(self):
        assessment = _assessment(signals=[_signal(summary="82% of external PRs merged", details={"merge_rate": 0.82})])
        result = _extract_signal_detail(assessment, "merged", "merge_rate")
        assert result == "82%"

    def test_median_hours_short(self):
        assessment = _assessment(signals=[_signal(summary="4h first response time", details={"median_hours": 0.5})])
        result = _extract_signal_detail(assessment, "first response", "median_hours")
        assert result == "30m"

    def test_median_hours_hours(self):
        assessment = _assessment(signals=[_signal(summary="4h first response time", details={"median_hours": 12.0})])
        result = _extract_signal_detail(assessment, "first response", "median_hours")
        assert result == "12h"

    def test_median_hours_days(self):
        assessment = _assessment(signals=[_signal(summary="slow first response time", details={"median_hours": 72.0})])
        result = _extract_signal_detail(assessment, "first response", "median_hours")
        assert result == "3d"

    def test_no_matching_signal(self):
        assessment = _assessment(signals=[_signal(summary="unrelated")])
        result = _extract_signal_detail(assessment, "nonexistent", "merge_rate")
        assert result == "\u2014"
