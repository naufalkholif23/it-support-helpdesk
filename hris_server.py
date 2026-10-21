import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DATABASE_PATH = Path(os.environ.get(
    "HRIS_DATABASE_PATH", Path.home() / ".suryanesia-hris" / "hris.sqlite3"
)).resolve()
HOST = os.environ.get("HRIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("HRIS_PORT", "8000"))
SESSION_HOURS = 8
PBKDF2_ITERATIONS = 310000
READ_ROLES = {"hr_admin", "system_admin"}
WRITE_ROLES = {"hr_admin", "system_admin"}
DEMO_ACCOUNTS = {
    "employee": ("employee.demo", "employee"),
    "manager": ("manager.demo", "manager"),
    "hr_admin": ("hr.demo", "hr_admin"),
    "payroll_admin": ("payroll.demo", "payroll_admin"),
    "system_admin": ("system.demo", "system_admin"),
}
DEMO_EMPLOYEES = [
    ("SAMPLE-001", "Demo Employee Alpha", "alpha@example.test", "People Operations", "Sample Coordinator", "active"),
    ("SAMPLE-002", "Demo Employee Bravo", "bravo@example.test", "IT Support", "Sample Specialist", "active"),
    ("SAMPLE-003", "Demo Employee Charlie", "charlie@example.test", "Finance", "Sample Analyst", "inactive"),
]

DATABASE_LOCK = threading.RLock()

class DatabaseConfigurationError(RuntimeError):
    pass


try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None
    POSTGRES_ERRORS = ()
    POSTGRES_INTEGRITY_ERRORS = ()
else:
    POSTGRES_ERRORS = (psycopg.Error,)
    POSTGRES_INTEGRITY_ERRORS = (psycopg.IntegrityError,)

DATABASE_ERRORS = (sqlite3.Error, DatabaseConfigurationError) + POSTGRES_ERRORS
DATABASE_INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + POSTGRES_INTEGRITY_ERRORS


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        return self.connection.execute(statement.replace("?", "%s"), parameters)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def connect_database():
    if os.environ.get("VERCEL") and not DATABASE_URL:
        raise DatabaseConfigurationError("DATABASE_URL is required on Vercel.")
    if DATABASE_URL:
        if psycopg is None:
            raise DatabaseConfigurationError(
                "Install the PostgreSQL driver from requirements.txt."
            )
        connection = psycopg.connect(
            DATABASE_URL,
            connect_timeout=5,
            row_factory=dict_row,
            sslmode="require",
        )
        return PostgresConnection(connection)

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DATABASE_PATH), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return salt.hex(), password_hash.hex()


def initialize_database():
    if DATABASE_URL:
        raise RuntimeError(
            "PostgreSQL schemas must be installed using the checked-in migration."
        )
    with DATABASE_LOCK:
        connection = connect_database()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
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
            )

            has_users = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if not has_users:
                configured_password = os.environ.get("HRIS_DEMO_PASSWORD")
                print("\nSynthetic development accounts (not for production):")
                for label, (username, role) in DEMO_ACCOUNTS.items():
                    password = configured_password or secrets.token_urlsafe(18)
                    salt, password_hash = hash_password(password)
                    connection.execute(
                        "INSERT INTO users (username, role, password_salt, password_hash) "
                        "VALUES (?, ?, ?, ?)",
                        (username, role, salt, password_hash),
                    )
                    print("  {} / {}".format(username, password))
                if configured_password:
                    print("  Passwords were set using HRIS_DEMO_PASSWORD.")
                else:
                    print("  Save these generated passwords; they are shown only during first setup.")
                print()

            has_employees = connection.execute("SELECT 1 FROM employees LIMIT 1").fetchone()
            if not has_employees:
                now = datetime.now(timezone.utc).isoformat()
                connection.executemany(
                    "INSERT INTO employees "
                    "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [row + (now, now) for row in DEMO_EMPLOYEES],
                )
            connection.commit()
        finally:
            connection.close()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def validate_employee(payload, employee_id=None):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    fields = {
        "id": payload.get("id", employee_id),
        "name": payload.get("name"),
        "email": payload.get("email"),
        "department": payload.get("department"),
        "position": payload.get("position"),
        "status": payload.get("status", "active"),
    }
    limits = {"id": 30, "name": 100, "email": 254, "department": 100, "position": 100}
    for field, maximum in limits.items():
        value = fields[field]
        if not isinstance(value, str):
            raise ValueError("{} is required.".format(field))
        value = value.strip()
        if not value or len(value) > maximum:
            raise ValueError("{} must be between 1 and {} characters.".format(field, maximum))
        fields[field] = value

    fields["id"] = fields["id"].upper()
    fields["email"] = fields["email"].lower()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,29}", fields["id"]):
        raise ValueError("ID may contain only letters, numbers, and hyphens.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", fields["email"]):
        raise ValueError("Enter a valid email address.")
    if fields["status"] not in ("active", "inactive"):
        raise ValueError("Status must be active or inactive.")
    return fields


class HRISHandler(SimpleHTTPRequestHandler):
    server_version = "SuryanesiaHRIS"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format_string, *args):
        path = urlparse(self.path).path
        if re.fullmatch(r"/api/employees/[^/]+", path):
            path = "/api/employees/{employeeId}"
        status = args[1] if len(args) > 1 else ""
        print("{} {} {}".format(self.command or "HTTP", path, status).strip())

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        try:
            DATABASE_PATH.relative_to(BASE_DIR)
        except ValueError:
            pass
        else:
            database_url = "/" + DATABASE_PATH.relative_to(BASE_DIR).as_posix()
            if parsed.path == database_url or parsed.path.startswith(database_url + "-"):
                self.send_error(404)
                return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(404)
            return
        if not self.valid_origin():
            self.send_json(403, {"error": "Request origin is not allowed."})
            return
        try:
            if parsed.path == "/api/auth/login":
                self.login(self.read_json_body())
            elif parsed.path == "/api/auth/logout":
                self.logout()
            elif parsed.path == "/api/employees":
                self.create_employee(self.read_json_body())
            else:
                self.send_json(404, {"error": "Endpoint not found."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except DATABASE_INTEGRITY_ERRORS as error:
            self.send_json(409, {"error": self.integrity_message(error)})
        except DATABASE_ERRORS:
            self.send_json(500, {"error": "Database operation failed."})

    def do_PUT(self):
        parsed = urlparse(self.path)
        if not self.valid_origin():
            self.send_json(403, {"error": "Request origin is not allowed."})
            return
        try:
            user = self.require_user()
            self.require_csrf()
            self.require_role(user, WRITE_ROLES)
            match = re.fullmatch(r"/api/employees/([^/]+)", parsed.path)
            if not match:
                self.send_json(404, {"error": "Endpoint not found."})
                return
            employee_id = match.group(1)
            payload = self.read_json_body()
            employee = validate_employee(payload, employee_id)
            with DATABASE_LOCK:
                connection = connect_database()
                try:
                    cursor = connection.execute(
                        "UPDATE employees SET employee_id = ?, full_name = ?, email = ?, "
                        "department = ?, position = ?, status = ?, updated_at = ? "
                        "WHERE employee_id = ?",
                        (
                            employee["id"], employee["name"], employee["email"],
                            employee["department"], employee["position"], employee["status"],
                            datetime.now(timezone.utc).isoformat(), employee_id,
                        ),
                    )
                    if cursor.rowcount == 0:
                        connection.rollback()
                        self.send_json(404, {"error": "Employee not found."})
                        return
                    connection.execute(
                        "INSERT INTO audit_logs (actor, action, employee_id, occurred_at, details) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            user["username"], "employee.updated", employee_id,
                            datetime.now(timezone.utc).isoformat(),
                            json.dumps({"fields": ["name", "email", "department", "position", "status"]}),
                        ),
                    )
                    connection.commit()
                finally:
                    connection.close()
            self.send_json(200, {"employee": employee})
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except DATABASE_INTEGRITY_ERRORS as error:
            self.send_json(409, {"error": self.integrity_message(error)})
        except DATABASE_ERRORS:
            self.send_json(500, {"error": "Database operation failed."})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not self.valid_origin():
            self.send_json(403, {"error": "Request origin is not allowed."})
            return
        try:
            user = self.require_user()
            self.require_csrf()
            self.require_role(user, WRITE_ROLES)
            match = re.fullmatch(r"/api/employees/([^/]+)", parsed.path)
            if not match:
                self.send_json(404, {"error": "Endpoint not found."})
                return
            with DATABASE_LOCK:
                connection = connect_database()
                try:
                    cursor = connection.execute(
                        "DELETE FROM employees WHERE employee_id = ?", (match.group(1),)
                    )
                    if cursor.rowcount == 0:
                        connection.rollback()
                        self.send_json(404, {"error": "Employee not found."})
                        return
                    connection.execute(
                        "INSERT INTO audit_logs (actor, action, employee_id, occurred_at, details) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            user["username"], "employee.deleted", match.group(1),
                            datetime.now(timezone.utc).isoformat(), "{}",
                        ),
                    )
                    connection.commit()
                finally:
                    connection.close()
            self.send_json(200, {"deleted": match.group(1)})
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except DATABASE_ERRORS:
            self.send_json(500, {"error": "Database operation failed."})

    def handle_api_get(self, parsed):
        try:
            if parsed.path == "/api/auth/session":
                user = self.current_user()
                if not user:
                    self.send_json(200, {"authenticated": False})
                    return
                self.send_json(200, {"authenticated": True, "user": user})
                return
            user = self.require_user()
            if parsed.path == "/api/employees":
                self.require_role(user, READ_ROLES)
                self.list_employees(parse_qs(parsed.query))
                return
            match = re.fullmatch(r"/api/employees/([^/]+)", parsed.path)
            if match:
                self.require_role(user, READ_ROLES)
                self.get_employee(match.group(1))
                return
            self.send_json(404, {"error": "Endpoint not found."})
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except DATABASE_ERRORS:
            self.send_json(500, {"error": "Database operation failed."})

    def login(self, payload):
        username = payload.get("username") if isinstance(payload, dict) else None
        password = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("Username and password are required.")
        with DATABASE_LOCK:
            connection = connect_database()
            try:
                row = connection.execute(
                    "SELECT username, role, password_salt, password_hash "
                    "FROM users WHERE username = ?",
                    (username.strip().lower(),),
                ).fetchone()
            finally:
                connection.close()
        if not row:
            self.send_json(401, {"error": "Invalid username or password."})
            return
        _, candidate_hash = hash_password(password, bytes.fromhex(row["password_salt"]))
        if not hmac.compare_digest(candidate_hash, row["password_hash"]):
            self.send_json(401, {"error": "Invalid username or password."})
            return

        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
        with DATABASE_LOCK:
            connection = connect_database()
            try:
                connection.execute(
                    "INSERT INTO sessions (token_hash, username, csrf_token, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(), row["username"], csrf_token, expires_at),
                )
                connection.commit()
            finally:
                connection.close()
        self.send_response(200)
        self.send_header(
            "Set-Cookie",
            "hris_session={}; HttpOnly; SameSite=Strict; Path=/; Max-Age={}{}".format(
                token,
                SESSION_HOURS * 60 * 60,
                "; Secure" if self.secure_cookie_attribute() else "",
            ),
        )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json_bytes({
            "authenticated": True,
            "user": {"username": row["username"], "role": row["role"]},
            "csrfToken": csrf_token,
        }))

    def logout(self):
        user = self.require_user()
        self.require_csrf()
        token = self.cookie_value("hris_session")
        with DATABASE_LOCK:
            connection = connect_database()
            try:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
                )
                connection.commit()
            finally:
                connection.close()
        self.send_response(200)
        self.send_header(
            "Set-Cookie",
            "hris_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{}".format(
                "; Secure" if self.secure_cookie_attribute() else ""
            ),
        )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json_bytes({"authenticated": False}))

    def current_user(self):
        token = self.cookie_value("hris_session")
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with DATABASE_LOCK:
            connection = connect_database()
            try:
                row = connection.execute(
                    "SELECT users.username, users.role, sessions.csrf_token, sessions.expires_at "
                    "FROM sessions JOIN users ON users.username = sessions.username "
                    "WHERE sessions.token_hash = ?",
                    (token_hash,),
                ).fetchone()
                if row and row["expires_at"] > datetime.now(timezone.utc).isoformat():
                    return {
                        "username": row["username"],
                        "role": row["role"],
                        "csrfToken": row["csrf_token"],
                    }
                if row:
                    connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                    connection.commit()
                return None
            finally:
                connection.close()

    def require_user(self):
        user = self.current_user()
        if not user:
            raise LookupError("Sign in to access employee records.")
        return user

    def require_role(self, user, allowed_roles):
        if user["role"] not in allowed_roles:
            raise PermissionError("Your account is not authorized for this action.")

    def require_csrf(self):
        user = self.current_user()
        supplied = self.headers.get("X-CSRF-Token", "")
        if not user or not hmac.compare_digest(supplied, user["csrfToken"]):
            raise PermissionError("CSRF validation failed.")

    def list_employees(self, query):
        search = query.get("search", [""])[0].strip()[:100]
        department = query.get("department", [""])[0].strip()[:100]
        status = query.get("status", [""])[0].strip().lower()
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
            page_size = min(100, max(1, int(query.get("pageSize", ["25"])[0])))
        except ValueError:
            self.send_json(400, {"error": "Page and pageSize must be integers."})
            return
        if status and status not in ("active", "inactive"):
            self.send_json(400, {"error": "Status must be active or inactive."})
            return

        conditions = []
        values = []
        if search:
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conditions.append(
                "(LOWER(employee_id) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(full_name) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(email) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(department) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(position) LIKE LOWER(?) ESCAPE '\\')"
            )
            values.extend([pattern] * 5)
        if department:
            conditions.append("department = ?")
            values.append(department)
        if status:
            conditions.append("status = ?")
            values.append(status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        with DATABASE_LOCK:
            connection = connect_database()
            try:
                total = connection.execute(
                    "SELECT COUNT(*) AS count FROM employees" + where, values
                ).fetchone()["count"]
                summary = connection.execute(
                    "SELECT COUNT(*) AS total, "
                    "COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS active, "
                    "COUNT(DISTINCT department) AS departments FROM employees"
                ).fetchone()
                departments = [
                    row["department"]
                    for row in connection.execute(
                        "SELECT DISTINCT department FROM employees ORDER BY LOWER(department)"
                    ).fetchall()
                ]
                rows = connection.execute(
                    "SELECT employee_id AS id, full_name AS name, email, department, position, status "
                    "FROM employees" + where + " ORDER BY LOWER(full_name) "
                    "LIMIT ? OFFSET ?",
                    values + [page_size, (page - 1) * page_size],
                ).fetchall()
            finally:
                connection.close()
        self.send_json(200, {
            "employees": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "summary": dict(summary),
            "departments": departments,
        })

    def get_employee(self, employee_id):
        with DATABASE_LOCK:
            connection = connect_database()
            try:
                row = connection.execute(
                    "SELECT employee_id AS id, full_name AS name, email, department, position, status "
                    "FROM employees WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()
            finally:
                connection.close()
        if not row:
            self.send_json(404, {"error": "Employee not found."})
            return
        self.send_json(200, {"employee": dict(row)})

    def create_employee(self, payload):
        user = self.require_user()
        self.require_csrf()
        self.require_role(user, WRITE_ROLES)
        employee = validate_employee(payload)
        now = datetime.now(timezone.utc).isoformat()
        with DATABASE_LOCK:
            connection = connect_database()
            try:
                connection.execute(
                    "INSERT INTO employees "
                    "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        employee["id"], employee["name"], employee["email"],
                        employee["department"], employee["position"], employee["status"], now, now,
                    ),
                )
                connection.execute(
                    "INSERT INTO audit_logs (actor, action, employee_id, occurred_at, details) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        user["username"], "employee.created", employee["id"], now,
                        json.dumps({"fields": ["name", "email", "department", "position", "status"]}),
                    ),
                )
                connection.commit()
            finally:
                connection.close()
        self.send_json(201, {"employee": employee})

    def valid_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return False
        allowed_origins = {
            item.strip()
            for item in os.environ.get("HRIS_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        }
        if allowed_origins:
            return origin in allowed_origins
        return origin == "http://{}:{}".format(HOST, PORT)

    @staticmethod
    def secure_cookie_attribute():
        return os.environ.get("VERCEL_ENV") in ("production", "preview")

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid content length.")
        if length < 1 or length > 16384:
            raise ValueError("Request body must be between 1 and 16384 bytes.")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Request body must contain valid JSON.")

    def cookie_value(self, name):
        for part in self.headers.get("Cookie", "").split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key == name:
                return value
        return ""

    def integrity_message(self, error):
        message = str(error)
        if "employees.email" in message or "idx_employees_email_lower" in message:
            return "Email is already assigned to another employee."
        if (
            "employees.employee_id" in message
            or "employees_pkey" in message
            or "employee_id" in message
        ):
            return "Employee ID already exists."
        return "The record conflicts with an existing record."

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("This development server must bind to loopback only.")
    try:
        DATABASE_PATH.relative_to(BASE_DIR)
    except ValueError:
        pass
    else:
        raise SystemExit("HRIS_DATABASE_PATH must be outside the served Helpdesk folder.")
    if not DATABASE_URL:
        initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), HRISHandler)
    print("Suryanesia HRIS development server: http://{}:{}/".format(HOST, PORT))
    print("Local development only. Do not expose this server to a network.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping development server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
