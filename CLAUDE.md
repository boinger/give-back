# give-back Development Guidelines

## Quick Reference

- **Tech Stack:** Python 3.11+, Click, httpx, rich
- **Linter/Formatter:** ruff (line-length: 120, rules: E, F, I)
- **Tests:** pytest + respx (httpx mock library)
- **Package Manager:** uv

## Architecture

give-back evaluates open-source repos for contribution viability using GitHub API signals.

```
CLI (cli.py)
  ├── assess ──► cache check → (hit: display cached) or (miss: auth → assess.py → output)
  │     ├── assess.py ──► fetch_repo_data (4 API calls) → evaluate_signals → scoring
  │     ├── signals/ (9 pure functions, each returns SignalResult)
  │     ├── scoring.py ──► signal results ──► Tier (GREEN/YELLOW/RED)
  │     └── state.py ──► ~/.give-back/state.json (assessment cache + reconstruct)
  ├── triage ──► fetch issues → check competition → rank → output
  │     ├── triage/fetch.py ──► REST issues API → filter + score
  │     ├── triage/compete.py ──► search for linked PRs + claim comments
  │     └── triage/rank.py ──► multi-level sort by friendliness
  ├── sniff ──► identify files → fetch content → heuristic assessment
  │     ├── sniff/files.py ──► extract file paths from issue body
  │     └── sniff/assess.py ──► file size, tests, churn, nesting → verdict
  ├── discover ──► search GitHub → rank → batch-assess → display
  │     ├── discover/search.py ──► GitHub search API → assess pipeline
  │     └── discover/rank.py ──► light ranking by search metadata
  ├── submit ──► read brief → push branch → create PR via gh
  │     └── submit.py ──► context.json + brief → git push → gh pr create
  ├── status ──► scan workspaces → refresh PR state → display
  │     └── status.py ──► context.json files + GitHub API → contribution list
  ├── audit ──► community profile + templates + labels + signals → checklist
  │     ├── audit.py ──► fetch_repo_data → health checks + evaluate_signals → report
  │     ├── audit_fix/ ──► --fix: interactive walkthrough → generate files + create labels
  │     └── audit_mine.py ──► --mine: batch-audit user's repos → ranked table
  ├── prepare/lifecycle.py ──► workspace state machine (working → pr_open → merged)
  ├── auth.py ──► GITHUB_TOKEN / gh CLI / unauthenticated
  ├── github_client.py ──► httpx ──► GitHub API (GraphQL + REST)
  └── output/ ──► rich (tables + summaries + JSON, split by command group)
```

**Phase 1 (assess):** Cache check first. On hit: reconstruct Assessment from cached JSON,
display, skip API calls. On miss: 4 API calls populate RepoData → 9 signals evaluate
independently → scoring computes weighted tier → cache result → output for terminal or JSON.

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
make run ARGS='conventions pallets/flask'  # scan contribution conventions
make run ARGS='conventions pallets/flask --issue 5432'  # with issue context
make run ARGS='prepare pallets/flask --issue 5432'  # fork + clone + branch + brief
make run ARGS='check'                     # run pre-flight guardrails in workspace
make run ARGS='skip google/protobuf'      # add to skip list
make run ARGS='unskip google/protobuf'    # remove from skip list
make run ARGS='discover --language python' # find repos to contribute to
make run ARGS='submit'                    # create PR from workspace
make run ARGS='status'                    # check contribution status
make run ARGS='audit pallets/flask'       # maintainer self-assessment checklist
make run ARGS='audit pallets/flask --fix' # interactively fix failing checks
make run ARGS='audit pallets/flask --fix --template-repo myorg/standards'  # custom templates from repo
make run ARGS='audit pallets/flask --fix --template-dir ./templates'       # custom templates from local dir
make run ARGS='audit --mine'              # batch-audit your repos (top 20 by activity)
make run ARGS='audit --mine --limit 10'   # audit top 10 repos
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
| `src/give_back/discover/search.py` | Repo discovery via GitHub search |
| `src/give_back/discover/rank.py` | Light ranking by search metadata |
| `src/give_back/submit.py` | PR creation from workspace context |
| `src/give_back/status.py` | Contribution tracking across repos |
| `src/give_back/audit.py` | Maintainer self-assessment checklist |
| `src/give_back/audit_fix/fix.py` | --fix orchestrator: resolve repo, walk fixes, summary |
| `src/give_back/audit_fix/templates.py` | Template content + write_if_missing utility |
| `src/give_back/audit_fix/license.py` | License quick-pick (GitHub Licenses API) |
| `src/give_back/audit_fix/contributing.py` | CONTRIBUTING.md section wizard |
| `src/give_back/audit_fix/labels.py` | Label creation via REST API |
| `src/give_back/audit_fix/resolver.py` | Template resolver (built-in / local dir / remote repo) |
| `src/give_back/audit_mine.py` | Batch audit across user's repos (--mine) |
