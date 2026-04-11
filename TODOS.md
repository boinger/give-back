# TODOs

## Custom-label detection for discover

**What:** Instead of only recognizing GitHub's stock "good first issue" / "help
wanted" labels, detect a project's custom contribution labels (e.g.
`Hacktoberfest`, `Documentation Needed`, `starter`, `contribution-welcome`) and
use them as an alternative friendliness signal.

**Why:** The `--any-issues` escape hatch (shipped in 949a820) lets users bypass
the label gate, but it returns *all* repos regardless of friendliness. Custom
label detection would preserve the quality filter while covering mature projects
that outgrew stock labels.

**Pros:** Closes the systematic blind spot without sacrificing signal quality.
Users get canonical projects (Pi-hole, Kubernetes) in default discover results.

**Cons:** Significant architectural addition. Requires either (a) fetching each
candidate's label list (extra API call per repo, rate-budget impact) or (b)
maintaining a heuristic list of known custom label patterns. Both approaches
have maintenance burden and false-positive risk.

**Context:** Discovered during the label-gate transparency work. Pi-hole/pi-hole
has `Hacktoberfest`, `Help Wanted` (capitalized differently), and
`Documentation Needed` — none matched the GitHub search API's
`good-first-issues:>0` qualifier, which only counts the exact stock label.
See `src/give_back/discover/search.py:_build_query` for the current gate.

**Depends on / blocked by:** Nothing. Independent of other work.

## Harden `_parse_config_yaml` or migrate to tomllib

**What:** `state.py:_parse_config_yaml` is a hand-rolled YAML subset parser
that silently drops lines it doesn't understand. A malformed `handoff.command`
gets parsed as `handoff_command = None`, leaving the user wondering why their
handoff didn't fire.

**Why:** Two paths forward — either (a) keep the no-deps parser but emit a
stderr warning when a recognized top-level key has unexpected shape, or
(b) migrate config to TOML and use stdlib `tomllib` (Python 3.11+). TOML is
strictly parseable, has clear semantics, and the dependency is already free.

**Context:** Flagged in the 2026-04-11 codebase audit (N2). Current behavior
is documented as intentional to avoid PyYAML, but `tomllib` came into stdlib
after the original decision.

**Depends on / blocked by:** If we go with (b), need to migrate any existing
`~/.give-back/config.yaml` files users may have on disk. Probably best done
as dual-format support first, then a deprecation window.

## Bound growth of `~/.give-back/state.json` cache sections

**What:** `state["assessments"]` and `state["discover_cache"]` grow without a
per-section entry cap. TTL is applied on read (reject if stale) but `save_state`
never prunes expired entries. A user who runs `discover` with many language/topic
combinations accumulates entries forever.

**Why:** Silent unbounded growth in a local JSON file. Impact is low in
practice (<1 MB at hundreds of entries) but the growth is invisible and the
file is rewritten atomically on every state change.

**Context:** Flagged in the 2026-04-11 codebase audit (N3). `_MAX_AUDIT_HISTORY = 5`
already caps audit history per repo — the pattern exists, just not applied to
the other two sections.

**Design question:** Cap by entry count (LRU-ish) or sweep expired entries on
every `save_state`? Sweep is simpler but scans the whole dict on every write;
cap-by-count needs LRU metadata. For typical usage patterns, periodic sweep
on write is probably fine.

**Depends on / blocked by:** Nothing.

## Triage residual depth-5 deep-nesting findings

**What:** After the three refactor commits on 2026-04-11 (status.py, cli/discover.py,
conventions/*.py), 17 depth-5 deep-nesting findings remain in `cli/*.py`,
`output/*.py`, `audit.py`, `audit_fix/fix.py`, and others. Most are legitimate
Click command shape (`command → try → with client → if json → action`) and
should be left alone. A few (`cli/check.py:163-168`, `cli/assess.py:76-130`,
`audit_fix/contributing.py:125`) might benefit from extract-function but
aren't causing pain.

**Why:** Fighting sloppylint's 5-level threshold is linter gaming, not cleaner
code. But if any of these functions grow further, extract at that point. The
natural touch point is whenever a Click command gains new conditional
branching.

**Context:** Flagged in the 2026-04-11 codebase audit (N4). sloppylint total
score after the 2026-04-11 refactors is 143 (down from 319 at session start).
Adopting `sloppylint --ci --max-score 143` as a regression gate would prevent
drift without forcing a cleanup campaign.

**Depends on / blocked by:** Nothing. Passive — revisit when touching any of
the flagged functions.

## Add coverage reporting to CI

**What:** `pytest-cov>=5.0` is in `[dependency-groups] dev` but the CI test
step runs `uv run pytest tests/ -v` without `--cov`. No coverage badge, no
trend tracking, no minimum-coverage gate.

**Why:** 1,085 tests against 14K LOC almost certainly yields high coverage,
but we have no number to cite or regress against.

**Context:** Flagged in the 2026-04-11 codebase audit (O1). Recommendation:

    uv run pytest tests/ -v \
      --cov=src/give_back \
      --cov-report=term-missing \
      --cov-fail-under=80

Start at 80 and ratchet up once the baseline is known.

**Depends on / blocked by:** Nothing.

## Add mypy or pyright to CI

**What:** Every public function has type annotations and `from __future__
import annotations` is used consistently, but no static type checker runs.
No `mypy.ini`, no `pyrightconfig.json`, no CI step.

**Why:** A codebase this type-disciplined is the ideal target for strict
type checking. First run will almost certainly catch latent signature-drift
issues that runtime tests miss.

**Context:** Flagged in the 2026-04-11 codebase audit (O2). `mypy --strict`
vs `pyright --strict` is a taste call — mypy is more common in the Python
ecosystem, pyright is faster and Microsoft-backed.

**Depends on / blocked by:** Nothing.

## CI workflow hygiene (concurrency, SHA pinning, caching)

**What:** `.github/workflows/ci.yml` has three minor gaps:
1. No `concurrency:` group — force-push on a PR branch triggers concurrent runs
2. Actions pinned by tag (`@v5`) rather than SHA — standard OSS practice but
   less secure against action-repo compromise
3. No explicit dependency caching via `setup-uv`'s cache key

**Why:** Each gap is individually minor for a one-job workflow on a solo
project, but combined they represent the kind of friction-free hygiene
improvements that add up.

**Context:** Flagged in the 2026-04-11 codebase audit (O3). Canonical
`concurrency:` block:

    concurrency:
      group: ${{ github.workflow }}-${{ github.ref }}
      cancel-in-progress: true

**Depends on / blocked by:** Nothing.
