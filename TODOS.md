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

## Ratchet mypy to strict mode

**What:** mypy was adopted in non-strict mode on 2026-04-25 (24 errors fixed
in the same PR). Strict mode surfaces an additional 92 errors across the
codebase, predominantly:

- 74 `[type-arg]` errors — generic types missing parameters (`dict` → `dict[str, X]`,
  `list` → `list[X]`)
- 11 `[no-any-return]` — functions returning Any from typed call sites
- 5 `[no-untyped-def]` — functions missing annotations (mostly private helpers
  and test fixtures)

**Why:** This codebase is well-typed; strict mode is the right long-term posture.
The non-strict baseline was a scope-cap decision (>50 strict errors → defer per
the scope-cap protocol in plan-fixes 0.1.0).

**Context:** First-run measurement on commit aff1d2b: 116 strict errors across
33 files. Non-strict baseline: 24 errors fixed inline. The expectation is to
ratchet over 2-3 follow-up PRs:

1. Enable `disallow_untyped_defs` and fix the 5 `[no-untyped-def]` errors.
2. Enable `disallow_any_generics` to surface `[type-arg]` and fix in waves of
   ~20 files per PR.
3. Enable `warn_return_any` to surface `[no-any-return]` and fix.
4. Flip `strict = true` once the underlying flags are all on.

**Depends on / blocked by:** Nothing.

