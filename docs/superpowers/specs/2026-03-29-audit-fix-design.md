# Design: `audit --fix`

## Problem

The `audit` command identifies missing community health files, templates, labels,
and conventions, but leaves the user to fix everything manually. For a maintainer
who just wants their repo contributor-friendly, the gap between "here's what's
wrong" and "here's how to fix it" is too wide.

## Solution

Add a `--fix` flag to the `audit` command. After running the normal audit and
displaying the checklist, `--fix` walks the user through each failing check
interactively, generating files, creating labels, and guiding decisions that
require human judgment.

## Flow

```
give-back audit owner/repo --fix

1. Run audit, display checklist (same as today)
2. If nothing failing → "Nothing to fix!" → exit
3. Resolve local repo directory:
   a. Check if cwd is a git repo whose remote matches owner/repo → use it
   b. If not → prompt: path to local clone, 'clone' to clone it, or 'abort'
   c. If 'clone' → git clone into cwd/repo, cd into it
4. Walk through each failing check in category order:
   - Show what will be created
   - Confirm or run wizard
   - Write file or create label
5. Display summary with local vs remote distinction
```

## Fixable checks

### Safe defaults (confirm and generate)

For each, show a preview of the file content, ask "Create this? [Y/n]".
Skip if the file already exists.

| Check | File | Content |
|-------|------|---------|
| code_of_conduct | `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 verbatim |
| security | `SECURITY.md` | Boilerplate pointing to GitHub private vulnerability reporting |
| pr_template | `.github/PULL_REQUEST_TEMPLATE.md` | Summary + Test plan + Checklist sections |
| issue_templates | `.github/ISSUE_TEMPLATE/bug_report.yml` | YAML form: steps to reproduce, expected/actual, version, OS |
| issue_templates | `.github/ISSUE_TEMPLATE/feature_request.yml` | YAML form: problem, proposed solution, alternatives |
| issue_templates | `.github/ISSUE_TEMPLATE/config.yml` | Enable blank issues |

### LICENSE (quick-pick)

```
No LICENSE file found.

Choose a license:
  1) MIT (most common open-source license)
  2) BSD 2-Clause
  3) Apache 2.0
  4) Other — choose from https://choosealicense.com, paste the URL
  5) Skip
```

- Options 1-3: fetch license text from GitHub Licenses API
  (`GET /licenses/{spdx_id}`), fill `[year]` (current year) and
  `[fullname]` (prompt once for name).
- Option 4: parse the SPDX slug from the pasted choosealicense.com URL,
  fetch and fill the same way.
- Option 5: skip.

### CONTRIBUTING.md (section checklist wizard)

```
CONTRIBUTING.md helps contributors understand your process.
Not required — lacking one doesn't mean you don't want contributors,
only that you don't feel the need for formal rules.

Create one? [Y/n]

If yes — which sections to include?
  1) Getting started (dev setup, prerequisites)
  2) Running tests
  3) Submitting changes (PR process)
  4) Code style
  5) Issue reporting guidelines
  6) Code of conduct reference

Include sections (comma-separated, default 1,2,3): 1,2,3,4
```

Uses `click.prompt` with comma-separated numbers. No new dependencies
needed. Click doesn't have a multi-select checkbox widget, and adding
one (questionary, InquirerPy) isn't worth a new dependency for a
6-option list. Numbered input is clear and fast.

Generates a markdown file with selected section headers and
`<!-- TODO: fill in your details -->` placeholders under each.

### Labels (GitHub API)

```
Create contributor-friendly labels on GitHub? [Y/n]
  - "good first issue" (green, #0e8a16)
  - "help wanted" (blue, #0075ca)
```

Created via `gh label create`. These take effect immediately on GitHub
(unlike file changes which need commit + push).

## Checks NOT fixable by --fix

| Category | Why |
|----------|-----|
| Signals (merge rate, response time, etc.) | Require behavior change, not files |
| Conventions (commit format, CI, etc.) | Too project-specific to generate |
| readme | Already exists in any real project; generating one is meaningless |

These are skipped silently during the fix walk. The normal audit output
already shows them with recommendations.

## Summary output

The summary distinguishes local file changes from remote GitHub changes:

```
Created locally (commit and push to apply):
  + CODE_OF_CONDUCT.md
  + SECURITY.md
  + .github/PULL_REQUEST_TEMPLATE.md
  + .github/ISSUE_TEMPLATE/bug_report.yml
  + .github/ISSUE_TEMPLATE/feature_request.yml
  + .github/ISSUE_TEMPLATE/config.yml
  + LICENSE
  + CONTRIBUTING.md

Applied to GitHub (effective immediately):
  + Label: good first issue
  + Label: help wanted

Skipped:
  - readme (already exists)
  - external_pr_merge_rate (not fixable via --fix)

Score: 9/13 -> 13/13
```

## Architecture

```
src/give_back/
  audit.py              (existing, unchanged)
  audit_fix/
    __init__.py
    fix.py              orchestrator: walk_fixes(), resolve_repo_dir()
    templates.py        string constants for CoC, SECURITY, PR template, issue forms
    license.py          quick-pick menu, GitHub Licenses API fetch, placeholder fill
    contributing.py     section checklist, skeleton generation
    labels.py           gh label create wrapper
```

New package `audit_fix/` keeps fix logic separate from audit evaluation.
Each concern is its own module. `fix.py` is the entry point called by
`cli.py`.

### Key functions

**`fix.py`:**
- `resolve_repo_dir(owner, repo) -> Path` — check cwd git remote, prompt
  if mismatch, optionally clone
- `walk_fixes(report, repo_dir, client) -> FixSummary` — iterate failing
  checks, dispatch to handlers, collect results

**`templates.py`:**
- String constants for each safe-default file
- `write_if_missing(path, content, label) -> bool` — check existence,
  confirm with user, write atomically. Uses its own atomic write that
  creates the temp file in the target's parent directory (not
  `~/.give-back/`), since `os.rename` fails across filesystems. Does
  not reuse `state.py:atomic_write_text` directly.

**`license.py`:**
- `pick_license(client) -> str | None` — display menu, fetch from API,
  fill placeholders, return content or None

**`contributing.py`:**
- `run_wizard() -> str | None` — section checklist, generate skeleton,
  return content or None

**`labels.py`:**
- `create_labels(owner, repo, missing: list[str]) -> list[str]` — accepts
  the list of missing label names from the audit result (avoids a
  redundant API call to re-check existence). Creates via `gh label create`,
  returns names successfully created.

## CLI integration

In `cli.py`, the `audit` command gains `--fix`:

```python
@click.option("--fix", is_flag=True, help="Interactively fix failing checks.")
```

After running the audit and displaying results:
1. If `--fix` and failures exist: resolve repo dir, call `walk_fixes()`
2. Display fix summary
3. Save audit result to state (same as today, but with updated report)

`--fix` is incompatible with `--compare` (error if both provided).
`--fix` with `--json` is an error. Fix mode is inherently interactive.
Automation users should parse `--json` output and apply fixes themselves.

## Error handling

| Scenario | Behavior |
|----------|----------|
| File already exists | Skip with "Already exists, skipping" |
| `gh` not installed or not authenticated | Skip labels with warning |
| GitHub Licenses API fails | Fall back to "visit choosealicense.com manually" |
| Clone fails | Abort with error message |
| Ctrl+C mid-walk | Clean exit, files written so far are kept (they're valid) |
| `--fix` + `--compare` | Error: flags are incompatible |
| `--fix` + `--json` | Error: flags are incompatible (fix is interactive) |
| cwd is not a git repo and user doesn't want to clone | Abort |

## Testing

### Unit tests

- Template content: string constants exist, have expected structure
- `resolve_repo_dir`: cwd matches, cwd doesn't match, no git repo
- License API fetch: mock via respx, verify placeholder substitution
- Contributing wizard: checklist selection -> expected markdown output
- Label creation: mock subprocess, verify `gh label create` calls
- `write_if_missing`: file exists (skip), file doesn't exist (write)

### Integration tests

- `--fix` with all checks failing: expected files written to tmp_path
- `--fix` with no failures: "Nothing to fix!" message
- `--fix` + `--compare`: error exit
- `--fix` + `--json`: error exit

## Dependencies

No new dependencies. Uses:
- `click` for prompts (already in stack)
- `httpx` via `GitHubClient` for Licenses API (already in stack)
- `subprocess` for `gh label create` (same pattern as `submit.py`)
- Own `write_if_missing` for atomic file writes (temp file in target
  directory, same pattern as `state.py` but filesystem-local)
