"""Tests for deps/filter.py dependency filtering."""

from unittest.mock import MagicMock

from give_back.deps.filter import filter_candidates


class TestFiltersUnresolved:
    def test_unresolved_entries_removed(self):
        candidates = [
            ("click", "pallets/click"),
            ("mystery-pkg", None),
            ("another-missing", None),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [])
        assert stats["unresolved"] == 2
        slugs = [slug for _, slug in filtered]
        assert "pallets/click" in slugs
        assert len(filtered) == 1


class TestFiltersPythonStdlib:
    def test_python_stdlib_removed(self):
        candidates = [
            ("os", "python/cpython"),
            ("sys", "python/cpython"),
            ("json", "python/cpython"),
            ("click", "pallets/click"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [])
        assert stats["stdlib"] == 3
        assert len(filtered) == 1
        assert filtered[0] == ("click", "pallets/click")


class TestFiltersGoStdlib:
    def test_go_stdlib_removed(self):
        candidates = [
            ("fmt", "golang/fmt"),
            ("net", "golang/net"),
            ("http", "golang/http"),
            ("github.com/gorilla/mux", "gorilla/mux"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [])
        assert stats["stdlib"] == 3
        assert len(filtered) == 1
        assert filtered[0] == ("github.com/gorilla/mux", "gorilla/mux")


class TestFiltersSameOrg:
    def test_same_org_removed(self):
        candidates = [
            ("flask", "pallets/flask"),
            ("jinja2", "pallets/jinja"),
            ("click", "pallets/click"),
            ("httpx", "encode/httpx"),
        ]
        filtered, stats = filter_candidates(candidates, "pallets", [])
        assert stats["same_org"] == 3
        assert len(filtered) == 1
        assert filtered[0] == ("httpx", "encode/httpx")


class TestFiltersSkipList:
    def test_skip_list_entries_removed(self):
        candidates = [
            ("httpx", "encode/httpx"),
            ("rich", "Textualize/rich"),
            ("click", "pallets/click"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", ["encode/httpx"])
        assert stats["skip_list"] == 1
        assert len(filtered) == 2
        slugs = [slug for _, slug in filtered]
        assert "encode/httpx" not in slugs


class TestCaseInsensitive:
    def test_owner_comparison_case_insensitive(self):
        candidates = [
            ("flask", "Pallets/flask"),
        ]
        filtered, stats = filter_candidates(candidates, "pallets", [])
        assert stats["same_org"] == 1
        assert len(filtered) == 0

    def test_skip_list_case_insensitive(self):
        candidates = [
            ("httpx", "Encode/Httpx"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", ["encode/httpx"])
        assert stats["skip_list"] == 1
        assert len(filtered) == 0


class TestPassesNormalDeps:
    def test_valid_deps_pass_through(self):
        candidates = [
            ("httpx", "encode/httpx"),
            ("rich", "Textualize/rich"),
            ("click", "pallets/click"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [])
        assert len(filtered) == 3
        assert stats["passed"] == 3
        assert stats["unresolved"] == 0
        assert stats["stdlib"] == 0
        assert stats["same_org"] == 0
        assert stats["skip_list"] == 0


class TestFilterStatsCounts:
    def test_stats_dict_has_correct_counts(self):
        candidates = [
            ("os", "python/cpython"),  # stdlib
            ("mystery", None),  # unresolved
            ("flask", "pallets/flask"),  # same-org
            ("httpx", "encode/httpx"),  # skip list
            ("rich", "Textualize/rich"),  # passes
            ("click", "other/click"),  # passes
        ]
        filtered, stats = filter_candidates(candidates, "pallets", ["encode/httpx"])
        assert stats["unresolved"] == 1
        assert stats["stdlib"] == 1
        assert stats["same_org"] == 1
        assert stats["skip_list"] == 1
        assert stats["archived"] == 0
        assert stats["passed"] == 2
        assert isinstance(stats["mega_projects"], list)


class TestMegaProjectFlaggedNotRemoved:
    def test_known_mega_project_flagged_but_kept(self):
        candidates = [
            ("protobuf", "google/protobuf"),
            ("httpx", "encode/httpx"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [])
        assert "google/protobuf" in stats["mega_projects"]
        # Mega-projects are NOT removed
        slugs = [slug for _, slug in filtered]
        assert "google/protobuf" in slugs
        assert stats["passed"] == 2

    def test_dynamic_mega_project_via_client(self):
        """A repo with >50k stars is flagged as mega but not removed."""
        mock_client = MagicMock()
        mock_client.rest_get.return_value = {
            "archived": False,
            "stargazers_count": 80_000,
        }
        candidates = [
            ("some-popular", "popular/repo"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [], client=mock_client)
        assert "popular/repo" in stats["mega_projects"]
        assert len(filtered) == 1

    def test_archived_repo_removed_via_client(self):
        """Archived repos are removed when client is provided."""
        mock_client = MagicMock()
        mock_client.rest_get.return_value = {
            "archived": True,
            "stargazers_count": 100,
        }
        candidates = [
            ("old-lib", "someone/old-lib"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [], client=mock_client)
        assert stats["archived"] == 1
        assert len(filtered) == 0

    def test_client_error_keeps_candidate(self):
        """If the API call fails, the candidate is kept."""
        mock_client = MagicMock()
        mock_client.rest_get.side_effect = Exception("network error")
        candidates = [
            ("some-lib", "someone/some-lib"),
        ]
        filtered, stats = filter_candidates(candidates, "myorg", [], client=mock_client)
        assert len(filtered) == 1
