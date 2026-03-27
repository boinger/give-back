"""Viability signal registry.

Each signal is a pure function (RepoData) -> SignalResult, wrapped in a SignalDef
NamedTuple that bundles the function with its display name and weight.
"""

from give_back.models import SignalDef, SignalWeight
from give_back.signals.ai_policy import evaluate_ai_policy
from give_back.signals.contributing import evaluate_contributing_content, evaluate_contributing_exists
from give_back.signals.ghost_closing import evaluate_ghost_closing
from give_back.signals.label_hygiene import evaluate_label_hygiene
from give_back.signals.license_gate import evaluate_license
from give_back.signals.pr_merge_rate import evaluate_pr_merge_rate
from give_back.signals.staleness import evaluate_staleness
from give_back.signals.time_to_response import evaluate_time_to_response

# 9 signals total (contributing.py exports two: existence + content)
ALL_SIGNALS: list[SignalDef] = [
    SignalDef(evaluate_license, "License", SignalWeight.GATE),
    SignalDef(evaluate_pr_merge_rate, "External PR merge rate", SignalWeight.HIGH),
    SignalDef(evaluate_ghost_closing, "Ghost-closing rate", SignalWeight.HIGH),
    SignalDef(evaluate_time_to_response, "Time-to-first-response", SignalWeight.MEDIUM),
    SignalDef(evaluate_contributing_exists, "CONTRIBUTING.md", SignalWeight.LOW),
    SignalDef(evaluate_contributing_content, "Contribution process", SignalWeight.MEDIUM),
    SignalDef(evaluate_ai_policy, "AI policy", SignalWeight.MEDIUM),
    SignalDef(evaluate_label_hygiene, "Issue label hygiene", SignalWeight.LOW),
    SignalDef(evaluate_staleness, "Staleness", SignalWeight.MEDIUM),
]
