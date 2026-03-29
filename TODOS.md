# TODOs

## Implement `discover` command

CLI and models are stubbed in `discover/search.py`. Needs:
- Build GitHub search query from language/topic/min-stars filters
- Fetch repos via search API with pagination
- Filter: must have open issues, must not be archived, pushed within 90 days
- Pre-screen: run lightweight viability check (license gate + activity signals)
- Rank by: good-first-issue count, recent activity, viability tier
- Output: table (rich) and JSON modes
- Tests in `tests/discover/`

## Implement `submit` command

CLI and models are stubbed in `submit.py`. Needs:
- Read `.give-back/context.json` for repo metadata (upstream, branch, issue)
- Read `.give-back/brief.md` for conventions (DCO, commit format, PR template)
- Push branch to fork via `git push -u origin <branch>`
- Build PR body from template sections + issue reference
- Apply DCO sign-off if required
- Create PR via `gh pr create` with correct base branch
- Update context.json status to `pr_open`
- Output: PR URL (rich) and JSON modes
- Tests in `tests/test_submit.py`

## Implement `status` command

CLI and models are stubbed in `status.py`. Needs:
- Scan `~/.give-back/state.json` for workspace entries with PR URLs
- Also scan workspace directories for `.give-back/context.json` files
- For each tracked contribution: query GitHub API for PR state + review state
- Detect: open, reviewed (approved/changes_requested), merged, closed
- Output: summary table (rich) and JSON modes
- Tests in `tests/test_status.py`
