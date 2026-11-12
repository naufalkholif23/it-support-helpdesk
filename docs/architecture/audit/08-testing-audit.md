# 08 — Testing audit

## Existing test infrastructure

The repository uses Python `unittest` with three test files:

| Test file | Coverage area |
|---|---|
| [tests/test_hris_api.py](../../../tests/test_hris_api.py) | HTTP/API behavior, SQLite-backed auth/session/CSRF/RBAC, demo mode, database behavior, employee CRUD, logging, and validation. |
| [tests/test_create_hr_admin.py](../../../tests/test_create_hr_admin.py) | Safe Neon target validation and administrator provisioning behavior with test doubles. |
| [tests/test_neon_postgres.py](../../../tests/test_neon_postgres.py) | Neon branch/endpoint validation plus optional PostgreSQL integration checks. |

Run command documented by [README.md](../../../README.md): `python -m unittest discover -s tests -v`.

## Existing evidence

The exact audited commit `b72d1ffdcb568c8a5e9ac23db0c1dfe3d4f6d89f` was tested in the prior work history: **58 tests passed; 2 optional Neon integration tests were skipped**. That is existing evidence, not a new test execution in this read-only audit. No tests were run in this audit phase.

`test_neon_postgres.py` contains integration tests that may create and delete rows in an external database. They require explicit `HRIS_TEST_DATABASE_URL` and are guarded against unsuitable targets; they must not be run against Preview or Production. The existing API tests use temporary SQLite paths and synthetic data according to the test setup and README.

## Coverage gaps

- No frontend unit, component, browser, or end-to-end test runner is configured.
- No cross-browser/responsive visual baseline is checked automatically.
- No route-wide permission matrix is evident for future modules.
- No automated check guarantees each SQL migration is applied in order and matches SQLite behavior.
- No Helpdesk server tests exist because Helpdesk remains browser-local.
- No employee self-service ownership tests exist because the corresponding backend is absent.
- Deployment routing, Vercel Function packaging, CDN dependency behavior, and Vercel environment scoping are not covered by local unit tests.

## Safe test strategy for restructuring

1. Keep the existing `unittest` suite and run it after each backend extraction. Continue using temporary SQLite databases and never provide real employee data.
2. Keep Neon integration tests opt-in, require a disposable explicitly named testing branch/database, and avoid them unless the target is independently verified.
3. Add unit tests around extracted auth policy, validation, database adapters, and each module’s service boundary.
4. Add API contract/authorization tests for every route: anonymous, employee, manager, payroll admin, HR admin, system admin, and demo identity where relevant.
5. Add browser-level smoke tests for root entry, login, direct dashboard access, refresh, fragment navigation, language switching, sidebar behavior, and API error states. Use synthetic data only.
6. Add regression tests for exact Vercel rewrites and adapter route reconstruction without requiring a live deployment.
7. For schema work, test forward migration and restore/rollback procedure on disposable SQLite/PostgreSQL databases; never run destructive tests against persistent environments.
8. Use visual snapshots only as a guard for preserving branding/layout during extraction, not as a reason to redesign.

## Acceptance criteria for test migration

- Existing 58-pass/2-skip baseline remains reproducible without credentials or external database access.
- The test suite does not silently connect to a configured production/Preview `DATABASE_URL`.
- Demo mode tests pass with `DATABASE_URL` absent and prove synthetic data isolation and mutation denial.
- Each migration phase has its own focused tests and documented rollback.
- The optional integration suite remains safely opt-in and target-validated.
