# TODOs

## Test coverage gaps

- `prepare/fork.py` at 69% — test gh CLI failure paths (not installed, not
  authenticated, fork rename). Lines 35-36, 45-46, 58-59, 77-78, 102-103, 123-124.
- `state.py` at 76% — test discover cache functions, config parsing edge cases,
  legacy format handling. Lines 269-303, 328-332.

## Architecture

- Split `cli.py` (1231 lines, 12 commands) into a `cli/` package. Each command
  in its own module. Highest-churn file in the project (28 changes in 90 days).
  Do this when the next command is added.
