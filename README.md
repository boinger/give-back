# give-back

A CLI tool that handles everything around contributing to open-source projects
except the actual coding. Find a project, evaluate whether it's worth your
time, pick an issue, understand the conventions, set up your workspace, and
then once you're done coding: submit your PR and track its progress.

## What it does

You want to contribute to open source but don't know where to start, or
you've tried contributing but been burned by repos that ignore PRs. give-back
solves both problems.

**Find a project.** Search GitHub for repos that actually welcome contributions,
filtered by language and topic, pre-screened for viability.

**Evaluate it.** Query 8 signals from the GitHub API: merge rate for outside
PRs, response time, ghost-closing rate, CONTRIBUTING.md quality, AI policy,
label hygiene, staleness, and license. Get a Green/Yellow/Red tier so you know
before you invest time.

**Pick an issue.** Triage open issues by scope, clarity, and competition.
Detect competing open PRs, claim comments, and merged PRs that may have already
fixed the problem.

**Understand the rules.** Scan the repo's conventions: commit format, DCO
requirements, merge strategy, PR template, test framework, linter config. Get
a brief so you don't submit a PR that violates the project's conventions.

**Set up and submit.** Fork, clone, branch, write your fix, run pre-flight
checks, and submit the PR with the right title, body, and labels. Track status
across all your contributions.

## Install

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
# Recommended: install as a global CLI tool
uv tool install --from git+https://github.com/boinger/give-back.git give-back

# Or from a local checkout
uv tool install --from ./give-back give-back

# Reinstall after source changes
uv tool install --from ./give-back give-back --reinstall
```

### Development install

```bash
git clone https://github.com/boinger/give-back.git
cd give-back
uv sync --group dev
```

## Authentication

Set `GITHUB_TOKEN` or run `gh auth login`. Without authentication, GitHub
limits requests to 60/hour, which isn't enough for a single assessment.

## Workflow

The commands follow a natural progression. You can run any command standalone
or follow the full flow.

### 1. Discover a project

Don't have a repo in mind? Search for one.

```bash
give-back discover --language python
give-back discover --topic kubernetes --min-stars 100
give-back discover --language rust --limit 5 --interactive
```

Each result is pre-screened for contribution viability. Use `--interactive` to
assess more repos in batches.

### 2. Assess viability

Point it at a repo and find out if your PR will actually get reviewed.

```bash
give-back assess pallets/flask
give-back assess pallets/flask --verbose    # detailed signal breakdown
give-back assess pallets/flask --json       # machine-readable output
give-back assess pallets/flask --no-cache   # force fresh API calls
```

Full GitHub URLs work too: `give-back assess https://github.com/pallets/flask`

Results are a Green/Yellow/Red tier. GREEN means go. YELLOW means proceed with
caution (check which signals are weak). RED means your time is probably better
spent elsewhere.

### 3. Find an issue

Triage open issues ranked by contribution-friendliness.

```bash
give-back triage pallets/flask
give-back triage pallets/flask --verbose              # show competition details
give-back triage pallets/flask --label "good first issue"  # filter by label
```

Issues are ranked by scope (S/M/L), clarity, and competition. The competition
check searches for open PRs, claim comments ("I'm working on this"), and
merged PRs that may have already fixed the problem.

### 4. Inspect the issue (optional)

Sniff the source files referenced in the issue to gauge code quality before
you commit to it.

```bash
give-back sniff pallets/flask 5432
give-back sniff pallets/flask 5432 --verbose
```

Reports file size, test coverage nearby, churn, and nesting depth. Helps you
avoid issues that look simple but touch gnarly code.

### 5. Learn the conventions

Scan the repo's contribution conventions so your PR matches their standards.

```bash
give-back conventions pallets/flask
give-back conventions pallets/flask --issue 5432   # include issue context
```

Produces a brief covering commit message format, DCO/sign-off requirements,
merge strategy, PR template sections, test framework, and code style.

### 6. Prepare your workspace

Fork the repo, clone your fork, create a branch, and write a contribution brief.

```bash
give-back prepare pallets/flask --issue 5432
give-back prepare pallets/flask --issue 5432 --skip-conventions  # if already scanned
give-back prepare pallets/flask --issue 5432 --dir ~/my-workspaces
```

Now write your fix. The workspace is ready with the right branch, remote, and
a `.give-back/` directory containing your context and brief.

### 7. Pre-flight check

Run from inside your workspace before submitting.

```bash
cd ~/give-back-workspaces/pallets/flask
give-back check
give-back check --verbose
```

Checks for uncommitted changes, branch state, and convention compliance.
BLOCK items must be fixed. WARN items are worth addressing.

### 8. Submit your PR

Create the PR with the right title, body, and conventions applied.

```bash
give-back submit
give-back submit --draft                            # create as draft
give-back submit --title "Fix type annotation"      # custom title
give-back submit --edit                             # edit PR body in $EDITOR
```

The title and body are auto-generated from your issue context and contribution
brief. The PR body uses the project's PR template section from the brief.

### 9. Track status

Check on all your open contributions across repos.

```bash
give-back status
give-back status --verbose    # include archived contributions
give-back status --dir ~/alt  # scan alternate workspace root
```

Shows PR state (open, reviewed, merged, closed) with review status per
reviewer.

## Additional commands

### Dependency walking

Find contribution opportunities in a project's dependency tree.

```bash
give-back deps traefik/traefik
give-back assess pallets/flask --deps    # combine assessment + dep walk
```

### Skip list

Exclude repos from dependency walking results.

```bash
give-back skip google/protobuf
give-back unskip google/protobuf
```

### Calibration

Test scoring thresholds against repos with known tiers.

```bash
give-back calibrate calibration.yml
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (GREEN or YELLOW tier) |
| 1 | Fatal error (network, auth, repo not found) |
| 2 | Partial assessment (some signals failed) |
| 3 | Gate failed (RED tier) |

## Claude Code skill

give-back includes a [Claude Code](https://github.com/anthropics/claude-code) skill that
guides you through the full workflow interactively. Install it:

```bash
# Symlink for automatic updates (recommended)
mkdir -p ~/.claude/skills/give-back
ln -sf "$(pwd)/skills/SKILL.md" ~/.claude/skills/give-back/SKILL.md
```

Then use `/give-back grafana/alloy` in Claude Code, or just say "help me
contribute to grafana/alloy."

## Development

```bash
make pre-commit    # format + lint + test (766 tests)
make test          # tests only
make lint          # ruff check + format
```
