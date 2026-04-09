#!/usr/bin/env bash
# Install give-back's tracked .githooks/ as the active git hooks directory.
#
# Uses an absolute path to avoid worktree resolution traps (relative
# core.hooksPath resolves differently in linked worktrees).
#
# Idempotent: re-running with the same target is a no-op. Warns loudly
# and overwrites if core.hooksPath is already pointed at something else
# (e.g. pre-commit.com or lefthook).
#
# Usage:
#   bash scripts/setup-hooks.sh          # verbose (default)
#   bash scripts/setup-hooks.sh --quiet  # only print on state change
set -euo pipefail

QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
TARGET="$REPO_ROOT/.githooks"
CURRENT=$(git config --get core.hooksPath || echo "")

if [[ -n "$CURRENT" && "$CURRENT" != "$TARGET" ]]; then
  echo "WARN: core.hooksPath is already set to: $CURRENT" >&2
  echo "      Overwriting with: $TARGET" >&2
  echo "      (If you use another hook manager like pre-commit.com or lefthook, revert with:" >&2
  echo "         git config core.hooksPath '$CURRENT')" >&2
fi

if [[ "$CURRENT" != "$TARGET" ]]; then
  git config core.hooksPath "$TARGET"
  if [[ $QUIET -eq 1 ]]; then
    echo "Installed git hooks. Bypass individual commits/pushes with --no-verify."
  else
    echo "Installed give-back git hooks at $TARGET."
    echo "Bypass individual commits/pushes with --no-verify."
  fi
else
  # State unchanged. In --quiet mode, print nothing. In verbose, confirm.
  if [[ $QUIET -eq 0 ]]; then
    echo "Git hooks already installed at $TARGET."
  fi
fi
