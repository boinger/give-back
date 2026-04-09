#!/usr/bin/env bash
# Smoke test for the git hooks + CI-parity Makefile infrastructure.
#
# Run via: make test-hooks
#
# Not wired into 'make test' on purpose — the pytest suite runs in ~2s and
# this smoke test adds noticeable overhead (shells out to make several times).
# Run it manually when touching hook scripts, the Makefile ci targets, or
# scripts/setup-hooks.sh.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "  ✓ $*"
}

echo "Smoke testing git hooks + CI-parity infrastructure..."

# 1. Hook files exist and are executable.
[[ -f .githooks/pre-commit ]] || fail ".githooks/pre-commit is missing"
[[ -f .githooks/pre-push    ]] || fail ".githooks/pre-push is missing"
[[ -x .githooks/pre-commit ]] || fail ".githooks/pre-commit is not executable"
[[ -x .githooks/pre-push    ]] || fail ".githooks/pre-push is not executable"
pass "hook files exist and are executable"

# 2. setup-hooks.sh exists and is executable.
[[ -f scripts/setup-hooks.sh ]] || fail "scripts/setup-hooks.sh is missing"
[[ -x scripts/setup-hooks.sh ]] || fail "scripts/setup-hooks.sh is not executable"
pass "setup-hooks.sh exists and is executable"

# 3. .gitattributes protects hook line endings.
grep -q '.githooks/\*\s*text eol=lf' .gitattributes || fail ".gitattributes missing .githooks/* LF rule"
pass ".gitattributes enforces LF on .githooks/"

# 4. make ci passes on the clean tree.
if ! make ci >/dev/null 2>&1; then
  fail "make ci failed on clean tree"
fi
pass "make ci passes on clean tree"

# 5. make ci-fast passes on the clean tree.
if ! make ci-fast >/dev/null 2>&1; then
  fail "make ci-fast failed on clean tree"
fi
pass "make ci-fast passes on clean tree"

# 6. make pre-commit alias still works.
if ! make pre-commit >/dev/null 2>&1; then
  fail "make pre-commit alias broken"
fi
pass "make pre-commit alias works"

# 7. setup-hooks is idempotent (re-run produces same state).
bash scripts/setup-hooks.sh --quiet >/dev/null 2>&1 || fail "setup-hooks initial run failed"
BEFORE=$(git config --get core.hooksPath || echo "")
bash scripts/setup-hooks.sh --quiet >/dev/null 2>&1 || fail "setup-hooks re-run failed"
AFTER=$(git config --get core.hooksPath || echo "")
if [[ "$BEFORE" != "$AFTER" ]]; then
  fail "setup-hooks not idempotent (before=$BEFORE after=$AFTER)"
fi
pass "setup-hooks is idempotent"

# 8. setup-hooks set an ABSOLUTE path (not relative) — avoids worktree trap.
CURRENT=$(git config --get core.hooksPath || echo "")
if [[ "$CURRENT" != /* ]]; then
  fail "core.hooksPath is not absolute (got: $CURRENT)"
fi
pass "core.hooksPath is absolute: $CURRENT"

# 9. setup-hooks warns if core.hooksPath points somewhere else.
ORIG=$(git config --get core.hooksPath || echo "")
git config core.hooksPath "/tmp/give-back-smoke-test-bogus-$$"
WARN_OUTPUT=$(bash scripts/setup-hooks.sh --quiet 2>&1 || true)
if ! echo "$WARN_OUTPUT" | grep -q "WARN"; then
  git config core.hooksPath "$ORIG"  # restore before failing
  fail "setup-hooks did not warn when overwriting a non-default hooksPath"
fi
pass "setup-hooks warns when overwriting non-default hooksPath"
# setup-hooks will have already restored the correct path; verify.
AFTER_WARN=$(git config --get core.hooksPath || echo "")
[[ "$AFTER_WARN" == "$ORIG" ]] || fail "setup-hooks did not restore correct path after warn (got: $AFTER_WARN)"

echo ""
echo "All hook smoke tests passed."
