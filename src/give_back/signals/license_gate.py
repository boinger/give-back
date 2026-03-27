"""GATE signal: OSS license check.

Verifies the repository has a recognized open-source license.
Flags problematic licenses (SSPL, BSL) that technically restrict use.
Missing license is a gate failure.
"""

from __future__ import annotations

from give_back.models import RepoData, SignalResult, SignalWeight, Tier

# Licenses that are technically "source available" but have restrictions
# that make contribution complicated or risky
PROBLEMATIC_LICENSES = {
    "sspl-1.0": "Server Side Public License — restricts service use",
    "busl-1.1": "Business Source License — time-delayed open source",
}

# Well-known OSS license identifiers (SPDX)
# Not exhaustive — anything not in PROBLEMATIC_LICENSES and not None is treated as OSS
COMMON_OSS_LICENSES = {
    "mit",
    "apache-2.0",
    "gpl-2.0",
    "gpl-3.0",
    "lgpl-2.1",
    "lgpl-3.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "mpl-2.0",
    "isc",
    "unlicense",
    "0bsd",
    "artistic-2.0",
    "bsl-1.0",  # Boost, not Business Source License
    "cc0-1.0",
    "ecl-2.0",
    "epl-2.0",
    "eupl-1.2",
    "agpl-3.0",
    "zlib",
    "postgresql",
}

NAME = "License"
WEIGHT = SignalWeight.GATE


def evaluate_license(data: RepoData) -> SignalResult:
    """Check for a recognized open-source license.

    Gate signal: returns score -1.0 (fail) or 1.0 (pass).
    """
    license_info = data.graphql.get("repository", {}).get("licenseInfo")

    # No license at all
    if license_info is None:
        return SignalResult(
            score=-1.0,
            tier=Tier.RED,
            summary="No license found",
            details={"license": None},
        )

    spdx_id = (license_info.get("spdxId") or "").lower()
    license_name = license_info.get("name", "Unknown")
    license_key = (license_info.get("key") or "").lower()

    # GitHub sometimes returns "NOASSERTION" for unrecognized licenses.
    # This is NOT a gate fail — the repo HAS a license, we just can't classify it.
    # Pass the gate but flag for human review. Include the repo URL for the license
    # file so the user can check it directly.
    if spdx_id in ("noassertion", "") and license_key in ("other", ""):
        license_url = f"https://github.com/{data.owner}/{data.repo}/blob/HEAD/LICENSE"
        return SignalResult(
            score=1.0,
            tier=Tier.YELLOW,
            summary=f"Unrecognized license ({license_name}) — verify at {license_url}",
            details={
                "license": license_name,
                "spdx_id": spdx_id,
                "needs_human": True,
                "license_url": license_url,
            },
        )

    # Check for problematic "source available" licenses
    if spdx_id in PROBLEMATIC_LICENSES or license_key in PROBLEMATIC_LICENSES:
        reason = PROBLEMATIC_LICENSES.get(spdx_id) or PROBLEMATIC_LICENSES.get(license_key, "Restricted license")
        return SignalResult(
            score=-1.0,
            tier=Tier.RED,
            summary=f"{license_name} — {reason}",
            details={"license": license_name, "spdx_id": spdx_id, "reason": reason},
        )

    # Known OSS or anything else not flagged — pass
    return SignalResult(
        score=1.0,
        tier=Tier.GREEN,
        summary=license_name,
        details={"license": license_name, "spdx_id": spdx_id},
    )
