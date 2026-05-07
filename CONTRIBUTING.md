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
make ci
```

This runs `ruff check`, `ruff format --check`, `mypy src/`, the full test
suite with coverage, and the sloppylint regression gate — exactly the
same checks CI runs. Everything must pass.

If `make ci` fails on formatting, run `make fix` to auto-format and
auto-fix ruff lint issues, then re-run `make ci`.

Individual gates are also available: `make lint`, `make format-check`,
`make type-check`, `make sloppylint`, `make test`.

`make pre-commit` is kept as a backward-compat alias.

### Git hooks

`make dev` installs two git hooks automatically:

- **pre-commit** runs a fast format check (`make ci-fast`) on every commit.
- **pre-push** runs the full `make ci` on every push.

You can bypass per-commit/per-push with `--no-verify`, or disable hooks
entirely for a clone with `git config --unset core.hooksPath`. The hooks
are tracked in `.githooks/`, so fixes propagate automatically.

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
make ci            # CI-equivalent checks (lint + format-check + test)
make fix           # auto-format + auto-fix ruff lint issues
```

## No paperwork

No CLA. No DCO. No sign-off required. Just clean code and passing tests.
