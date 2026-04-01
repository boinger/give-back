# TODOs

## Architecture

- Split `cli.py` (1231 lines, 12 commands) into a `cli/` package. Each command
  in its own module. Highest-churn file in the project (28 changes in 90 days).
  Do this when the next command is added.
