# 01 — Project inventory

## Scope and evidence

Read-only audit of branch `refactor/clean-architecture` at `b72d1ffdcb568c8a5e9ac23db0c1dfe3d4f6d89f`. The working tree was clean before these audit documents were added. The repository has 24 tracked files. No secret values, environment files, deployment settings, or databases were read.

The inventory and architectural findings below are based on tracked files and source/configuration review. Static image and icon files were inventoried, not semantically inspected.

## Tracked-file inventory

| Group | Count | Files |
|---|---:|---|
| HTML | 5 | [index.html](../../../index.html), [platform.html](../../../platform.html), [login.html](../../../login.html), [admin-login.html](../../../admin-login.html), [admin.html](../../../admin.html) |
| Python | 6 | [hris_server.py](../../../hris_server.py), [api/index.py](../../../api/index.py), [scripts/create_hr_admin.py](../../../scripts/create_hr_admin.py), [tests/test_hris_api.py](../../../tests/test_hris_api.py), [tests/test_create_hr_admin.py](../../../tests/test_create_hr_admin.py), [tests/test_neon_postgres.py](../../../tests/test_neon_postgres.py) |
| SQL | 2 | [migrations/001_core_hr.sql](../../../migrations/001_core_hr.sql), [migrations/002_user_email_login.sql](../../../migrations/002_user_email_login.sql) |
| JSON | 4 | [package.json](../../../package.json), [package-lock.json](../../../package-lock.json), [skills-lock.json](../../../skills-lock.json), [vercel.json](../../../vercel.json) |
| TypeScript | 1 | [neon.ts](../../../neon.ts) |
| Markdown | 1 | [README.md](../../../README.md) |
| Text | 1 | [requirements.txt](../../../requirements.txt) |
| Image/icon | 2 | [logo-green.png](../../../logo-green.png), [favicon.ico](../../../favicon.ico) |
| Extensionless configuration | 2 | [.gitignore](../../../.gitignore), [.vercelignore](../../../.vercelignore) |
| **Total** | **24** | |

No separate CSS, frontend JavaScript, framework source tree, checked-in database file, `.env.example`, or additional migration files were present in the tracked inventory. Most application styling and browser logic are embedded in HTML.

## Entry points and responsibilities

| Entry point | Verified responsibility |
|---|---|
| [platform.html](../../../platform.html) | Public platform-selection page; entry routes lead into the Employee Hub/HRIS experience. |
| [index.html](../../../index.html) | Main application shell: sidebar/navigation, dashboard and module views, localization, frontend authentication checks, and Helpdesk prototype UI/data behavior. This is a large, combined responsibility. |
| [login.html](../../../login.html) | HRIS server-session login, demo entry UI, and return destination handling. |
| [admin-login.html](../../../admin-login.html) | Legacy Helpdesk prototype sign-in; credentials and role handling are client-side only. |
| [admin.html](../../../admin.html) | Legacy Helpdesk administration UI; ticket state is browser-local. |
| [hris_server.py](../../../hris_server.py) | Local Python HTTP server and Vercel function handler logic: routes, authentication, sessions, authorization, SQLite/PostgreSQL access, validation, HR business operations, demo data, and static-file handling. |
| [api/index.py](../../../api/index.py) | Vercel Python Function adapter. Reconstructs the original `/api/...` route from Vercel rewrite query parameters, then delegates to `HRISHandler`. |
| [scripts/create_hr_admin.py](../../../scripts/create_hr_admin.py) | Explicitly guarded administrator provisioning utility. |

## Existing architectural pattern

**Verified:** The application is a static HTML/vanilla JavaScript frontend and a Python modular-monolith precursor. The backend is centralized in one handler module; Vercel exposes that handler through a single Python Function. SQLite supports local development, while PostgreSQL is selected by `DATABASE_URL`. Helpdesk behavior is not yet a shared-backend module: it primarily uses browser storage and separate client-side pages.

The runtime is compatible with a modular monolith, but the code is not yet separated by product area or service boundary. The architecture decision should therefore be implemented through incremental extraction, not a framework replacement.

## Large-responsibility files

- [index.html](../../../index.html): combines shell, navigation, responsive styling, many route views, English/Indonesian strings, authentication/session checks, API client behavior, and Helpdesk local persistence. Changes here have broad visual and routing regression risk.
- [hris_server.py](../../../hris_server.py): combines HTTP transport, routing, static serving, auth/session/CSRF, RBAC, data adapters, SQL, validation, domain operations, demo handling, and logging. Changes here have broad security and deployment risk.
- [admin.html](../../../admin.html) and [admin-login.html](../../../admin-login.html): Helpdesk presentation, storage, and a client-only access gate are co-located.

## Dependency declarations

- [requirements.txt](../../../requirements.txt): `psycopg[binary]` and `python-dotenv`; no Python web framework is declared.
- [package.json](../../../package.json) and [package-lock.json](../../../package-lock.json): Neon-related Node packages; the application frontend has no Node build or test scripts in the manifest.
- [neon.ts](../../../neon.ts): Neon tooling/configuration surface, not the application’s Python database adapter.

## Configuration and documentation

Deployment behavior is in [vercel.json](../../../vercel.json), the Vercel adapter [api/index.py](../../../api/index.py), and [.vercelignore](../../../.vercelignore). [README.md](../../../README.md) documents setup, deployment, tests, demo mode, API, and known limitations. [.gitignore](../../../.gitignore) excludes local environment/configuration and database artifacts.

## Important unknowns

- Vercel project settings, Deployment Protection, branch-to-project connection, actual deployment status, and environment-variable presence/scope were not accessible from the repository and were not inspected.
- No local `.env` values were read. Referenced variable names and their configuration status are documented in [07-vercel-deployment-audit.md](07-vercel-deployment-audit.md).
- No live database was connected to. Schema findings are limited to source initialization and migration SQL.
- The exact browser behavior of every prototype route has not been exhaustively exercised in a browser during this read-only audit.

See [09-target-architecture.md](09-target-architecture.md) for the file-level migration map and [10-migration-roadmap.md](10-migration-roadmap.md) for an independently reviewable sequence.
