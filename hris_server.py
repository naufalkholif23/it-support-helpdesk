import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.app.api.responses import HttpUtilitiesMixin, json_bytes
from backend.app.core.config import (
    BASE_DIR,
    DATABASE_PATH,
    DATABASE_URL,
    HOST,
    PORT,
    POSTGRES_EXPECTED_DATABASE,
    POSTGRES_EXPECTED_HOSTNAME,
    POSTGRES_SSLROOTCERT,
)
from backend.app.core.exceptions import (
    DatabaseConfigurationError,
    DemoConfigurationError,
)
from backend.app.database.connection import (
    DATABASE_ERRORS,
    DATABASE_INTEGRITY_ERRORS,
    POSTGRES_ERRORS,
    POSTGRES_INTEGRITY_ERRORS,
    PostgresConnection,
    dict_row,
    psycopg,
    connect_database as _connect_database,
    validate_postgres_database_url,
)
from backend.app.modules.auth.demo import demo_mode_enabled, demo_session_secret
from backend.app.modules.auth.origin import (
    is_valid_origin,
    normalize_origin,
    secure_cookie_attribute,
    vercel_origin,
)
from backend.app.modules.auth.password import PBKDF2_ITERATIONS, hash_password
from backend.app.modules.auth.permissions import (
    READ_ROLES,
    WRITE_ROLES,
    is_demo_user,
)
from backend.app.modules.auth.service import AuthServiceMixin
from backend.app.modules.auth.session import (
    DEMO_SESSION_COOKIE,
    DEMO_SESSION_HOURS,
    SESSION_HOURS,
    SessionHandlerMixin,
)
from backend.app.modules.auth.validators import validate_login_identifier
from backend.app.modules.dashboard import service as dashboard_service
from backend.app.modules.employees import repository as employee_repository
from backend.app.database.initialize import initialize_database as _initialize_database
from backend.app.database.seed import (
    DEMO_ACCOUNTS,
    DEMO_EMPLOYEES,
    PUBLIC_DEMO_EMPLOYEES,
    demo_employee_records,
)
from backend.app.modules.employees import service as employee_service
from backend.app.modules.employees.validators import validate_employee
from backend.app.modules.helpdesk import service as helpdesk_service
from backend.app.modules.employee_portal import service as employee_portal_service
from backend.app.modules.quick_access import service as quick_access_service


DATABASE_LOCK = threading.RLock()


def connect_database():
    return _connect_database(
        DATABASE_URL,
        DATABASE_PATH,
        vercel=bool(os.environ.get("VERCEL")),
        render=os.environ.get("HRIS_DEPLOYMENT", "").strip().lower() == "render",
        expected_hostname=POSTGRES_EXPECTED_HOSTNAME,
        expected_database=POSTGRES_EXPECTED_DATABASE,
        sslrootcert=POSTGRES_SSLROOTCERT,
    )


def initialize_database():
    return _initialize_database(
        connect_database=connect_database,
        database_lock=DATABASE_LOCK,
        database_url=DATABASE_URL,
        demo_password=os.environ.get("HRIS_DEMO_PASSWORD"),
    )


def employee_summary(connection, include_monthly_records=False):
    return employee_repository.employee_summary(
        connection, include_monthly_records=include_monthly_records
    )


class HRISHandler(
    HttpUtilitiesMixin,
    AuthServiceMixin,
    SessionHandlerMixin,
    SimpleHTTPRequestHandler,
):
    server_version = "SuryanesiaHRIS"
    sys_version = ""
    database_lock = DATABASE_LOCK
    render_static_files = frozenset({
        "/admin-login.html",
        "/admin.html",
        "/favicon.ico",
        "/index.html",
        "/login.html",
        "/logo-green.png",
        "/platform.html",
    })
    render_static_aliases = {
        "/employee-hub": "/index.html",
        "/hris": "/index.html",
        "/hris/": "/index.html",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def database_connection(self):
        return connect_database()

    def log_message(self, format_string, *args):
        path = urlparse(self.path).path
        if re.fullmatch(r"/api/employees/[^/]+", path):
            path = "/api/employees/{employeeId}"
        status = args[1] if len(args) > 1 else ""
        print("{} {} {}".format(self.command or "HTTP", path, status).strip())

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(200, {"status": "ok"})
            return
        if parsed.path == "/api/public-entry":
            destination = (
                "/employee-hub#home"
                if demo_mode_enabled() or self.current_user()
                else "/login.html"
            )
            self.redirect(destination)
            return
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        if parsed.path == "/":
            destination = (
                "/employee-hub#home"
                if demo_mode_enabled() or self.current_user()
                else "/login.html"
            )
            self.redirect(destination)
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
        if parsed.path == "/employee-hub":
            self.path = "/index.html"
        elif parsed.path in ("/hris", "/hris/"):
            self.path = "/index.html"
        if os.environ.get("HRIS_DEPLOYMENT", "").strip().lower() == "render":
            target = self.render_static_aliases.get(parsed.path, parsed.path)
            if target not in self.render_static_files:
                self.send_error(404)
                return
            self.path = target + (("?" + parsed.query) if parsed.query else "")
        super().do_GET()

    def do_HEAD(self):
        if os.environ.get("HRIS_DEPLOYMENT", "").strip().lower() != "render":
            super().do_HEAD()
            return
        parsed = urlparse(self.path)
        target = self.render_static_aliases.get(parsed.path, parsed.path)
        if target not in self.render_static_files:
            self.send_error(404)
            return
        self.path = target + (("?" + parsed.query) if parsed.query else "")
        super().do_HEAD()

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(404)
            return
        if not self.valid_origin():
            self.send_json(403, {"error": "Request origin is not allowed."})
            return
        try:
            if parsed.path == "/api/auth/demo-login" and demo_mode_enabled():
                self.read_json_body()
                self.start_demo_session()
            elif parsed.path == "/api/auth/login":
                self.login(self.read_json_body())
            elif parsed.path == "/api/auth/logout":
                self.logout()
            elif parsed.path == "/api/employees":
                self.create_employee(self.read_json_body())
            elif parsed.path == "/api/admin/quick-access":
                user = self.require_user()
                self.require_non_demo_user(user)
                self.require_csrf()
                self.require_role(user, WRITE_ROLES)
                item = quick_access_service.create_item(
                    self.read_json_body(), user, connect_database, DATABASE_LOCK
                )
                self.send_json(201, {"item": item})
            elif parsed.path == "/api/helpdesk/tickets":
                user = self.require_user()
                self.require_non_demo_user(user)
                self.require_csrf()
                ticket = helpdesk_service.create_ticket(
                    self.read_json_body(), user, connect_database, DATABASE_LOCK
                )
                self.send_json(201, {"ticket": ticket})
            elif re.fullmatch(r"/api/helpdesk/tickets/([^/]+)/comments", parsed.path):
                user = self.require_user()
                self.require_non_demo_user(user)
                self.require_csrf()
                match = re.fullmatch(
                    r"/api/helpdesk/tickets/([^/]+)/comments", parsed.path
                )
                payload = self.read_json_body()
                if not isinstance(payload, dict):
                    self.send_json(400, {"error": "Request body must be a JSON object."})
                    return
                ticket = helpdesk_service.add_comment(
                    match.group(1),
                    payload.get("comment"),
                    user,
                    connect_database,
                    DATABASE_LOCK,
                )
                if not ticket:
                    self.send_json(404, {"error": "Ticket not found."})
                    return
                self.send_json(201, {"ticket": ticket})
            elif demo_mode_enabled():
                self.require_non_demo_user(self.require_user())
                self.send_json(404, {"error": "Endpoint not found."})
            else:
                self.send_json(404, {"error": "Endpoint not found."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except DemoConfigurationError:
            self.send_json(503, {"error": "Demo mode is not configured correctly."})
        except DatabaseConfigurationError:
            self.send_json(500, {"error": "Database operation failed."})
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
            quick_access_match = re.fullmatch(
                r"/api/admin/quick-access/([^/]+)", parsed.path
            )
            if quick_access_match:
                self.require_non_demo_user(user)
                self.require_csrf()
                self.require_role(user, WRITE_ROLES)
                item = quick_access_service.update_item(
                    quick_access_match.group(1),
                    self.read_json_body(),
                    connect_database,
                    DATABASE_LOCK,
                )
                if not item:
                    self.send_json(404, {"error": "Quick Access item not found."})
                    return
                self.send_json(200, {"item": item})
                return
            if re.fullmatch(r"/api/helpdesk/tickets/[^/]+", parsed.path):
                self.require_non_demo_user(user)
                self.require_csrf()
                ticket_id = parsed.path.rsplit("/", 1)[-1]
                ticket = helpdesk_service.update_ticket(
                    ticket_id,
                    self.read_json_body(),
                    user,
                    connect_database,
                    DATABASE_LOCK,
                )
                if not ticket:
                    self.send_json(404, {"error": "Ticket not found."})
                    return
                self.send_json(200, {"ticket": ticket})
                return
            self.require_non_demo_user(user)
            self.require_csrf()
            self.require_role(user, WRITE_ROLES)
            match = re.fullmatch(r"/api/employees/([^/]+)", parsed.path)
            if not match:
                self.send_json(404, {"error": "Endpoint not found."})
                return
            employee_id = match.group(1)
            payload = self.read_json_body()
            status, response = employee_service.update_employee(
                employee_id,
                payload,
                user,
                connect_database,
                DATABASE_LOCK,
            )
            self.send_json(status, response)
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except DemoConfigurationError:
            self.send_json(503, {"error": "Demo mode is not configured correctly."})
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
            self.require_non_demo_user(user)
            self.require_csrf()
            self.require_role(user, WRITE_ROLES)
            quick_access_match = re.fullmatch(
                r"/api/admin/quick-access/([^/]+)", parsed.path
            )
            if quick_access_match:
                item_id = quick_access_match.group(1)
                if not quick_access_service.delete_item(
                    item_id, connect_database, DATABASE_LOCK
                ):
                    self.send_json(404, {"error": "Quick Access item not found."})
                    return
                self.send_json(200, {"deleted": item_id})
                return
            match = re.fullmatch(r"/api/employees/([^/]+)", parsed.path)
            if not match:
                self.send_json(404, {"error": "Endpoint not found."})
                return
            employee_id = match.group(1)
            if not employee_service.delete_employee(
                employee_id,
                user,
                connect_database,
                DATABASE_LOCK,
            ):
                self.send_json(404, {"error": "Employee not found."})
                return
            self.send_json(200, {"deleted": employee_id})
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except DemoConfigurationError:
            self.send_json(503, {"error": "Demo mode is not configured correctly."})
        except DatabaseConfigurationError:
            self.send_json(500, {"error": "Database operation failed."})
        except DATABASE_ERRORS:
            self.send_json(500, {"error": "Database operation failed."})

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if not self.valid_origin():
            self.send_json(403, {"error": "Request origin is not allowed."})
            return
        try:
            user = self.require_user()
            self.require_non_demo_user(user)
            self.require_csrf()
            self.require_role(user, WRITE_ROLES)
            match = re.fullmatch(
                r"/api/admin/quick-access/([^/]+)/status", parsed.path
            )
            if not match:
                self.send_json(404, {"error": "Endpoint not found."})
                return
            payload = self.read_json_body()
            if not isinstance(payload, dict):
                self.send_json(400, {"error": "Request body must be a JSON object."})
                return
            item = quick_access_service.set_status(
                match.group(1),
                payload.get("status"),
                connect_database,
                DATABASE_LOCK,
            )
            if not item:
                self.send_json(404, {"error": "Quick Access item not found."})
                return
            self.send_json(200, {"item": item})
        except PermissionError as error:
            self.send_json(403, {"error": str(error)})
        except LookupError as error:
            self.send_json(401, {"error": str(error)})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except DemoConfigurationError:
            self.send_json(503, {"error": "Demo mode is not configured correctly."})
        except DatabaseConfigurationError:
            self.send_json(500, {"error": "Database operation failed."})
        except DATABASE_INTEGRITY_ERRORS as error:
            self.send_json(409, {"error": self.integrity_message(error)})
        except DATABASE_ERRORS:
            self.send_json(500, {"error": "Database operation failed."})

    def handle_api_get(self, parsed):
        try:
            if parsed.path == "/api/auth/session":
                if demo_mode_enabled():
                    user = self.current_user()
                    if user:
                        self.send_json(200, {
                            "authenticated": True,
                            "demoMode": is_demo_user(user),
                            "user": user,
                        })
                    else:
                        self.start_demo_session()
                    return
                user = self.current_user()
                if not user:
                    payload = {"authenticated": False}
                    if getattr(self, "expired_session", False):
                        payload["expired"] = True
                    self.send_json(200, payload)
                    return
                self.send_json(200, {"authenticated": True, "user": user})
                return
            user = self.require_user()
            if parsed.path == "/api/portal/profile":
                if is_demo_user(user):
                    self.send_json(
                        200,
                        {"account": user, "employee": None, "demoMode": True},
                    )
                    return
                profile = employee_portal_service.get_profile(
                    user, connect_database, DATABASE_LOCK
                )
                if not profile:
                    self.send_json(404, {"error": "Profile not found."})
                    return
                self.send_json(200, profile)
                return
            if parsed.path == "/api/quick-access":
                if is_demo_user(user):
                    self.send_json(200, {"items": []})
                    return
                items = quick_access_service.list_items(
                    connect_database, DATABASE_LOCK, active_only=True
                )
                self.send_json(200, {"items": items})
                return
            quick_access_match = re.fullmatch(
                r"/api/quick-access/([^/]+)", parsed.path
            )
            if quick_access_match:
                if is_demo_user(user):
                    self.send_json(404, {"error": "Quick Access item not found."})
                    return
                item = quick_access_service.get_item(
                    quick_access_match.group(1),
                    connect_database,
                    DATABASE_LOCK,
                    active_only=True,
                )
                if not item:
                    self.send_json(404, {"error": "Quick Access item not found."})
                    return
                self.send_json(200, {"item": item})
                return
            if parsed.path == "/api/admin/quick-access":
                self.require_non_demo_user(user)
                self.require_role(user, WRITE_ROLES)
                items = quick_access_service.list_items(
                    connect_database, DATABASE_LOCK
                )
                self.send_json(200, {"items": items})
                return
            if is_demo_user(user):
                if parsed.path == "/api/dashboard/summary":
                    self.demo_dashboard_summary()
                    return
                if parsed.path == "/api/employees":
                    self.demo_list_employees(parse_qs(parsed.query))
                    return
                match = re.fullmatch(r"/api/employees/([^/]+)", parsed.path)
                if match:
                    self.demo_get_employee(match.group(1))
                    return
                self.send_json(404, {"error": "Endpoint not found."})
                return
            if parsed.path == "/api/helpdesk/dashboard/summary":
                result = helpdesk_service.dashboard_summary(
                    user, connect_database, DATABASE_LOCK
                )
                self.send_json(200, result)
                return
            if parsed.path == "/api/helpdesk/tickets":
                tickets = helpdesk_service.list_tickets(
                    user, connect_database, DATABASE_LOCK, parse_qs(parsed.query)
                )
                self.send_json(200, {"tickets": tickets})
                return
            match = re.fullmatch(r"/api/helpdesk/tickets/([^/]+)", parsed.path)
            if match:
                ticket = helpdesk_service.get_ticket(
                    match.group(1), user, connect_database, DATABASE_LOCK
                )
                if not ticket:
                    self.send_json(404, {"error": "Ticket not found."})
                    return
                self.send_json(200, {"ticket": ticket})
                return
            if parsed.path.startswith("/api/helpdesk/"):
                self.send_json(404, {"error": "Endpoint not found."})
                return
            if parsed.path == "/api/dashboard/summary":
                self.require_role(user, READ_ROLES)
                self.dashboard_summary()
                return
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
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except DemoConfigurationError:
            self.send_json(503, {"error": "Demo mode is not configured correctly."})
        except DatabaseConfigurationError:
            self.send_json(500, {"error": "Database operation failed."})
        except DATABASE_ERRORS:
            self.send_json(500, {"error": "Database operation failed."})

    def demo_list_employees(self, query):
        search = query.get("search", [""])[0].strip()[:100].casefold()
        department = query.get("department", [""])[0].strip()[:100]
        position = query.get("position", [""])[0].strip()[:100]
        status = query.get("status", [""])[0].strip().lower()
        sort_by = query.get("sortBy", ["name"])[0].strip().lower()
        sort_order = query.get("sortOrder", ["asc"])[0].strip().lower()
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
            page_size = min(100, max(1, int(query.get("pageSize", ["25"])[0])))
        except ValueError:
            self.send_json(400, {"error": "Page and pageSize must be integers."})
            return
        sort_fields = {
            "name": "name",
            "id": "id",
            "department": "department",
            "position": "position",
            "status": "status",
        }
        if status and status not in ("active", "inactive"):
            self.send_json(400, {"error": "Status must be active or inactive."})
            return
        if sort_by not in sort_fields or sort_order not in ("asc", "desc"):
            self.send_json(400, {"error": "Sort field or direction is invalid."})
            return

        records = demo_employee_records()
        departments = sorted({item["department"] for item in records}, key=str.casefold)
        positions = sorted({item["position"] for item in records}, key=str.casefold)
        filtered = [
            item for item in records
            if (not search or any(
                search in item[field].casefold()
                for field in ("id", "name", "email", "department", "position")
            ))
            and (not department or item["department"] == department)
            and (not position or item["position"] == position)
            and (not status or item["status"] == status)
        ]
        field = sort_fields[sort_by]
        filtered.sort(key=lambda item: (item[field].casefold(), item["id"].casefold()))
        if sort_order == "desc":
            filtered.reverse()
        total = len(filtered)
        start = (page - 1) * page_size
        summary = {
            "total": len(records),
            "active": sum(item["status"] == "active" for item in records),
            "inactive": sum(item["status"] == "inactive" for item in records),
            "departments": len({item["department"] for item in records}),
        }
        self.send_json(200, {
            "employees": filtered[start:start + page_size],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "summary": summary,
            "departments": departments,
            "positions": positions,
        })

    def demo_dashboard_summary(self):
        records = demo_employee_records()
        summary = {
            "total": len(records),
            "active": sum(item["status"] == "active" for item in records),
            "inactive": sum(item["status"] == "inactive" for item in records),
            "departments": len({item["department"] for item in records}),
            "new_this_month": len(records),
        }
        status_counts = {}
        department_counts = {}
        for item in records:
            status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
            department_counts[item["department"]] = department_counts.get(item["department"], 0) + 1
        self.send_json(200, {
            "summary": summary,
            "byStatus": [
                {"status": name, "total": count}
                for name, count in sorted(status_counts.items())
            ],
            "byDepartment": [
                {"department": name, "total": count}
                for name, count in sorted(
                    department_counts.items(),
                    key=lambda item: (-item[1], item[0].casefold()),
                )
            ],
        })

    def demo_get_employee(self, employee_id):
        employee = next(
            (item for item in demo_employee_records() if item["id"] == employee_id),
            None,
        )
        if not employee:
            self.send_json(404, {"error": "Employee not found."})
            return
        self.send_json(200, {"employee": employee})

    def list_employees(self, query):
        try:
            result = employee_service.list_employees(
                query, connect_database, DATABASE_LOCK
            )
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(200, result)

    def dashboard_summary(self):
        result = dashboard_service.get_summary(connect_database, DATABASE_LOCK)
        self.send_json(200, result)

    def get_employee(self, employee_id):
        employee = employee_service.get_employee(
            employee_id, connect_database, DATABASE_LOCK
        )
        if not employee:
            self.send_json(404, {"error": "Employee not found."})
            return
        self.send_json(200, {"employee": employee})

    def create_employee(self, payload):
        user = self.require_user()
        self.require_non_demo_user(user)
        self.require_csrf()
        self.require_role(user, WRITE_ROLES)
        employee = employee_service.create_employee(
            payload, user, connect_database, DATABASE_LOCK
        )
        self.send_json(201, {"employee": employee})

    def valid_origin(self):
        return is_valid_origin(self.headers.get("Origin"), HOST, PORT)

    @staticmethod
    def normalize_origin(value, require_https=False):
        return normalize_origin(value, require_https=require_https)

    @staticmethod
    def vercel_origin(domain):
        return vercel_origin(domain)

    @staticmethod
    def secure_cookie_attribute():
        return secure_cookie_attribute()


def main():
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("This development server must bind to loopback only.")
    try:
        DATABASE_PATH.relative_to(BASE_DIR)
    except ValueError:
        pass
    else:
        raise SystemExit("HRIS_DATABASE_PATH must be outside the served Helpdesk folder.")
    if not DATABASE_URL and not demo_mode_enabled():
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
