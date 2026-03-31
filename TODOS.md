# TODOs

## Batch audit across user's repos (`audit --mine`)

Scan the authenticated user's GitHub repos and batch-run audit, presenting
results as a ranked list to drill into.

**Defaults:** Public, non-archived repos only. Sorted by most recent commit
(repos you're actively working on first). Cap at 20 repos by default
(nobody's burning a weekend on 100 repos).

**Flags:**
- `--all` — include private and archived repos
- `--limit N` — override the 20-repo default

**Flow:**
1. `gh api user/repos` (or GitHubClient) → filter by visibility + archived
2. Sort by `pushed_at` descending (most recently active first)
3. Batch-audit top N, using cached results when fresh
4. Display ranked table (score, repo name, top failing check)
5. Interactive: pick a repo to see full audit or run `--fix`

**Rate limits:** ~4 API calls per audit. 20 repos = ~80 calls. Well within
5000/hour. Cache via existing audit_results in state.json to skip re-audits
of repos audited recently.

**Effort:** M. **Priority:** P3. **Depends on:** audit + audit progress tracking (done).

