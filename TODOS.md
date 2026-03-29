# TODOs

## Audit progress tracking

Save audit results to `state.json` keyed by repo. On repeat runs, show the
delta: "Last audit: 9/13, now 11/13. +2 since March." Lets maintainers track
improvement over time.

**Effort:** S. **Priority:** P2. **Depends on:** audit command (done).

## Audit auto-fix mode (`--fix`)

Generate missing community health files with safe defaults only. No judgment
calls automated.

**What gets generated directly:**
- CODE_OF_CONDUCT.md (Contributor Covenant v2.1 verbatim)
- SECURITY.md (boilerplate pointing to GitHub private vulnerability reporting)
- Issue templates (YAML forms for bug report + feature request)
- PR template (boilerplate with summary + test plan sections)
- Labels via `gh label create` (reversible)

**What gets guided, not generated:**
- LICENSE: link to https://choosealicense.com/ (license choice is a legal
  decision, not an automation target)
- CONTRIBUTING.md: generate a skeleton with TODO markers the user fills in
  (dev setup, test commands, PR conventions are project-specific)

**Effort:** M. **Priority:** P2. **Depends on:** audit command (done).
