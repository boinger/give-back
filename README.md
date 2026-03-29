# give-back

Evaluate whether an open-source project is viable for outside contributions.

Point give-back at a GitHub repo and it queries the API to assess:
- External PR merge rate
- Time-to-first-response for outside contributors
- Ghost-closing (PRs closed without comment)
- CONTRIBUTING.md quality and friction level
- AI/LLM contribution policy
- Issue label hygiene
- Project staleness
- License compatibility

Results are a Green/Yellow/Red viability tier with a signal breakdown.

## Install

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

### Global install (recommended)

Install as a standalone CLI tool available from any directory:

```bash
uv tool install --from git+https://github.com/boinger/give-back.git give-back
```

Or from a local checkout:

```bash
uv tool install --from ./give-back give-back
```

After changes to the source, reinstall to pick them up:

```bash
uv tool install --from ./give-back give-back --reinstall
```

### Development install

For contributing to give-back itself:

```bash
git clone https://github.com/boinger/give-back.git
cd give-back
uv sync --group dev
```

## Usage

```bash
# Assess a repo
give-back assess pallets/flask

# Full GitHub URL also works
give-back assess https://github.com/pallets/flask

# JSON output for scripting
give-back assess pallets/flask --json

# Detailed signal data
give-back assess pallets/flask --verbose

# Skip cached results
give-back assess pallets/flask --no-cache

# Walk dependencies and find contribution opportunities
give-back deps traefik/traefik

# Combine viability assessment + dep walk
give-back assess pallets/flask --deps

# Skip repos from dep-walking results
give-back skip google/protobuf
give-back unskip google/protobuf

# Find good starter issues (Phase 2)
give-back triage pallets/flask

# Filter by label
give-back triage pallets/flask --label "good first issue"

# Scan contribution conventions (Phase 3 — clones the repo)
give-back conventions pallets/flask

# Include issue context in the brief
give-back conventions pallets/flask --issue 5432

# Prepare a contribution workspace (Phase 4 — forks and clones)
give-back prepare pallets/flask --issue 5432

# Run pre-flight checks in your workspace
cd ~/give-back-workspaces/pallets/flask
give-back check

# Inspect code quality for a specific issue
give-back sniff pallets/flask 5432

# Discover repos to contribute to (not yet implemented)
give-back discover --language python
give-back discover --topic kubernetes --min-stars 100

# Submit a PR from your workspace (not yet implemented)
cd ~/give-back-workspaces/pallets/flask
give-back submit
give-back submit --title "Fix type annotation" --draft

# Check status of your contributions (not yet implemented)
give-back status
```

## Authentication

Strongly recommended. Set `GITHUB_TOKEN` or run `gh auth login`.

Without authentication, GitHub limits requests to 60/hour — likely insufficient
for a single assessment (4 API calls).

## Exit Codes

- `0` — Assessment completed successfully
- `1` — Fatal error (network failure, auth failure, repo not found)
- `2` — Partial assessment (some signals failed, tier may be capped)

## Claude Code Skill

give-back includes a Claude Code skill for guided contribution workflows.
Install the skill to get `/give-back` as a slash command:

```bash
mkdir -p ~/.claude/skills/give-back
cp skills/SKILL.md ~/.claude/skills/give-back/SKILL.md
```

Or symlink for automatic updates:

```bash
mkdir -p ~/.claude/skills/give-back
ln -sf "$(pwd)/skills/SKILL.md" ~/.claude/skills/give-back/SKILL.md
```

Then in Claude Code, use `/give-back grafana/alloy` to run the full guided
workflow, or any natural language like "help me contribute to grafana/alloy".

## Development

```bash
make pre-commit    # format + lint + test
make test          # run tests
make lint          # run linter
```
