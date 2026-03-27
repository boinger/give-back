"""Viability signal registry.

Each signal is a pure function (RepoData) -> SignalResult, wrapped in a SignalDef
NamedTuple that bundles the function with its display name and weight.

ALL_SIGNALS is populated as signal modules are implemented.
"""

from give_back.models import SignalDef

# 9 signals total (contributing.py exports two: existence + content)
# Populated incrementally as signal modules are implemented in Steps 3-5.
ALL_SIGNALS: list[SignalDef] = []
