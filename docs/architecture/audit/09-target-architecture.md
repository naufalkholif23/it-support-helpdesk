# 09 — Target architecture and migration map

## Design decision

Use the agreed **single modular project / modular monolith**: Employee Portal, HRIS Admin, and Helpdesk remain separate frontend areas and backend domain modules while sharing one authentication/authorization system and one primary database. Keep the current HTML/CSS/JavaScript and Python stack. Do not introduce a framework or service split without evidence that the existing deployment model cannot support the requirement.

## Proposed structure

```text
employee-hub/
  apps/
    employee-portal/
      index.html
      modules/
    hris-admin/
      index.html
      modules/
    helpdesk/
      index.html
      modules/
  shared/
    frontend/
      components/
      navigation/
      localization/
      api-client.js
      styles/
    contracts/
  backend/
    app/
      api/
        routes/
        responses.py
      auth/
        sessions.py
        passwords.py
        csrf.py
        permissions.py
      core/
        config.py
        errors.py
        logging.py
      database/
        connections.py
        repositories/
      modules/
        dashboard/
        employees/
        helpdesk/
      web/
        local_server.py
  api/
    index.py                 # thin Vercel-compatible entry
  migrations/
  scripts/
  tests/
    unit/
    integration/
    e2e/
  docs/
    architecture/
    database/
    api/
    deployment/
```

This is a logical target, not a mandate to create every directory in one change. Keep entry points shallow and split only when responsibilities are extracted and tested. Preserve root static route compatibility or configure verified rewrites for new app entry pages.

## Dependency rules

1. Frontend modules depend on shared frontend components and API contracts, never on database internals.
2. API route handlers depend on auth/policy and module services; they should not own SQL.
3. Domain services depend on repositories/interfaces, not HTTP request objects.
4. Database adapters own SQLite/PostgreSQL dialect and connection behavior.
5. Auth and permission policies are shared by all three application areas. Module-specific policies remain explicit and server-side.
6. `api/index.py` is deployment glue only; business rules stay in the shared Python application package.
7. Migrations describe approved persistent schema changes and are never executed on request startup.

## Target file map

| Current file | Current responsibility | Proposed destination | Priority | Dependencies / risk |
|---|---|---|---|---|
| [index.html](../../../index.html) | Main shell, navigation, multiple page views, inline styles/scripts, directory/dashboard and Helpdesk prototype. | Split shell into `shared/frontend`; Employee Portal, HRIS Admin and Helpdesk views into `apps/*`; keep route compatibility. | High | Most cross-cutting UI risk; preserve fragments, responsive behavior, localization, branding, and API contracts. |
| [login.html](../../../login.html) | HRIS login and demo entry. | Shared auth UI under `shared/frontend` or a stable root route. | Medium | Must preserve return URL validation, cookie/session behavior, and demo separation. |
| [platform.html](../../../platform.html) | Platform selector. | Shared public landing entry, retaining current route. | Low | Ensure root and static rewrites remain compatible. |
| [admin-login.html](../../../admin-login.html) | Legacy client-side Helpdesk login. | Replace access gate with shared auth; retain page only as transitional public prototype. | High | Hardcoded/client-side auth cannot protect data; coordinate with server policy. |
| [admin.html](../../../admin.html) | Helpdesk local ticket administration. | `apps/helpdesk` admin UI with shared API client. | High | Must not imply secure admin access until backend authorization exists. |
| [hris_server.py](../../../hris_server.py) | Handler, routing, auth, database, validation, demo and business logic. | `backend/app/*`; keep compatibility wrapper during staged extraction. | Highest | Security and Vercel runtime risk; migrate one responsibility per reviewable change. |
| [api/index.py](../../../api/index.py) | Vercel route adapter. | Keep at root `api/index.py` as a thin adapter importing backend app. | Highest | Vercel discovery and rewrite compatibility. |
| [migrations/001_core_hr.sql](../../../migrations/001_core_hr.sql) | Core PostgreSQL schema. | Keep in `migrations/` with migration state/versioning added only after approval. | Medium | Existing data compatibility; no rewrite or destructive migration. |
| [migrations/002_user_email_login.sql](../../../migrations/002_user_email_login.sql) | Add user email and unique index. | Keep in ordered migration directory. | Medium | Existing email population and uniqueness must remain documented. |
| [requirements.txt](../../../requirements.txt) | Python runtime dependencies. | Keep at deploy root or configure build explicitly if reorganized. | Low | Vercel install discovery; test packaging. |
| [scripts/create_hr_admin.py](../../../scripts/create_hr_admin.py) | Guarded admin provisioning. | `scripts/` using extracted config/database/auth APIs. | Medium | Preserve strict target verification and prompt behavior. |
| [tests/test_hris_api.py](../../../tests/test_hris_api.py) | API/auth/DB tests. | `tests/integration/` with unit tests added separately. | Medium | Preserve temp DB isolation and test discovery. |
| [tests/test_create_hr_admin.py](../../../tests/test_create_hr_admin.py) | Admin bootstrap safety tests. | `tests/unit/` or `tests/integration/` based on final test boundaries. | Low | Keep all wrong-target rejection cases. |
| [tests/test_neon_postgres.py](../../../tests/test_neon_postgres.py) | Neon safety and optional integration checks. | `tests/integration/` and remain explicitly opt-in. | Medium | External DB side effects; never run on persistent environments. |
| [vercel.json](../../../vercel.json) | Function inclusion, rewrites, headers. | Keep at root and update only after route/package verification. | Highest | Entry and static routing regression can block all deployments. |
| [.vercelignore](../../../.vercelignore) | Function/deploy exclusions. | Keep at root; update as migration docs/modules are moved. | Medium | Accidental exclusion of runtime imports or inclusion of test artifacts. |
| [README.md](../../../README.md) | Setup, security, API, demo, deployment and limitations. | Keep as entry docs; link to maintained architecture/API/deployment docs. | Medium | Avoid conflicting setup and safety instructions. |
| [requirements.txt](../../../requirements.txt), [package.json](../../../package.json), [package-lock.json](../../../package-lock.json), [neon.ts](../../../neon.ts), [skills-lock.json](../../../skills-lock.json) | Python/Neon tooling declarations and lock/config files. | Retain only where actively used; document purpose and do not remove based on name alone. | Low | Package tooling and deployment discovery; usage should be confirmed before pruning. |
| [logo-green.png](../../../logo-green.png), [favicon.ico](../../../favicon.ico) | Brand assets. | Shared static assets. | Low | Preserve paths or update every reference. |
| [.gitignore](../../../.gitignore) | Ignore secrets, local databases, generated files. | Keep at root and extend only with verified generated paths. | High | Must continue protecting credentials and local data. |

## Architecture decisions still needed

- Whether Helpdesk accepts anonymous ticket creation or requires an Employee Portal session.
- Which roles own Helpdesk tickets/assets/knowledge, and whether current `users.role` values must be extended.
- How each authenticated employee maps to exactly one employee record and what fields are self-editable.
- Which planned HRIS features are in scope for implementation versus preserved as placeholders.
- Data retention, audit scope, privacy, backup/restore, and approval policies for real HR data.

No target folders or application code were created or moved as part of the audit.
