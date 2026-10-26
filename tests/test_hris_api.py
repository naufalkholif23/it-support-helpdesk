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

import hris_server
from api.index import handler as VercelApiHandler
from api.index import routed_request_path


@contextlib.contextmanager
def test_database_connection():
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
                "VERCEL",
                "VERCEL_ENV",
            )
        }
        hris_server.DATABASE_URL = ""
        hris_server.DATABASE_PATH = hris_server.Path(cls.temp_directory.name) / "test.sqlite3"
        for name in ("HRIS_ALLOWED_ORIGINS", "VERCEL", "VERCEL_ENV"):
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
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.csrf_token = ""

    def request(self, path, method="GET", payload=None, csrf=True):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if method in ("POST", "PUT", "DELETE"):
            headers["Origin"] = self.base_url
            if csrf and self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method
        )
        try:
            response = self.client.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        return response.code, json.loads(response.read().decode("utf-8"))

    def login(self, username):
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"username": username, "password": "test-only-password"},
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

    def test_directory_requires_authentication(self):
        status, payload = self.request("/api/employees")
        self.assertEqual(status, 401)
        self.assertIn("Sign in", payload["error"])

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
        with test_database_connection() as connection:
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
        with test_database_connection() as connection:
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

        with test_database_connection() as connection:
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
        for path in ("/", "/index.html", "/login.html", "/admin-login.html", "/admin.html"):
            with self.subTest(path=path):
                response = self.client.open(self.base_url + path, timeout=5)
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers.get("Content-Type", ""))
                self.assertIn(b"<!DOCTYPE html>", response.read()[:256])

    def test_employee_search_and_status_filters_are_paginated(self):
        self.login("system.demo")
        now = hris_server.datetime.now(hris_server.timezone.utc).isoformat()
        with test_database_connection() as connection:
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

        with test_database_connection() as connection:
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

    def test_logout_revokes_session(self):
        self.login("hr.demo")
        status, _ = self.request("/api/auth/logout", method="POST")
        self.assertEqual(status, 200)
        status, payload = self.request("/api/employees")
        self.assertEqual(status, 401)
        self.assertIn("Sign in", payload["error"])

    def test_session_cookie_is_secure_for_production_deployments(self):
        original_vercel_env = os.environ.get("VERCEL_ENV")
        os.environ["VERCEL_ENV"] = "production"
        try:
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"username": "hr.demo", "password": "test-only-password"},
            )
            self.assertEqual(status, 200)
            session_cookie = next(
                cookie for cookie in self.cookies if cookie.name == "hris_session"
            )
            self.assertTrue(session_cookie.secure)
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
        os.environ["HRIS_ALLOWED_ORIGINS"] = "https://hub.example.test"
        try:
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"username": "hr.demo", "password": "test-only-password"},
            )
            self.assertEqual(status, 403)

            os.environ["HRIS_ALLOWED_ORIGINS"] = self.base_url
            status, _ = self.request(
                "/api/auth/login",
                method="POST",
                payload={"username": "hr.demo", "password": "test-only-password"},
            )
            self.assertEqual(status, 200)
        finally:
            if original_allowed_origins is None:
                os.environ.pop("HRIS_ALLOWED_ORIGINS", None)
            else:
                os.environ["HRIS_ALLOWED_ORIGINS"] = original_allowed_origins

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


if __name__ == "__main__":
    unittest.main()
