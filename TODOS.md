# TODOs

## ~~Phase 1b: Dependency Walking~~ DONE

Implemented: `give-back deps`, `--deps` flag on `assess`, `skip`/`unskip` commands.
Supports go.mod, pyproject.toml (PEP 621 + Poetry), requirements.txt.
Resolves via PyPI API and Go module paths. Filters stdlib, same-org, archived,
skip list, mega-projects.

## ~~Phase 1.1: authorAssociation Bias Reconciliation~~ DONE

Implemented in reconcile.py. Conditional two-phase assessment: if PR merge rate
is suspiciously low but other signals are healthy, investigates collaborator role
transitions via search API. Re-scores if transitions found. Max 5 author lookups.

## ~~Scoring Threshold Auto-Calibration~~ DONE

Implemented: `give-back calibrate repos.yaml`. Accepts YAML/JSON with expected
tiers, runs assessments, outputs confusion matrix + accuracy + threshold suggestions.

## ~~LLM-Assisted License Evaluation~~ DONE

Implemented in license_eval.py. When license gate returns REVIEW and ANTHROPIC_API_KEY
is set, fetches LICENSE file and asks Claude Haiku to classify it. Purely additive —
falls back to manual review link when no API key is available.

## Future work

- ~~**Phase 3: Convention Scan**~~ DONE — `give-back conventions` clones, analyzes
  commit format, merge strategy, PR templates, branch naming, DCO, tests, style.
- ~~**Phase 4: Prepare Workspace**~~ DONE — `give-back prepare` forks, clones, branches,
  writes brief + context.json, runs configurable handoff. `give-back check` runs
  pre-flight guardrails in the workspace.
- **CLA detection** — detect Contributor License Agreements in conventions scan.
  Check for CLA bot configs (.github/workflows/cla*.yml, .clabot, cla.json),
  known CLA services (CLA Assistant, EasyCLA) in recent PR comments/checks.
  Surface in brief ("CLA required, sign before submitting") and warn in
  `give-back check`. Prompted by grafana/alloy requiring CLA sign-off.
- ~~**Ghost-closing bot awareness**~~ DONE — PRs with only bot comments/reviews
  (CLA bots, CI bots, stale bots) now correctly count as ghost-closed. Bot
  detection shared between ghost_closing and time_to_response via _bots.py.
- ~~**Go module resolution**~~ DONE — resolves non-GitHub Go module hosts
  (gopkg.in, k8s.io, sigs.k8s.io, go.uber.org, etc.) via go-import HTML meta
  tags. Caches results per session. Skips "mod" proxy entries, only extracts
  git VCS pointing to GitHub.
- **Rust/Node/Ruby dep-walking** — Cargo.toml, package.json, Gemfile ecosystem support.
- **PR pagination** — paginate to fill the 12-month window for prolific repos.
