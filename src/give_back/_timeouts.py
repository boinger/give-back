"""Shared subprocess timeout constants.

Network-touching subprocess calls (git fetch/pull/push/clone, gh repo fork,
gh pr create) all share the same failure mode: on a slow network (airport
WiFi, tether, constrained corporate proxy), a too-tight timeout produces a
spurious fatal error with no retry. Centralizing the value here prevents
future sites from drifting back to a tighter literal and makes the tradeoff
visible in one place.
"""

# Seconds to allow for git/gh subprocess calls that hit the network.
# Matches first-push or first-clone of a large branch on a slow uplink;
# still bounded so a genuinely stuck operation can't block forever.
NETWORK_SUBPROCESS_TIMEOUT = 300
