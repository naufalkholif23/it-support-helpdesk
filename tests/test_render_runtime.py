import contextlib
import http.client
import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import hris_server
import render_server
from backend.app.core.exceptions import DatabaseConfigurationError
from backend.app.database import connection as database_connection
from backend.app.modules.auth.origin import (
    is_valid_origin,
    secure_cookie_attribute,
    validate_render_allowed_origins,
)
from backend.app.modules.auth.password import hash_password
from backend.app.modules.auth.service import AuthServiceMixin
from backend.app.api.responses import HttpUtilitiesMixin
from api.index import routed_request_path


TEST_DATABASE_URL = (
    "postgresql://test:placeholder@db.example.test/neondb"
    "?sslmode=require&channel_binding=require"
)
TEST_EXPECTED_HOSTNAME = "db.example.test"
TEST_EXPECTED_DATABASE = "neondb"


class RenderConfigurationTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.ca_bundle = Path(self.temp_directory.name) / "test-ca-bundle.pem"
        self.ca_bundle.write_text("test-only CA placeholder", encoding="ascii")
        self.render_environment = {
            "HRIS_DEPLOYMENT": "render",
            "DATABASE_URL": TEST_DATABASE_URL,
            "HRIS_POSTGRES_EXPECTED_HOSTNAME": TEST_EXPECTED_HOSTNAME,
            "HRIS_POSTGRES_EXPECTED_DATABASE": TEST_EXPECTED_DATABASE,
            "HRIS_POSTGRES_SSLROOTCERT": str(self.ca_bundle),
            "PORT": "10000",
            "HRIS_ALLOWED_ORIGINS": "https://employee.example.test",
        }


class RenderRunnerTests(RenderConfigurationTestCase):
    def test_runner_sets_deployment_mode_before_loading_backend_configuration(self):
        source = (
            "import os, dotenv\n"
            "os.environ.pop('HRIS_DEPLOYMENT', None)\n"
            "os.environ['DATABASE_URL'] = {!r}\n"
            "os.environ['HRIS_POSTGRES_EXPECTED_HOSTNAME'] = {!r}\n"
            "os.environ['HRIS_POSTGRES_EXPECTED_DATABASE'] = {!r}\n"
            "os.environ['HRIS_POSTGRES_SSLROOTCERT'] = {!r}\n"
            "os.environ['PORT'] = '10000'\n"
            "os.environ['HRIS_ALLOWED_ORIGINS'] = 'https://employee.example.test'\n"
            "def fail_if_dotenv_loads(*args, **kwargs):\n"
            "    raise AssertionError('dotenv must not load in Render mode')\n"
            "dotenv.load_dotenv = fail_if_dotenv_loads\n"
            "import render_server\n"
            "render_server.validate_deployment_configuration()\n"
            "from backend.app.core.config import DATABASE_URL, DEPLOYMENT\n"
            "assert DEPLOYMENT == 'render'\n"
            "assert DATABASE_URL == os.environ['DATABASE_URL']\n"
        ).format(
            TEST_DATABASE_URL,
            TEST_EXPECTED_HOSTNAME,
            TEST_EXPECTED_DATABASE,
            str(self.ca_bundle),
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", source],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0)

    def test_runner_uses_render_host_and_platform_port(self):
        self.assertEqual(
            render_server.server_bindings({
                "PORT": "10000",
            }),
            ("0.0.0.0", 10000),
        )

    def test_runner_local_default_is_explicitly_opt_in(self):
        environment = {}
        with self.assertRaisesRegex(RuntimeError, "PORT is required"):
            render_server.server_bindings(environment)
        self.assertEqual(
            render_server.server_bindings(environment, allow_local_default=True),
            ("0.0.0.0", 8000),
        )

    def test_runner_rejects_missing_or_invalid_postgres_url(self):
        for value in ("", "sqlite:///local.db", "postgresql://host"):
            with self.subTest(database_url=value):
                with patch.dict(os.environ, {
                    **self.render_environment,
                    "DATABASE_URL": value,
                }, clear=False):
                    with self.assertRaises(DatabaseConfigurationError):
                        render_server.validate_deployment_configuration()

    def test_runner_rejects_missing_port_and_invalid_origins(self):
        with patch.dict(os.environ, self.render_environment, clear=False):
            os.environ.pop("PORT", None)
            with self.assertRaisesRegex(RuntimeError, "PORT"):
                render_server.validate_deployment_configuration()

        with patch.dict(os.environ, {
            **self.render_environment,
            "HRIS_ALLOWED_ORIGINS": "http://employee.example.test",
        }, clear=False):
            with self.assertRaises(ValueError):
                render_server.validate_deployment_configuration()

    def test_runner_rejects_invalid_port(self):
        for value in ("zero", "0", "65536"):
            with self.subTest(port=value):
                with self.assertRaisesRegex(RuntimeError, "PORT"):
                    render_server.server_bindings({
                        "DATABASE_URL": TEST_DATABASE_URL,
                        "PORT": value,
                    })

    def test_main_binds_render_host_and_does_not_initialize_sqlite(self):
        created_servers = []

        class FakeServer:
            def __init__(self, address, handler):
                self.address = address
                self.handler = handler
                self.closed = False
                created_servers.append(self)

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                self.closed = True

        with patch.dict(os.environ, self.render_environment, clear=False), patch(
            "render_server.ThreadingHTTPServer", FakeServer
        ), patch.object(
            hris_server, "DATABASE_URL", TEST_DATABASE_URL
        ), patch.object(
            hris_server, "initialize_database", side_effect=AssertionError
        ) as initialize_database, patch.object(
            hris_server, "connect_database", side_effect=AssertionError
        ) as connect_database:
            render_server.main()

        self.assertEqual(created_servers[0].address, ("0.0.0.0", 10000))
        self.assertTrue(created_servers[0].closed)
        initialize_database.assert_not_called()
        connect_database.assert_not_called()

    def test_runner_rejects_target_mismatch_before_opening_listener(self):
        with patch.dict(os.environ, {
            **self.render_environment,
            "HRIS_POSTGRES_EXPECTED_HOSTNAME": "other.example.test",
        }, clear=False), patch(
            "render_server.ThreadingHTTPServer"
        ) as server:
            with self.assertRaises(DatabaseConfigurationError):
                render_server.main()
        server.assert_not_called()

    def test_runner_requires_explicit_target_configuration(self):
        for variable in (
            "HRIS_POSTGRES_EXPECTED_HOSTNAME",
            "HRIS_POSTGRES_EXPECTED_DATABASE",
        ):
            with self.subTest(variable=variable), patch.dict(
                os.environ,
                {**self.render_environment, variable: ""},
                clear=False,
            ), patch("render_server.ThreadingHTTPServer") as server:
                with self.assertRaises(DatabaseConfigurationError):
                    render_server.main()
                server.assert_not_called()

    def test_runner_requires_a_readable_ca_bundle_before_opening_listener(self):
        with patch.dict(os.environ, {
            **self.render_environment,
            "HRIS_POSTGRES_SSLROOTCERT": str(
                Path(self.temp_directory.name) / "missing-ca.pem"
            ),
        }, clear=False), patch(
            "render_server.ThreadingHTTPServer"
        ) as server:
            with self.assertRaises(DatabaseConfigurationError):
                render_server.main()
        server.assert_not_called()

    def test_vercel_health_rewrite_still_resolves_to_existing_route(self):
        self.assertEqual(
            routed_request_path("/api?__vercel_route=health"),
            "/api/health",
        )


class RenderDatabaseTests(RenderConfigurationTestCase):
    def test_render_connection_uses_postgres_without_sqlite_fallback(self):
        postgres_connection = object()
        with patch.object(
            database_connection, "connect_postgres", return_value=postgres_connection
        ) as connect_postgres, patch.object(
            database_connection, "connect_sqlite"
        ) as connect_sqlite:
            result = database_connection.connect_database(
                TEST_DATABASE_URL,
                "unused.sqlite3",
                render=True,
                expected_hostname=TEST_EXPECTED_HOSTNAME,
                expected_database=TEST_EXPECTED_DATABASE,
                sslrootcert=str(self.ca_bundle),
            )
        self.assertIs(result, postgres_connection)
        connect_postgres.assert_called_once_with(
            TEST_DATABASE_URL,
            sslmode="verify-full",
            sslrootcert=str(self.ca_bundle),
        )
        connect_sqlite.assert_not_called()

    def test_render_connection_fails_before_sqlite_for_missing_or_invalid_url(self):
        for value in ("", "sqlite:///local.db", "https://example.test"):
            with self.subTest(database_url=value):
                with patch.object(
                    database_connection, "connect_sqlite"
                ) as connect_sqlite:
                    with self.assertRaises(DatabaseConfigurationError):
                        database_connection.connect_database(
                            value,
                            "unused.sqlite3",
                            render=True,
                            expected_hostname=TEST_EXPECTED_HOSTNAME,
                            expected_database=TEST_EXPECTED_DATABASE,
                            sslrootcert=str(self.ca_bundle),
                        )
                connect_sqlite.assert_not_called()

    def test_url_validation_does_not_include_credentials_in_errors(self):
        with self.assertRaises(DatabaseConfigurationError) as raised:
            database_connection.validate_postgres_database_url(
                "postgresql://person:do-not-leak@db.example.test/neondb"
                "?password=do-not-leak",
                TEST_EXPECTED_HOSTNAME,
                TEST_EXPECTED_DATABASE,
            )
        self.assertNotIn("do-not-leak", str(raised.exception))

    def test_accepts_neon_tls_query_parameters_without_weakening_runtime_tls(self):
        validated = database_connection.validate_postgres_database_url(
            TEST_DATABASE_URL, TEST_EXPECTED_HOSTNAME, TEST_EXPECTED_DATABASE
        )
        self.assertEqual(validated, TEST_DATABASE_URL)

    def test_rejects_routing_credential_and_tls_query_parameters(self):
        parameters = (
            "host=attacker.example",
            "hostaddr=192.0.2.10",
            "port=6543",
            "dbname=other",
            "database=other",
            "user=other",
            "password=other",
            "service=production",
            "servicefile=%2Ftmp%2Fservice.conf",
            "sslrootcert=%2Ftmp%2Fca.pem",
            "sslcert=%2Ftmp%2Fclient.pem",
            "sslkey=%2Ftmp%2Fclient.key",
            "sslpassword=other",
            "sslcrl=%2Ftmp%2Fcrl.pem",
            "sslcrldir=%2Ftmp%2Fcrls",
            "sslmode=disable",
            "channel_binding=prefer",
        )
        for parameter in parameters:
            with self.subTest(parameter=parameter), self.assertRaises(
                DatabaseConfigurationError
            ):
                database_connection.validate_postgres_database_url(
                    "postgresql://test:placeholder@db.example.test/neondb?"
                    + parameter,
                    TEST_EXPECTED_HOSTNAME,
                    TEST_EXPECTED_DATABASE,
                )

    def test_rejects_duplicate_and_unknown_query_parameters(self):
        for query in (
            "sslmode=require&sslmode=verify-full",
            "unknown_option=value",
        ):
            with self.subTest(query=query), self.assertRaises(
                DatabaseConfigurationError
            ):
                database_connection.validate_postgres_database_url(
                    "postgresql://test:placeholder@db.example.test/neondb?"
                    + query,
                    TEST_EXPECTED_HOSTNAME,
                    TEST_EXPECTED_DATABASE,
                )

    def test_rejects_hostname_or_database_target_mismatch(self):
        invalid_targets = (
            (
                "postgresql://test:placeholder@other.example.test/neondb",
                TEST_EXPECTED_HOSTNAME,
                TEST_EXPECTED_DATABASE,
            ),
            (
                "postgresql://test:placeholder@db.example.test/other",
                TEST_EXPECTED_HOSTNAME,
                TEST_EXPECTED_DATABASE,
            ),
        )
        for url, hostname, database in invalid_targets:
            with self.subTest(url=url), self.assertRaises(
                DatabaseConfigurationError
            ):
                database_connection.validate_postgres_database_url(
                    url, hostname, database
                )

    def test_rejects_non_neondb_expected_database(self):
        with self.assertRaises(DatabaseConfigurationError):
            database_connection.validate_postgres_database_url(
                TEST_DATABASE_URL, TEST_EXPECTED_HOSTNAME, "other"
            )

    def test_requires_existing_ca_bundle(self):
        with self.assertRaises(DatabaseConfigurationError):
            database_connection.validate_postgres_sslrootcert("")
        with self.assertRaises(DatabaseConfigurationError):
            database_connection.validate_postgres_sslrootcert(
                str(Path(self.temp_directory.name) / "missing.pem")
            )
        self.assertEqual(
            database_connection.validate_postgres_sslrootcert(
                str(self.ca_bundle)
            ),
            str(self.ca_bundle),
        )

    @unittest.skipIf(hris_server.psycopg is None, "psycopg is not installed")
    def test_psycopg_receives_verify_full_root_certificate_and_timeout(self):
        from backend.app.database import postgres

        fake_connection = object()
        with patch.object(
            postgres.psycopg, "connect", return_value=fake_connection
        ) as connect:
            result = postgres.connect_postgres(
                TEST_DATABASE_URL,
                sslmode="verify-full",
                sslrootcert=str(self.ca_bundle),
            )
        self.assertIsInstance(result, postgres.PostgresConnection)
        connect.assert_called_once_with(
            TEST_DATABASE_URL,
            connect_timeout=5,
            row_factory=postgres.dict_row,
            sslmode="verify-full",
            sslrootcert=str(self.ca_bundle),
        )


class RenderOriginAndCookieTests(unittest.TestCase):
    def test_render_requires_configured_https_origin(self):
        with patch.dict(os.environ, {
            "HRIS_DEPLOYMENT": "render",
            "HRIS_ALLOWED_ORIGINS": "https://employee.example.test",
            "VERCEL": "1",
            "VERCEL_ENV": "production",
            "VERCEL_URL": "old-project.vercel.app",
            "VERCEL_PROJECT_PRODUCTION_URL": "old-production.vercel.app",
        }, clear=False):
            self.assertTrue(is_valid_origin(
                "https://employee.example.test", "0.0.0.0", 10000
            ))
            self.assertFalse(is_valid_origin(
                "http://employee.example.test", "0.0.0.0", 10000
            ))
            self.assertFalse(is_valid_origin(
                "https://unknown.example.test", "0.0.0.0", 10000
            ))
            self.assertFalse(is_valid_origin(
                "https://anything.example.test", "0.0.0.0", 10000
            ))
            self.assertFalse(is_valid_origin(
                "https://*.example.test", "0.0.0.0", 10000
            ))

    def test_render_configuration_rejects_missing_http_and_wildcard_origins(self):
        invalid_origins = (
            "",
            "http://employee.example.test",
            "https://*.example.test",
            "https://employee.example.test,",
        )
        for value in invalid_origins:
            with self.subTest(origin=value):
                with self.assertRaises(ValueError):
                    validate_render_allowed_origins(value)

        self.assertEqual(
            validate_render_allowed_origins(
                "https://employee.example.test/,https://preview.example.test"
            ),
            ("https://employee.example.test", "https://preview.example.test"),
        )

    def test_render_session_cookie_preserves_security_attributes(self):
        password_salt, password_hash = hash_password("test-only-password")

        class FakeResult:
            def __init__(self, row=None, rows=None):
                self.row = row
                self.rows = rows or []

            def fetchone(self):
                return self.row

            def fetchall(self):
                return self.rows

        class FakeConnection:
            def execute(self, statement, parameters=()):
                if "FROM users WHERE" in statement:
                    return FakeResult({
                        "username": "preview.admin",
                        "role": "hr_admin",
                        "password_salt": password_salt,
                        "password_hash": password_hash,
                    })
                if "FROM user_roles" in statement:
                    return FakeResult(rows=[])
                return FakeResult()

            def commit(self):
                pass

            def close(self):
                pass

        class RecordingBase:
            def __init__(self):
                self.headers = []
                self.status = None
                self.wfile = io.BytesIO()

            def send_response(self, status):
                self.status = status

            def send_header(self, name, value):
                self.headers.append((name, value))

            def end_headers(self):
                pass

        class RecordingAuthHandler(AuthServiceMixin, HttpUtilitiesMixin, RecordingBase):
            database_lock = threading.RLock()

            def __init__(self):
                RecordingBase.__init__(self)

            def database_connection(self):
                return FakeConnection()

            @staticmethod
            def secure_cookie_attribute():
                return secure_cookie_attribute()

        with patch.dict(os.environ, {"HRIS_DEPLOYMENT": "render"}, clear=False):
            handler = RecordingAuthHandler()
            handler.login({
                "email": "preview.admin@example.test",
                "password": "test-only-password",
            })

        cookie = dict(handler.headers)["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Secure", cookie)


class RenderHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        cls.server = hris_server.ThreadingHTTPServer(
            ("127.0.0.1", port), hris_server.HRISHandler
        )
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True
        )
        cls.server_thread.start()
        cls.base_url = "http://127.0.0.1:{}".format(port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def request(self, path, method="GET"):
        request = urllib.request.Request(
            self.base_url + path, method=method
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            return response.status, response.read(), response.headers
        finally:
            response.close()

    def test_health_is_public_minimal_and_does_not_connect_to_database(self):
        with patch.dict(os.environ, {"HRIS_DEPLOYMENT": "render"}, clear=False), \
                patch.object(hris_server, "connect_database", side_effect=AssertionError):
            status, body, headers = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"status": "ok"}')
        self.assertIn("application/json", headers.get("Content-Type", ""))

    def test_render_static_allowlist_serves_required_frontend(self):
        with patch.dict(os.environ, {"HRIS_DEPLOYMENT": "render"}, clear=False), \
                patch.object(hris_server, "connect_database", side_effect=AssertionError):
            for path in (
                "/index.html",
                "/login.html",
                "/platform.html",
                "/admin-login.html",
                "/admin.html",
                "/favicon.ico",
                "/logo-green.png",
                "/employee-hub",
                "/hris/",
            ):
                with self.subTest(path=path):
                    status, body, _ = self.request(path)
                    self.assertEqual(status, 200)
                    self.assertTrue(body)

    def test_render_static_allowlist_blocks_internal_files_and_traversal(self):
        blocked_paths = (
            "/backend/",
            "/backend/app/core/config.py",
            "/migrations/",
            "/migrations/001_core_hr.sql",
            "/tests/",
            "/docs/",
            "/.git/",
            "/.env",
            "/.env.local",
            "/requirements.txt",
            "/README.md",
            "/hris_server.py",
            "/render_server.py",
            "/vercel.json",
            "/package.json",
            "/neon.ts",
            "/hris.sqlite3",
            "/%2e%2e/hris_server.py",
            "/%252e%252e/hris_server.py",
            "/%2e%2e%2fhris_server.py",
            "/%2e%2e%5chris_server.py",
            "/backend%2fapp%2fcore%2fconfig.py",
            "/backend%252fapp%252fcore%252fconfig.py",
            "/backend//app/core/config.py",
            "//backend/app/core/config.py",
            "/backend/./app/core/config.py",
            "/index.html/../hris_server.py",
            "/.env/",
            "/%2egit/config",
            "/%5c..%5chris_server.py",
            "/backend/../hris_server.py",
        )
        with patch.dict(os.environ, {"HRIS_DEPLOYMENT": "render"}, clear=False), \
                patch.object(hris_server, "connect_database", side_effect=AssertionError):
            for path in blocked_paths:
                with self.subTest(path=path):
                    status, _, _ = self.request(path)
                    self.assertEqual(status, 404)

    def test_render_head_requests_use_the_same_static_allowlist(self):
        with patch.dict(os.environ, {"HRIS_DEPLOYMENT": "render"}, clear=False):
            status, _, _ = self.request("/index.html", method="HEAD")
            self.assertEqual(status, 200)
            for path in ("/hris_server.py", "/backend/app/core/config.py"):
                with self.subTest(path=path):
                    status, _, _ = self.request(path, method="HEAD")
                    self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
