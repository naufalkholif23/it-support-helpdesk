# Suryanesia Employee Hub

## Run locally

The frontend is static HTML, and the Core HR server uses Python with SQLite by default. Python 3.8 or later and the dependencies in `requirements.txt` must already be available; the startup script does not install packages.

```powershell
Set-Location "D:\Magang Suryanesia\Employee Hub"
.\scripts\start-local.ps1
```

The script isolates the process to loopback and local SQLite, clears Vercel and `DATABASE_URL` settings for the server process, prepares the schema and synthetic accounts, then starts the server in the foreground. It never deletes or resets the local database. If port 8000 is occupied, stop the process using it or choose another port with `.\scripts\start-local.ps1 -Port 8010`. To use an alternate SQLite file (for example, for an isolated test), pass `-DatabasePath "$env:TEMP\employee-hub-test.sqlite3"`; the path must be outside the served project folder. Press Ctrl+C to stop the server. If startup reports missing dependencies, activate the intended Python environment and install the already-declared `requirements.txt` separately.

Open the localhost URL printed by the script (normally `http://127.0.0.1:8000/`). An unauthenticated visitor is sent to `/login.html`; a signed-in visitor is sent to the Employee Hub dashboard. `/hris` remains available to HR and system administrators through the shared session and navigation. The optional `/platform.html` page remains available directly. The development server binds to loopback only and must not be exposed to a network. Tailwind CSS, Font Awesome, and Plus Jakarta Sans are loaded from external CDNs.

On first start, the server creates `%USERPROFILE%\.suryanesia-hris\hris.sqlite3` and synthetic employee records. Demo accounts are created only for local SQLite development, using the application's password hashing. Random passwords are printed once when the accounts are first created; save them securely. Existing accounts are not reset if the database already contains users. The seeded usernames are `employee.demo`, `manager.demo`, `hr.demo`, `payroll.demo`, `system.demo`, and `it.support`; each also has a corresponding `@example.test` email. `HRIS_DEMO_PASSWORD` can set a shared local password before accounts are first created, but the startup script deliberately does not set it.

Local demo accounts accept either their username or synthetic work email (for example, `hr.demo` or `hr.demo@example.test`) and the password printed by the server. Successful sign-in always opens the Employee Hub dashboard; HR administrators can then open HRIS from the sidebar.

The startup script's `-Port` parameter selects a local port. For direct server startup, `HRIS_PORT` changes the port and `HRIS_DATABASE_PATH` changes the SQLite location; keep the database outside the served project folder.

To use PostgreSQL locally, set `DATABASE_URL` in the ignored `.env.local` file in the project root. The server loads that file without overriding variables already set in the process. A configured `DATABASE_URL` selects PostgreSQL; with no URL, the existing SQLite database and demo-account initialization are used. Point local testing only at the `employee-hub-testing` Neon branch; do not run the SQLite initializer against PostgreSQL.

## Core HR directory

The Employee Directory preserves the existing Suryanesia shell, colors, typography, sidebar, and responsive layout. It provides:

- API-backed search by employee name, ID, email, or position; department, position, and status filters; and pagination.
- Sortable employee, ID, department, position, and status columns.
- Employee detail view and validated add/edit forms with conflict detection.
- Confirmed active/inactive status changes that retain employee history.
- Permanent record deletion remains a separate, explicitly confirmed action.
- Loading, empty, and error states.
- Server-side sessions, CSRF checks, role authorization, and an audit trail for create/update/delete.
- Synthetic local seed users and employee records only.

Directory access is currently restricted to HR administrator and system administrator roles. Employee, manager, and payroll administrator roles are denied access. Manager/team-level data scoping and employee self-service workflows beyond the account profile are not implemented.

## Sign-in and sessions

The Employee Hub and Helpdesk staff dashboard use the server-managed HRIS session for sign-in and logout. The sign-in page accepts a work email or username and password; account email is stored on the existing `users` record and uniquely indexed case-insensitively. Existing API session cookies remain `HttpOnly` and `SameSite=Strict`, and are `Secure` on Vercel and Render. The frontend checks `/api/auth/session` before rendering internal routes and returns to sign-in with an expiry notice when the server reports an expired session. A successful sign-in lands on the Employee Hub dashboard. Protected API authorization remains enforced by the backend.

## Quick Access forms

The Employee Hub dashboard loads active employee-visible forms from `GET /api/quick-access` in its Quick Access section. Local SQLite initialization creates draft records for Business Trip Form and Office Amenities Form without inventing target URLs. HR and system administrators can manage these records under **HRIS → Settings → Form Management**; updates require the existing session, origin, CSRF, and role checks. Only HTTPS Google Forms links are accepted, and a form must have a URL before it can be activated. Employee accounts see only active items with employee visibility.

The SQLite schema and defaults are applied idempotently at local startup. For a PostgreSQL deployment, apply `migrations/004_quick_access.sql` manually after the existing schema migrations. No migration was applied to an external database as part of this work.

## Employee profile and Helpdesk

The Employee Profile page reads the signed-in account and, when explicitly linked, that account's employee record from the backend. The local seed links only `employee.demo` to the synthetic `SAMPLE-001` record; other accounts show that no employee record is linked. The profile endpoint never accepts a client-supplied employee ID.

Helpdesk ticket submission, the employee's ticket list/detail/timeline, and staff status/assignee/resolution updates use authenticated API routes backed by local SQLite. Employees can view and comment on their own tickets; `it_support`, `hr_admin`, and `system_admin` can view and manage the queue. Writes require the existing session, origin, and CSRF checks. The legacy `admin-login.html` now forwards to shared sign-in, and `admin.html` uses server session and role checks. Attachments are not supported. Asset inventory and non-Helpdesk employee requests remain mock/local prototype content.

The additive `migrations/003_helpdesk_local.sql` is provided for manual PostgreSQL schema setup, but it is not applied automatically and was not run against any external database. Local SQLite initialization is the only database setup verified for this work.

## Legacy Vercel Demo Mode (inactive)

The Vercel adapter and its configuration remain in the repository as legacy files, but Vercel is not part of the active deployment architecture. The following behavior describes that retained adapter only; do not configure Vercel Preview or Production environments for the current Full Render deployment.

If the legacy Vercel host is deliberately reactivated in the future, Demo Mode requires `HRIS_DEMO_MODE=1` and a randomly generated `HRIS_DEMO_SESSION_SECRET` of at least 32 bytes. It activates only when Vercel reports `VERCEL_ENV=preview` or `production`. The root URL opens an isolated signed demo session using synthetic in-code records without connecting to or requiring `DATABASE_URL`; demo sessions cannot read real HR data or perform mutations. HR Admin sign-in continues to require the configured database. The legacy mode fails closed without a valid session-signing secret. Modules without a backend remain prototypes and do not represent real payroll, approvals, or employee transactions.

No Google, phone, employee-ID, SAML, remember-me, or password-recovery flow is configured. The email mapping is not inferred from usernames: a real deployment must apply `migrations/002_user_email_login.sql` after the core schema migration and populate each existing user's verified work email through the approved database change process before enabling email sign-in. The migration is not run by the application or this development task. `python -m scripts.create_hr_admin` now asks for an email when creating a new administrator.

The HRIS dashboard at `/hris` uses an aggregate-only endpoint for employee totals, active/inactive status, department counts, and employee records created in the current UTC month; access follows the same HR administrator and system administrator policy. The monthly figure is a record-creation date, not a hire date: the employee schema does not store join dates, probation, employment type, or contract dates, so the Employee page does not present those as employee metrics. Attendance, leave, payroll, task, location, and other employee lifecycle sections remain unavailable because those data models and workflows are not implemented. The Employee Hub dashboard retains its employee-facing welcome, announcements, quick links, and Helpdesk entry points, and includes a month calendar with an empty state until company events are configured.

## Employee Hub navigation

The sidebar starts with Dashboard, Request Center, SOP & Guidelines, Policies, Employee Corner, and Quick Links under Employee Hub. Other existing employee routes remain grouped under Employee Services. The HRIS section follows for authorized HR administrators, with Helpdesk below it. HRIS contains the dashboard, employee, recruitment, time, finance, payroll, productivity, company, applications, integrations, and settings links; form administration is nested under **Settings → Form Management**. Quick Access is a section on the Employee Hub dashboard, not a separate sidebar page. The dashboard also provides a company calendar date grid and quick actions for employee requests, Helpdesk tickets, company information, and Quick Links; event data is not available until configured. Sidebar groups use a single expanded submenu, and route-backed pages use URL fragments (for example, `#employees` or `#attendance`) so a page can be bookmarked or reopened directly.

The Home dashboard shows authorized employee aggregates and honest unavailable states for unimplemented modules. The Employee Directory and Helpdesk ticket views use the existing server API. Other HRIS routes intentionally show a localized placeholder; they do not imply that the corresponding HR process or integration is implemented. On mobile, use the header menu button to open the sidebar and select a link to close it.

## API

- `GET /api/auth/session`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/portal/profile`
- `GET /api/helpdesk/tickets`
- `POST /api/helpdesk/tickets`
- `GET /api/helpdesk/tickets/{ticketId}`
- `POST /api/helpdesk/tickets/{ticketId}/comments`
- `PUT /api/helpdesk/tickets/{ticketId}` (Helpdesk staff only)
- `GET /api/helpdesk/dashboard/summary` (Helpdesk staff only)
- `GET /api/dashboard/summary` (HR and system administrators only; aggregate employee counts)
- `GET /api/employees?search=&department=&position=&status=&sortBy=&sortOrder=&page=&pageSize=`
- `GET /api/employees/{employeeId}`
- `POST /api/employees`
- `PUT /api/employees/{employeeId}`
- `DELETE /api/employees/{employeeId}`

The API validates employee IDs, email, required fields, status, sort fields, and unique IDs/emails. Employee list/detail responses include the record update timestamp used for optimistic edit conflict detection. Session tokens are stored hashed in the database; passwords use PBKDF2 hashes.

## Deployment: Render and permanent Neon database

The active deployment architecture is one Render Web Service serving the Employee Hub frontend and backend, backed by one permanent Neon PostgreSQL project and its default/primary branch. This is a single environment; Vercel is not active hosting. Existing Vercel adapter and configuration files are retained unchanged for legacy use.

Configure the Render Web Service with:

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python render_server.py`
- **Health Check Path:** `/api/health`

Set these environment variables in Render's private environment settings:

- `DATABASE_URL` — the TLS-enabled PostgreSQL connection URL for the permanent Neon database.
- `HRIS_POSTGRES_EXPECTED_HOSTNAME` — the exact hostname of the approved Neon endpoint used by `DATABASE_URL` (set the pooled or direct endpoint hostname that the URL actually uses).
- `HRIS_POSTGRES_EXPECTED_DATABASE` — set to `neondb`.
- `HRIS_POSTGRES_SSLROOTCERT` — path to a readable CA bundle file made available to the service; startup fails if this path is missing or unreadable.
- `HRIS_ALLOWED_ORIGINS` — exact HTTPS origin(s) used to access the service, comma-separated if needed. Wildcards and HTTP origins are rejected in Render mode.

Do not put credentials in this README, source files, or a Render manifest. The Render runner binds to `0.0.0.0`, requires Render's `PORT`, validates the exact configured database hostname and name before opening the HTTP listener, and never initializes SQLite. PostgreSQL runtime connections force `sslmode=verify-full`; the URL may include `sslmode=require` and `channel_binding=require`, but routing overrides, credentials in query parameters, duplicate parameters, and unknown parameters are rejected. The configured CA bundle path is passed explicitly to Psycopg; a successful startup validates that the file is readable, but does not prove a live TLS handshake. `/api/health` is unauthenticated and database-independent. Session cookies use `Secure`, `HttpOnly`, and `SameSite=Strict`; no cross-origin CORS access is enabled.

PostgreSQL migrations are never run by the Render runner, build command, health check, or application startup. After reviewing the target and ensuring an approved recovery plan, apply the migrations manually to the permanent database in this order: `migrations/001_core_hr.sql`, `migrations/002_user_email_login.sql`, `migrations/003_helpdesk_local.sql`, then `migrations/004_quick_access.sql`. Keep a record of the applied migration files. Do not run the local SQLite initializer against PostgreSQL.

After migrations succeed, the first HR administrator must be provisioned manually from an authorized trusted machine. Authenticate the Neon CLI and set the exact allowlist variables `HRIS_ADMIN_ALLOWED_NEON_PROJECT_ID`, `HRIS_ADMIN_ALLOWED_NEON_BRANCH_ID`, `HRIS_ADMIN_ALLOWED_NEON_BRANCH_NAME`, and `HRIS_ADMIN_ALLOWED_NEON_DATABASE_NAME` for the permanent database, then run `python -m scripts.create_hr_admin` from the project root. The tool verifies project/branch identity, the default/primary flag, writable endpoint, exact URL hostname/database, and the connected target; it rejects connection-routing overrides and uses TLS certificate and hostname verification (`sslmode=verify-full`). It refuses to change an existing account and requires this exact target-bound confirmation before requesting a password: `CREATE PERMANENT EMPLOYEE HUB DATABASE <project-id>/<branch-id>/<branch-name>/<database-name> I HAVE VERIFIED THIS TARGET IS CORRECT AND AUTHORIZED`. The password is prompted without echo and stored only as the application's salted password hash.

Neon branch names and metadata do not establish whether a database contains production data. Before provisioning or migration, the operator must independently verify the intended permanent project, branch, database, authorization, and data. Never commit the connection URL or credentials. PostgreSQL startup does not seed users or employee records; plan authorized account onboarding and data loading separately.

Local development defaults to loopback HTTP and SQLite (`HRIS_DATABASE_PATH` can select another SQLite file outside the project). The repository still contains the legacy Vercel adapter and configuration, but they are not part of the active deployment path and must not be used to configure a second hosting environment.

## Tests

From the project root:

```powershell
python -m unittest discover -s tests -v
```

Tests patch the database path to a temporary SQLite database, disable any configured PostgreSQL URL, and use synthetic credentials. The optional Neon integration test is skipped unless all of these environment variables are set: `HRIS_TEST_DATABASE_URL`, `NEON_PROJECT_ID`, `NEON_BRANCH_ID`, `NEON_BRANCH_NAME`, `NEON_DATABASE_HOST`, and `NEON_DATABASE_NAME`. Leave them unset for normal local testing. Only run the integration test against an explicitly authorized, disposable test database/branch—never the permanent default/primary database or any database containing useful data. The test verifies the URL against Neon branch and endpoint metadata, requires the `users`, `employees`, `sessions`, and `audit_logs` tables to be empty, creates a temporary non-admin account, exercises login/session/logout, and removes that account afterward. It aborts if any table contains rows. Do not delete existing data merely to run the test, and keep all environment values and the test connection URL out of source control.

## Security and remaining production work

This is a development foundation, **not a production HRIS**. Before entering real employee data, the organization must approve identity and privacy controls, implement SSO/MFA and login rate limiting, review role and manager/team scoping, configure database backups/restore and retention, and complete security and privacy testing. The current HRIS demo roles are not an approved identity provider.

Helpdesk tickets and requests remain a browser-side prototype using browser storage. The Employee Hub `login.html` uses the HRIS server session; `admin-login.html` and `admin.html` remain legacy demo-only client-side pages using `sessionStorage`, and their role checks can be bypassed. Demo Helpdesk accounts and ticket operations are not production integrations. Do not use the legacy Helpdesk pages to protect or store real employee/support data.
