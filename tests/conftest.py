"""Shared test fixtures and helpers."""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_graphql_fixture(name: str) -> dict:
    """Load a GraphQL response fixture by name (without .json extension)."""
    path = FIXTURES_DIR / "graphql" / f"{name}.json"
    return json.loads(path.read_text())
