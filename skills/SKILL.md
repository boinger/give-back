---
name: give-back
description: |
  Evaluate open-source repos for contribution viability and guide the full
  contribution workflow. Runs viability assessment, finds starter issues,
  scans conventions, and sets up workspaces.
  Use when the user wants to contribute to an open-source project, evaluate
  a repo, find good first issues, or prepare a contribution workspace.
  Trigger on: "contribute to", "is this repo friendly", "find issues in",
  "good first issue", "evaluate this project", "give-back", "contribution
  viability".
---

# give-back: Open Source Contribution Guide

You have access to the `give-back` CLI tool. Use it to help the user evaluate
and contribute to open-source projects.

## Prerequisites

Check that give-back is installed:

```bash
which give-back || echo "NOT_INSTALLED"
```

If NOT_INSTALLED, install it:

```bash
uv tool install --from git+https://github.com/boinger/give-back.git give-back
```

Check that `GITHUB_TOKEN` is set or `gh` is authenticated:

```bash
[ -n "$GITHUB_TOKEN" ] && echo "TOKEN_SET" || (gh auth status 2>/dev/null && echo "GH_AUTH" || echo "NO_AUTH")
```

If NO_AUTH, tell the user: "give-back needs GitHub authentication. Run
`gh auth login` or set `GITHUB_TOKEN`." Do not proceed without auth.

## Invocation

The user may invoke this skill in several ways:

- `/give-back <owner/repo>` — full guided workflow for a specific repo
- `/give-back` — ask which repo to evaluate
- Natural language: "I want to contribute to grafana/alloy", "find good
  first issues in dozzle", "is this repo contribution-friendly?"

Parse the repo argument. Accept `owner/repo` or full GitHub URLs.

## Workflow

Run the steps below in order. After each step, interpret the output for the
user and offer the next step. Stop early if the results indicate the user
should not proceed (RED tier, no issues, etc.).

### Step 1: Assess viability

```bash
give-back assess <owner/repo> --verbose
```

Use `--no-cache` if the user is re-evaluating a repo they assessed previously,
or if stale results could be misleading (e.g., they last assessed it days ago).

Interpret the results:

- **GREEN**: "This repo looks healthy for contributions." Proceed to Step 2.
- **YELLOW**: Explain which signals are weak. Ask the user if they want to
  proceed anyway or pick a different repo.
- **RED**: "This repo has issues that make contribution risky." Explain why
  (gate failure, low merge rate, ghost-closing, etc.). Recommend picking a
  different project unless the user has a specific reason to proceed.

Highlight the most useful signals: merge rate, response time, ghost-closing
rate. These tell the user whether their work will actually get reviewed and
merged.

If a signal shows "low sample" caveat, mention it. Small data means less
confidence.

### Step 2: Find starter issues

```bash
give-back triage <owner/repo> --verbose
```

Present the results as a curated shortlist, not a raw dump:

1. **Best bets**: Issues with small/medium scope, high clarity, no competition.
   These are the ones to start with.
2. **Worth considering**: Larger scope but well-described, or medium clarity.
3. **Skip**: Issues with active competing PRs. Note which ones and why.

If the user sees something they like, offer to sniff it (Step 3) or go
straight to preparing a workspace (Step 4).

If no candidates are found, suggest trying with `--label "good first issue"`
or `--label "help wanted"`. If still nothing, the repo may not be a good
target for a first contribution right now.

### Step 3: Inspect issue code quality (optional)

Only run this if the user picks a specific issue:

```bash
give-back sniff <owner/repo> <issue_number>
```

Interpret the verdict:

- **LOOKS_GOOD**: Files are manageable, tests exist nearby, reasonable
  complexity. Good to proceed.
- **CAUTION**: Large files, deep nesting, or no test coverage. Warn the
  user this might be harder than it looks.
- **RISKY**: Very large files, high churn, deep nesting. Suggest picking
  a different issue unless the user is experienced.

### Step 4: Scan conventions

```bash
give-back conventions <owner/repo> --issue <number>
```

Summarize the key conventions the user needs to follow:

- Commit message format (conventional commits? imperative mood?)
- Whether DCO sign-off is required (`git commit -s`)
- Merge strategy (squash, rebase, merge)
- PR template sections to fill out
- PR template checklist handling (see below)
- Test framework and how to run tests
- Linter/formatter and config

**PR template checklists:** When a project has a PR template with a
checklist, remove items that don't apply to your change. Do NOT leave
irrelevant items unchecked. Many projects' CONTRIBUTING.md explicitly
requires removing inapplicable items, and leaving them in signals that
you didn't read the guidelines. Only keep unchecked items if the template
itself says to leave them.

This is the "read the room before you speak" step. Following conventions
dramatically increases the chance of a PR getting merged.

### Step 5: Prepare workspace

```bash
give-back prepare <owner/repo> --issue <number>
```

Available flags:
- `--skip-conventions` — skip the convention scan for faster setup. Use this
  when the user already knows the project's conventions (e.g., repeat
  contributor, or conventions were already scanned in Step 4).
- `--dir <path>` — custom workspace directory instead of the default
  `~/give-back-workspaces`.

This forks the repo, clones the fork, creates a branch from upstream, and
writes a contribution brief.

**Lifecycle handling:** If the workspace already exists with a different issue,
prepare will automatically handle the transition:
- If the old branch has unpushed work or uncommitted changes, prepare will
  BLOCK and tell the user to commit+push, stash, or discard first.
- If the old branch was pushed with a PR, prepare archives it and moves on.
- If the old branch had no work, prepare cleans it up silently.

If prepare reports archiving a previous issue, inform the user about the
transition (e.g., "Archived issue #100, PR submitted at ...").

Tell the user:

1. Where the workspace was created
2. The branch name
3. Key points from the brief (conventions to follow, test commands, etc.)
4. "You're ready to start coding. When you're done, run `give-back check`
   from the workspace directory before submitting your PR."

### Step 6: Pre-flight checks (in workspace)

When the user is in a give-back workspace and says they're ready to submit,
or asks for a pre-flight check:

**Important:** `give-back check` reads `.give-back/context.json` from the
current working directory. It must be run from inside the workspace created
by `give-back prepare`. If the user isn't already there, cd into the
workspace first:

```bash
cd <workspace_path> && give-back check --verbose
```

Interpret the results. Any BLOCK severity means the user needs to fix
something before submitting. WARN items are worth addressing but won't
prevent submission.

**PR status awareness:** `check` now detects if a PR already exists for the
current branch and updates context.json with the PR status.

- If check reports **pr_open**: The user's PR is already submitted. Do NOT
  offer to "continue work" or "submit a PR." Instead, offer to help with
  review feedback or address requested changes.
- If check reports **merged**: The contribution was merged. Congratulate
  the user. No further action needed on this issue.
- If no PR is detected: Normal flow, user hasn't submitted yet.

## Skipping steps

The user doesn't have to follow the full workflow. Adapt:

- "Just assess this repo" — run Step 1 only.
- "Find me issues" — run Steps 1 and 2.
- "I already know the issue, set up my workspace" — run Steps 4 and 5,
  skip triage and sniff. Consider `--skip-conventions` if conventions
  were already scanned or the user knows the project.
- "Check my PR" — run Step 6 only (must be in workspace).

## Additional commands

If the user asks about dependencies:

```bash
give-back assess <owner/repo> --deps --verbose
```

Or standalone dep walking:

```bash
give-back deps <owner/repo> --verbose
```

If the user wants to skip a repo from future dep results:

```bash
give-back skip <owner/repo>
give-back unskip <owner/repo>
```

## Tone

Be direct about what the signals mean for the user's time investment.
"93% merge rate and 23-minute response time means your PR will get looked at
fast." Or: "30% merge rate with 2-week response, your work might sit for a
while." Help them make an informed decision about where to invest effort.
