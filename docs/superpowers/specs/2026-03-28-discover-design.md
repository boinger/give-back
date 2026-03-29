# Design: `give-back discover` Command

**Date**: 2026-03-28
**Status**: Approved
**Supersedes**: None

## Problem

New open-source contributors don't know where to start. They need to find repos
that are viable for outside contributions, but browsing GitHub manually doesn't
surface viability signals (merge rate, responsiveness, ghost-closing). give-back
already evaluates repos you know about. `discover` finds repos you don't.

## Target User

Both new and experienced contributors. Defaults optimize for new contributors
(friendly, guided). `--verbose` shows full signal breakdown for experienced users.

## Approach: Funnel + Cache

Search GitHub, light-rank by metadata, check assessment cache for known repos,
assess up to `--limit` repos (default 10), display results with viability tier.
Non-interactive by default (composable in pipelines). `--interactive` adds the
"assess more?" loop for exploratory sessions.

## CLI Flags

```
give-back discover --language python          # required: at least --language or --topic
give-back discover --topic kubernetes --language go  # AND: both filters applied
give-back discover --language rust --min-stars 200   # default: 50
give-back discover --language python --limit 10      # assess up to 10 repos (default 10)
give-back discover --language python --batch-size 3  # assess 3 at a time (default 5)
give-back discover --language python --interactive   # "assess more?" loop after each batch
give-back discover --language python --json          # full JSON output, no interactive
give-back discover --language python --no-cache      # skip all caches
give-back discover --language python --verbose        # full signal breakdown per repo
```

## Search Pipeline

```
give-back discover --language python --min-stars 100

  1. Build two search queries:
     Base: archived:false pushed:>90d-ago sort:stars
     If --language: append language:python
     If --topic: append topic:kubernetes
     If both: AND them (language:go topic:kubernetes)
     Q1: base + good-first-issues:>0 + stars:>min_stars
     Q2: base + help-wanted-issues:>0 + stars:>min_stars
         (only if Q1 returns fewer than --limit results)

  2. Fetch via /search/repositories (new method on GitHubClient)
     - per_page=30
     - Deduplicate Q1 and Q2 results by full_name

  3. Light-rank by search metadata:
     - good_first_issue_count (highest weight)
     - days since last push (fewer = better)
     - has description (boolean)
     - open_issues > 0 (boolean)

  4. Check assessment cache:
     - For each repo: get_cached_assessment(owner, repo)
     - Cache hit: attach tier, mark from_cache=True
     - Cache miss: add to assess queue

  5. Assess unknowns up to --limit (default 10):
     - Assess in batches of --batch-size (default 5, named constant)
     - run_assessment() for each (reuse existing pipeline)
     - Cache results via save_assessment()
     - Progress bar via rich
     - --limit controls total repos assessed (not total searched)

  6. Display results table (stable order, see Ranking section)

  7. If --interactive: prompt "Assess next batch? [Y/n/done]"
     - Only in terminal (stdin.isatty())
     - Repeats steps 5-7 for the next --batch-size unknowns
     - Without --interactive: assess up to --limit and exit
```

## GitHub Client Change

New method `search_repos()` on GitHubClient. Same pattern as existing `search()`
but hits `/search/repositories` instead of `/search/issues`. Uses the same
search rate limit tracking (30 req/min).

Parameters: `query: str, per_page: int = 30, sort: str = "stars"`
Returns: parsed JSON (same as `search()`).

## Output Format

### Terminal (default)

```
  Searching for Python repos with contribution opportunities...
  Found 47 repos. Assessing top 5...

  #  Repository            Stars  Tier    GFI  Response  Description
  1  pallets/flask         68.2k  GREEN    12     4h     Web microframework
  2  psf/requests          52.1k  GREEN     8     6h     HTTP for Humans
  3  encode/httpx          13.4k  YELLOW    3    18h     Async HTTP client
  4  tiangolo/fastapi      78.3k  YELLOW   15    72h     Modern web API
  5  psf/black             39.1k  GREEN     5     2h     Code formatter

  Use `give-back triage <repo>` to find starter issues.

  (with --interactive: "42 more repos available. Assess next batch? [Y/n/done]")
```

### --verbose

Adds: merge rate %, ghost-closing %, full signal tier per repo.

### --json

Outputs full list as JSON. Assesses all repos up to `--limit` in one pass.
No interactive prompt (even with `--interactive`).

```json
{
  "query": "language:python stars:>100 ...",
  "total_searched": 47,
  "assessed_count": 5,
  "cache_hits": 2,
  "results": [
    {
      "owner": "pallets",
      "repo": "flask",
      "description": "Web microframework",
      "stars": 68200,
      "language": "Python",
      "topics": ["web", "flask"],
      "open_issue_count": 45,
      "good_first_issue_count": 12,
      "tier": "green",
      "from_cache": false,
      "skip_reason": null
    }
  ]
}
```

## Caching

### Assessment cache (existing)

Reuse `get_cached_assessment()` and `save_assessment()` from state.py. Each
batch-assessed repo gets cached with 24h TTL, same as `give-back assess`.

### Discover cache (new)

Store search results (metadata only) in state.json under a new `discover_cache` key.
Key: SHA-256 hash of the full assembled query string (future-proof against new
parameters like `--sort`). Value: timestamp, original query string, and list of
repo metadata dicts.

On repeat run with matching cache < 24h old:
```
  Found cached discover results from 3 hours ago (47 repos, 10 assessed).
  Use cached results or fetch fresh? [cached/Fresh]
```

`--no-cache` skips both caches entirely.

## Data Models

### DiscoverResult (already stubbed)

Add `from_cache: bool = False` to existing dataclass.

### DiscoverSummary (already stubbed)

Add `assessed_count: int = 0` and `cache_hits: int = 0`.

## Ranking

Light rank uses search metadata only (no API calls). All weights are named
constants in `discover/rank.py` for tuning. No calibration mechanism yet (unlike
assess tiers). If the ranking proves unreliable, a future `calibrate-discover`
command could be added using the same pattern as `calibrate`.

```python
# Initial weights — expect tuning after real-world usage
_GFI_WEIGHT = 3          # points per good-first-issue (capped at 30 total)
_HELP_WANTED_WEIGHT = 1  # points per help-wanted-issue (capped at 10 total)
_RECENT_PUSH_7D = 10     # pushed in last 7 days
_RECENT_PUSH_30D = 5     # pushed in last 30 days
_HAS_DESCRIPTION = 5     # repo has a non-empty description
_ACTIVE_ISSUES = 5       # open_issues > 10
```

Sort by score descending. Ties broken by stars descending.

After assessment, results keep their original light-rank order. Tier is displayed
as a column, not used for re-sorting. This avoids the confusing UX where the list
reorders between batches. Users can visually scan the Tier column to find GREEN
repos.

## File Structure

### New files

| File | Purpose |
|------|---------|
| `discover/rank.py` | Light ranking by search metadata |
| `output/discover.py` | Rich table + JSON output |
| `tests/discover/__init__.py` | Test package |
| `tests/discover/test_search.py` | Search + cache integration tests |
| `tests/discover/test_rank.py` | Ranking logic tests |

### Modified files

| File | Change |
|------|--------|
| `github_client.py` | Add `search_repos()` method |
| `output/__init__.py` | Re-export discover output functions |
| `cli.py` | Flesh out discover command stub |
| `state.py` | Add discover cache read/write |
| `discover/search.py` | Implement `discover_repos()` + batch assess logic |

## Error Handling

- **No results**: Print friendly message, exit 0.
- **Low rate budget**: Before each batch, check `client._rate_remaining`. If
  remaining < batch_size * 6 (worst case per-repo cost), reduce batch size or
  warn and pause. For unauthenticated users (60 core/hr), default batch size
  drops to 2 automatically. This is dynamic, not just auth-based.
- **All cached in batch**: Skip assessment, show results, prompt for next batch.
- **Assessment fails for one repo**: Show "assessment failed" for that repo,
  continue with others. Don't crash the batch.
- **Rate limit hit mid-batch**: Show partial results, warn about rate limit,
  suggest waiting or using `--no-cache` later.
- **Non-TTY (piped)**: `--interactive` is ignored. Assess up to `--limit`, exit.
- **Search returns < limit**: Display all, no "more?" prompt.

## Testing Strategy

- Mock `/search/repositories` via respx
- Mock `run_assessment()` to return fixed Assessment objects
- Test: query building, deduplication, ranking order, cache hit/miss paths,
  batch sizing, JSON output structure
- Test edge cases: no results, all cached, partial assessment failure
