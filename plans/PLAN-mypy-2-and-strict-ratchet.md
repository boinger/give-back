# PLAN: mypy 1.20.2 → 2.0.0 + strict-mode ratchet

Source of truth for the coordinated mypy major bump and the strict-mode
ratchet. Five PRs total, one concern per PR (per CONTRIBUTING.md). Each
step has independent rollback. Full design context lives in
`~/.claude/plans/encapsulated-stargazing-graham.md` (eng-cleared
2026-05-06).

## Sequence

- [ ] **Step 0** — Bump `mypy` 1.20.2 → 2.0.0 in isolation (no strict
      flag changes). PR title: `chore(deps): bump mypy 1.20.2 -> 2.0.0`.
- [ ] **Step 1** — Enable `disallow_untyped_defs`. Fixes 5
      `[no-untyped-def]` errors in `assess.py`, `exceptions.py`,
      `calibrate.py`.
- [ ] **Step 2a** — Enable `disallow_any_generics`. First wave of
      `[type-arg]` fixes: `state.py`, `guardrails.py`, `audit.py`.
- [ ] **Step 2b/c** — Remaining `[type-arg]` fixes (split only if
      single-PR diff exceeds ~250 lines).
- [ ] **Step 3** — Enable `warn_return_any`. Fixes 11 `[no-any-return]`.
- [ ] **Step 4** — Probe with `uv run mypy src/ --strict`; fix any new
      error codes that surface; replace the four flags with
      `strict = true`. Remove the strict-ratchet item from `TODOS.md`
      and update the `[tool.mypy]` comment block.

## Per-step verification (every step)

`make ci` does NOT run mypy or sloppylint locally — both are
GitHub-Actions-only by default. Each step must invoke them explicitly:

```bash
make ci
uv run mypy src/
uv run --with sloppylint sloppylint --max-score 151 src/
```

Step 0 additionally:

```bash
uv export --no-hashes --no-emit-project -o /tmp/give-back-post-mypy2.txt
pip-audit --no-deps --disable-pip -r /tmp/give-back-post-mypy2.txt
```

## Rollback (any step)

```bash
git checkout pyproject.toml uv.lock   # Step 0 only
git revert <sha>                      # Steps 1-4
uv sync --all-groups
```

## What changes in mypy 2.0.0 (relevant to give-back)

- `--local-partial-types` now ON by default
- `--strict-bytes` now ON by default (PEP 688 alignment)
- Class-var `None` type comments removed (soundness fix; 0 instances in
  give-back)

## Out of scope (preserved for follow-up)

- Bumping runtime deps (`click`, `httpx`, `rich`) — all current.
- Type-checking `tests/` — separate decision.
- Direct transitive bumps — `librt`, `pathspec` resolve naturally with
  the mypy bump.
- `make ci` consolidation + Python-version matrix widening — added to
  `TODOS.md` as follow-ups; depend on this ratchet landing first.
