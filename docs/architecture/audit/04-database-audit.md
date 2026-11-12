# 04 — Database audit

## Engines and connection selection

**Verified from source and documentation:**

- Local development defaults to SQLite. `HRIS_DATABASE_PATH` can select an SQLite file, and the documented default is outside the served project directory. SQLite initialization and synthetic seed behavior are implemented in [hris_server.py](../../../hris_server.py).
- PostgreSQL is selected when `DATABASE_URL` is configured. The driver is `psycopg[binary]` from [requirements.txt](../../../requirements.txt). The connection path requires TLS and has a short connection timeout according to the source/documentation.
- On Vercel, the server requires `DATABASE_URL` for authenticated HRIS database operations. Public demo requests use predefined synthetic data and do not require a production database connection.
- No database was connected to during this audit; no schema was changed and no migrations were executed.

## Tables and relationships

The PostgreSQL baseline is [migrations/001_core_hr.sql](../../../migrations/001_core_hr.sql), with additive email support in [migrations/002_user_email_login.sql](../../../migrations/002_user_email_login.sql).

| Table | Columns/constraints evidenced in source | Relationships and usage |
|---|---|---|
| `users` | `username` primary key; `role` required and constrained to `employee`, `manager`, `hr_admin`, `payroll_admin`, `system_admin`; password salt/hash required; later nullable email. Email has a case-insensitive unique index for non-null addresses in PostgreSQL. | Referenced by `sessions.username`. Auth/login and role checks. |
| `employees` | `employee_id` primary key; required name, email, department, position, status, created/updated timestamps; status constrained to active/inactive. Case-insensitive unique email and indexes for department, status and lowercased name. | Directory and dashboard aggregates. No verified FK to `users`. |
| `sessions` | Hashed token primary key; username FK to users with `ON DELETE CASCADE`; CSRF token and expiration timestamp; expiry index. | HRIS session persistence. |
| `audit_logs` | Generated identity `id`; actor, action, employee ID, occurrence time, JSON/text details required; index on employee ID/time. | Records employee create/update/delete actions. No FK to `employees`, which allows a deletion event to remain after record deletion. |

No tables for attendance, leave, payroll, recruiting, approvals, Helpdesk tickets, assets, announcements, employee documents, or notifications were found in the checked-in migrations or source schema initialization.

## Migration order and execution

1. Apply `001_core_hr.sql`.
2. Apply `002_user_email_login.sql`.

The application does not run PostgreSQL migrations automatically. The README says migrations must be applied through a trusted, reviewed process, and existing users need verified work emails populated before email login is enabled. `scripts/create_hr_admin.py` separately verifies its intended Neon target before provisioning; it is not a general schema migration runner.

## SQLite/PostgreSQL parity and differences

- Both backends implement the same four core entities and the source has explicit adapter behavior.
- SQLite initialization can add the email column to an existing local users table after inspecting `PRAGMA table_info`; PostgreSQL uses migration 002.
- PostgreSQL uses database-specific identity syntax and a partial unique email index (`WHERE email IS NOT NULL`). SQLite uses SQLite-compatible schema/index initialization. Their DDL is not byte-identical.
- Null emails can remain on existing accounts; case-insensitive uniqueness is enforced for populated email values.
- No comparison against a live schema was made. Drift between deployed databases and checked-in migrations is therefore **unknown**.

## Data lifecycle and seed data

- SQLite local setup creates synthetic demo users and employee records. The server may print generated local demo passwords on initial setup; this behavior is for local development and must not be repurposed as production provisioning.
- PostgreSQL has no automatic app seed process described; production/Preview accounts and records require explicit provisioning.
- The public demo employee records are in-code dummy records, separate from database reads.
- No retention, backup/restore, privacy deletion, or employee-data export workflow was verified.

## Risks and follow-up

1. Establish a schema-drift check that compares migration state with disposable test databases; do not point it at Preview or Production without approval.
2. Add migration version tracking and rollback guidance before schema growth; currently migration ordering is file-name/manual-process based.
3. Keep demo API data isolated from every repository/connection path, and test that invariant without setting `DATABASE_URL`.
4. Before shared Helpdesk persistence, approve a data model, retention/access requirements, and migration/backfill plan. Do not import browser `localStorage` as authoritative data without an explicit user/data policy.
5. For Employee Portal access, design per-employee identity mapping and row-level ownership checks before adding profile, leave, or attendance APIs.
6. A modular repository layer should preserve parameter binding, transactions, uniqueness behavior, and optimistic update semantics across SQLite/PostgreSQL.

## Unknowns

Production/Preview schema state, migration application records, actual row counts, data quality, backup configuration, and live constraints were not inspected. No real employee records were accessed.
