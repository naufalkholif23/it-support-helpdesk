SQLITE_CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    email TEXT,
    role TEXT NOT NULL CHECK (role IN (
        'employee', 'manager', 'hr_admin', 'payroll_admin', 'system_admin'
    )),
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    department TEXT NOT NULL,
    position TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_employees_department
    ON employees(department);
CREATE INDEX IF NOT EXISTS idx_employees_status
    ON employees(status);
CREATE INDEX IF NOT EXISTS idx_employees_name
    ON employees(full_name);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_employee
    ON audit_logs(employee_id, occurred_at);
"""


def apply_sqlite_schema(connection):
    connection.executescript(SQLITE_CORE_SCHEMA)


def apply_sqlite_migrations(connection):
    user_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    if "email" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN email TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower "
        "ON users (LOWER(email)) WHERE email IS NOT NULL"
    )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role = 'it_support'),
            PRIMARY KEY (username, role)
        );
        CREATE TABLE IF NOT EXISTS user_employee_links (
            username TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
            employee_id TEXT NOT NULL UNIQUE REFERENCES employees(employee_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS helpdesk_tickets (
            ticket_id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
            reporter_username TEXT NOT NULL REFERENCES users(username),
            reporter_name TEXT NOT NULL,
            reporter_email TEXT NOT NULL,
            department TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'Open', 'In Progress', 'Pending', 'Resolved', 'Closed'
            )),
            assigned_to TEXT,
            resolution TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_helpdesk_tickets_reporter
            ON helpdesk_tickets(reporter_username, created_at);
        CREATE INDEX IF NOT EXISTS idx_helpdesk_tickets_status
            ON helpdesk_tickets(status, updated_at);
        CREATE TABLE IF NOT EXISTS helpdesk_ticket_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL REFERENCES helpdesk_tickets(ticket_id) ON DELETE CASCADE,
            actor_username TEXT NOT NULL REFERENCES users(username),
            event_type TEXT NOT NULL,
            details TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_helpdesk_events_ticket
            ON helpdesk_ticket_events(ticket_id, occurred_at);
        CREATE TABLE IF NOT EXISTS helpdesk_ticket_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL REFERENCES helpdesk_tickets(ticket_id) ON DELETE CASCADE,
            author_username TEXT NOT NULL REFERENCES users(username),
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_helpdesk_comments_ticket
            ON helpdesk_ticket_comments(ticket_id, created_at);
        CREATE TABLE IF NOT EXISTS quick_access_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            icon TEXT NOT NULL,
            target_url TEXT,
            display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
            visibility TEXT NOT NULL CHECK (visibility IN ('employees', 'hr_admin')),
            status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'inactive')),
            created_by TEXT REFERENCES users(username) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (status != 'active' OR target_url IS NOT NULL)
        );
        CREATE INDEX IF NOT EXISTS idx_quick_access_visibility_status_order
            ON quick_access_items(visibility, status, display_order);
        """
    )
