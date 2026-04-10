# Design: Discover Auto-Fallback

## Problem

`discover` requires repos to have open issues labeled "good first issue" or
"help wanted". Mature projects that use custom label taxonomies get silently
pruned. The recently shipped `--any-issues` escape hatch (949a820) makes the
gate visible and bypassable, but users must know about the flag to use it.

Auto-fallback closes the loop: when the label-gated search returns sparse
results, automatically run a second ungated search and show the extra repos
in a separate table. Users see canonical projects (Pi-hole, Kubernetes)
without knowing about `--any-issues` or understanding why they were missing.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Trigger | Auto for interactive, opt-in for JSON | Humans benefit from richer results; JSON consumers need predictable API cost |
| Presentation | Two separate tables | Clear separation between label-gated (friendliness-proven) and ungated (broader) pools |
| Assessment | Full assessment for fallback repos | Without tier colors the second table is just a list — not actionable |
| Fallback limit | Fill up to --limit total | Gated returns 3 + limit is 10 = up to 7 fallback repos. User always gets --limit total |
| Numbering | Continuous across both tables | "Pick repo #6" is unambiguous regardless of which table it came from |
| Approach | Single discover_repos call | Keeps orchestration, caching, and rate budget in one place |

## Data Model

`DiscoverSummary` gains one field:

```python
fallback_results: list[DiscoverResult] = field(default_factory=list)
"""Repos from the ungated fallback search, deduplicated against gated results."""
```

- Empty by default (no fallback ran).
- Deduplicated **against the primary pool**: if a repo appears in both the
  gated and ungated searches, it stays in the primary `results` table and is
  removed from `fallback_results`. The primary table is never modified by the
  fallback — deduplication only removes from the fallback side.
- Same `DiscoverResult` type as the primary pool.
- `slice_results()` carries `fallback_results` forward.

## Search Pipeline

After the existing gated search + assessment (Steps 1-12 in `discover_repos`),
a new **Step 13: Auto-fallback** fires when ALL conditions hold:

1. `label_gate_active is True` (user didn't pass `--any-issues`)
2. `len(results) < min(limit, 5)` (sparse threshold, same as the hint)
3. `auto_fallback is True` (CLI resolves the tri-state default)

### Fallback steps

```
Step 13a: Build ungated query (_build_query with label_filter=None)
Step 13b: Run search (search_repos — separate cache key via query hash)
Step 13c: Deduplicate — remove from the fallback pool any repo whose
          full_name already appears in the primary `results` list.
          Primary results are never modified.
Step 13d: Rank the fallback pool (rank_repos — no GFI/HW bonuses apply)
Step 13e: Take up to (limit - len(results)) repos
Step 13f: Assess each (same batch loop, same rate budget check)
Step 13g: Populate summary.fallback_results
```

### Rate budget

Fallback assessment shares the rate budget with primary assessment. If
budget was exhausted during gated assessment, fallback repos get
`skip_reason = "Skipped — rate limit too low for assessment"`.

### Caching

The fallback search gets its own discover cache entry (different query
hash since the query string differs from the gated queries). Independent
of the gated cache.

## CLI Interface

### New flag

```python
@click.option("--auto-fallback/--no-auto-fallback", default=None,
              help="Auto-search without label gate when results are sparse.")
```

Tri-state resolution in the CLI layer:

| `--auto-fallback` | `--json` | Effective value |
|--------------------|----------|-----------------|
| not specified | no | `True` (auto for terminal) |
| not specified | yes | `False` (predictable for JSON) |
| `--auto-fallback` | either | `True` (explicit opt-in) |
| `--no-auto-fallback` | either | `False` (explicit opt-out) |

### Threading

`auto_fallback` threads through `discover_repos` and the interactive loop
re-call (same pattern as `any_issues` and `verbose`).

## Output

### Terminal (`print_discover`)

When `summary.fallback_results` is non-empty, after the primary table and
the "Use give-back triage" line, render:

```
  Also found (no "good first issue" / "help wanted" labels):

  ┌─────┬──────────────────────────┬────────┬──────────┬────────┬─────────────────────┐
  │   5 │ pi-hole/pi-hole          │ 56.5k  │  GREEN   │    312 │ A black hole for... │
  │   6 │ pi-hole/docker-pi-hole   │ 10.9k  │  GREEN   │     88 │ Pi-hole in Docker   │
  └─────┴──────────────────────────┴────────┴──────────┴────────┴─────────────────────┘
```

- Same table format as the primary table (reuse rendering logic).
- Numbering continues from the primary table (repo #5 if primary had 4).
- Subordinate one-line header: `Also found (no "good first issue" / "help wanted" labels):`
  Not a full stats repeat. No "Assessed N (M from cache)" — just the label.

### Sparse hint interaction

- When fallback fires and returns results → hint is suppressed (the table
  IS the hint, in more useful form).
- When fallback fires but returns 0 repos → hint fires as before.
- When fallback doesn't fire (not sparse, or `--no-auto-fallback`) → hint
  fires as before when sparse.

### JSON (`print_discover_json`)

Three states, distinguishable by JSON consumers:

| State | `fallback_triggered` | `fallback_results` |
|-------|---------------------|--------------------|
| Fallback didn't run (not sparse, or opt-out) | field absent | field absent |
| Fallback ran, found repos | `true` | `[...items...]` |
| Fallback ran, found nothing | `true` | `[]` |

Example (fallback ran and found repos):
```json
{
  "fallback_triggered": true,
  "fallback_results": [ ... same schema as results ... ]
}
```

This lets JSON consumers distinguish "fallback didn't run" (fields absent)
from "fallback ran but found nothing" (`fallback_triggered: true` with an
empty array). Existing JSON shape is unchanged when fallback doesn't fire.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| `--any-issues` + auto-fallback | No fallback — gate is already off. `auto_fallback` param ignored. |
| Gated returns 0, fallback returns 0 | Both tables empty. Sparse hint fires. |
| Gated returns 8, limit is 10 | 8 >= min(10, 5), fallback does NOT fire. |
| Gated returns 3, limit is 10 | 3 < 5, fallback fires. Up to 7 fallback repos. |
| Rate limit exhausted during gated | Fallback still fires (sparse check uses result count). Fallback repos may also get `skip_reason`. |
| `--interactive` with fallback | See "Interactive loop with fallback" below. |

### Interactive loop with fallback

The interactive loop calls `discover_repos` repeatedly with increasing limits.
Each call is a fresh pipeline execution (gated search → assessment → optional
fallback). Concretely:

1. **First batch** (limit=10): Gated returns 3 repos. 3 < min(10, 5), so
   fallback fires and fills up to 7 more. User sees two tables (3 + 7).

2. **"Show more"** (limit=20): `discover_repos` runs again with limit=20.
   The gated search re-runs (may return the same 3, or the GitHub API may
   paginate differently). The pipeline re-evaluates sparsity at the new limit:
   if gated still returns < min(20, 5) = 5, fallback fires again with a
   budget of 20 - len(gated). The `slice_results` method then extracts only
   the new repos (offset past what was already shown).

3. **Key behavior:** The gated query is always re-run first. The fallback
   query is only re-run if the gated result count is still sparse at the new
   limit. If the gated search returns enough results at the higher limit
   (unlikely but possible if GitHub's ranking shifted), no fallback occurs
   on the subsequent batch.

4. **Both pools paginate through the same `slice_results` mechanism.** The
   interactive loop tracks `shown_count` as `len(results) + len(fallback_results)`
   and slices both lists. `slice_results` already carries `fallback_results`.

## Files Changed

| File | Change |
|------|--------|
| `src/give_back/discover/search.py` | `DiscoverSummary.fallback_results`, Step 13 fallback pipeline, `auto_fallback` param, `slice_results` update |
| `src/give_back/cli/discover.py` | `--auto-fallback/--no-auto-fallback` flag, tri-state resolution, thread through interactive loop |
| `src/give_back/output/discover.py` | Second table rendering, continuous numbering, hint suppression logic, JSON fallback fields |
| `src/give_back/discover/rank.py` | No changes (rank_repos already handles repos without GFI/HW markers) |
| `README.md` | Document auto-fallback behavior in discover section |
| `CLAUDE.md` | Add example: `discover --no-auto-fallback` |
| `src/give_back/skill/SKILL.md` | Update discover guidance for auto-fallback behavior |
| `tests/discover/test_search.py` | Fallback trigger conditions, deduplication, fill-to-limit, rate budget sharing |
| `tests/discover/test_output.py` | Two-table rendering, continuous numbering, hint suppression, JSON conditional fields |

## Not In Scope

- **Custom-label detection** — detecting non-stock labels like `Hacktoberfest`.
  Tracked in TODOS.md as a separate initiative.
- **Fallback ranking changes** — the existing `rank_repos` handles ungated
  repos fine (GFI/HW bonuses just don't apply). No special ranking needed.
- **Fallback-specific caching** — the ungated search uses the same caching
  mechanism as any other discover search. No new cache infrastructure.
