import http.cookiejar
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit

import hris_server


NEON_PROJECT_ID = "small-sound-44823719"
NEON_BRANCH_ID = "br-autumn-art-az0q5n0y"
NEON_BRANCH_NAME = "employee-hub-testing"
DATABASE_NAME = "neondb"
EXPECTED_DATABASE_HOST = "ep-morning-hall-azdybl02.c-3.ap-southeast-1.aws.neon.tech"
EXPECTED_DATABASE_HOSTS = {
    EXPECTED_DATABASE_HOST,
    EXPECTED_DATABASE_HOST.replace(".c-", "-pooler.c-", 1),
}


def configured_database_host(database_url):
    parsed = None
    try:
        parsed = urlsplit(database_url)
        hostname = parsed.hostname
        database_name = unquote(parsed.path.lstrip("/"))
    except (AttributeError, ValueError):
        hostname = None
        database_name = None

    if (
        not parsed
        or parsed.scheme not in ("postgres", "postgresql")
        or not hostname
        or database_name != DATABASE_NAME
    ):
        raise RuntimeError("Neon integration test database target could not be verified.")
    return hostname.lower().rstrip(".")


def verify_neon_branch_metadata(database_host, branch_response, endpoints_response):
    branches = branch_response.get("branches") if isinstance(branch_response, dict) else None
    matching_branches = [
        branch for branch in branches or []
        if isinstance(branch, dict)
        and branch.get("id") == NEON_BRANCH_ID
        and branch.get("name") == NEON_BRANCH_NAME
        and branch.get("project_id") == NEON_PROJECT_ID
        and branch.get("default") is False
        and branch.get("primary") is False
    ]
    if len(matching_branches) != 1 or database_host not in EXPECTED_DATABASE_HOSTS:
        raise RuntimeError("Neon integration test database target could not be verified.")

    endpoints = (
        endpoints_response.get("endpoints")
        if isinstance(endpoints_response, dict)
        else None
    )
    matching_hosts = set()
    for endpoint in endpoints or []:
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("project_id") != NEON_PROJECT_ID
            or endpoint.get("branch_id") != NEON_BRANCH_ID
            or endpoint.get("type") != "read_write"
            or endpoint.get("disabled")
        ):
            continue
        hosts = endpoint.get("hosts", {})
        if not isinstance(hosts, dict):
            continue
        for host in (
            endpoint.get("host"),
            hosts.get("read_write_host"),
            hosts.get("read_write_pooled_host"),
        ):
            if isinstance(host, str) and host:
                matching_hosts.add(host.lower().rstrip("."))

    if database_host not in matching_hosts:
        raise RuntimeError("Neon integration test database target could not be verified.")


def neon_api_json(path):
    executable = shutil.which("neon.cmd") if os.name == "nt" else shutil.which("neon")
    if not executable:
        raise RuntimeError("Authenticated Neon CLI is required to verify the test database.")

    arguments = [executable, "api", path, "--output", "json"]
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        arguments = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            subprocess.list2cmdline(arguments),
        ]
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Neon branch verification failed.") from None
    if result.returncode != 0:
        raise RuntimeError("Neon branch verification failed.")
    try:
        return json.loads(result.stdout)
    except (TypeError, ValueError):
        raise RuntimeError("Neon branch metadata could not be verified.") from None


def verify_neon_testing_database(database_url):
    database_host = configured_database_host(database_url)
    branches = neon_api_json("/projects/{}/branches".format(NEON_PROJECT_ID))
    endpoints = neon_api_json(
        "/projects/{}/branches/{}/endpoints".format(
            NEON_PROJECT_ID, NEON_BRANCH_ID
        )
    )
    verify_neon_branch_metadata(database_host, branches, endpoints)


class NeonTargetGuardTests(unittest.TestCase):
    def setUp(self):
        pooled_host = EXPECTED_DATABASE_HOST.replace(".c-", "-pooler.c-", 1)
        self.branch_response = {
            "branches": [{
                "id": NEON_BRANCH_ID,
                "name": NEON_BRANCH_NAME,
                "project_id": NEON_PROJECT_ID,
                "default": False,
                "primary": False,
            }]
        }
        self.endpoints_response = {
            "endpoints": [{
                "project_id": NEON_PROJECT_ID,
                "branch_id": NEON_BRANCH_ID,
                "type": "read_write",
                "host": EXPECTED_DATABASE_HOST,
                "hosts": {
                    "read_write_host": EXPECTED_DATABASE_HOST,
                    "read_write_pooled_host": pooled_host,
                },
            }]
        }

    def test_accepts_verified_testing_branch_and_endpoint(self):
        verify_neon_branch_metadata(
            EXPECTED_DATABASE_HOST,
            self.branch_response,
            self.endpoints_response,
        )

    def test_accepts_testing_branch_pooler_endpoint(self):
        pooled_host = EXPECTED_DATABASE_HOST.replace(".c-", "-pooler.c-", 1)
        verify_neon_branch_metadata(
            pooled_host,
            self.branch_response,
            self.endpoints_response,
        )

    def test_rejects_default_branch(self):
        self.branch_response["branches"][0]["default"] = True
        with self.assertRaises(RuntimeError):
            verify_neon_branch_metadata(
                EXPECTED_DATABASE_HOST,
                self.branch_response,
                self.endpoints_response,
            )

    def test_rejects_main_branch_identity(self):
        self.branch_response["branches"][0]["name"] = "main"
        with self.assertRaises(RuntimeError):
            verify_neon_branch_metadata(
                EXPECTED_DATABASE_HOST,
                self.branch_response,
                self.endpoints_response,
            )

    def test_rejects_host_not_owned_by_testing_branch(self):
        with self.assertRaises(RuntimeError):
            verify_neon_branch_metadata(
                "ep-production.example.neon.tech",
                self.branch_response,
                self.endpoints_response,
            )

    def test_rejects_endpoint_with_wrong_branch_identity(self):
        self.endpoints_response["endpoints"][0]["branch_id"] = "br-main"
        with self.assertRaises(RuntimeError):
            verify_neon_branch_metadata(
                EXPECTED_DATABASE_HOST,
                self.branch_response,
                self.endpoints_response,
            )

    def test_rejects_connection_url_for_wrong_database(self):
        with self.assertRaises(RuntimeError):
            configured_database_host(
                "postgresql://{}".format(EXPECTED_DATABASE_HOST)
            )


@unittest.skipUnless(
    os.environ.get("HRIS_TEST_DATABASE_URL"),
    "Set HRIS_TEST_DATABASE_URL to run the isolated Neon integration test.",
)
class NeonPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_database_url = hris_server.DATABASE_URL
        cls.original_host = hris_server.HOST
        cls.original_port = hris_server.PORT
        test_database_url = os.environ["HRIS_TEST_DATABASE_URL"].strip()
        verify_neon_testing_database(test_database_url)
        hris_server.DATABASE_URL = test_database_url
        cls.username = "neon-test-" + secrets.token_hex(6)
        cls.email = cls.username + "@example.test"
        cls.password = secrets.token_urlsafe(24)
        cls.user_created = False
        cls.environment_names = (
            "HRIS_ALLOWED_ORIGINS",
            "VERCEL",
            "VERCEL_ENV",
            "VERCEL_URL",
            "VERCEL_PROJECT_PRODUCTION_URL",
        )
        cls.original_environment = {
            name: os.environ.get(name) for name in cls.environment_names
        }
        for name in cls.environment_names:
            os.environ.pop(name, None)

        try:
            connection = hris_server.connect_database()
            try:
                database = connection.execute(
                    "SELECT current_database() AS name"
                ).fetchone()
                if database["name"] != "neondb":
                    raise RuntimeError("Integration tests require the neondb database.")
                counts = {
                    table: connection.execute(
                        "SELECT COUNT(*) AS count FROM " + table
                    ).fetchone()["count"]
                    for table in ("users", "employees", "sessions", "audit_logs")
                }
                if any(counts.values()):
                    raise RuntimeError(
                        "Integration tests require an empty employee-hub-testing database."
                    )

                salt, password_hash = hris_server.hash_password(cls.password)
                connection.execute(
                    "INSERT INTO users (username, email, role, password_salt, password_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cls.username, cls.email, "employee", salt, password_hash),
                )
                connection.commit()
                cls.user_created = True
            finally:
                connection.close()

            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                cls.port = probe.getsockname()[1]
            hris_server.HOST = "127.0.0.1"
            hris_server.PORT = cls.port
            cls.server = hris_server.ThreadingHTTPServer(
                ("127.0.0.1", cls.port), hris_server.HRISHandler
            )
            cls.server.daemon_threads = False
            cls.server_thread = threading.Thread(
                target=cls.server.serve_forever, daemon=True
            )
            cls.server_thread.start()
            cls.base_url = "http://127.0.0.1:{}".format(cls.port)
        except Exception:
            cls._remove_test_user()
            cls._restore_environment()
            hris_server.DATABASE_URL = cls.original_database_url
            hris_server.HOST = cls.original_host
            hris_server.PORT = cls.original_port
            raise

    @classmethod
    def _restore_environment(cls):
        for name, value in cls.original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @classmethod
    def _remove_test_user(cls):
        if not cls.user_created:
            return
        connection = hris_server.connect_database()
        try:
            connection.execute("DELETE FROM users WHERE username = ?", (cls.username,))
            connection.commit()
        finally:
            connection.close()
            cls.user_created = False

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, "server"):
                cls.server.shutdown()
                cls.server.server_close()
                cls.server_thread.join(timeout=2)
            cls._remove_test_user()
            connection = hris_server.connect_database()
            try:
                remaining = {
                    table: connection.execute(
                        "SELECT COUNT(*) AS count FROM " + table
                    ).fetchone()["count"]
                    for table in ("users", "employees", "sessions", "audit_logs")
                }
            finally:
                connection.close()
            if any(remaining.values()):
                raise AssertionError("Temporary Neon test data was not fully removed.")
        finally:
            cls._restore_environment()
            hris_server.DATABASE_URL = cls.original_database_url
            hris_server.HOST = cls.original_host
            hris_server.PORT = cls.original_port

    def setUp(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.csrf_token = ""

    def request(self, path, method="GET", payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if method in ("POST", "PUT", "DELETE"):
            headers["Origin"] = self.base_url
            if self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method
        )
        try:
            response = self.client.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        return response.code, json.loads(response.read().decode("utf-8"))

    def sign_in_and_out(self, identifier):
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": identifier, "password": self.password},
        )
        self.assertEqual(status, 200)
        self.csrf_token = payload["csrfToken"]
        self.assertEqual(payload["user"]["username"], self.username)

        status, session = self.request("/api/auth/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["role"], "employee")

        status, _ = self.request("/api/employees")
        self.assertEqual(status, 403)

        status, _ = self.request("/api/auth/logout", method="POST")
        self.assertEqual(status, 200)
        status, session = self.request("/api/auth/session")
        self.assertEqual(status, 200)
        self.assertFalse(session["authenticated"])
        self.csrf_token = ""

    def test_postgres_login_session_logout_and_role_checks(self):
        status, payload = self.request(
            "/api/auth/login",
            method="POST",
            payload={"email": self.email, "password": "incorrect-test-password"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "Invalid email or password.")
        self.sign_in_and_out(self.email)
        self.sign_in_and_out(self.username.upper())

    def test_postgres_employee_queries_and_transaction_rollback(self):
        employee_id = "NEON-TEST-" + secrets.token_hex(4).upper()
        now = hris_server.datetime.now(hris_server.timezone.utc).isoformat()
        connection = hris_server.connect_database()
        try:
            connection.execute(
                "INSERT INTO employees "
                "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    employee_id,
                    "Synthetic Neon Test",
                    employee_id.lower() + "@example.test",
                    "Integration Tests",
                    "Temporary Record",
                    "active",
                    now,
                    now,
                ),
            )
            summary = hris_server.employee_summary(connection, include_monthly_records=True)
            self.assertGreaterEqual(summary["total"], 1)
            self.assertGreaterEqual(summary["active"], 1)

            pattern = "%" + employee_id.lower() + "%"
            matches = connection.execute(
                "SELECT employee_id FROM employees "
                "WHERE LOWER(employee_id) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(full_name) LIKE LOWER(?) ESCAPE '\\'",
                (pattern, pattern),
            ).fetchall()
            self.assertEqual([row["employee_id"] for row in matches], [employee_id])

            cursor = connection.execute(
                "UPDATE employees SET status = ?, updated_at = ? WHERE employee_id = ?",
                ("inactive", now, employee_id),
            )
            self.assertEqual(cursor.rowcount, 1)
            connection.execute(
                "INSERT INTO audit_logs (actor, action, employee_id, occurred_at, details) "
                "VALUES (?, ?, ?, ?, ?)",
                ("neon-integration-test", "employee.updated", employee_id, now, "{}"),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM audit_logs WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()["count"],
                1,
            )
        finally:
            connection.rollback()
            connection.close()

        connection = hris_server.connect_database()
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM employees WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()["count"],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM audit_logs WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()["count"],
                0,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
