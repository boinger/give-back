# Design: `give-back status` Command

**Date**: 2026-03-28
**Status**: Approved
**Supersedes**: None

## Problem

After preparing a workspace and submitting a PR, there is no way to check
what happened. Did the PR get reviewed? Merged? Ignored? Users need to
manually check each repo on GitHub. `status` closes the loop on the
contribution lifecycle.

## Approach

Scan workspace directories for `.give-back/context.json` files, hit the
GitHub API to get current PR state and review status, update local context,
and display a summary table.

**Side effect note:** `status` is a mutating command. It updates each
workspace's context.json with fresh PR state from the API. This is intentional
(keeps local state current for `check` and other commands) but worth knowing
if piping `status --json` while another process reads context.json. The writes
use `update_context_status()` which uses atomic file operations.

## Data Sources

Contribution data lives in `.give-back/context.json` files inside each
workspace directory (e.g., `~/give-back-workspaces/pallets/flask/.give-back/context.json`).
Each contains: `upstream_owner`, `repo`, `issue_number`, `branch_name`,
`fork_owner`, `status` (working/pr_open/merged/closed), `pr_url`, `pr_number`,
`previous_issues` (archive of old contributions in this workspace).

The default workspace directory comes from `~/.give-back/config.yaml`
(`workspace_dir`, default `~/give-back-workspaces`).

## Pipeline

```
give-back status

  1. Load config → get workspace_dir (or --dir override)
  2. Scan workspace_dir/*/*/.give-back/context.json
     - Glob pattern assumes owner/repo layout from prepare.
       Symlinks or non-standard nesting will be silently missed.
  3. Parse each context → extract current contribution + archived
  4. For each contribution with a pr_number:
     a. GET /repos/{owner}/{repo}/pulls/{pr_number} → state, merged_at
     b. GET /repos/{owner}/{repo}/pulls/{pr_number}/reviews → review state
     c. Update context.json with fresh pr_state via update_context_status()
  5. For contributions without pr_number but with a branch + fork_owner:
     a. Use find_pr_for_branch() to check if a PR was created externally
     b. If found, update context.json
  6. Build list[ContributionStatus]
  7. Display via print_status() or print_status_json()
```

## CLI Flags

```
give-back status                    # show current contributions, refresh from API
give-back status --json             # JSON output
give-back status --verbose          # include archived contributions
give-back status --dir <path>       # scan alternate workspace root
```

## Output Format

### Terminal (default)

```
  Tracking 3 contribution(s) across 2 repos.

  Repository          Issue   Branch                  PR       Status     Review
  pallets/flask       #5432   give-back/5432-fix-x    #6789    open       changes_requested
  encode/httpx        #234    fix/234-timeout         #567     merged     approved
  pallets/flask       —       give-back/100-old       —        working    —

  2 archived contributions (use --verbose to see)
```

With `--verbose`, archived contributions are appended:

```
  Archived:
    pallets/flask  #100  merged   PR #200  archived 2026-03-15
    pallets/flask  #50   —        no PR    archived 2026-02-01
```

Status column colored: green for merged, yellow for open, red for closed, dim for working.
Review column: green for approved, red for changes_requested, dim for pending or none.

### JSON

```json
{
  "contributions": [
    {
      "owner": "pallets",
      "repo": "flask",
      "issue_number": 5432,
      "branch_name": "give-back/5432-fix-x",
      "pr_url": "https://github.com/pallets/flask/pull/6789",
      "pr_number": 6789,
      "pr_state": "open",
      "review_state": "changes_requested",
      "workspace_path": "/Users/jeff/give-back-workspaces/pallets/flask"
    }
  ],
  "archived": [
    {
      "owner": "pallets",
      "repo": "flask",
      "issue_number": 100,
      "pr_url": "https://github.com/pallets/flask/pull/200",
      "status": "merged",
      "archived_at": "2026-03-15T..."
    },
    {
      "owner": "pallets",
      "repo": "flask",
      "issue_number": 50,
      "pr_url": null,
      "status": "working",
      "archived_at": "2026-02-01T..."
    }
  ]
}
```

Archived entries with no PR have `pr_url: null` and `status` from when they
were archived (typically "working" if abandoned without a PR).

## Review State Detection

Query `/repos/{owner}/{repo}/pulls/{pr_number}/reviews`. GitHub returns
reviews in chronological order. Multiple reviewers may each have multiple
reviews (approve, then request changes, then approve again).

Algorithm: track the **most recent review state per reviewer**, then aggregate:

```python
latest_per_reviewer: dict[str, str] = {}
for review in reviews:
    login = review["user"]["login"]
    state = review["state"]  # APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED
    if state in ("APPROVED", "CHANGES_REQUESTED"):
        latest_per_reviewer[login] = state

if not latest_per_reviewer:
    return None  # no actionable reviews
if any(s == "CHANGES_REQUESTED" for s in latest_per_reviewer.values()):
    return "changes_requested"
if any(s == "APPROVED" for s in latest_per_reviewer.values()):
    return "approved"
return "pending"
```

This handles the case where a reviewer approves, the author pushes changes,
and the same reviewer requests changes. The latest state per reviewer wins.

## Error Handling

- **Workspace dir missing**: "No workspaces found at {path}." Exit 0.
- **No context.json files**: "No tracked contributions." Exit 0.
- **GitHub API fails for one PR**: Show cached/local state with "(stale)" note.
  Continue checking others. Do not crash the whole status report.
- **Unauthenticated**: Show local state only, warn "API refresh requires auth."
- **Corrupt context.json**: Skip with warning, continue with others.
- **Archived entry with no pr_url**: Display with "—" for PR and review columns.

## API Call Budget

Each contribution with a PR costs 2 API calls (PR state + reviews). A
contribution without a pr_number but with a branch costs 1 call
(find_pr_for_branch search). Contributions in "working" state with no
branch info cost 0 calls.

For 15 tracked contributions, worst case is ~30 calls. No caching for
status — it is always a live "what is happening now" command. The 5,000/hr
core limit is more than sufficient for any realistic number of contributions.

## Known Limitations

- **Deleted workspaces**: If a user `rm -rf`s a workspace, status loses
  track of that contribution. The PR may still be open on GitHub but status
  won't show it. Acceptable for v1. A future enhancement could persist
  workspace paths in state.json during prepare and check for missing dirs.
- **Non-standard workspace layouts**: The glob pattern assumes `owner/repo`
  nesting from prepare. Symlinks or manual directory structures are missed.
- **Single workspace_dir**: Only one root is scanned (config + `--dir`).
  Users with workspaces spread across multiple directories need multiple
  `status --dir` invocations.

## Reuse

| Existing code | Used for |
|---------------|----------|
| `lifecycle.py:read_workspace_context()` | Parse context.json |
| `lifecycle.py:update_context_status()` | Write fresh state back |
| `lifecycle.py:find_pr_for_branch()` | Find PR when no pr_number saved |
| `state.py:load_config()` | Get workspace_dir |
| `output/_shared.py` | Rich table patterns |
| `console.py:stderr_console` | Status messages |

## File Structure

### New/modified files

| File | Change |
|------|--------|
| `status.py` | Replace stub with implementation |
| `output/status.py` | Rich table + JSON output (new) |
| `output/__init__.py` | Re-export status functions |
| `cli.py` | Replace status stub with full wiring |
| `tests/test_status.py` | Tests (new) |

## Testing Strategy

- Mock filesystem with tmp_path containing fake context.json files
- Mock GitHub API with MagicMock client for PR state and review queries
- Test: workspace scanning (found, missing, corrupt), PR state refresh,
  review aggregation (per-reviewer latest wins), archived contributions
  (with and without pr_url), --dir flag, error handling (API failure
  graceful degradation), JSON output structure, --verbose archive display,
  unauthenticated mode (local state only)
