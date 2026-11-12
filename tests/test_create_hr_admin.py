import contextlib
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hris_server
from scripts import create_hr_admin
from backend.app.database import postgres


TARGET = {
    "project_id": "project-fixture",
    "branch_id": "branch-fixture",
    "branch_name": "main",
    "database_name": "employee_hub",
}
HOST = "ep-primary.example.neon.tech"
TARGET_ENV = {
    create_hr_admin.ALLOWED_TARGET_VARIABLES[key]: value
    for key, value in TARGET.items()
}


def valid_branch_response(target=None, default=True, primary=True):
    target = target or TARGET
    return {
        "branches": [{
            "id": target["branch_id"],
            "name": target["branch_name"],
            "project_id": target["project_id"],
            "default": default,
            "primary": primary,
        }]
    }


def valid_endpoints_response(target=None, host=HOST):
    target = target or TARGET
    return {
        "endpoints": [{
            "project_id": target["project_id"],
            "branch_id": target["branch_id"],
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
    def __init__(self, database_name="employee_hub", host=HOST):
        self.info = SimpleNamespace(host=host)
        self.database_name = database_name
        self.existing_account = None
        self.insert_error = None
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement, parameters=()):
        self.statements.append((statement, parameters))
        if "current_database()" in statement:
            return FakeCursor({"name": self.database_name})
        if "SELECT username FROM users" in statement:
            return FakeCursor(self.existing_account)
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
        hris_server.DATABASE_URL = (
            "postgresql://test@ep-primary.example.neon.tech/employee_hub"
        )
        self.target_environment = patch.dict(os.environ, TARGET_ENV, clear=False)
        self.target_environment.start()
        self.addCleanup(self.target_environment.stop)
        self.addCleanup(setattr, hris_server, "DATABASE_URL", self.database_url)
        self.cli_responses = [
            valid_branch_response(),
            valid_endpoints_response(),
        ]
        self.cli_patch = patch.object(
            create_hr_admin,
            "neon_api_json",
            side_effect=lambda _path: self.cli_responses.pop(0),
        )
        self.cli_patch.start()
        self.addCleanup(self.cli_patch.stop)

    def target_config(self):
        return create_hr_admin.load_allowed_target()

    def verified_host(self):
        return create_hr_admin.verify_configured_database_target(
            hris_server.DATABASE_URL, self.target_config()
        )

    def test_allowed_target_is_read_from_explicit_environment(self):
        self.assertEqual(self.target_config(), TARGET)

    def test_missing_allowed_target_fails_closed(self):
        environment = dict(TARGET_ENV)
        environment.pop("HRIS_ADMIN_ALLOWED_NEON_BRANCH_ID")
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            create_hr_admin.load_allowed_target(environment)

    def test_primary_branch_name_is_not_rejected_by_heuristic(self):
        self.assertEqual(self.target_config()["branch_name"], "main")

    def test_rejects_wrong_database_before_neon_api_request(self):
        with patch.object(create_hr_admin, "neon_api_json") as neon_api_json:
            with self.assertRaises(create_hr_admin.ProvisioningTargetError):
                create_hr_admin.verify_configured_database_target(
                    "postgresql://test@ep-primary.example.neon.tech/other_database",
                    self.target_config(),
                )
        neon_api_json.assert_not_called()

    def test_main_rejects_connection_override_before_connecting(self):
        hris_server.DATABASE_URL += "?host=attacker.example"
        with patch.object(create_hr_admin, "neon_api_json") as neon_api_json, patch.object(
            create_hr_admin, "connect_verified_database"
        ) as connect:
            with self.assertRaisesRegex(SystemExit, "target verification failed"):
                create_hr_admin.main()
        neon_api_json.assert_not_called()
        connect.assert_not_called()

    def test_rejects_non_postgres_database_url(self):
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            create_hr_admin.verify_configured_database_target(
                "sqlite:///local.db", self.target_config()
            )

    def test_rejects_connection_parameters_that_can_override_target(self):
        for parameter in (
            "host=attacker.example",
            "hostaddr=192.0.2.10",
            "service=production",
            "port=6543",
            "dbname=production",
        ):
            with self.subTest(parameter=parameter), patch.object(
                create_hr_admin, "neon_api_json"
            ) as neon_api_json:
                url = (
                    "postgresql://test@ep-primary.example.neon.tech/"
                    "employee_hub?{}".format(parameter)
                )
                with self.assertRaises(create_hr_admin.ProvisioningTargetError):
                    create_hr_admin.verify_configured_database_target(
                        url, self.target_config()
                    )
                neon_api_json.assert_not_called()

    def test_allows_only_non_routing_tls_connection_parameters(self):
        url = (
            "postgresql://test@ep-primary.example.neon.tech/employee_hub"
            "?sslmode=require&channel_binding=require"
        )
        self.assertEqual(
            create_hr_admin.parse_database_target(url, "employee_hub"),
            HOST,
        )

    def test_rejects_branch_metadata_for_another_project(self):
        self.cli_responses[0]["branches"][0]["project_id"] = "other-project"
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()

    def test_rejects_branch_id_mismatch(self):
        self.cli_responses[0]["branches"][0]["id"] = "another-branch"
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()

    def test_allows_exact_default_or_primary_branch(self):
        for flags in (
            {"default": True, "primary": False},
            {"default": False, "primary": True},
            {"default": True, "primary": True},
        ):
            with self.subTest(flags=flags):
                self.cli_responses = [
                    valid_branch_response(
                        default=flags["default"], primary=flags["primary"]
                    ),
                    valid_endpoints_response(),
                ]
                self.assertEqual(self.verified_host(), HOST)

    def test_rejects_branch_not_marked_default_or_primary(self):
        self.cli_responses[0]["branches"][0].update(
            {"default": False, "primary": False}
        )
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()

    def test_rejects_invalid_default_or_primary_metadata(self):
        self.cli_responses[0]["branches"][0]["primary"] = "true"
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()

    def test_rejects_unverifiable_neon_metadata(self):
        with patch.object(
            create_hr_admin,
            "neon_api_json",
            side_effect=create_hr_admin.ProvisioningTargetError(
                "verification unavailable"
            ),
        ):
            with self.assertRaises(create_hr_admin.ProvisioningTargetError):
                self.verified_host()

    def test_rejects_endpoint_host_not_associated_with_target_branch(self):
        self.cli_responses[1] = valid_endpoints_response(host="ep-main.example.neon.tech")
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()
        self.assertEqual(self.connection.statements, [])

    def test_rejects_endpoint_with_wrong_branch_identity(self):
        self.cli_responses[1]["endpoints"][0]["branch_id"] = "another-branch"
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()

    def test_rejects_endpoint_with_wrong_project_identity(self):
        self.cli_responses[1]["endpoints"][0]["project_id"] = "another-project"
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            self.verified_host()

    def test_rejects_read_only_or_disabled_endpoints(self):
        for changes in ({"type": "read_only"}, {"disabled": True}):
            with self.subTest(changes=changes):
                self.cli_responses = [
                    valid_branch_response(),
                    valid_endpoints_response(),
                ]
                self.cli_responses[1]["endpoints"][0].update(changes)
                with self.assertRaises(create_hr_admin.ProvisioningTargetError):
                    self.verified_host()

    def test_verified_connection_enforces_hostname_verification(self):
        with patch.object(
            create_hr_admin, "connect_postgres", return_value=object()
        ) as connect:
            result = create_hr_admin.connect_verified_database(
                hris_server.DATABASE_URL
            )
        self.assertIsNotNone(result)
        connect.assert_called_once_with(
            hris_server.DATABASE_URL, sslmode="verify-full"
        )

    def test_postgres_driver_receives_verified_tls_for_provisioning(self):
        connection = object()
        with patch.object(postgres, "psycopg") as psycopg:
            psycopg.connect.return_value = connection
            result = postgres.connect_postgres(
                hris_server.DATABASE_URL, sslmode="verify-full"
            )
        self.assertIs(result.connection, connection)
        psycopg.connect.assert_called_once()
        self.assertEqual(
            psycopg.connect.call_args.kwargs["sslmode"],
            "verify-full",
        )

    def test_postgres_driver_keeps_require_as_application_default(self):
        connection = object()
        with patch.object(postgres, "psycopg") as psycopg:
            psycopg.connect.return_value = connection
            result = postgres.connect_postgres(hris_server.DATABASE_URL)
        self.assertIs(result.connection, connection)
        self.assertEqual(
            psycopg.connect.call_args.kwargs["sslmode"],
            "require",
        )

    def test_rejects_wrong_connected_database_or_endpoint(self):
        expected_host = self.verified_host()
        for connection in (
            FakePostgresConnection(database_name="production"),
            FakePostgresConnection(host="ep-main.example.neon.tech"),
        ):
            with self.subTest(database_name=connection.database_name, host=connection.info.host):
                with self.assertRaises(create_hr_admin.ProvisioningTargetError):
                    create_hr_admin.verify_target_database(
                        hris_server.PostgresConnection(connection),
                        self.target_config(),
                        expected_host,
                    )

    def test_sqlite_connection_is_rejected(self):
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            create_hr_admin.verify_target_database(
                object(), self.target_config(), HOST
            )

    def test_existing_account_is_not_modified(self):
        self.connection.existing_account = {"username": "new.hr"}
        with self.assertRaises(create_hr_admin.ProvisioningTargetError):
            create_hr_admin.ensure_account_does_not_exist(
                hris_server.PostgresConnection(self.connection),
                "new.hr",
                "new.hr@example.test",
            )
        self.assertFalse(any(
            "INSERT INTO users" in sql for sql, _ in self.connection.statements
        ))

    def test_main_stops_for_existing_account_before_confirmation(self):
        self.connection.existing_account = {"username": "new.hr"}
        inputs = iter(("new.hr", "new.hr@example.test"))
        with patch.object(
            create_hr_admin,
            "connect_verified_database",
            return_value=hris_server.PostgresConnection(self.connection),
        ), patch("builtins.input", side_effect=lambda _prompt: next(inputs)), patch.object(
            create_hr_admin.getpass, "getpass"
        ) as password_prompt, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "already exists"):
                create_hr_admin.main()

        password_prompt.assert_not_called()
        self.assertTrue(self.connection.rolled_back)
        self.assertTrue(self.connection.closed)
        self.assertFalse(any(
            "INSERT INTO users" in sql for sql, _ in self.connection.statements
        ))

    def test_main_rejects_missing_allowlist_before_connecting(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            hris_server, "connect_database"
        ) as connect_database, patch("builtins.input") as input_prompt:
            with self.assertRaisesRegex(SystemExit, "target verification failed"):
                create_hr_admin.main()
        connect_database.assert_not_called()
        input_prompt.assert_not_called()

    def run_main(self, confirmation):
        inputs = iter(("new.hr", "new.hr@example.test", confirmation))
        output = io.StringIO()
        with patch.object(
            create_hr_admin,
            "connect_verified_database",
            return_value=hris_server.PostgresConnection(self.connection),
        ), patch("builtins.input", side_effect=lambda _prompt: next(inputs)), patch.object(
            create_hr_admin.getpass,
            "getpass",
            side_effect=("correct-horse-battery-16", "correct-horse-battery-16"),
        ), contextlib.redirect_stdout(output):
            create_hr_admin.main()
        return output.getvalue()

    def test_requires_target_specific_confirmation_before_password_or_insert(self):
        output = self.run_main("CREATE")
        self.assertIn("Account creation cancelled.", output)
        self.assertIn("permanent Employee Hub database", output)
        self.assertFalse(any(
            "INSERT INTO users" in sql for sql, _ in self.connection.statements
        ))
        self.assertFalse(self.connection.committed)
        self.assertTrue(self.connection.rolled_back)

    def test_confirmation_phrase_names_permanent_target_and_operator_attestation(self):
        phrase = create_hr_admin.confirmation_phrase(self.target_config())
        self.assertIn("PERMANENT EMPLOYEE HUB DATABASE", phrase)
        self.assertIn(TARGET["project_id"], phrase)
        self.assertIn(TARGET["branch_id"], phrase)
        self.assertIn(TARGET["branch_name"], phrase)
        self.assertIn(TARGET["database_name"], phrase)
        self.assertIn("I HAVE VERIFIED THIS TARGET IS CORRECT AND AUTHORIZED", phrase)

    def test_confirmed_account_uses_hr_admin_and_backend_password_hash(self):
        with patch.object(
            hris_server,
            "hash_password",
            return_value=("test-salt", "test-password-hash"),
        ) as hash_password:
            output = self.run_main(
                create_hr_admin.confirmation_phrase(self.target_config())
            )

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

    def test_duplicate_account_race_is_rejected_without_overwrite(self):
        self.connection.insert_error = hris_server.sqlite3.IntegrityError(
            "synthetic duplicate"
        )
        with self.assertRaisesRegex(SystemExit, "already in use"):
            self.run_main(create_hris_admin_confirmation())
        self.assertTrue(self.connection.rolled_back)
        self.assertFalse(self.connection.committed)
        self.assertTrue(self.connection.closed)

    def test_database_errors_do_not_leak_password_or_connection_url(self):
        password = "correct-horse-battery-16"
        database_url = hris_server.DATABASE_URL
        self.connection.insert_error = hris_server.POSTGRES_ERRORS[0](
            "{} {}".format(password, database_url)
        )
        inputs = iter((
            "new.hr",
            "new.hr@example.test",
            create_hr_admin.confirmation_phrase(self.target_config()),
        ))
        output = io.StringIO()
        with patch.object(
            create_hr_admin,
            "connect_verified_database",
            return_value=hris_server.PostgresConnection(self.connection),
        ), patch("builtins.input", side_effect=lambda _prompt: next(inputs)), patch.object(
            create_hr_admin.getpass,
            "getpass",
            side_effect=(password, password),
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                create_hr_admin.main()

        self.assertNotIn(password, output.getvalue())
        self.assertNotIn(database_url, output.getvalue())
        self.assertNotIn(password, str(raised.exception))
        self.assertNotIn(database_url, str(raised.exception))
        self.assertTrue(self.connection.rolled_back)
        self.assertFalse(self.connection.committed)


def create_hris_admin_confirmation():
    return create_hr_admin.confirmation_phrase(TARGET)


if __name__ == "__main__":
    unittest.main()
