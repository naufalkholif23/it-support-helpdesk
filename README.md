# Suryanesia Employee Hub

## Run locally

The frontend and local Core HR server use Python's standard library and SQLite. No package install or frontend build is needed for local development. In PowerShell:

```powershell
Set-Location .\Helpdesk
python .\hris_server.py
```

Run these commands from the workspace root. If already inside `Helpdesk`, omit the `Set-Location` command.

Open `http://127.0.0.1:8000/`. The development server binds to loopback only and must not be exposed to a network. Tailwind CSS, Font Awesome, and Plus Jakarta Sans are loaded from external CDNs.

On first start, the server creates a local SQLite database at `%USERPROFILE%\.suryanesia-hris\hris.sqlite3` and synthetic employee records. Demo accounts are created only for local SQLite development. The server generates random passwords and prints them once during local database initialization. `HRIS_DEMO_PASSWORD` can set a shared local demo password before the database is first created; it does not reset existing accounts.

Set `HRIS_PORT` to change the local port. Set `HRIS_DATABASE_PATH` to change the SQLite location; it must remain outside the served project folder.

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
4. From a trusted machine, apply `migrations/001_core_hr.sql` once to the intended database. Do not run schema migrations from a Function invocation.
5. Set `HRIS_ALLOWED_ORIGINS` to the exact origin(s) for the deployment, comma-separated and without trailing slashes. Use separate, narrowly scoped values for Preview and Production; do not use `*`.
6. Create the first HR administrator interactively from the project root with `python -m scripts.create_hr_admin`. The script prompts for a password without echoing it and requires at least 16 characters.
7. Deploy a Preview using synthetic data only, then validate login/logout, CSRF, role denials, CRUD, audit records, and session cookies before considering Production.

Vercel sets `VERCEL_ENV` for Preview and Production, which makes the session cookie `Secure`. API mutations require a matching configured `Origin` and the session CSRF token. The database adapter enforces TLS and uses a short connection timeout.

Do not run the local SQLite initializer against PostgreSQL. Production schema changes must use reviewed migration files. Preview and Production must use separate databases, and the application currently does not automatically seed PostgreSQL with users or employee records.

## Tests

From the `Helpdesk` folder:

```powershell
python -m unittest discover -s tests -v
```

Tests patch the database path to a temporary SQLite database, disable any configured PostgreSQL URL, and use synthetic credentials. They do not intentionally modify the development or production database.

## Security and remaining production work

This is a development foundation, **not a production HRIS**. Before entering real employee data, the organization must approve identity and privacy controls, implement SSO/MFA and login rate limiting, review role and manager/team scoping, configure database backups/restore and retention, and complete security and privacy testing. The current HRIS demo roles are not an approved identity provider.

Helpdesk tickets and requests remain a browser-side prototype using browser storage. The legacy `login.html`, `admin-login.html`, and `admin.html` pages use demo-only client-side authentication and `sessionStorage`; their role checks can be bypassed and are not server authorization. Demo accounts and ticket operations are not production integrations. Do not use these pages to protect or store real employee/support data.
