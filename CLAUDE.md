# give-back Development Guidelines

## Quick Reference

- **Tech Stack:** Python 3.13+, Click, httpx, rich
- **Linter/Formatter:** ruff (line-length: 120, rules: E, F, I)
- **Tests:** pytest + respx (httpx mock library)
- **Package Manager:** uv

## Architecture

give-back evaluates open-source repos for contribution viability using GitHub API signals.

```
CLI (cli.py)
  ├── auth.py ──► GITHUB_TOKEN / gh CLI / unauthenticated
  ├── github_client.py ──► httpx ──► GitHub API (GraphQL + REST)
  ├── signals/ (9 pure functions, each returns SignalResult)
  │     └── all consume RepoData, registered via SignalDef NamedTuple
  ├── scoring.py ──► signal results ──► Tier (GREEN/YELLOW/RED)
  ├── state.py ──► ~/.give-back/state.json (assessment cache)
  └── output.py ──► rich (table + summary)
```

**Data flow:** 4 API calls populate RepoData → 9 signals evaluate independently →
scoring computes weighted tier → output formats for terminal or JSON.

**Signal architecture:** Pure functions `(RepoData) -> SignalResult`. No ABC — each
signal is wrapped in `SignalDef(func, name, weight)` NamedTuple. Registry is an explicit
list in `signals/__init__.py`.

## Hard Rules

- **No catch-all exceptions.** Every handler names the specific exception it catches.
  All custom exceptions inherit from `GiveBackError` in `exceptions.py`.
- **Signals are pure.** They receive `RepoData` and return `SignalResult`. No API calls,
  no side effects, no global state.
- **Atomic state writes.** `state.py` writes to a temp file then renames to prevent
  corruption from Ctrl+C.

## Commands

```bash
make pre-commit    # format + lint + test
make test          # run tests
make lint          # run ruff
make run ARGS='assess pallets/flask'  # run CLI
```

## Key Files

| File | Purpose |
|------|---------|
| `src/give_back/models.py` | Tier, SignalWeight, SignalDef, SignalResult, RepoData, Assessment |
| `src/give_back/exceptions.py` | Named exception hierarchy |
| `src/give_back/signals/__init__.py` | ALL_SIGNALS registry |
| `src/give_back/scoring.py` | Weighted tier computation |
| `src/give_back/github_client.py` | httpx wrapper for GitHub API |
| `src/give_back/graphql/queries.py` | GraphQL query strings |
