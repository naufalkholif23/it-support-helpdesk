import http.cookiejar
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

import hris_server
from api.index import handler as VercelApiHandler
from api.index import routed_request_path


class PostgresAdapterTests(unittest.TestCase):
    @unittest.skipIf(hris_server.psycopg is None, "psycopg is not installed")
    def test_database_url_selects_postgres_with_tls_and_named_rows(self):
        original_database_url = hris_server.DATABASE_URL
        hris_server.DATABASE_URL = "postgresql://test.invalid/test"
        fake_connection = Mock()
        try:
            with patch.object(hris_server.psycopg, "connect", return_value=fake_connection) as connect:
                connection = hris_server.connect_database()
            self.assertIsInstance(connection, hris_server.PostgresConnection)
            connect.assert_called_once_with(
                hris_server.DATABASE_URL,
                connect_timeout=5,
                row_factory=hris_server.dict_row,
                sslmode="require",
            )
            connection.close()
            fake_connection.close.assert_called_once()
        finally:
            hris_server.DATABASE_URL = original_database_url


@contextlib.contextmanager
def database_connection_context():
    connection = hris_server.connect_database()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


class EmployeeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        cls.original_database_path = hris_server.DATABASE_PATH
        cls.original_database_url = hris_server.DATABASE_URL
        cls.original_port = hris_server.PORT
        cls.original_environment = {
            name: os.environ.get(name)
            for name in (
                "HRIS_DEMO_PASSWORD",
                "HRIS_ALLOWED_ORIGINS",
                "HRIS_DEMO_MODE",
                "HRIS_DEMO_SESSION_SECRET",
                "VERCEL",
                "VERCEL_ENV",
            )
        }
        hris_server.DATABASE_URL = ""
        hris_server.DATABASE_PATH = hris_server.Path(cls.temp_directory.name) / "test.sqlite3"
        for name in (
            "HRIS_ALLOWED_ORIGINS",
            "HRIS_DEMO_MODE",
            "HRIS_DEMO_SESSION_SECRET",
            "VERCEL",
            "VERCEL_ENV",
        ):
            os.environ.pop(name, None)
        os.environ["HRIS_DEMO_PASSWORD"] = "test-only-password"

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        hris_server.PORT = port
        with contextlib.redirect_stdout(io.StringIO()):
            hris_server.initialize_database()
        cls.server = hris_server.ThreadingHTTPServer(("127.0.0.1", port), VercelApiHandler)
        cls.server.daemon_threads = False
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = "http://127.0.0.1:{}".format(port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)
        hris_server.DATABASE_PATH = cls.original_database_path
        hris_server.DATABASE_URL = cls.original_database_url
        hris_server.PORT = cls.original_port
        for name, value in cls.original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cls.temp_directory.cleanup()

    def setUp(self):
        with database_connection_context() as connection:
            connection.execute("DELETE FROM helpdesk_tickets")
        self.reset_client()

    def reset_client(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.csrf_token = ""

    def request(
        self, path, method="GET", payload=None, csrf=True, origin=None, include_origin=True
    ):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            if include_origin:
                headers["Origin"] = origin or self.base_url
            if csrf and self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method
        )
        try:
            response = self.client.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            return response.code, json.loads(response.read().decode("utf-8"))
        finally:
            response.close()

    def login(self, username):
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": username + "@example.test", "password": "test-only-password"},
        )
        self.assertEqual(status, 200)
        self.csrf_token = payload["csrfToken"]
        return payload["user"]

    def employee_payload(self, employee_id="SAMPLE-900"):
        return {
            "id": employee_id,
            "name": "Synthetic Test Employee",
            "email": employee_id.lower() + "@example.test",
            "department": "Quality",
            "position": "Sample Tester",
            "status": "active",
        }

    def helpdesk_payload(self):
        return {
            "name": "Synthetic Employee",
            "email": "employee@example.test",
            "department": "Testing",
            "category": "IT Support",
            "priority": "High",
            "subject": "Synthetic laptop test",
            "description": "A test-only ticket description.",
        }

    def test_helpdesk_employee_ticket_and_it_support_workflow(self):
        self.login("employee.demo")
        status, created = self.request(
            "/api/helpdesk/tickets",
            method="POST",
            payload=self.helpdesk_payload(),
        )
        self.assertEqual(status, 201)
        ticket = created["ticket"]
        ticket_id = ticket["id"]
        self.assertEqual(ticket["status"], "Open")
        self.assertEqual(ticket["reporter_username"], "employee.demo")
        self.assertEqual(ticket["timeline"][0]["type"], "created")

        status, listed = self.request("/api/helpdesk/tickets")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in listed["tickets"]], [ticket_id])
        status, comment = self.request(
            "/api/helpdesk/tickets/{}/comments".format(ticket_id),
            method="POST",
            payload={"comment": "Employee follow-up from the test."},
        )
        self.assertEqual(status, 201)
        self.assertEqual(comment["ticket"]["comments"][0]["author"], "employee.demo")

        self.reset_client()
        self.login("manager.demo")
        status, denied = self.request("/api/helpdesk/tickets/{}".format(ticket_id))
        self.assertEqual(status, 404)
        status, listed = self.request("/api/helpdesk/tickets")
        self.assertEqual(status, 200)
        self.assertEqual(listed["tickets"], [])
        status, _ = self.request(
            "/api/helpdesk/tickets/{}".format(ticket_id),
            method="PUT",
            payload={"status": "Resolved"},
        )
        self.assertEqual(status, 403)

        self.reset_client()
        user = self.login("it.support")
        self.assertIn("it_support", user["roles"])
        status, summary = self.request("/api/helpdesk/dashboard/summary")
        self.assertEqual(status, 200)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["byStatus"]["Open"], 1)
        status, listed = self.request("/api/helpdesk/tickets?search=laptop&priority=High")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in listed["tickets"]], [ticket_id])
        status, updated = self.request(
            "/api/helpdesk/tickets/{}".format(ticket_id),
            method="PUT",
            payload={
                "status": "In Progress",
                "pic": "it.support",
                "resolution": "Investigating",
                "comment": "Assigned to local IT Support.",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["ticket"]["status"], "In Progress")
        self.assertEqual(updated["ticket"]["pic"], "it.support")
        self.assertEqual(len(updated["ticket"]["comments"]), 2)

        self.reset_client()
        self.login("employee.demo")
        status, owned = self.request("/api/helpdesk/tickets/{}".format(ticket_id))
        self.assertEqual(status, 200)
        self.assertEqual(owned["ticket"]["status"], "In Progress")

    def test_helpdesk_routes_require_authentication_and_csrf(self):
        status, _ = self.request("/api/helpdesk/tickets")
        self.assertEqual(status, 401)
        self.login("employee.demo")
        request = urllib.request.Request(
            self.base_url + "/api/helpdesk/tickets",
            data=json.dumps(self.helpdesk_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": self.base_url},
            method="POST",
        )
        try:
            response = self.client.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            self.assertEqual(response.code, 403)
            self.assertIn("CSRF", response.read().decode("utf-8"))
        finally:
            response.close()

    def test_helpdesk_comment_rejects_non_object_json(self):
        self.login("employee.demo")
        status, created = self.request(
            "/api/helpdesk/tickets",
            method="POST",
            payload=self.helpdesk_payload(),
        )
        self.assertEqual(status, 201)
        status, payload = self.request(
            "/api/helpdesk/tickets/{}/comments".format(created["ticket"]["id"]),
            method="POST",
            payload=[],
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "Request body must be a JSON object.")

    def test_helpdesk_list_rejects_invalid_filters(self):
        self.login("employee.demo")
        status, payload = self.request("/api/helpdesk/tickets?status=Unreviewed")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "Status is invalid.")

    def test_employee_portal_profile_uses_only_the_signed_in_account(self):
        self.login("employee.demo")
        status, profile = self.request("/api/portal/profile")
        self.assertEqual(status, 200)
        self.assertEqual(profile["account"]["username"], "employee.demo")
        self.assertEqual(profile["employee"]["id"], "SAMPLE-001")
        self.assertEqual(profile["employee"]["name"], "Demo Employee Alpha")

        self.reset_client()
        self.login("manager.demo")
        status, profile = self.request("/api/portal/profile")
        self.assertEqual(status, 200)
        self.assertEqual(profile["account"]["username"], "manager.demo")
        self.assertIsNone(profile["employee"])

    def test_directory_requires_authentication(self):
        status, payload = self.request("/api/employees")
        self.assertEqual(status, 401)
        self.assertIn("Sign in", payload["error"])

    def test_login_uses_case_insensitive_account_email(self):
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": "HR.DEMO@EXAMPLE.TEST", "password": "test-only-password"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["authenticated"])
        status, session = self.request("/api/auth/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["username"], "hr.demo")

    def test_login_accepts_case_insensitive_username(self):
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": "HR.DEMO", "password": "test-only-password"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["authenticated"])
        status, session = self.request("/api/auth/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["username"], "hr.demo")

    def test_login_rejects_invalid_email_and_unknown_email_generically(self):
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": "not an identifier", "password": "wrong"},
        )
        self.assertEqual(status, 400)
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": "unknown@example.test", "password": "wrong"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "Invalid email or password.")
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": "unknown.user", "password": "wrong"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "Invalid email or password.")

    def test_database_errors_return_a_generic_login_response(self):
        with patch(
            "hris_server.connect_database",
            side_effect=hris_server.sqlite3.OperationalError("synthetic database detail"),
        ):
            status, payload = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo", "password": "test-only-password"},
            )
        self.assertEqual(status, 500)
        self.assertEqual(payload, {"error": "Database operation failed."})

    def test_existing_local_users_receive_demo_email_during_additive_migration(self):
        legacy_path = hris_server.Path(self.temp_directory.name) / "legacy.sqlite3"
        salt, password_hash = hris_server.hash_password("test-only-password")
        connection = hris_server.sqlite3.connect(str(legacy_path))
        try:
            connection.execute(
                "CREATE TABLE users (username TEXT PRIMARY KEY, role TEXT NOT NULL, "
                "password_salt TEXT NOT NULL, password_hash TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?)",
                ("hr.demo", "hr_admin", salt, password_hash),
            )
            connection.commit()
        finally:
            connection.close()

        original_path = hris_server.DATABASE_PATH
        hris_server.DATABASE_PATH = legacy_path
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                hris_server.initialize_database()
            with database_connection_context() as connection:
                row = connection.execute(
                    "SELECT email FROM users WHERE username = 'hr.demo'"
                ).fetchone()
            self.assertEqual(row["email"], "hr.demo@example.test")
            status, payload = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload["authenticated"])
        finally:
            hris_server.DATABASE_PATH = original_path

    def test_dashboard_summary_requires_authentication(self):
        status, payload = self.request("/api/dashboard/summary")
        self.assertEqual(status, 401)
        self.assertIn("Sign in", payload["error"])

    def test_hr_admin_can_read_aggregated_dashboard_summary(self):
        self.login("hr.demo")
        status, payload = self.request("/api/dashboard/summary")
        self.assertEqual(status, 200)
        self.assertIn("summary", payload)
        self.assertIn("byDepartment", payload)
        self.assertIn("byStatus", payload)
        self.assertNotIn("employees", payload)
        self.assertNotIn("email", payload)
        with database_connection_context() as connection:
            expected_total = connection.execute(
                "SELECT COUNT(*) FROM employees"
            ).fetchone()[0]
            expected_departments = connection.execute(
                "SELECT department, COUNT(*) AS total FROM employees "
                "GROUP BY department ORDER BY total DESC, LOWER(department)"
            ).fetchall()
            expected_status = connection.execute(
                "SELECT status, COUNT(*) AS total FROM employees GROUP BY status ORDER BY status"
            ).fetchall()
        self.assertEqual(payload["summary"]["total"], expected_total)
        now = hris_server.datetime.now(hris_server.timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (
            month_start.replace(year=month_start.year + 1, month=1)
            if month_start.month == 12
            else month_start.replace(month=month_start.month + 1)
        )
        with database_connection_context() as connection:
            expected_new_this_month = connection.execute(
                "SELECT COUNT(*) FROM employees WHERE created_at >= ? AND created_at < ?",
                (month_start.isoformat(), next_month.isoformat()),
            ).fetchone()[0]
        self.assertEqual(payload["summary"]["new_this_month"], expected_new_this_month)
        self.assertEqual(
            payload["byDepartment"],
            [dict(row) for row in expected_departments],
        )
        self.assertEqual(payload["byStatus"], [dict(row) for row in expected_status])

    def test_vercel_rewritten_session_route(self):
        status, payload = self.request("/api?__vercel_route=auth/session")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"authenticated": False})
        self.assertEqual(
            routed_request_path("/api?__vercel_route=public-entry"),
            "/api/public-entry",
        )

    def test_public_demo_mode_uses_only_synthetic_read_only_data(self):
        os.environ.pop("HRIS_DEMO_MODE", None)
        os.environ.pop("HRIS_DEMO_SESSION_SECRET", None)
        self.csrf_token = ""
        with patch.dict(os.environ, {
            "HRIS_DEMO_MODE": "1",
            "HRIS_DEMO_SESSION_SECRET": "test-demo-session-secret-" + ("x" * 32),
        }):
            with patch.object(
                hris_server,
                "connect_database",
                side_effect=AssertionError("Demo mode must not access a database."),
            ) as connect:
                status, payload = self.request("/api/auth/session")
                self.assertEqual(status, 200)
                self.assertTrue(payload["authenticated"])
                self.assertTrue(payload["demoMode"])
                self.assertEqual(payload["user"]["username"], "demo.viewer")
                self.assertEqual(payload["user"]["role"], "demo_viewer")
                self.csrf_token = payload["csrfToken"]

                status, payload = self.request("/api/auth/session")
                self.assertEqual(status, 200)
                self.assertTrue(payload["authenticated"])
                self.assertTrue(payload["demoMode"])
                self.assertEqual(payload["user"]["role"], "demo_viewer")

                status, payload = self.request("/api/dashboard/summary")
                self.assertEqual(status, 200)
                self.assertEqual(payload["summary"]["total"], 3)
                self.assertEqual(payload["summary"]["active"], 2)

                status, payload = self.request("/api/employees?search=demo")
                self.assertEqual(status, 200)
                self.assertEqual(payload["total"], 3)
                self.assertEqual(
                    {item["id"] for item in payload["employees"]},
                    {"DEMO-001", "DEMO-002", "DEMO-003"},
                )
                self.assertTrue(all(
                    item["email"].endswith("@example.test")
                    for item in payload["employees"]
                ))

                status, payload = self.request("/api/employees/DEMO-001")
                self.assertEqual(status, 200)
                self.assertEqual(payload["employee"]["id"], "DEMO-001")

                status, payload = self.request("/api/quick-access")
                self.assertEqual(status, 200)
                self.assertEqual(payload["items"], [])

                mutation_requests = (
                    ("POST", "/api/employees", self.employee_payload("DEMO-900")),
                    ("PUT", "/api/employees/DEMO-001", self.employee_payload("DEMO-001")),
                    ("DELETE", "/api/employees/DEMO-001", None),
                )
                for method, path, body in mutation_requests:
                    with self.subTest(method=method):
                        status, payload = self.request(path, method=method, payload=body)
                        self.assertEqual(status, 403)
                        self.assertIn("read-only", payload["error"])

                status, payload = self.request(
                    "/api/auth/logout", method="POST", payload={}
                )
                self.assertEqual(status, 200)
                self.assertFalse(payload["authenticated"])
                status, payload = self.request("/api/auth/session")
                self.assertEqual(status, 200)
                self.assertTrue(payload["authenticated"])
                self.assertTrue(payload["demoMode"])
                self.assertFalse(connect.called)

    def test_hr_admin_login_and_mutations_remain_available_when_demo_is_enabled(self):
        with patch.dict(os.environ, {
            "HRIS_DEMO_MODE": "1",
            "HRIS_DEMO_SESSION_SECRET": "test-demo-session-secret-" + ("x" * 32),
        }):
            status, payload = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
            )
            self.assertEqual(status, 200)
            self.csrf_token = payload["csrfToken"]

            status, session = self.request("/api/auth/session")
            self.assertEqual(status, 200)
            self.assertTrue(session["authenticated"])
            self.assertFalse(session["demoMode"])
            self.assertEqual(session["user"]["role"], "hr_admin")

            status, payload = self.request("/api/employees/DEMO-001")
            self.assertEqual(status, 404)
            status, payload = self.request("/api/employees/SAMPLE-001")
            self.assertEqual(status, 200)

            status, _ = self.request(
                "/api/employees",
                method="POST",
                payload=self.employee_payload("SAMPLE-900"),
            )
            self.assertEqual(status, 201)
            status, payload = self.request("/api/employees/SAMPLE-900", method="DELETE")
            self.assertEqual(status, 200)
            self.assertEqual(payload["deleted"], "SAMPLE-900")

    def test_demo_mode_can_be_enabled_separately_for_vercel_environments(self):
        for vercel_environment in ("preview", "production"):
            with self.subTest(vercel_environment=vercel_environment):
                with patch.dict(os.environ, {
                    "HRIS_DEMO_MODE": "1",
                    "VERCEL": "1",
                    "VERCEL_ENV": vercel_environment,
                }):
                    self.assertTrue(hris_server.demo_mode_enabled())

        with patch.dict(os.environ, {
            "HRIS_DEMO_MODE": "1",
            "VERCEL": "1",
            "VERCEL_ENV": "development",
        }):
            self.assertFalse(hris_server.demo_mode_enabled())
        with patch.dict(os.environ, {
            "HRIS_DEMO_MODE": "1",
            "VERCEL": "1",
        }):
            os.environ.pop("VERCEL_ENV", None)
            self.assertFalse(hris_server.demo_mode_enabled())

    def test_demo_mode_fails_closed_without_session_secret(self):
        with patch.dict(os.environ, {"HRIS_DEMO_MODE": "true"}, clear=False):
            os.environ.pop("HRIS_DEMO_SESSION_SECRET", None)
            with patch.object(
                hris_server,
                "connect_database",
                side_effect=AssertionError("Demo mode must not access a database."),
            ) as connect:
                status, payload = self.request("/api/auth/session")
                self.assertEqual(status, 503)
                self.assertEqual(payload["error"], "Demo mode is not configured correctly.")
                self.assertFalse(connect.called)

    def test_public_entry_redirects_to_dashboard_when_demo_mode_is_enabled(self):
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, response, code, message, headers, new_url):
                return None

        opener = urllib.request.build_opener(
            NoRedirectHandler(), urllib.request.HTTPCookieProcessor(self.cookies)
        )
        for vercel_environment in ("preview", "production"):
            with self.subTest(vercel_environment=vercel_environment):
                with patch.dict(os.environ, {
                    "HRIS_DEMO_MODE": "1",
                    "HRIS_DEMO_SESSION_SECRET": "test-demo-session-secret-" + ("x" * 32),
                    "VERCEL": "1",
                    "VERCEL_ENV": vercel_environment,
                }):
                    for path in ("/", "/api?__vercel_route=public-entry"):
                        request = urllib.request.Request(self.base_url + path)
                        try:
                            response = opener.open(request, timeout=5)
                        except urllib.error.HTTPError as error:
                            response = error
                        try:
                            self.assertEqual(response.code, 302)
                            self.assertEqual(
                                response.headers.get("Location"),
                                "/employee-hub#home",
                            )
                        finally:
                            response.close()

        request = urllib.request.Request(self.base_url + "/api?__vercel_route=public-entry")
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            self.assertEqual(response.code, 302)
            self.assertEqual(response.headers.get("Location"), "/login.html")
        finally:
            response.close()

    def test_payroll_role_cannot_read_employee_directory(self):
        self.login("payroll.demo")
        status, payload = self.request("/api/employees")
        self.assertEqual(status, 403)
        self.assertIn("not authorized", payload["error"])

    def test_employee_role_cannot_read_or_mutate_hr_directory(self):
        self.login("employee.demo")
        status, _ = self.request("/api/employees", method="POST", payload=self.employee_payload())
        self.assertEqual(status, 403)
        status, _ = self.request("/api/employees")
        self.assertEqual(status, 403)

    def test_manager_directory_access_is_denied_until_team_scope_exists(self):
        self.login("manager.demo")
        status, _ = self.request("/api/employees")
        self.assertEqual(status, 403)

    def test_non_hr_roles_are_denied_all_directory_operations(self):
        denied_operations = [
            ("GET", "/api/employees", None),
            ("GET", "/api/employees/SAMPLE-001", None),
            ("GET", "/api/dashboard/summary", None),
            ("POST", "/api/employees", self.employee_payload("RBAC-TEST-900")),
            ("PUT", "/api/employees/SAMPLE-001", self.employee_payload("SAMPLE-001")),
            ("DELETE", "/api/employees/SAMPLE-001", None),
        ]
        for username in ("employee.demo", "manager.demo", "payroll.demo"):
            with self.subTest(username=username):
                self.setUp()
                self.login(username)
                for method, path, payload in denied_operations:
                    with self.subTest(method=method, path=path):
                        status, _ = self.request(path, method=method, payload=payload)
                        self.assertEqual(status, 403)

        with database_connection_context() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM employees WHERE employee_id = 'RBAC-TEST-900'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM audit_logs WHERE employee_id = 'SAMPLE-001'"
                ).fetchone()[0],
                0,
            )

    def test_system_admin_can_read_and_mutate_directory(self):
        self.login("system.demo")
        status, _ = self.request("/api/employees")
        self.assertEqual(status, 200)
        status, _ = self.request("/api/dashboard/summary")
        self.assertEqual(status, 200)
        status, _ = self.request("/api/employees/SAMPLE-001")
        self.assertEqual(status, 200)

        status, _ = self.request(
            "/api/employees", method="POST", payload=self.employee_payload("SYSTEM-TEST-900")
        )
        self.assertEqual(status, 201)
        updated = self.employee_payload("SYSTEM-TEST-900")
        updated["name"] = "Synthetic System Admin Update"
        status, _ = self.request(
            "/api/employees/SYSTEM-TEST-900", method="PUT", payload=updated
        )
        self.assertEqual(status, 200)
        status, _ = self.request("/api/employees/SYSTEM-TEST-900", method="DELETE")
        self.assertEqual(status, 200)

    def test_existing_helpdesk_pages_are_served(self):
        for path in (
            "/",
            "/platform.html",
            "/employee-hub",
            "/hris",
            "/hris/",
            "/index.html",
            "/login.html",
            "/admin-login.html",
            "/admin.html",
        ):
            with self.subTest(path=path):
                response = self.client.open(self.base_url + path, timeout=5)
                try:
                    self.assertEqual(response.status, 200)
                    self.assertIn("text/html", response.headers.get("Content-Type", ""))
                    content = response.read()
                finally:
                    response.close()
                self.assertIn(b"<!DOCTYPE html>", content[:256])
                if path == "/":
                    self.assertIn(b"Suryanesia Employee Platform", content)
                    self.assertIn(b"Sign in", content)
                if path in ("/employee-hub", "/index.html"):
                    self.assertIn(b"auth-gate", content)
                    self.assertIn(b"EMPLOYEE HUB", content)
                    self.assertIn(b"DEMO MODE", content)
                if path in ("/hris", "/hris/"):
                    self.assertIn(b"auth-gate", content)
                    self.assertIn(b"function isHrisPlatform()", content)
                    self.assertIn(b"Loading HR dashboard...", content)
                if path == "/login.html":
                    self.assertIn(b'type="text"', content)
                    self.assertIn(b"Work email or username", content)
                    self.assertIn(b"/api/auth/login", content)
                    self.assertIn(b"Masuk ke Employee Hub", content)
                    self.assertIn(b"/api/auth/demo-login", content)
                    self.assertIn(b"Back to Platform Selection", content)
                    self.assertNotIn(b"admin123", content)

    def test_platform_home_templates_and_safe_login_return_paths_are_distinct(self):
        frontend = (hris_server.BASE_DIR / "index.html").read_text(encoding="utf-8")
        login = (hris_server.BASE_DIR / "login.html").read_text(encoding="utf-8")
        platform = (hris_server.BASE_DIR / "platform.html").read_text(encoding="utf-8")
        admin = (hris_server.BASE_DIR / "admin.html").read_text(encoding="utf-8")

        self.assertIn("const hrisDashboardHome = setDashboardHome();", frontend)
        self.assertIn("--transition-smooth: 260ms cubic-bezier(0.22, 1, 0.36, 1);", frontend)
        self.assertIn("@media (prefers-reduced-motion: reduce)", frontend)
        self.assertIn("#content-area.page-transition-out", frontend)
        self.assertIn("setAppModalOpen(modal, isOpen)", frontend)
        self.assertIn("class=\"app-modal fixed", frontend)
        self.assertIn("class=\"h-24 animate-pulse rounded-2xl bg-gray-200\"", frontend)
        self.assertIn("animate-pulse rounded-2xl border border-gray-200 bg-white p-5", frontend)
        self.assertNotIn("views.en.home = shell;", frontend)
        self.assertIn("viewId === 'home' && isHrisPlatform()", frontend)
        self.assertIn("configureEmployeeHubHome();", frontend)
        self.assertIn("isEmployeeHubHome && isHrisPlatform()", frontend)
        self.assertIn("const href = isEmployeeHubHome ? '/employee-hub#home' : item.href;", frontend)
        self.assertNotIn('class="sidebar-brand-text', frontend)
        self.assertIn('<img src="logo-green.png" alt="Suryanesia Logo" class="h-10 object-contain">', frontend)
        self.assertIn("id=\"employee-quick-access-grid\"", frontend)
        self.assertIn("id=\"request-quick-access-grid\"", frontend)
        self.assertIn('id="request-quick-access-grid" class="grid grid-cols-1 gap-5 md:grid-cols-2"', frontend)
        self.assertIn('bg-white rounded-2xl border border-gray-200 p-6 shadow-sm hover:border-surya-green transition-colors group flex h-full flex-col', frontend)
        self.assertIn("title: 'text-orange-600'", frontend)
        self.assertIn("button: 'group-hover:bg-orange-500'", frontend)
        self.assertIn("title: 'text-blue-600'", frontend)
        self.assertIn("button: 'group-hover:bg-blue-600'", frontend)
        self.assertIn("${colorTheme.button} group-hover:text-white transition-colors", frontend)
        self.assertIn("requestGrid ? 'grid-cols-1 md:grid-cols-2'", frontend)
        self.assertIn("Business Trip & Office Forms", frontend)
        self.assertIn("Form Perjalanan Dinas & Kantor", frontend)
        self.assertIn("renderQuickAccessGrid('request-quick-access-grid')", frontend)
        self.assertIn("if (viewId === 'request' && !isHrisPlatform()) loadQuickAccess();", frontend)
        self.assertIn("Business trip and office forms will appear here after an administrator configures and activates them.", frontend)
        self.assertNotIn("function quickAccessPageView()", frontend)
        self.assertNotIn("key: 'quick-access', route: 'quick-access'", frontend)
        self.assertIn("'quick-access-management': 'Form Management'", frontend)
        employee_hub_home = frontend.split("function configureEmployeeHubHome()", 1)[1].split(
            "configureEmployeeHubHome();", 1
        )[0]
        self.assertEqual(employee_hub_home.count('<img src="favicon.ico" alt="Suryanesia icon" class="h-full w-full object-contain">'), 2)
        self.assertEqual(employee_hub_home.count("h-32 w-32 items-center justify-center rounded-full bg-white p-2 shadow-xl"), 2)
        self.assertIn("max-w-6xl p-4 pb-12 md:p-8", employee_hub_home)
        self.assertIn("rounded-3xl bg-surya-green p-8 text-white shadow-lg md:flex-row md:p-10", employee_hub_home)
        self.assertIn("Everything you need,<br>in one place.", employee_hub_home)
        self.assertIn("Company update", employee_hub_home)
        self.assertIn("There are no company announcements published yet.", employee_hub_home)
        self.assertIn("Quick Request", employee_hub_home)
        self.assertIn("Find Something", employee_hub_home)
        self.assertIn("Quick Links", employee_hub_home)
        self.assertIn('aria-label="Company Calendar and Quick Actions"', employee_hub_home)
        self.assertIn('id="dashboard-calendar"', employee_hub_home)
        self.assertIn("No company events have been configured.", employee_hub_home)
        self.assertIn("onclick=\"navigate('my-requests')\"", employee_hub_home)
        self.assertIn("onclick=\"openTicketForm()\"", employee_hub_home)
        self.assertIn("onclick=\"navigate('company-information')\"", employee_hub_home)
        self.assertIn("onclick=\"navigate('links')\"", employee_hub_home)
        self.assertLess(employee_hub_home.index("Quick Request"), employee_hub_home.index("Frequently used"))
        self.assertLess(employee_hub_home.index("Frequently used"), employee_hub_home.index("employee-quick-access-grid"))
        self.assertIn("id=\"employee-hub-date\"", employee_hub_home)
        self.assertIn("hover-card rounded-2xl border border-gray-200 bg-white p-5 shadow-sm", frontend)
        self.assertIn("item.targetUrl", frontend)
        sidebar_menu = frontend.split("const sidebarMenu = [", 1)[1].split("const sidebarLabels", 1)[0]
        for earlier, later in (
            ("key: 'home'", "key: 'request-center'"),
            ("key: 'request-center'", "key: 'sop-guidelines'"),
            ("key: 'sop-guidelines'", "key: 'policies'"),
            ("key: 'policies'", "key: 'employee-corner'"),
            ("key: 'employee-corner'", "key: 'quick-links'"),
            ("key: 'quick-links'", "key: 'hris'"),
            ("key: 'hris'", "key: 'helpdesk'"),
        ):
            self.assertLess(sidebar_menu.index(earlier), sidebar_menu.index(later))
        self.assertNotIn("{ type: 'section', key: 'employee-hub' }", sidebar_menu)
        self.assertIn("key: 'employee-services'", sidebar_menu)
        self.assertIn("type: 'section', key: 'helpdesk'", sidebar_menu)
        self.assertIn("function loginDestination()", login)
        self.assertIn("@media (prefers-reduced-motion: reduce)", login)
        self.assertIn(".login-card,", login)
        self.assertIn("return '/employee-hub#home';", login)
        self.assertNotIn("return '/hris#home';", login)
        self.assertIn('href="/employee-hub"', platform)
        self.assertIn('href="/hris"', platform)
        self.assertIn("--transition-smooth: 260ms cubic-bezier(0.22, 1, 0.36, 1);", admin)
        self.assertIn("@media (prefers-reduced-motion: reduce)", admin)

    def test_root_entry_routes_to_login_or_employee_hub(self):
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, response, code, message, headers, new_url):
                return None

        opener = urllib.request.build_opener(
            NoRedirectHandler(), urllib.request.HTTPCookieProcessor(self.cookies)
        )
        try:
            response = opener.open(self.base_url + "/", timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            self.assertEqual(response.code, 302)
            self.assertEqual(response.headers.get("Location"), "/login.html")
        finally:
            response.close()

        self.login("system.demo")
        try:
            response = opener.open(self.base_url + "/", timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            self.assertEqual(response.code, 302)
            self.assertEqual(response.headers.get("Location"), "/employee-hub#home")
        finally:
            response.close()

    def test_employee_search_and_status_filters_are_paginated(self):
        self.login("system.demo")
        now = hris_server.datetime.now(hris_server.timezone.utc).isoformat()
        with database_connection_context() as connection:
            connection.executemany(
                "INSERT INTO employees "
                "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "PAGE-{:02d}".format(index),
                        "Page Sample {:02d}".format(index),
                        "page-{:02d}@example.test".format(index),
                        "Pagination",
                        "Synthetic Role",
                        "active" if index % 2 == 0 else "inactive",
                        now,
                        now,
                    )
                    for index in range(1, 28)
                ],
            )
        status, payload = self.request(
            "/api/employees?department=Pagination&position=Synthetic+Role&status=active"
            "&sortBy=id&sortOrder=desc&page=2&pageSize=5"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 13)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(len(payload["employees"]), 5)
        self.assertEqual(payload["employees"][0]["id"], "PAGE-16")
        self.assertIn("Pagination", payload["departments"])
        self.assertIn("Synthetic Role", payload["positions"])
        self.assertEqual(payload["summary"]["inactive"], 15)

        status, payload = self.request("/api/employees?sortBy=invalid")
        self.assertEqual(status, 400)

        status, payload = self.request("/api/employees?position=Missing+Role")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 0)

    def test_employee_department_and_position_facets_are_grouped_and_ordered(self):
        self.login("hr.demo")
        now = hris_server.datetime.now(hris_server.timezone.utc).isoformat()
        employee_ids = ("DISTINCT-900", "DISTINCT-901", "DISTINCT-902")
        with database_connection_context() as connection:
            connection.executemany(
                "INSERT INTO employees "
                "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        employee_id,
                        "Distinct Query Test",
                        employee_id.lower() + "@example.test",
                        department,
                        position,
                        "active",
                        now,
                        now,
                    )
                    for employee_id, department, position in zip(
                        employee_ids,
                        ("Regression Beta", "Regression Alpha", "Regression Alpha"),
                        ("Regression Role B", "Regression Role A", "Regression Role A"),
                    )
                ],
            )

        try:
            status, payload = self.request(
                "/api/employees?department=Regression+Alpha&position=Regression+Role+A"
                "&page=1&pageSize=1"
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["total"], 2)
            self.assertEqual(payload["page"], 1)
            self.assertEqual(len(payload["employees"]), 1)
            departments = [
                value for value in payload["departments"]
                if value.startswith("Regression ")
            ]
            positions = [
                value for value in payload["positions"]
                if value.startswith("Regression ")
            ]
            self.assertEqual(set(departments), {"Regression Alpha", "Regression Beta"})
            self.assertEqual(set(positions), {"Regression Role A", "Regression Role B"})
            self.assertEqual(
                [value.lower() for value in departments],
                sorted(value.lower() for value in departments),
            )
            self.assertEqual(
                [value.lower() for value in positions],
                sorted(value.lower() for value in positions),
            )
        finally:
            with database_connection_context() as connection:
                connection.executemany(
                    "DELETE FROM employees WHERE employee_id = ?",
                    [(employee_id,) for employee_id in employee_ids],
                )

    def test_hr_admin_can_create_search_update_and_delete_with_audit(self):
        user = self.login("hr.demo")
        self.assertEqual(user["role"], "hr_admin")
        status, dashboard_before = self.request("/api/dashboard/summary")
        self.assertEqual(status, 200)

        status, payload = self.request(
            "/api/employees", method="POST", payload=self.employee_payload()
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["employee"]["id"], "SAMPLE-900")

        status, payload = self.request("/api/employees?search=synthetic&department=Quality")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["employees"]), 1)
        self.assertEqual(payload["employees"][0]["id"], "SAMPLE-900")
        original_updated_at = payload["employees"][0]["updated_at"]

        updated = self.employee_payload()
        updated["name"] = "Synthetic Updated Employee"
        updated["department"] = "New Department"
        updated["status"] = "inactive"
        updated["updated_at"] = original_updated_at
        status, payload = self.request(
            "/api/employees/SAMPLE-900", method="PUT", payload=updated
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["employee"]["status"], "inactive")
        status, dashboard = self.request("/api/dashboard/summary")
        self.assertEqual(status, 200)
        self.assertEqual(
            dashboard["summary"]["total"],
            dashboard_before["summary"]["total"] + 1,
        )
        self.assertEqual(
            next(item["total"] for item in dashboard["byStatus"] if item["status"] == "inactive"),
            next(
                item["total"]
                for item in dashboard_before["byStatus"]
                if item["status"] == "inactive"
            ) + 1,
        )
        self.assertEqual(
            next(item["total"] for item in dashboard["byDepartment"] if item["department"] == "New Department"),
            1,
        )

        status, payload = self.request("/api/employees?status=inactive&search=Updated")
        self.assertEqual(status, 200)
        self.assertEqual(payload["employees"][0]["id"], "SAMPLE-900")
        self.assertEqual(payload["summary"]["total"], dashboard["summary"]["total"])
        self.assertEqual(payload["summary"]["inactive"], dashboard["summary"]["inactive"])
        stale_update = self.employee_payload()
        stale_update["updated_at"] = original_updated_at
        status, payload = self.request(
            "/api/employees/SAMPLE-900", method="PUT", payload=stale_update
        )
        self.assertEqual(status, 409)
        self.assertIn("changed", payload["error"])

        status, payload = self.request("/api/employees/SAMPLE-900", method="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(payload["deleted"], "SAMPLE-900")

        with database_connection_context() as connection:
            actions = [
                row["action"]
                for row in connection.execute(
                    "SELECT action FROM audit_logs WHERE employee_id = 'SAMPLE-900' ORDER BY id"
                ).fetchall()
            ]
        self.assertEqual(actions, ["employee.created", "employee.updated", "employee.deleted"])

    def test_validation_duplicate_conflict_and_csrf(self):
        self.login("hr.demo")
        invalid = self.employee_payload()
        invalid["email"] = "not-an-email"
        status, _ = self.request("/api/employees", method="POST", payload=invalid)
        self.assertEqual(status, 400)

        status, _ = self.request(
            "/api/employees", method="POST", payload=self.employee_payload("SAMPLE-001")
        )
        self.assertEqual(status, 409)

        status, _ = self.request(
            "/api/employees", method="POST", payload=self.employee_payload("SAMPLE-901"), csrf=False
        )
        self.assertEqual(status, 403)

    def test_put_and_delete_require_origin_and_csrf(self):
        self.login("hr.demo")
        original_employee = self.employee_payload("SAMPLE-001")
        original_employee.update({
            "name": "Demo Employee Alpha",
            "email": "alpha@example.test",
            "department": "People Operations",
            "position": "Sample Coordinator",
        })

        mutation_requests = (
            ("PUT", "/api/employees/SAMPLE-001", original_employee),
            ("DELETE", "/api/employees/SAMPLE-001", None),
        )
        for method, path, payload in mutation_requests:
            with self.subTest(method=method, failure="missing origin"):
                status, _ = self.request(
                    path,
                    method=method,
                    payload=payload,
                    include_origin=False,
                )
                self.assertEqual(status, 403)

            with self.subTest(method=method, failure="missing csrf"):
                status, _ = self.request(
                    path,
                    method=method,
                    payload=payload,
                    csrf=False,
                )
                self.assertEqual(status, 403)

        with database_connection_context() as connection:
            employee = connection.execute(
                "SELECT full_name, email FROM employees WHERE employee_id = ?",
                ("SAMPLE-001",),
            ).fetchone()
            self.assertEqual(employee["full_name"], "Demo Employee Alpha")
            self.assertEqual(employee["email"], "alpha@example.test")
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM audit_logs WHERE employee_id = ?",
                    ("SAMPLE-001",),
                ).fetchone()[0],
                0,
            )

    def test_logout_revokes_session(self):
        self.login("hr.demo")
        status, _ = self.request("/api/auth/logout", method="POST")
        self.assertEqual(status, 200)
        status, payload = self.request("/api/employees")
        self.assertEqual(status, 401)
        self.assertIn("Sign in", payload["error"])

    def test_expired_session_is_reported_and_revoked(self):
        self.login("hr.demo")
        with database_connection_context() as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = ?",
                ("2000-01-01T00:00:00+00:00",),
            )
        status, payload = self.request("/api/auth/session")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"authenticated": False, "expired": True})
        status, payload = self.request("/api/auth/session")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"authenticated": False})

    def test_session_cookie_is_secure_for_production_deployments(self):
        original_vercel_env = os.environ.get("VERCEL_ENV")
        os.environ["VERCEL_ENV"] = "production"
        try:
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
            )
            self.assertEqual(status, 200)
            session_cookie = next(
                cookie for cookie in self.cookies if cookie.name == "hris_session"
            )
            self.assertTrue(session_cookie.secure)
            self.assertTrue(session_cookie.has_nonstandard_attr("HttpOnly"))
            self.assertEqual(session_cookie.get_nonstandard_attr("SameSite"), "Strict")
        finally:
            if original_vercel_env is None:
                os.environ.pop("VERCEL_ENV", None)
            else:
                os.environ["VERCEL_ENV"] = original_vercel_env

    def test_postgres_schema_is_never_initialized_implicitly(self):
        original_database_url = hris_server.DATABASE_URL
        hris_server.DATABASE_URL = "postgresql://example.invalid/not-used"
        try:
            with self.assertRaisesRegex(RuntimeError, "migration"):
                hris_server.initialize_database()
        finally:
            hris_server.DATABASE_URL = original_database_url

    def test_postgres_connection_translates_sql_placeholders(self):
        class FakeConnection:
            def execute(self, statement, parameters):
                self.statement = statement
                self.parameters = parameters
                return "cursor"

        connection = FakeConnection()
        adapter = hris_server.PostgresConnection(connection)
        result = adapter.execute("SELECT ? WHERE name = ?", (1, "synthetic"))
        self.assertEqual(result, "cursor")
        self.assertEqual(connection.statement, "SELECT %s WHERE name = %s")
        self.assertEqual(connection.parameters, (1, "synthetic"))

    def test_vercel_requires_managed_database_configuration(self):
        original_vercel = os.environ.get("VERCEL")
        original_database_url = hris_server.DATABASE_URL
        hris_server.DATABASE_URL = ""
        os.environ["VERCEL"] = "1"
        try:
            with self.assertRaisesRegex(
                hris_server.DatabaseConfigurationError, "DATABASE_URL"
            ):
                hris_server.connect_database()
        finally:
            hris_server.DATABASE_URL = original_database_url
            if original_vercel is None:
                os.environ.pop("VERCEL", None)
            else:
                os.environ["VERCEL"] = original_vercel

    def test_vercel_rewrite_restores_api_path_and_forwards_query(self):
        cases = (
            (
                "/api?__vercel_route=auth/session",
                "/api/auth/session",
            ),
            (
                "/api?__vercel_route=employees&search=sample+name&page=2&pageSize=10",
                "/api/employees?search=sample+name&page=2&pageSize=10",
            ),
            (
                "/api?__vercel_route=employees%2FSAMPLE-001",
                "/api/employees/SAMPLE-001",
            ),
        )
        for rewritten_path, expected_path in cases:
            with self.subTest(rewritten_path=rewritten_path):
                self.assertEqual(routed_request_path(rewritten_path), expected_path)

    def test_mutations_require_an_exact_configured_origin(self):
        original_allowed_origins = os.environ.get("HRIS_ALLOWED_ORIGINS")
        os.environ["HRIS_ALLOWED_ORIGINS"] = " https://HUB.example.test:443/, "
        try:
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                origin="https://untrusted.example.test",
            )
            self.assertEqual(status, 403)
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                include_origin=False,
            )
            self.assertEqual(status, 403)

            status, payload = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                origin="https://hub.example.test",
            )
            self.assertEqual(status, 200)
            self.csrf_token = payload["csrfToken"]
            status, session = self.request("/api/auth/session")
            self.assertEqual(status, 200)
            self.assertTrue(session["authenticated"])

            status, _ = self.request(
                "/api/auth/logout",
                method="POST",
                csrf=False,
                origin="https://hub.example.test",
            )
            self.assertEqual(status, 403)
            status, _ = self.request(
                "/api/auth/logout",
                method="POST",
                origin="https://hub.example.test",
            )
            self.assertEqual(status, 200)
        finally:
            if original_allowed_origins is None:
                os.environ.pop("HRIS_ALLOWED_ORIGINS", None)
            else:
                os.environ["HRIS_ALLOWED_ORIGINS"] = original_allowed_origins

    def test_vercel_rejects_http_origins_and_untrusted_ports(self):
        original_environment = {
            name: os.environ.get(name)
            for name in (
                "VERCEL_ENV",
                "VERCEL_URL",
                "VERCEL_PROJECT_PRODUCTION_URL",
                "HRIS_ALLOWED_ORIGINS",
            )
        }
        os.environ["VERCEL_ENV"] = "production"
        os.environ["VERCEL_URL"] = "employee-hub-deployment.vercel.app"
        os.environ["VERCEL_PROJECT_PRODUCTION_URL"] = "employee.suryanesia.example"
        os.environ["HRIS_ALLOWED_ORIGINS"] = (
            "http://employee.suryanesia.example, "
            "https://*.suryanesia.example"
        )
        try:
            for origin in (
                "http://employee.suryanesia.example",
                "https://employee.suryanesia.example:8443",
                "https://employee.suryanesia.example.attacker.test",
                "https://preview.suryanesia.example",
                "null",
            ):
                with self.subTest(origin=origin):
                    status, _ = self.request(
                        "/api/auth/login",
                        method="POST",
                        payload={
                            "email": "hr.demo@example.test",
                            "password": "test-only-password",
                        },
                        origin=origin,
                    )
                    self.assertEqual(status, 403)
        finally:
            for name, value in original_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_vercel_origin_allowlist_uses_deployment_and_production_domains(self):
        original_environment = {
            name: os.environ.get(name)
            for name in (
                "VERCEL_ENV",
                "VERCEL_URL",
                "VERCEL_PROJECT_PRODUCTION_URL",
                "HRIS_ALLOWED_ORIGINS",
            )
        }
        os.environ["VERCEL_ENV"] = "production"
        os.environ["VERCEL_URL"] = "employee-hub-deployment.vercel.app"
        os.environ["VERCEL_PROJECT_PRODUCTION_URL"] = "employee.suryanesia.example"
        os.environ.pop("HRIS_ALLOWED_ORIGINS", None)
        try:
            status, payload = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                origin="https://employee.suryanesia.example",
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload["authenticated"])

            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                origin="https://employee-hub-deployment.vercel.app",
            )
            self.assertEqual(status, 200)
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                origin="https://untrusted.example.test",
            )
            self.assertEqual(status, 403)

            os.environ["VERCEL_ENV"] = "preview"
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                origin="https://employee.suryanesia.example",
            )
            self.assertEqual(status, 403)
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"email": "hr.demo@example.test", "password": "test-only-password"},
                origin="https://employee-hub-deployment.vercel.app",
            )
            self.assertEqual(status, 200)
        finally:
            for name, value in original_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_request_logs_do_not_include_search_terms_or_employee_ids(self):
        self.login("hr.demo")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status, _ = self.request(
                "/api/employees?search=synthetic-private-search-term"
            )
            self.assertEqual(status, 200)
            status, _ = self.request("/api/employees/SAMPLE-001")
            self.assertEqual(status, 200)
        logged = output.getvalue()
        self.assertNotIn("synthetic-private-search-term", logged)
        self.assertNotIn("SAMPLE-001", logged)

    def test_quick_access_requires_hr_role_and_manages_employee_forms(self):
        self.login("employee.demo")
        status, items = self.request("/api/quick-access")
        self.assertEqual(status, 200)
        self.assertEqual(items["items"], [])
        status, _ = self.request("/api/admin/quick-access")
        self.assertEqual(status, 403)
        status, _ = self.request(
            "/api/admin/quick-access",
            method="POST",
            payload={"title": "Unauthorized"},
        )
        self.assertEqual(status, 403)
        self.reset_client()
        self.login("it.support")
        status, _ = self.request("/api/admin/quick-access")
        self.assertEqual(status, 403)

        self.reset_client()
        self.login("hr.demo")
        status, defaults = self.request("/api/admin/quick-access")
        self.assertEqual(status, 200)
        by_id = {item["id"]: item for item in defaults["items"]}
        self.assertEqual(set(by_id), {"business-trip", "office-amenities"})
        self.assertEqual(by_id["business-trip"]["status"], "draft")
        self.assertIsNone(by_id["business-trip"]["targetUrl"])

        status, activation_error = self.request(
            "/api/admin/quick-access/office-amenities/status",
            method="PATCH",
            payload={"status": "active"},
        )
        self.assertEqual(status, 400)
        self.assertIn("URL", activation_error["error"])

        payload = {
            "title": "Business Trip Form",
            "description": "Submit a business trip request.",
            "category": "HR / Administration",
            "icon": "fa-plane",
            "displayOrder": 1,
            "visibility": "employees",
            "status": "active",
        }
        status, invalid = self.request(
            "/api/admin/quick-access/business-trip",
            method="PUT",
            payload={**payload, "targetUrl": "http://docs.google.com/forms/d/e/test/viewform"},
        )
        self.assertEqual(status, 400)
        self.assertIn("Google Forms URL", invalid["error"])

        form_url = "https://docs.google.com/forms/d/e/synthetic-id/viewform"
        status, item = self.request(
            "/api/admin/quick-access/business-trip",
            method="PUT",
            payload={**payload, "targetUrl": form_url},
        )
        self.assertEqual(status, 200)
        self.assertEqual(item["item"]["status"], "active")

        status, created = self.request(
            "/api/admin/quick-access",
            method="POST",
            payload={
                "title": "Synthetic Test Shortcut",
                "description": "A test-only shortcut.",
                "category": "Testing",
                "icon": "fa-flask",
                "targetUrl": "https://forms.gle/synthetic-test-form",
                "displayOrder": 3,
                "visibility": "employees",
                "status": "active",
            },
        )
        self.assertEqual(status, 201)
        created_id = created["item"]["id"]

        self.reset_client()
        self.login("employee.demo")
        status, visible = self.request("/api/quick-access")
        self.assertEqual(status, 200)
        self.assertEqual(
            [entry["id"] for entry in visible["items"]],
            ["business-trip", created_id],
        )
        status, hidden = self.request("/api/quick-access/office-amenities")
        self.assertEqual(status, 404)

        self.reset_client()
        self.login("hr.demo")
        status, changed = self.request(
            "/api/admin/quick-access/business-trip/status",
            method="PATCH",
            payload={"status": "inactive"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(changed["item"]["status"], "inactive")
        status, deleted = self.request(
            "/api/admin/quick-access/office-amenities",
            method="DELETE",
        )
        self.assertEqual(status, 200)
        self.assertEqual(deleted["deleted"], "office-amenities")
        status, deleted = self.request(
            "/api/admin/quick-access/{}".format(created_id),
            method="DELETE",
        )
        self.assertEqual(status, 200)

        with database_connection_context() as connection:
            connection.execute(
                "UPDATE quick_access_items SET status = 'draft', target_url = NULL "
                "WHERE id = 'business-trip'"
            )
            connection.execute(
                "INSERT INTO quick_access_items "
                "(id, title, description, category, icon, target_url, display_order, "
                "visibility, status, created_by, created_at, updated_at) "
                "VALUES ('office-amenities', 'Office Amenities Form', "
                "'Request office supplies and amenities.', 'Office', 'fa-box-open', "
                "NULL, 2, 'employees', 'draft', NULL, 'test', 'test')"
            )

    def test_quick_access_rejects_non_google_urls_and_employee_status_mutations(self):
        self.login("employee.demo")
        status, _ = self.request(
            "/api/admin/quick-access/business-trip/status",
            method="PATCH",
            payload={"status": "active"},
        )
        self.assertEqual(status, 403)
        self.reset_client()
        self.login("hr.demo")
        status, payload = self.request(
            "/api/admin/quick-access/business-trip",
            method="PUT",
            payload={
                "title": "Business Trip Form",
                "description": "Submit a business trip request.",
                "category": "HR / Administration",
                "icon": "fa-plane",
                "targetUrl": "https://example.test/forms/business-trip",
                "displayOrder": 1,
                "visibility": "employees",
                "status": "active",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("Google Forms URL", payload["error"])

if __name__ == "__main__":
    unittest.main()
