"""Data models for issue triage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Scope(Enum):
    SMALL = "S"
    MEDIUM = "M"
    LARGE = "L"


class Clarity(Enum):
    HIGH = "HIGH"
    MEDIUM = "MED"
    LOW = "LOW"


class Competition(Enum):
    NONE = "None"
    LOW = "Low"  # Competing PR exists but stale (6+ months)
    HIGH = "High"  # Active competing PR or recent claim comment
    RESOLVED = "Resolved"  # Merged PR may already address this issue


@dataclass
class IssueCandidate:
    """A candidate issue for contribution, scored by triage metadata."""

    number: int
    title: str
    url: str
    labels: list[str]
    scope: Scope
    clarity: Clarity
    competition: Competition
    competition_detail: str | None = None
    """e.g., 'PR #5410 stale 8 months' or 'claimed by @user 2 days ago'"""

    staleness_risk: bool = False
    """True if issue is >1 year old with no recent activity."""

    created_at: str = ""
    updated_at: str = ""
    comment_count: int = 0
    description_length: int = 0
    body: str = ""
    """Raw issue body for sniff phase file extraction."""

    priority_labels: list[str] = field(default_factory=list)
    """Which contribution-friendly labels this issue has (good-first-issue, help-wanted, etc.)."""
