import contextlib
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hris_server
from scripts import create_hr_admin


PROJECT_ID = create_hr_admin.NEON_PROJECT_ID
BRANCH_ID = create_hr_admin.NEON_BRANCH_ID
BRANCH_NAME = create_hr_admin.NEON_BRANCH_NAME
HOST = "ep-testing.example.neon.tech"


def valid_branch_response():
    return {
        "branches": [{
            "id": BRANCH_ID,
            "name": BRANCH_NAME,
            "project_id": PROJECT_ID,
            "default": False,
            "primary": False,
        }]
    }


def valid_endpoints_response(host=HOST):
    return {
        "endpoints": [{
            "project_id": PROJECT_ID,
            "branch_id": BRANCH_ID,
            "type": "read_write",
            "host": host,
            "hosts": {
                "read_write_host": host,
                "read_write_pooled_host": host.replace(
                    ".example", "-pooler.example"
                ),
            },
        }]
    }


class FakePostgresConnection:
    def __init__(self, database_name="neondb", host=HOST):
        self.info = SimpleNamespace(host=host)
        self.database_name = database_name
        self.insert_error = None
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement, parameters=()):
        self.statements.append((statement, parameters))
        if "current_database()" in statement:
            return FakeCursor({"name": self.database_name})
        if "INSERT INTO users" in statement and self.insert_error:
            raise self.insert_error
        return FakeCursor(None)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class CreateHrAdminTests(unittest.TestCase):
    def setUp(self):
        self.connection = FakePostgresConnection()
        self.database_url = hris_server.DATABASE_URL
        hris_server.DATABASE_URL = "postgresql://test@ep-testing.example.neon.tech/neondb"
        self.cli_responses = [valid_branch_response(), valid_endpoints_response()]
        self.cli_patch = patch.object(
            create_hr_admin,
            "neon_api_json",
            side_effect=lambda _path: self.cli_responses.pop(0),
        )
        self.cli_patch.start()
        self.addCleanup(self.cli_patch.stop)
        self.addCleanup(setattr, hris_server, "DATABASE_URL", self.database_url)

    def verified_host(self):
        return create_hr_admin.verify_configured_database_target(
            hris_server.DATABASE_URL
        )

    def test_rejects_wrong_database(self):
        self.connection.database_name = "production"
        expected_host = self.verified_host()
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            create_hr_admin.verify_target_database(
                hris_server.PostgresConnection(self.connection), expected_host
            )
        self.assertEqual(len(self.connection.statements), 1)

    def test_rejects_wrong_branch_before_database_query(self):
        self.cli_responses[0]["branches"][0]["name"] = "main"
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()
        self.assertEqual(self.connection.statements, [])

    def test_rejects_unverifiable_neon_metadata(self):
        with patch.object(
            create_hr_admin,
            "neon_api_json",
            side_effect=create_hr_admin.ProvisioningTargetError("verification unavailable"),
        ):
            with self.assertRaises(create_hr_admin.ProvisioningTargetError):
                self.verified_host()

    def test_rejects_wrong_configured_database_before_neon_api_request(self):
        with patch.object(create_hr_admin, "neon_api_json") as neon_api_json:
            with self.assertRaises(create_hr_admin.ProvisioningTargetError):
                create_hr_admin.verify_configured_database_target(
                    "postgresql://test@ep-testing.example.neon.tech/production"
                )
        neon_api_json.assert_not_called()

    def test_rejects_endpoint_host_not_associated_with_target_branch(self):
        self.cli_responses[1] = valid_endpoints_response("ep-main.example.neon.tech")
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()
        self.assertEqual(self.connection.statements, [])

    def test_rejects_invalid_endpoint_hosts_metadata(self):
        self.cli_responses[1]["endpoints"][0]["hosts"] = None
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()

    def test_branch_marker_environment_variable_does_not_replace_api_verification(self):
        with patch.dict(os.environ, {"NEON_BRANCH": "main"}):
            expected_host = self.verified_host()
            create_hr_admin.verify_target_database(
                hris_server.PostgresConnection(self.connection), expected_host
            )

    def test_sqlite_connection_is_rejected(self):
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            create_hr_admin.verify_target_database(object(), HOST)

    def test_main_rejects_unverified_target_before_connecting(self):
        self.cli_responses[1] = valid_endpoints_response("ep-main.example.neon.tech")
        with patch.object(hris_server, "connect_database") as connect_database, patch(
            "builtins.input"
        ) as input_prompt:
            with self.assertRaisesRegex(SystemExit, "target verification failed"):
                create_hr_admin.main()
        connect_database.assert_not_called()
        input_prompt.assert_not_called()

    def run_main(self, confirmation):
        inputs = iter(("new.hr", "new.hr@example.test", confirmation))
        output = io.StringIO()
        with patch.object(
            hris_server,
            "connect_database",
            return_value=hris_server.PostgresConnection(self.connection),
        ), patch("builtins.input", side_effect=lambda _prompt: next(inputs)), patch.object(
            create_hr_admin.getpass,
            "getpass",
            side_effect=("correct-horse-battery-16", "correct-horse-battery-16"),
        ), contextlib.redirect_stdout(output):
            create_hr_admin.main()
        return output.getvalue()

    def test_requires_explicit_confirmation_before_insert(self):
        output = self.run_main("no")
        self.assertIn("Account creation cancelled.", output)
        self.assertFalse(any("INSERT INTO users" in sql for sql, _ in self.connection.statements))
        self.assertFalse(self.connection.committed)
        self.assertTrue(self.connection.rolled_back)

    def test_confirmed_account_uses_hr_admin_and_backend_password_hash(self):
        with patch.object(
            hris_server,
            "hash_password",
            return_value=("test-salt", "test-password-hash"),
        ) as hash_password:
            output = self.run_main("CREATE")

        hash_password.assert_called_once_with("correct-horse-battery-16")
        insert = next(
            (sql, params)
            for sql, params in self.connection.statements
            if "INSERT INTO users" in sql
        )
        self.assertEqual(
            insert[1],
            (
                "new.hr",
                "new.hr@example.test",
                "hr_admin",
                "test-salt",
                "test-password-hash",
            ),
        )
        self.assertTrue(self.connection.committed)
        self.assertTrue(self.connection.closed)
        self.assertNotIn("correct-horse-battery-16", output)
        self.assertNotIn("test-password-hash", output)
        self.assertNotIn("test-salt", output)
        self.assertNotIn("postgresql://", output)

    def test_duplicate_account_is_rejected_and_transaction_rolled_back(self):
        self.connection.insert_error = hris_server.sqlite3.IntegrityError(
            "synthetic duplicate"
        )
        with self.assertRaisesRegex(SystemExit, "already in use"):
            self.run_main("CREATE")
        self.assertTrue(self.connection.rolled_back)
        self.assertFalse(self.connection.committed)
        self.assertTrue(self.connection.closed)


if __name__ == "__main__":
    unittest.main()
