# Contributing to give-back

We don't care how you write your code. Use AI, don't use AI, dictate it to
your dog. What matters is that the result is clean, tested, and does one
thing well.

## Setup

```bash
git clone https://github.com/boinger/give-back.git
cd give-back
uv sync --group dev
```

## Before you submit

```bash
make pre-commit
```

This runs format, lint, and the full test suite. Everything must pass.

## Code style

- **Formatter/linter:** ruff, configured in `pyproject.toml`
- **Line length:** 120
- **Imports:** sorted by ruff (stdlib, third-party, first-party)

Don't fight the linter. If ruff complains, fix it. If you think ruff is
wrong, open an issue and we'll talk about it.

## How we write code

- **No catch-all exceptions.** Every handler names the specific exception it
  catches. All custom exceptions inherit from `GiveBackError`.
- **Signals are pure functions.** They take `RepoData`, return `SignalResult`.
  No API calls, no side effects, no global state.
- **Atomic state writes.** Anything touching disk writes to a temp file first,
  then renames.
- **One concern per PR.** Don't bundle a bug fix with a refactor. Don't sneak
  in whitespace cleanup. If you found something else wrong, open a separate PR.

## Commits

Use imperative mood: "Add feature", "Fix bug", "Remove dead code". Not
"Added", "Fixes", "Removing".

Keep messages short and descriptive. Say what changed and why, not how.

## Branches

No strict naming convention. Just make it descriptive enough that someone
reading `git branch` can tell what you're working on.

## PRs

Fill out the PR template. If a checklist item doesn't apply to your change,
remove it. Don't leave irrelevant items unchecked.

## Tests

If you change behavior, update or add tests. If no tests cover the code you
touched, write them. We use pytest with respx for HTTP mocking.

```bash
make test          # run tests
make pre-commit    # format + lint + test
```

## No paperwork

No CLA. No DCO. No sign-off required. Just clean code and passing tests.
