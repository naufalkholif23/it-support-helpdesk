# Suryanesia Employee Hub

## Run locally

The frontend is static HTML, and the Core HR server uses Python with SQLite by default. Install the Python dependencies before running the server or tests:

```powershell
Set-Location .\Helpdesk
python -m pip install -r requirements.txt
python .\hris_server.py
```

Run these commands from the workspace root. If already inside `Helpdesk`, omit the `Set-Location` command.

Open `http://127.0.0.1:8000/`. The development server binds to loopback only and must not be exposed to a network. Tailwind CSS, Font Awesome, and Plus Jakarta Sans are loaded from external CDNs.

On first start, the server creates a local SQLite database at `%USERPROFILE%\.suryanesia-hris\hris.sqlite3` and synthetic employee records. Demo accounts are created only for local SQLite development. The server generates random passwords and prints them once during local database initialization. `HRIS_DEMO_PASSWORD` can set a shared local demo password before the database is first created; it does not reset existing accounts.

Open `http://127.0.0.1:8000/`; unauthenticated visitors are sent to the Employee Hub sign-in page. Local demo accounts accept either their username or synthetic work email (for example, `hr.demo` or `hr.demo@example.test`) and the password printed by the server.

Set `HRIS_PORT` to change the local port. Set `HRIS_DATABASE_PATH` to change the SQLite location; it must remain outside the served project folder.

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

Directory access is currently restricted to HR administrator and system administrator roles. Employee, manager, and payroll administrator roles are denied access. Manager/team-level data scoping and employee self-service are not implemented.

## Sign-in and sessions

The Employee Hub uses the server-managed HRIS session for sign-in and logout. The sign-in page accepts a work email or username and password; account email is stored on the existing `users` record and uniquely indexed case-insensitively. Existing API session cookies remain `HttpOnly` and `SameSite=Strict`, and are `Secure` on Vercel. The frontend checks `/api/auth/session` before rendering internal routes, preserves same-site Employee Hub destinations through sign-in, and returns to sign-in with an expiry notice when the server reports an expired session. Protected API authorization remains enforced by the backend.

No Google, phone, employee-ID, SAML, remember-me, or password-recovery flow is configured. The email mapping is not inferred from usernames: a real deployment must apply `migrations/002_user_email_login.sql` after the core schema migration and populate each existing user's verified work email through the approved database change process before enabling email sign-in. The migration is not run by the application or this development task. `python -m scripts.create_hr_admin` now asks for an email when creating a new administrator.

The Home dashboard uses an aggregate-only endpoint for employee totals, active/inactive status, department counts, and employee records created in the current UTC month; access follows the same HR administrator and system administrator policy. The monthly figure is a record-creation date, not a hire date: the employee schema does not store join dates, probation, employment type, or contract dates, so the Employee page does not present those as employee metrics. Attendance, leave, payroll, task, location, and other employee lifecycle sections remain unavailable because those data models and workflows are not implemented.

## Employee Hub navigation

The main sidebar groups Home, Employee Profile, Employees, Recruitment, Time, Finance, Payroll, Productivity, Company, Applications, Integrations, and Settings. The previously available Employee Hub and Helpdesk links remain grouped below them. Sidebar groups use a single expanded submenu, and route-backed pages use URL fragments (for example, `#employees` or `#attendance`) so a page can be bookmarked or reopened directly.

The Home dashboard shows authorized employee aggregates and honest unavailable states for unimplemented modules. The Employee Directory and existing Helpdesk views provide their existing functionality. Other HRIS routes intentionally show a localized placeholder; they do not imply that the corresponding HR process or integration is implemented. On mobile, use the header menu button to open the sidebar and select a link to close it.

## API

- `GET /api/auth/session`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/dashboard/summary` (HR and system administrators only; aggregate employee counts)
- `GET /api/employees?search=&department=&position=&status=&sortBy=&sortOrder=&page=&pageSize=`
- `GET /api/employees/{employeeId}`
- `POST /api/employees`
- `PUT /api/employees/{employeeId}`
- `DELETE /api/employees/{employeeId}`

The API validates employee IDs, email, required fields, status, sort fields, and unique IDs/emails. Employee list/detail responses include the record update timestamp used for optimistic edit conflict detection. Session tokens are stored hashed in the database; passwords use PBKDF2 hashes.

## Vercel and managed PostgreSQL

The repository includes a Python Function at `api/index.py`, with a Vercel rewrite forwarding `/api/*` routes to the existing HRIS handler, a PostgreSQL driver, and a PostgreSQL schema migration. Vercel Functions do not use the local SQLite file for durable production storage. **The application is not cleared for production HR data or public HRIS use yet.**

Before deploying a preview:

1. Connect this repository to a Vercel project with the project root set to this folder.
2. Provision a managed PostgreSQL database (for example, Neon) and use its TLS-enabled connection URL.
3. Set `DATABASE_URL` separately for Preview and Production in Vercel. Do not commit `.env` files or put secrets in HTML or JavaScript.
4. From a trusted machine, apply `migrations/001_core_hr.sql` and then `migrations/002_user_email_login.sql` to the intended database. Do not run schema migrations from a Function invocation. Before enabling sign-in, populate the new email field with verified work emails for existing users and confirm there are no duplicate addresses (case-insensitive).
5. Enable Vercel system environment variables for the project. The app allows the assigned deployment HTTPS origin from `VERCEL_URL`; Production additionally allows the production domain from `VERCEL_PROJECT_PRODUCTION_URL`. Set `HRIS_ALLOWED_ORIGINS` to any other exact HTTPS origin(s) used to open the app, comma-separated. An optional trailing slash and the default HTTPS port are normalized; paths, wildcards, non-HTTPS production origins, and unknown domains are rejected. Configure extra origins separately for Preview and Production; Preview does not inherit the production domain. Do not use `*`.
6. Create the first HR administrator only after confirming `DATABASE_URL` targets the intended database. For Neon, authenticate the Neon CLI and run `python -m scripts.create_hr_admin` from the project root. Before opening a database connection, the script verifies the configured database name and hostname against Neon API metadata for the expected project and branch. It then verifies the active database and connected endpoint again; if either check is unavailable or mismatched, it stops. It prompts for username, work email, and a password without echoing it (minimum 16 characters), then requires typing `CREATE` before insertion. It creates the application role `hr_admin`.
7. Deploy a Preview using synthetic data only, then validate login/logout, CSRF, role denials, CRUD, audit records, and session cookies before considering Production.

Vercel sets `VERCEL_ENV` for Preview and Production, which makes the session cookie `Secure`. Login and all API mutations require an exact allowed `Origin`; logout and other authenticated mutations also require the session CSRF token. The frontend sends same-origin API requests with the browser's origin and session credentials. The database adapter enforces TLS and uses a short connection timeout.

Local development defaults to loopback HTTP and SQLite (`HRIS_DATABASE_PATH` can select another SQLite file outside the project). Vercel Preview and Production require `DATABASE_URL` pointing to their respective managed PostgreSQL databases; `VERCEL_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, and `VERCEL_ENV` are Vercel system variables, not manually copied secrets. `HRIS_ALLOWED_ORIGINS` is only needed for additional custom aliases not represented by those Vercel domains.

Do not run the local SQLite initializer against PostgreSQL. Production schema changes must use reviewed migration files. Preview and Production must use separate databases, and the application currently does not automatically seed PostgreSQL with users or employee records.

## Tests

From the `Helpdesk` folder:

```powershell
python -m unittest discover -s tests -v
```

Tests patch the database path to a temporary SQLite database, disable any configured PostgreSQL URL, and use synthetic credentials. The optional Neon integration test requires `HRIS_TEST_DATABASE_URL` to point explicitly to the `employee-hub-testing` branch and requires its `users`, `employees`, `sessions`, and `audit_logs` tables to be empty; it aborts if any contain rows. Use only a disposable testing database, and do not delete existing data merely to run the test. The test creates a temporary non-admin account, exercises login/session/logout, and removes that account afterward. Do not point it at `main`, Preview, or Production.

## Security and remaining production work

This is a development foundation, **not a production HRIS**. Before entering real employee data, the organization must approve identity and privacy controls, implement SSO/MFA and login rate limiting, review role and manager/team scoping, configure database backups/restore and retention, and complete security and privacy testing. The current HRIS demo roles are not an approved identity provider.

Helpdesk tickets and requests remain a browser-side prototype using browser storage. The Employee Hub `login.html` uses the HRIS server session; `admin-login.html` and `admin.html` remain legacy demo-only client-side pages using `sessionStorage`, and their role checks can be bypassed. Demo Helpdesk accounts and ticket operations are not production integrations. Do not use the legacy Helpdesk pages to protect or store real employee/support data.
