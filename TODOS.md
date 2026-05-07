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

## Consolidate `make ci` to include mypy and sloppylint

**What:** `make ci` currently runs `lint + format-check + test-ci` only.
mypy and sloppylint are gated only by `.github/workflows/ci.yml` (mypy on
Python 3.11, sloppylint as a separate step). Local `make ci` passes even
when those gates would fail in GitHub Actions.

**Why:** Local verification should match CI exactly. The "Before you
submit" section of CONTRIBUTING.md tells contributors `make ci` runs
"exactly the same checks CI runs" — that's no longer true after mypy and
sloppylint were added. Closing the gap restores the contract.

**Pros:** Contributors catch mypy/sloppylint regressions before push
instead of CI-failure-and-revert cycle. CONTRIBUTING.md becomes accurate
again. No CI workflow change needed (the duplication is intentional —
local mirror of remote).

**Cons:** `make ci` becomes slower (mypy adds ~10s, sloppylint ~3s).
Could be mitigated with a `make ci-fast`-style split, but `make ci-fast`
already exists for the pre-commit hook.

**Context:** Surfaced during the mypy 2.0 + strict ratchet plan-eng-review
on 2026-05-06. The ratchet plan worked around the gap by invoking mypy
and sloppylint explicitly per step, which is fine for that plan but
doesn't fix the durable issue. Right approach: after the ratchet lands,
add `mypy` and `sloppylint` rules to the Makefile and update
CONTRIBUTING.md.

**Depends on / blocked by:** Mypy strict ratchet (so the consolidated
`make ci` reflects strict-mode behavior, not non-strict).

## Widen mypy CI to the full Python version matrix

**What:** `.github/workflows/ci.yml` currently runs mypy only when
`matrix.python-version == '3.11'`. The full matrix is 3.11/3.12/3.13.
Drop the guard so mypy runs on all three.

**Why:** Type errors can be Python-version-conditional. mypy's behavior
depends on `python_version` config and on stub availability per
interpreter. Catching cross-version drift in CI is cheap once the
single-version baseline is clean.

**Pros:** Catches version-conditional issues (e.g., `typing` vs
`collections.abc` differences, version-gated stubs) at PR time rather
than in production. Modest CI-time increase.

**Cons:** ~20 extra seconds of CI time per push (mypy is fast, but 3x
isn't free). Slight risk of flakes if a stub mismatch only affects one
interpreter.

**Context:** Surfaced during the mypy 2.0 + strict ratchet plan-eng-review
on 2026-05-06. The single-version guard was reasonable for the
non-strict baseline (mypy is mypy — version-of-target shouldn't matter
much). Becomes more valuable once `strict = true` lands and the project
relies on tight type safety across all supported runtimes.

**Depends on / blocked by:** Mypy strict ratchet (no point widening
matrix while we're still ratcheting flag-by-flag).

