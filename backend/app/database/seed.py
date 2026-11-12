import secrets
from datetime import datetime, timezone

from ..modules.auth.password import hash_password

DEMO_ACCOUNTS = {
    "employee": ("employee.demo", "employee"),
    "manager": ("manager.demo", "manager"),
    "hr_admin": ("hr.demo", "hr_admin"),
    "payroll_admin": ("payroll.demo", "payroll_admin"),
    "system_admin": ("system.demo", "system_admin"),
    "it_support": ("it.support", "employee"),
}

DEMO_EMPLOYEES = [
    ("SAMPLE-001", "Demo Employee Alpha", "alpha@example.test", "People Operations", "Sample Coordinator", "active"),
    ("SAMPLE-002", "Demo Employee Bravo", "bravo@example.test", "IT Support", "Sample Specialist", "active"),
    ("SAMPLE-003", "Demo Employee Charlie", "charlie@example.test", "Finance", "Sample Analyst", "inactive"),
]

PUBLIC_DEMO_EMPLOYEES = (
    ("DEMO-001", "Demo Employee Alpha", "alpha.demo@example.test", "People Operations", "Sample Coordinator", "active"),
    ("DEMO-002", "Demo Employee Bravo", "bravo.demo@example.test", "IT Support", "Sample Specialist", "active"),
    ("DEMO-003", "Demo Employee Charlie", "charlie.demo@example.test", "Finance", "Sample Analyst", "inactive"),
)


def demo_employee_records():
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": employee_id,
            "name": name,
            "email": email,
            "department": department,
            "position": position,
            "status": status,
            "updated_at": now,
            "created_at": now,
        }
        for employee_id, name, email, department, position, status in PUBLIC_DEMO_EMPLOYEES
    ]


def seed_development_users(connection, demo_password=None):
    has_users = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if not has_users:
        print("\nSynthetic development accounts (not for production):")
        for label, (username, role) in DEMO_ACCOUNTS.items():
            password = demo_password or secrets.token_urlsafe(18)
            salt, password_hash = hash_password(password)
            connection.execute(
                "INSERT INTO users (username, email, role, password_salt, password_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, username + "@example.test", role, salt, password_hash),
            )
            print("  {} / {}".format(username + "@example.test", password))
        if demo_password:
            print("  Passwords were set using HRIS_DEMO_PASSWORD.")
        else:
            print("  Save these generated passwords; they are shown only during first setup.")
        print()
    else:
        for label, (username, role) in DEMO_ACCOUNTS.items():
            if label == "it_support" and not connection.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            ).fetchone():
                password = demo_password or secrets.token_urlsafe(18)
                salt, password_hash = hash_password(password)
                connection.execute(
                    "INSERT INTO users (username, email, role, password_salt, password_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username, username + "@example.test", role, salt, password_hash),
                )
                print(
                    "Synthetic local IT Support account: {} / {}".format(
                        username + "@example.test", password
                    )
                )
            connection.execute(
                "UPDATE users SET email = ? WHERE username = ? AND role = ? AND email IS NULL",
                (username + "@example.test", username, role),
            )
    support_user = connection.execute(
        "SELECT role FROM users WHERE username = 'it.support'"
    ).fetchone()
    if support_user and support_user["role"] == "employee":
        connection.execute(
            "INSERT OR IGNORE INTO user_roles (username, role) VALUES (?, ?)",
            ("it.support", "it_support"),
        )


def seed_development_employees(connection, now=None):
    has_employees = connection.execute("SELECT 1 FROM employees LIMIT 1").fetchone()
    if not has_employees:
        if now is None:
            now = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            "INSERT INTO employees "
            "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [row + (now, now) for row in DEMO_EMPLOYEES],
        )
    employee_account = connection.execute(
        "SELECT 1 FROM users WHERE username = 'employee.demo'"
    ).fetchone()
    if employee_account:
        connection.execute(
            "INSERT OR IGNORE INTO user_employee_links (username, employee_id) "
            "SELECT 'employee.demo', employee_id FROM employees "
            "WHERE employee_id = 'SAMPLE-001'"
        )


def seed_quick_access_items(connection, now=None):
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    defaults = (
        (
            "business-trip",
            "Business Trip Form",
            "Submit your business trip request.",
            "HR / Administration",
            "fa-plane",
            1,
        ),
        (
            "office-amenities",
            "Office Amenities Form",
            "Request office supplies and amenities.",
            "Office",
            "fa-box-open",
            2,
        ),
    )
    connection.executemany(
        "INSERT INTO quick_access_items "
        "(id, title, description, category, icon, target_url, display_order, "
        "visibility, status, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?, 'employees', 'draft', NULL, ?, ?) "
        "ON CONFLICT(id) DO NOTHING",
        [item + (now, now) for item in defaults],
    )
