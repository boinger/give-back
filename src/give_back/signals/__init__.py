"""Viability signal registry.

Each signal is a pure function (RepoData) -> SignalResult, wrapped in a SignalDef
NamedTuple that bundles the function with its display name and weight.
"""

from give_back.models import SignalDef, SignalWeight
from give_back.signals.license_gate import evaluate_license

# 9 signals total (contributing.py exports two: existence + content)
# Remaining signals added in Steps 4-5.
ALL_SIGNALS: list[SignalDef] = [
    SignalDef(evaluate_license, "License", SignalWeight.GATE),
]
