# TODOs

## ~~Phase 1b: Dependency Walking~~ DONE

Implemented: `give-back deps`, `--deps` flag on `assess`, `skip`/`unskip` commands.
Supports go.mod, pyproject.toml (PEP 621 + Poetry), requirements.txt.
Resolves via PyPI API and Go module paths. Filters stdlib, same-org, archived,
skip list, mega-projects.

## Phase 1.1: authorAssociation Bias Reconciliation
**Priority:** P1 | **Effort:** S (human: ~2d / CC: ~15min)
**Depends on:** Phase 1 scoring thresholds calibrated

When PR merge rate scores LOW/RED but other signals suggest a healthy project,
investigate collaborator role transitions via additional API calls. Re-score if
external contributors were later promoted to collaborator (making their historical
PRs appear "internal"). Currently Phase 1 shows a --verbose warning only.

**Why:** The authorAssociation bias systematically penalizes the healthiest repos —
the ones that promote active contributors. Calibration first tells us whether this
is a real problem or a theoretical one.

## Scoring Threshold Auto-Calibration
**Priority:** P2 | **Effort:** S (human: ~2d / CC: ~15min)
**Depends on:** Phase 1 shipped

Add `give-back calibrate` command that runs the gate against a user-provided list
of repos with known friendliness ratings (YAML file mapping repos to expected tiers).
Outputs a confusion matrix and suggests threshold adjustments. Makes calibration
repeatable as signals evolve.

## LLM-Assisted License Evaluation
**Priority:** P2 | **Effort:** S (human: ~1d / CC: ~15min)
**Depends on:** Phase 1 shipped

When the license gate encounters an unrecognized license (SPDX "NOASSERTION" /
"Other"), fetch the LICENSE file text via REST contents API and pass it to an LLM
for classification. The LLM provides an estimate ("this looks like a permissive
license with X clause") while the user still makes the final call. Currently Phase 1
links to the LICENSE file URL for manual review.

**Why:** Many legitimate OSS projects use custom or less-common licenses that
GitHub's SPDX classifier doesn't recognize. An LLM can read the actual text and
give a useful first-pass assessment, reducing the manual review burden. This crosses
the "no LLM in Phase 1" boundary, so it ships as a later enhancement.
