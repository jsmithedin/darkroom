# Branch protection, Actions hardening and test review (issue #87)

Done 2026-11-24, after the repo became public.

## Settings applied
- **`main` protection:** pull request required (0 approvals, single maintainer), status checks
  `backend`, `frontend`, `image` and `skills` must pass, no force pushes, no deletion, and it
  applies to admins too. "Up to date before merge" is **off**: CI also runs on `main` after
  every merge, and requiring it breaks stacked PRs (each merge forces the next to be updated
  and re-run). If a check is renamed, update the rule or merges will wait forever. In an
  emergency, an admin can turn off "Do not allow bypassing" in the branch rule.
- **Merge settings:** merge commits, squash and rebase are all allowed (history uses merge
  commits); merged branches are deleted automatically.
- **Actions:** workflow token defaults to read-only (already); fork PR workflows need approval
  for **all** outside contributors (was first-time only).
- **Security:** secret scanning and push protection enabled; Dependabot security updates were
  already on; `.github/dependabot.yml` adds weekly version updates for uv, npm, Actions and
  Docker, grouped to minor and patch.

## Self-hosted runner risk (PR #41)
`deploy.yml` is safe as written: it runs only from `workflow_run` after CI passes on a push to
`main`, only for this repository, with read-only permissions. The residual risk is the runner
itself. On a public repo any workflow file from a fork PR could ask for `runs-on: self-hosted`;
the approval requirement above is what stops it, so **never approve a fork PR's workflows
without reading them**. If that is uncomfortable, a pull-based deploy on the NUC (a timer that
fetches `main`, builds and restarts when CI is green) removes the runner and the risk. Free
GitHub plans cannot restrict a runner to specific workflows.

## Test review
- Backend: 619 tests in about 4.5 minutes locally; 97% statement coverage. Weakest files:
  `auth/google.py` (62%, the real Google OIDC network calls are faked in tests) and
  `importer/cli.py` (75%).
- Frontend: 119 tests; 85% statements, 82% branches, 80% functions. Weakest: `api/hooks.ts`,
  `RefList.tsx` and `Purchases.tsx` (about 60 to 70%).
- CI now enforces **floors, not targets**: backend 95% (`--cov-fail-under`), frontend 80%
  statements and lines, 75% branches and functions. They sit a little under today's numbers so
  they catch a real drop without punishing a small refactor. Raise them when coverage rises.
- Migrations: every backend test run builds the schema from empty with Alembic, and
  `test_models_match_migrations` fails if models and migrations drift. There is no
  upgrade-from-previous-release test; with one deployment and a backup before each deploy,
  that is not worth building yet.
- Dependency audit: left to Dependabot alerts and security updates rather than a CI step that
  can fail for reasons unrelated to a change.
- The `image` job builds the Docker image, imports `app.main`, checks compose has no `ports:`
  and runs the backup self-test.

## Still open (not worth doing now)
- A browser end-to-end test (Playwright) of logging a roll, and a PWA install check.
- The OAuth flow is tested against fakes; it has now also been used for real from Claude
  Desktop (see `claude-skills.md`).
