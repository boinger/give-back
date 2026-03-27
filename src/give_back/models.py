"""Core data models for give-back."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, NamedTuple


class Tier(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class SignalWeight(Enum):
    GATE = "gate"  # Pass/fail — any gate failure → RED
    HIGH = "high"  # 3x multiplier in weighted average
    MEDIUM = "medium"  # 2x multiplier
    LOW = "low"  # 1x multiplier


WEIGHT_MULTIPLIERS: dict[SignalWeight, int] = {
    SignalWeight.HIGH: 3,
    SignalWeight.MEDIUM: 2,
    SignalWeight.LOW: 1,
}

# Tier thresholds (applied to weighted average of non-GATE signal scores)
TIER_GREEN_THRESHOLD = 0.7
TIER_YELLOW_THRESHOLD = 0.4


@dataclass
class SignalResult:
    """Result from evaluating a single viability signal."""

    score: float
    """0.0 (bad) to 1.0 (good). GATE signals: 1.0 = pass, -1.0 = fail."""

    tier: Tier
    """This signal's individual tier, derived from score."""

    summary: str
    """One-line human-readable finding, e.g. '82% of external PRs merged'."""

    details: dict = field(default_factory=dict)
    """Raw data for --verbose and --json output."""

    low_sample: bool = False
    """True if <10 data points; shown as caveat in output."""

    skip: bool = False
    """True if there's no data to evaluate (e.g., no CONTRIBUTING.md).
    Scoring drops skipped signals from the weighted average. Output shows '—'."""


def score_to_tier(score: float) -> Tier:
    """Convert a numeric score (0.0-1.0) to a tier."""
    if score >= TIER_GREEN_THRESHOLD:
        return Tier.GREEN
    if score >= TIER_YELLOW_THRESHOLD:
        return Tier.YELLOW
    return Tier.RED


@dataclass
class RepoData:
    """Aggregated API responses for a single repository.

    Populated by 4 API calls:
    - GraphQL (repo metadata + PRs)
    - REST community profile (contributing file location + health score)
    - REST contents (CONTRIBUTING.md text, only if community profile found a file)
    - REST search (AI policy keywords — only if CONTRIBUTING.md is silent on AI)
    """

    owner: str
    repo: str
    graphql: dict
    """Raw GraphQL response from the main viability query."""

    community: dict
    """REST community profile response."""

    contributing_text: str | None
    """CONTRIBUTING.md content (None if no file found)."""

    search: dict
    """REST search results (AI policy keywords). Empty dict if search was skipped."""


class SignalDef(NamedTuple):
    """A signal function bundled with its metadata.

    Using NamedTuple ensures every signal has name and weight at definition time —
    a missing field is a TypeError at import, not a runtime AttributeError.
    """

    func: Callable[[RepoData], SignalResult]
    name: str
    weight: SignalWeight


@dataclass
class Assessment:
    """Complete viability assessment for a repository."""

    owner: str
    repo: str
    overall_tier: Tier
    signals: list[SignalResult]
    gate_passed: bool
    incomplete: bool
    """True if a HIGH/GATE signal failed to evaluate (tier capped at YELLOW)."""

    timestamp: str
    """ISO 8601 timestamp of when the assessment was performed."""


@dataclass
class Config:
    """User configuration from ~/.give-back/config.yaml."""

    workspace_dir: str = "~/give-back-workspaces"
    """Directory where contribution workspaces are created."""

    handoff_command: str | None = None
    """Command to run after workspace is set up (e.g., 'claude', 'cursor .', 'code .')."""
