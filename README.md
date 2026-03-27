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

# Inspect code quality for a specific issue
give-back sniff pallets/flask 5432
```

## Authentication

Strongly recommended. Set `GITHUB_TOKEN` or run `gh auth login`.

Without authentication, GitHub limits requests to 60/hour — likely insufficient
for a single assessment (4 API calls).

## Exit Codes

- `0` — Assessment completed successfully
- `1` — Fatal error (network failure, auth failure, repo not found)
- `2` — Partial assessment (some signals failed, tier may be capped)

## Development

```bash
make pre-commit    # format + lint + test
make test          # run tests
make lint          # run linter
```
