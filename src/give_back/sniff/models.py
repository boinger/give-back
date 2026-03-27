"""Data models for code quality sniff assessment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileAssessment:
    """Assessment of a single source file referenced in an issue."""

    path: str
    lines: int
    recent_commits: int
    has_tests: bool
    max_indent_depth: int
    concerns: list[str] = field(default_factory=list)


@dataclass
class SniffResult:
    """Overall code quality sniff result for an issue."""

    issue_number: int
    issue_title: str
    files: list[FileAssessment]
    verdict: str  # "LOOKS_GOOD" / "MESSY" / "DUMPSTER_FIRE"
    summary: str
