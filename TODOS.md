# TODOs

## Reduce reconciliation overcount with date-based heuristic

`reconcile.py:_check_author_transition` counts all merged PRs from a
collaborator author as "reclassified external." This overcounts because it
includes PRs created after the author was promoted to collaborator.

Fix: use PR `created_at` dates from search results to estimate the transition
point. The author's earliest PR approximates when they started contributing.
PRs created within the last N months (e.g., 6) are likely post-promotion and
should not be reclassified. Only count PRs older than the estimated transition
window. Still a heuristic (GitHub doesn't expose historical association), but
significantly more accurate than counting everything.

Affected files: `src/give_back/reconcile.py` (`_check_author_transition`),
`tests/test_reconcile.py`.

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
