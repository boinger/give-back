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

