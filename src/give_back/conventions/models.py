"""Data models for convention scan results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommitFormat:
    """Detected commit message conventions."""

    style: str
    """'conventional' / 'imperative' / 'mixed' / 'unknown'"""

    examples: list[str] = field(default_factory=list)
    """3-5 example commit messages from recent merges."""

    prefix_pattern: str | None = None
    """e.g., 'feat:', 'fix:' if conventional commits detected."""


@dataclass
class PrTemplate:
    """PR description template found in the repo."""

    path: str
    sections: list[str] = field(default_factory=list)
    """Section headers extracted from the template."""

    raw_content: str = ""


@dataclass
class BranchConvention:
    """Detected branch naming patterns."""

    pattern: str
    """'type/description' / 'issue-description' / 'mixed' / 'unknown'"""

    examples: list[str] = field(default_factory=list)


@dataclass
class CITestInfo:
    """Detected test framework and CI configuration."""

    framework: str | None = None
    """'pytest', 'go test', 'jest', 'cargo test', etc."""

    test_dir: str | None = None
    """'tests/', 'test/', 'src/test/', etc."""

    ci_config: str | None = None
    """'.github/workflows/', 'Makefile', '.travis.yml', etc."""

    run_command: str | None = None
    """'make test', 'pytest', 'go test ./...', etc."""


@dataclass
class StyleInfo:
    """Detected code style tooling."""

    linter: str | None = None
    formatter: str | None = None
    config_file: str | None = None
    line_length: int | None = None


@dataclass
class ReviewInfo:
    """Detected review process details."""

    required_checks: list[str] = field(default_factory=list)
    """CI check names from PR history or branch protection."""

    typical_reviewers: list[str] = field(default_factory=list)
    """Frequent reviewers from recent merged PRs."""


@dataclass
class CLAInfo:
    """CLA system metadata — what to sign and where."""

    required: bool = False
    system: str = "unknown"
    """One of: 'cla-assistant', 'easycla', 'google', 'apache', 'dco', 'unknown'"""
    signing_url: str | None = None
    """Direct URL to sign the CLA, or None if not derivable."""
    detection_source: str = ""
    """How we detected it: 'config-file', 'ci-workflow', 'pr-comment', 'contributing-md'"""


@dataclass
class ContributionBrief:
    """Complete convention scan output — the playbook for Phase 4."""

    owner: str
    repo: str
    issue_number: int | None = None
    issue_title: str | None = None
    generated_at: str = ""

    commit_format: CommitFormat = field(default_factory=lambda: CommitFormat(style="unknown"))
    pr_template: PrTemplate | None = None
    branch_convention: BranchConvention = field(default_factory=lambda: BranchConvention(pattern="unknown"))
    test_info: CITestInfo = field(default_factory=CITestInfo)
    merge_strategy: str = "unknown"
    """'squash' / 'merge' / 'rebase' / 'mixed' / 'unknown'"""

    style_info: StyleInfo = field(default_factory=StyleInfo)
    dco_required: bool = False
    cla_info: CLAInfo = field(default_factory=CLAInfo)
    review_info: ReviewInfo = field(default_factory=ReviewInfo)
    notes: list[str] = field(default_factory=list)

    default_branch: str = "main"
    """The project's default branch name (for branching off of)."""

    @property
    def cla_required(self) -> bool:
        """Backward-compat property — delegates to cla_info.required."""
        return self.cla_info.required
