# Phase 2B — Core and database extraction

## Summary

Extracted application startup configuration, database configuration exceptions, and SQLite/PostgreSQL connection adapters from `hris_server.py` into `backend.app`. The existing handler remains the compatibility facade and retains its public database globals/functions for current application code, tests, and scripts.

No API behavior, authentication logic, schema, migration, seed data, dependency declaration, Vercel configuration, or deployment behavior was intentionally changed.

## Before

`hris_server.py` contained environment loading, DB-related configuration, exception classes, optional `psycopg` imports, error tuples, the PostgreSQL wrapper, SQLite/PostgreSQL connection selection, local SQLite initialization, and all other HTTP/auth/domain logic.

`api/index.py`, `scripts/create_hr_admin.py`, and tests import `hris_server`. Existing tests and provisioning code patch or assign `hris_server.DATABASE_URL` and `hris_server.connect_database`.

## After

```text
backend/
  __init__.py
  app/
    __init__.py
    core/
      __init__.py
      config.py
      exceptions.py
    database/
      __init__.py
      connection.py
      postgres.py
      sqlite.py
hris_server.py                 # compatibility facade plus existing application handler
```

## Files created

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` | Loads the existing `.env.local` using the same options and defines `BASE_DIR`, `DATABASE_URL`, `DATABASE_PATH`, `HOST`, and `PORT`. |
| `backend/app/core/exceptions.py` | Defines `DatabaseConfigurationError` and its `DemoConfigurationError` subclass. |
| `backend/app/database/sqlite.py` | Opens SQLite using the existing path, timeout, row factory, foreign-key pragma, and WAL pragma. |
| `backend/app/database/postgres.py` | Optional psycopg import, error aliases, placeholder-translating `PostgresConnection`, and TLS-enforced PostgreSQL connection. |
| `backend/app/database/connection.py` | Selects the configured database adapter and exposes the established database error tuples. |
| Package `__init__.py` files | Allow direct Python package imports without adding dependencies. |
| `docs/architecture/migration/phase-2b-core-database.md` | This Phase 2B implementation record. |

## Files changed

| File | Change |
|---|---|
| `hris_server.py` | Imports extracted configuration/errors/adapters, re-exports the existing database symbols, and keeps a zero-argument `connect_database()` wrapper. |

The Phase 2A characterization test in `tests/test_hris_api.py` was preserved and not modified in Phase 2B. Phase 1 audit documents were also left untouched.

## Responsibilities and dependencies

```text
core.config ───────────────> dotenv, standard library
core.exceptions ──────────> standard library
database.sqlite ──────────> sqlite3
database.postgres ────────> core.exceptions, optional psycopg
database.connection ──────> core.exceptions, sqlite adapter, postgres adapter
hris_server.py ───────────> core configuration/exceptions, database facade
```

There are no imports from the new modules back into `hris_server.py`, `api/index.py`, or scripts, avoiding a circular dependency. Local SQLite schema initialization remains in `hris_server.initialize_database()` and executes in the same order as before. PostgreSQL schema migrations remain manual; no migrations or schema definitions were moved.

## Backward compatibility

- `hris_server.DATABASE_URL`, `DATABASE_PATH`, `HOST`, and `PORT` remain available.
- `hris_server.connect_database()` remains zero-argument and delegates using the current facade globals. Therefore assigning or patching `hris_server.DATABASE_URL` or `hris_server.DATABASE_PATH` changes the adapter behavior used by existing callers.
- Runtime handler and scripts continue resolving `connect_database` through the `hris_server` module, so `patch("hris_server.connect_database", ...)` remains effective.
- `PostgresConnection`, `psycopg`, `dict_row`, database configuration exceptions, and database error tuples remain available from `hris_server`.
- The Postgres adapter retains `connect_timeout=5`, `sslmode="require"`, the psycopg dict row factory, and `?` to `%s` placeholder translation.
- SQLite retains its 10-second timeout, `sqlite3.Row`, foreign keys, WAL mode, and parent-directory creation.

## Environment variable names

Configuration module values are initialized from `DATABASE_URL`, `HRIS_DATABASE_PATH`, `HRIS_HOST`, and `HRIS_PORT`. `.env.local` loading remains local and does not override existing process environment values.

Other environment reads remain at their existing runtime locations because this phase does not extract demo/auth/origin policy: `HRIS_ALLOWED_ORIGINS`, `HRIS_DEMO_MODE`, `HRIS_DEMO_SESSION_SECRET`, `HRIS_DEMO_PASSWORD`, `VERCEL`, `VERCEL_ENV`, `VERCEL_URL`, and `VERCEL_PROJECT_PRODUCTION_URL`. No values are recorded here. No `.env.example` existed in the inspected repository; none was added.

## Validation

- Focused compatibility and adapter tests: **4 passed**.
- Full suite: **59 tests run, 57 passed, 2 optional Neon integration tests skipped** (`HRIS_TEST_DATABASE_URL` not configured).
- `python -m compileall -q .`: passed.
- All new backend modules and `hris_server` imported successfully.
- `git diff --check`: passed.
- Existing temporary SQLite tests continue to isolate their DB under a temporary directory.
- PostgreSQL connection/placeholder behavior remains covered by mocks; no external database was contacted.

## Limitations and remaining work

- `hris_server.py` still owns SQLite schema initialization and seed behavior, HTTP routing, origin policy, auth/session logic, business logic, and domain SQL. These are explicitly out of scope for Phase 2B.
- Configuration is loaded once at import time, as before. Tests that modify database configuration continue to patch the facade globals.
- PostgreSQL behavior was not verified against a live server; only adapter mocks and the optional target-guard tests ran.
- Vercel Function packaging/deployment was not executed. The root `api/index.py` and `vercel.json` were not changed.
- No production database, deployment, environment configuration, migrations, or schema was modified.
