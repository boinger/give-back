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
  ├── assess ──► auth → github_client → signals → scoring → output
  │     ├── signals/ (9 pure functions, each returns SignalResult)
  │     ├── scoring.py ──► signal results ──► Tier (GREEN/YELLOW/RED)
  │     └── state.py ──► ~/.give-back/state.json (assessment cache)
  ├── triage ──► fetch issues → check competition → rank → output
  │     ├── triage/fetch.py ──► REST issues API → filter + score
  │     ├── triage/compete.py ──► search for linked PRs + claim comments
  │     └── triage/rank.py ──► multi-level sort by friendliness
  ├── sniff ──► identify files → fetch content → heuristic assessment
  │     ├── sniff/files.py ──► extract file paths from issue body
  │     └── sniff/assess.py ──► file size, tests, churn, nesting → verdict
  ├── auth.py ──► GITHUB_TOKEN / gh CLI / unauthenticated
  ├── github_client.py ──► httpx ──► GitHub API (GraphQL + REST)
  └── output.py ──► rich (tables + summaries + JSON)
```

**Phase 1 (assess):** 4 API calls populate RepoData → 9 signals evaluate independently →
scoring computes weighted tier → output formats for terminal or JSON.

**Phase 2 (triage + sniff):** Fetch open issues → filter by labels/activity/clarity →
check for competing PRs and claim comments → rank by friendliness. Sniff inspects
referenced source files for code quality heuristics.

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
make run ARGS='assess pallets/flask'       # viability gate
make run ARGS='assess pallets/flask --deps'  # viability + dep walk
make run ARGS='deps traefik/traefik'      # walk deps only
make run ARGS='triage pallets/flask'      # find starter issues
make run ARGS='sniff pallets/flask 123'   # inspect issue code quality
make run ARGS='skip google/protobuf'      # add to skip list
make run ARGS='unskip google/protobuf'    # remove from skip list
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
| `src/give_back/triage/fetch.py` | Issue fetching + filtering |
| `src/give_back/triage/compete.py` | Competing work detection |
| `src/give_back/triage/rank.py` | Candidate ranking |
| `src/give_back/sniff/files.py` | File path extraction + content fetch |
| `src/give_back/sniff/assess.py` | Heuristic code quality assessment |
