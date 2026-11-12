# 10 — Migration roadmap

## Principles

- Incrementally extract the existing modular monolith; do not rebuild it.
- Keep Employee Portal, HRIS Admin, and Helpdesk logically separated while sharing backend, identity/authorization, and the approved primary database.
- Preserve current URLs, visual design, existing login, directory behavior, API contracts, Vercel compatibility, and data.
- Each phase is a separate reviewable branch/commit with tests and an explicit rollback. Do not deploy or change Production settings without separate approval.
- Do not turn placeholders into claims of implemented workflows; scope new feature work separately.

## Phase 0 — Baseline and contracts

**Objective:** Record current runtime/API/visual behavior and agree policy contracts before moving code.  
**Files/modules:** Existing `README.md`, `vercel.json`, `api/index.py`, `hris_server.py`, current HTML and tests; add tests/docs only when approved.  
**Dependencies:** Audit acceptance; decisions on roles, Helpdesk access, Employee Portal identity mapping, environments, and feature scope.  
**Expected output:** Baseline API snapshots, route/role matrix, responsive/UI checklist, non-secret environment matrix, test baseline, migration/rollback conventions.  
**Risks:** Assuming prototype behavior is a production contract; collecting real data.  
**Required tests:** Existing Python suite; synthetic browser smoke baseline; verify external DB tests are not implicitly enabled.  
**Acceptance:** Existing route and authorization behavior is documented and reproducible; open product/security decisions are resolved or explicitly deferred.  
**Rollback:** No runtime changes; discard only the phase’s newly added documentation/test commit if rejected.

## Phase 1 — Backend foundation extraction

**Objective:** Separate config, errors, database connections, auth policy, and HTTP adapter without changing behavior.  
**Files/modules:** Extract from `hris_server.py` into `backend/app/core`, `auth`, and `database`; retain `hris_server.py` as a compatibility facade; keep root `api/index.py`.  
**Dependencies:** Phase 0 contracts.  
**Expected output:** Importable modular package, same local server entry, same Vercel adapter, unchanged API responses and schema.  
**Risks:** Import/bundling failure on Vercel, cookie/session changes, SQLite/PostgreSQL divergence.  
**Required tests:** Existing 58-pass baseline, auth/session/CSRF/RBAC tests, SQLite adapter tests, Vercel path reconstruction tests.  
**Acceptance:** All existing tests pass; no API/schema changes; local and function imports resolve; demo still works without `DATABASE_URL`.  
**Rollback:** Revert the extraction commit, retaining all pre-existing files; do not roll back database state because none changes.

## Phase 2 — HRIS services and repositories

**Objective:** Move employee and dashboard SQL/business rules behind repositories and module services.  
**Files/modules:** `backend/app/modules/employees`, `backend/app/modules/dashboard`, `database/repositories`; update tests and thin route handlers.  
**Dependencies:** Phase 1; stable authorization and response contracts.  
**Expected output:** Modular HRIS services with unchanged list/detail/CRUD and aggregate behavior.  
**Risks:** Search/filter/sort/pagination regressions, transaction or audit loss, stale update handling differences.  
**Required tests:** Existing API suite plus repository parity tests on temporary SQLite and, when explicitly safe, disposable PostgreSQL.  
**Acceptance:** API contracts, authorization, audit records, optimistic conflict handling, and database behavior match baseline.  
**Rollback:** Revert service extraction; no schema migration or data transformation in this phase.

## Phase 3 — Frontend shared shell and HRIS/Employee separation

**Objective:** Extract the existing inline frontend into shared shell components and area-owned views without redesigning.  
**Files/modules:** Gradual extraction from `index.html`; `login.html`, `platform.html`; new `shared/frontend`, `apps/employee-portal`, `apps/hris-admin`.  
**Dependencies:** Phase 0 visual baseline; API contracts stable.  
**Expected output:** Separate area ownership, shared navigation/API/localization helpers, preserved visual identity and routes.  
**Risks:** Broken hash routes, event listeners, language switching, mobile layout, auth gates, direct refresh.  
**Required tests:** Browser smoke tests for root, login, dashboard direct link, refresh, all existing nav links, language switching, mobile sidebar, and API error states.  
**Acceptance:** Existing visual and behavior baseline is preserved; unimplemented areas remain clearly placeholders; no unauthorized data is rendered.  
**Rollback:** Restore previous entry point/rewrite and revert only the frontend extraction commit.

## Phase 4 — Helpdesk authentication and backend boundary

**Objective:** Replace client-only access checks with the shared server auth/authorization system.  
**Files/modules:** `admin-login.html`, `admin.html`, Helpdesk frontend module, shared auth policies, API routing and tests.  
**Dependencies:** Role/access decisions from Phase 0; shared auth foundation; database ownership and retention approval.  
**Expected output:** Authenticated Helpdesk admin routes and explicit permission checks; legacy demo credentials no longer serve as a trust boundary.  
**Risks:** Existing prototype semantics differ from real support workflow; role enumeration/schema compatibility; anonymous ticket abuse if allowed.  
**Required tests:** Anonymous/employee/manager/HR/admin permission matrix; CSRF/origin tests; direct API calls; ticket audit and ownership tests.  
**Acceptance:** No Helpdesk privileged operation is authorized only by JavaScript/local storage; policy is documented and tested.  
**Rollback:** Revert only new route/UI changes; preserve legacy prototype as clearly non-sensitive fallback if product approves. Never migrate sensitive production data in this phase.

## Phase 5 — Helpdesk persistence (only if approved)

**Objective:** Replace browser-local ticket/assets data with shared backend/database modules.  
**Files/modules:** Helpdesk services/repositories/API, approved migration SQL, frontend API client, integration tests.  
**Dependencies:** Phase 4; approved schema, data ownership, retention, migration/backfill policy, and anonymous-vs-authenticated submission decision.  
**Expected output:** Shared durable Helpdesk data with server-side validation, authorization, audit, and explicit error behavior.  
**Risks:** Data loss/duplication, unsafe localStorage import, changed ticket workflow, migration rollback.  
**Required tests:** Migration forward/rollback on disposable DBs, authorization matrix, persistence/reload, conflict handling, backup/restore rehearsal.  
**Acceptance:** Migrations are additive/reviewed, existing HRIS behavior is unchanged, and no browser-only authorization remains.  
**Rollback:** Application rollback first; use a reviewed backward-compatible schema plan. Never drop or rewrite tables as an automatic rollback.

## Phase 6 — Employee Portal identity and scoped workflows

**Objective:** Implement approved employee self-service with strong user-to-employee ownership.  
**Files/modules:** Auth identity mapping, employee repository/service, Portal APIs/UI, migrations only as approved, tests.  
**Dependencies:** Verified account provisioning and employee mapping; privacy/field edit policy; Phase 1/2 architecture.  
**Expected output:** Explicitly scoped profile and individually approved workflows (not all possible HRIS modules at once).  
**Risks:** Cross-employee disclosure, incorrect identity mapping, exposing sensitive HR/payroll fields.  
**Required tests:** Own-record access, cross-record denial, role changes, session revocation, redaction/field policy, audit/retention.  
**Acceptance:** Every endpoint derives employee identity from server session and enforces ownership; no client-supplied employee ID can override policy.  
**Rollback:** Disable the new routes/UI via a reviewed feature gate; preserve old schema/data and existing admin functions.

## Phase 7 — Vercel/deployment hardening and operations

**Objective:** Validate modular packaging and documented environment boundaries without accidental Production changes.  
**Files/modules:** `vercel.json`, `api/index.py`, `.vercelignore`, `requirements.txt`, deployment docs, test workflow.  
**Dependencies:** Runtime modules stable; authorized Preview access.  
**Expected output:** Verified Preview build, exact route behavior, scoped environment variables, independent Preview/Production databases, operational rollback runbook.  
**Risks:** Wrong project/branch/DB scope, public exposure, missing Python imports, accidental production deployment.  
**Required tests:** Local packaging check, Preview-only deployment smoke tests after separate approval, auth/demo isolation and sensitive API denial.  
**Acceptance:** Deployment commit matches reviewed branch; Preview URL and environment are verified; no Production branch/domain/settings changed without explicit approval.  
**Rollback:** Revert Preview branch commit or restore prior Preview deployment; never use `vercel --prod` or alter Production without explicit authorization.

## Cross-phase acceptance

- Every phase preserves existing features and records unsupported behavior honestly.
- No changes to Production data, environment variables, domains, branch, or deployment without separate explicit approval.
- Existing tests remain safe and reproducible; external DB tests are opt-in and target-verified.
- Schema changes are additive, reviewed, and independently reversible; database backups are verified before any production migration.
- Changes to public demo behavior maintain synthetic data isolation and server-side read-only enforcement.

## Local implementation status

- The existing modularization through Phase 2E is present; its verification is recorded in [Phase 2E](../migration/phase-2e-http-utilities.md).
- The local Helpdesk now uses the shared server session, role authorization, CSRF/origin checks, and SQLite-backed ticket APIs. The employee portal can read the signed-in account's explicitly linked, non-sensitive employee profile.
- `employee.demo` is linked only to the synthetic `SAMPLE-001` employee during local initialization. Other seeded accounts are not implicitly mapped to employee records.
- `admin-login.html` delegates to shared sign-in; `admin.html` is a Helpdesk staff view for `it_support`, `hr_admin`, and `system_admin`. These local roles and workflows have not been approved as a production access policy.
- Local tickets and profile mapping are not automatically migrated to PostgreSQL. `migrations/003_helpdesk_local.sql` is a manual schema artifact and has not been run against an external database.
- Attachments, asset inventory persistence, generic employee requests, attendance, leave, payroll, and other HR workflows remain unimplemented or prototype-only. Deployment hardening and production readiness remain out of scope.

## Outstanding decisions before implementation

1. Helpdesk ticket creation: anonymous, employee-authenticated, or both?
2. What permissions should `helpdesk_admin`/support roles have, and should they be distinct from HR/system administrators?
3. How will each employee user be provisioned and mapped to an employee record?
4. Which real workflows are in scope for the first implementation phase versus preserved as placeholders?
5. What retention, privacy, audit, and backup requirements apply to employee and support records?
6. Which Vercel environments and deployment branches are approved for future validation?
