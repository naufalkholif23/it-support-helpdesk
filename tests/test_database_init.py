import io
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from backend.app.database.initialize import initialize_database
from backend.app.database.schema import apply_sqlite_migrations, apply_sqlite_schema
from backend.app.database.seed import (
    DEMO_ACCOUNTS,
    DEMO_EMPLOYEES,
    PUBLIC_DEMO_EMPLOYEES,
    demo_employee_records,
    seed_development_employees,
    seed_development_users,
)
import hris_server


class DatabaseInitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_init.sqlite3")
        self.lock = threading.RLock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_schema_idempotency(self):
        conn = self.connect()
        try:
            apply_sqlite_schema(conn)
            # Applying a second time should not raise error (CREATE TABLE IF NOT EXISTS)
            apply_sqlite_schema(conn)
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertTrue({"users", "employees", "sessions", "audit_logs"}.issubset(tables))
        finally:
            conn.close()

    def test_additive_migration_idempotency_and_legacy_upgrade(self):
        conn = self.connect()
        try:
            # Create a legacy users table without email column
            conn.execute(
                """
                CREATE TABLE users (
                    username TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                )
                """
            )
            # Run migration: should add email and index
            apply_sqlite_migrations(conn)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            self.assertIn("email", cols)

            # Running migration again should be a safe no-op
            apply_sqlite_migrations(conn)
            cols_again = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            self.assertIn("email", cols_again)
            index = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='idx_users_email_lower'"
            ).fetchone()
            self.assertIn("LOWER(email)", index["sql"])
            self.assertIn("WHERE email IS NOT NULL", index["sql"])
        finally:
            conn.close()

    def test_postgres_guard_raises_runtime_error(self):
        with self.assertRaisesRegex(RuntimeError, "migration"):
            initialize_database(
                connect_database=self.connect,
                database_lock=self.lock,
                database_url="configured-test-database",
            )

    def test_full_initialization_seeds_users_and_employees(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            initialize_database(
                connect_database=self.connect,
                database_lock=self.lock,
                database_url="",
                demo_password="custom-dev-password",
            )

        conn = self.connect()
        try:
            users = conn.execute("SELECT username, email, role FROM users").fetchall()
            self.assertEqual(len(users), len(DEMO_ACCOUNTS))
            for u in users:
                self.assertTrue(u["email"].endswith("@example.test"))

            employees = conn.execute("SELECT employee_id, full_name, email FROM employees").fetchall()
            self.assertEqual(len(employees), len(DEMO_EMPLOYEES))
            quick_access = conn.execute(
                "SELECT id, target_url, status FROM quick_access_items ORDER BY id"
            ).fetchall()
            self.assertEqual(
                [tuple(row) for row in quick_access],
                [
                    ("business-trip", None, "draft"),
                    ("office-amenities", None, "draft"),
                ],
            )
        finally:
            conn.close()

    def test_quick_access_default_seed_preserves_admin_configuration(self):
        initialize_database(self.connect, self.lock, database_url="")
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE quick_access_items SET target_url = ?, status = ? "
                "WHERE id = ?",
                (
                    "https://docs.google.com/forms/d/e/test/viewform",
                    "active",
                    "business-trip",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        initialize_database(self.connect, self.lock, database_url="")
        conn = self.connect()
        try:
            item = conn.execute(
                "SELECT target_url, status FROM quick_access_items WHERE id = ?",
                ("business-trip",),
            ).fetchone()
            self.assertEqual(
                tuple(item),
                ("https://docs.google.com/forms/d/e/test/viewform", "active"),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM quick_access_items"
                ).fetchone()[0],
                2,
            )
        finally:
            conn.close()

    def test_seeding_backfills_missing_emails_on_existing_users(self):
        conn = self.connect()
        try:
            apply_sqlite_schema(conn)
            apply_sqlite_migrations(conn)
            # Insert a dev user with NULL email
            conn.execute(
                "INSERT INTO users (username, email, role, password_salt, password_hash) "
                "VALUES ('hr.demo', NULL, 'hr_admin', 'salt', 'hash')"
            )
            conn.commit()

            seed_development_users(conn)
            conn.commit()

            row = conn.execute("SELECT email FROM users WHERE username = 'hr.demo'").fetchone()
            self.assertEqual(row["email"], "hr.demo@example.test")
        finally:
            conn.close()

    def test_initialization_preserves_existing_account_and_employee_data(self):
        conn = self.connect()
        try:
            apply_sqlite_schema(conn)
            apply_sqlite_migrations(conn)
            conn.execute(
                "INSERT INTO users (username, email, role, password_salt, password_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                ("hr.demo", "verified@example.test", "hr_admin", "existing-salt", "existing-hash"),
            )
            conn.execute(
                "INSERT INTO employees "
                "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "EXISTING-001", "Existing Employee", "employee@verified.test",
                    "People", "Coordinator", "active", "created", "updated",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        initialize_database(self.connect, self.lock, database_url="")

        conn = self.connect()
        try:
            user = conn.execute(
                "SELECT email, password_salt, password_hash FROM users WHERE username = 'hr.demo'"
            ).fetchone()
            self.assertEqual(
                tuple(user),
                ("verified@example.test", "existing-salt", "existing-hash"),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                2,
            )
            support = conn.execute(
                "SELECT email, role FROM users WHERE username = 'it.support'"
            ).fetchone()
            self.assertEqual(tuple(support), ("it.support@example.test", "employee"))
            employee = conn.execute(
                "SELECT email FROM employees WHERE employee_id = 'EXISTING-001'"
            ).fetchone()
            self.assertEqual(employee["email"], "employee@verified.test")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_seed_failure_rolls_back_uncommitted_rows_and_closes_connection(self):
        output = io.StringIO()
        with patch(
            "backend.app.database.initialize.seed_development_employees",
            side_effect=ValueError("synthetic seed failure"),
        ):
            with patch("sys.stdout", output):
                with self.assertRaisesRegex(ValueError, "synthetic seed failure"):
                    initialize_database(self.connect, self.lock, database_url="")

        conn = self.connect()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
                0,
            )
        finally:
            conn.close()

    def test_connection_closed_on_success_and_exception(self):
        mock_conn = MagicMock()
        mock_connect = MagicMock(return_value=mock_conn)

        # On success
        with patch("backend.app.database.initialize.apply_sqlite_schema"):
            with patch("backend.app.database.initialize.apply_sqlite_migrations"):
                with patch("backend.app.database.initialize.seed_development_users"):
                    with patch("backend.app.database.initialize.seed_development_employees"):
                        initialize_database(mock_connect, self.lock, database_url="")
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

        # On exception
        mock_conn.reset_mock()
        mock_connect.reset_mock()
        with patch("backend.app.database.initialize.apply_sqlite_schema", side_effect=ValueError("Boom")):
            with self.assertRaises(ValueError):
                initialize_database(mock_connect, self.lock, database_url="")
        mock_conn.close.assert_called_once()

    def test_facade_patchability(self):
        # Verify hris_server.initialize_database observes patched DATABASE_URL and DATABASE_PATH
        orig_url = hris_server.DATABASE_URL
        hris_server.DATABASE_URL = "postgresql://patched.test/db"
        try:
            with self.assertRaisesRegex(RuntimeError, "migration"):
                hris_server.initialize_database()
        finally:
            hris_server.DATABASE_URL = orig_url

    def test_public_demo_records_builder(self):
        records = demo_employee_records()
        self.assertEqual(len(records), len(PUBLIC_DEMO_EMPLOYEES))
        for r in records:
            self.assertIn("id", r)
            self.assertIn("name", r)
            self.assertIn("email", r)
            self.assertIn("department", r)
            self.assertIn("position", r)
            self.assertIn("status", r)
            self.assertIn("created_at", r)
            self.assertIn("updated_at", r)


if __name__ == "__main__":
    unittest.main()
