# TODOs

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

