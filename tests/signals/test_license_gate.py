"""Tests for the license gate signal."""

from give_back.models import RepoData, Tier
from give_back.signals.license_gate import evaluate_license


def _make_repo_data(license_info: dict | None) -> RepoData:
    return RepoData(
        owner="test",
        repo="repo",
        graphql={"repository": {"licenseInfo": license_info}},
        community={},
        contributing_text=None,
        search={},
    )


class TestLicenseGate:
    def test_mit_passes(self):
        data = _make_repo_data({"spdxId": "MIT", "name": "MIT License", "key": "mit"})
        result = evaluate_license(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN
        assert "MIT" in result.summary

    def test_apache_passes(self):
        data = _make_repo_data({"spdxId": "Apache-2.0", "name": "Apache License 2.0", "key": "apache-2.0"})
        result = evaluate_license(data)
        assert result.score == 1.0

    def test_gpl3_passes(self):
        data = _make_repo_data({"spdxId": "GPL-3.0", "name": "GNU General Public License v3.0", "key": "gpl-3.0"})
        result = evaluate_license(data)
        assert result.score == 1.0

    def test_no_license_fails(self):
        data = _make_repo_data(None)
        result = evaluate_license(data)
        assert result.score == -1.0
        assert result.tier == Tier.RED
        assert "No license" in result.summary

    def test_sspl_fails(self):
        data = _make_repo_data({"spdxId": "SSPL-1.0", "name": "Server Side Public License v1", "key": "sspl-1.0"})
        result = evaluate_license(data)
        assert result.score == -1.0
        assert result.tier == Tier.RED
        assert "Server Side Public License" in result.summary

    def test_busl_fails(self):
        data = _make_repo_data({"spdxId": "BUSL-1.1", "name": "Business Source License 1.1", "key": "busl-1.1"})
        result = evaluate_license(data)
        assert result.score == -1.0
        assert result.tier == Tier.RED

    def test_noassertion_needs_human_review(self):
        data = _make_repo_data({"spdxId": "NOASSERTION", "name": "Other", "key": "other"})
        result = evaluate_license(data)
        assert result.score == 1.0  # Gate passes — has a license, just unrecognized
        assert result.tier == Tier.YELLOW
        assert "verify at" in result.summary
        assert result.details["needs_human"] is True

    def test_unknown_license_passes(self):
        """A license with a valid spdxId that's not in our known lists should still pass."""
        data = _make_repo_data({"spdxId": "WTFPL", "name": "WTFPL", "key": "wtfpl"})
        result = evaluate_license(data)
        assert result.score == 1.0
        assert result.tier == Tier.GREEN

    def test_empty_graphql_response(self):
        """Handle malformed graphql response gracefully."""
        data = RepoData(
            owner="test",
            repo="repo",
            graphql={},
            community={},
            contributing_text=None,
            search={},
        )
        result = evaluate_license(data)
        assert result.score == -1.0
