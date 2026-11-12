# 03 — Backend and API audit

## Architecture

[hris_server.py](../../../hris_server.py) is both the local `http.server` application and the central Vercel runtime handler. It contains request routing, static-file behavior, origin checks, authentication, sessions, CSRF, role authorization, demo-mode logic, validation, SQL, SQLite/PostgreSQL connection behavior, dashboard/directory services, and logging. [api/index.py](../../../api/index.py) adapts Vercel rewrite query parameters into the routes expected by this handler and forwards GET/POST/PUT/DELETE.

This is a workable modular-monolith starting point, but transport, policy, domain logic, and persistence have high change coupling. No separate repository, service, controller, model, or domain-module packages were found.

## Endpoint inventory

All endpoints below are implemented in `hris_server.py`, with the Vercel adapter forwarding requests. The handler is the source of truth for authorization; frontend visibility is not an access boundary.

| Method | Route | Purpose and status | Authentication / permission | Data touched / consumer |
|---|---|---|---|---|
| GET | `/api/public-entry` | Redirect to dashboard in enabled demo mode, otherwise platform/login entry; implemented. | Public. | No database; browser entry. |
| GET | `/api/auth/session` | Check current server session; when public demo is enabled, creates/returns a demo session; implemented. | Public route; returns session identity only. | `sessions`, `users` for normal HRIS sessions; demo session path is signed and synthetic. Login shell and main app consume it. |
| POST | `/api/auth/login` | Authenticate username/email and password; create session; implemented. | Public login; same-origin origin validation. | `users`, `sessions`; `login.html`. |
| POST | `/api/auth/demo-login` | Start an isolated public demo session when configured; implemented conditionally. | Public only when demo mode is enabled; origin validation. | No real user/employee records; `login.html`/demo UI. |
| POST | `/api/auth/logout` | Revoke session and clear cookie; implemented. | Authenticated session and CSRF validation for the normal session flow; origin validation. | `sessions`; frontend logout. |
| GET | `/api/dashboard/summary` | Aggregate employee counts, status and department/creation metrics; implemented. | `hr_admin` or `system_admin`; demo returns hardcoded synthetic aggregates. | `employees`; HRIS dashboard. |
| GET | `/api/employees` | Search/filter/sort/page employee directory; implemented. | `hr_admin` or `system_admin`; demo returns synthetic employee list. | `employees`; Employee Directory. |
| GET | `/api/employees/{employeeId}` | Read one directory record; implemented. | `hr_admin` or `system_admin`; demo returns a synthetic record. | `employees`; Employee Directory detail. |
| POST | `/api/employees` | Create employee record; implemented. | Authenticated non-demo user, CSRF, `hr_admin` or `system_admin`; demo is denied. | `employees`, `audit_logs`; directory form. |
| PUT | `/api/employees/{employeeId}` | Validate/update employee record with optional optimistic concurrency; implemented. | Authenticated non-demo user, CSRF, `hr_admin` or `system_admin`; demo is denied. | `employees`, `audit_logs`; directory edit form. |
| DELETE | `/api/employees/{employeeId}` | Permanently delete employee record; implemented with explicit UI confirmation. | Authenticated non-demo user, CSRF, `hr_admin` or `system_admin`; demo is denied. | `employees`, `audit_logs`; directory UI. |

No backend endpoints for attendance, leave, payroll, recruitment, assets, announcements, approvals, or Helpdesk tickets were found in the route dispatch reviewed. Unmatched `/api/*` routes return not-found responses rather than invoking a generic data handler.

## Authentication and authorization placement

- User password verification, session issuance/revocation, cookie policy, demo tokens, CSRF, role checks and session lookup are all in `hris_server.py`.
- Normal protected requests resolve the server session, then apply role checks. Directory read and write policies currently use the same HR/system-admin role sets.
- Employee, manager, and payroll-admin roles are not granted directory access in the current policy.
- Demo identity is separately marked and synthetic endpoints are allowlisted. Mutating employee operations require both non-demo identity and a privileged role.
- POST requests use exact-origin checks; authenticated mutations use CSRF validation. Do not replace these with frontend-only checks.

## Database and business logic coupling

Handler functions execute parameterized SQL directly through a connection abstraction. SQLite is the local default; a PostgreSQL connection is selected when `DATABASE_URL` is set. The implementation normalizes placeholder syntax and abstracts connection details, but database querying and business validation remain mixed into HTTP flow.

The current core operations are dashboard aggregation, employee search/list/detail/create/update/delete, auth/session operations, and audit entries for employee mutations. There is no verified shared Helpdesk domain service.

## Error handling and logging

The handler maps validation failures to 400, unauthenticated requests to 401, denied permissions/origins to 403, missing resources/routes to 404, conflicts/integrity errors to 409, demo configuration failures to 503, and database failures to generic 500 responses. Database errors avoid exposing driver details to clients. Access logging normalizes employee detail paths and does not include search query strings.

This is useful baseline behavior, but response payloads are not yet represented by shared typed schemas, logs are plain output rather than structured audit/operational telemetry, and error translation is duplicated across HTTP methods.

## Vercel compatibility boundaries

- Keep root `api/index.py` as the discoverable Python Function entry or replace it only with an explicitly verified Vercel-compatible adapter.
- Preserve the `handler` interface and importability of Python dependencies and internal modules at function bundle time.
- Keep static files available at their expected routes and preserve the `__vercel_route` rewrite translation.
- Do not assume process-local state persists across invocations; session and HR data must remain in the database, while demo-session tokens are self-contained.
- Keep migrations out of request execution; they are reviewed, manually applied SQL.

## Recommended backend extraction map

| Existing responsibility | Current location | Target module |
|---|---|---|
| HTTP dispatch, JSON responses, origin validation, static routing | [hris_server.py](../../../hris_server.py) | `backend/app/api/` and `backend/app/web/` |
| Authentication/session/CSRF/demo token logic | [hris_server.py](../../../hris_server.py) | `backend/app/auth/` |
| Roles and permission policies | [hris_server.py](../../../hris_server.py) | `backend/app/auth/permissions.py` |
| Employee validation and CRUD | [hris_server.py](../../../hris_server.py) | `backend/app/modules/employees/` |
| Dashboard aggregates | [hris_server.py](../../../hris_server.py) | `backend/app/modules/dashboard/` |
| Database connection/adapters | [hris_server.py](../../../hris_server.py) | `backend/app/database/` |
| Vercel request adaptation | [api/index.py](../../../api/index.py) | Keep as thin deployment adapter |
| HR administrator bootstrap | [scripts/create_hr_admin.py](../../../scripts/create_hr_admin.py) | Keep as deployment/operations script; use extracted config/auth/database APIs |
| Demo Helpdesk data and interactions | [index.html](../../../index.html), [admin.html](../../../admin.html) | Helpdesk frontend module first; shared backend module only after data/security requirements are approved |

## Risks

The highest-risk refactor is moving auth, database, and route logic while preserving both local Python serving and Vercel Function behavior. Extract behind compatibility wrappers with tests at each step; do not change the public API shape or database schema in the same commit as module moves.
