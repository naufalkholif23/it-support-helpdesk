import getpass
import json
import os
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

import hris_server


NEON_PROJECT_ID = "small-sound-44823719"
NEON_BRANCH_ID = "br-autumn-art-az0q5n0y"
NEON_BRANCH_NAME = "employee-hub-testing"
DATABASE_NAME = "neondb"


class ProvisioningTargetError(RuntimeError):
    pass


def response_items(response, key):
    if not isinstance(response, dict):
        raise ProvisioningTargetError(
            "Neon returned invalid branch metadata; no account was created."
        )
    items = response.get(key)
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ProvisioningTargetError(
            "Neon returned invalid branch metadata; no account was created."
        )
    return items


def neon_api_json(path):
    executable = shutil.which("neon.cmd") if os.name == "nt" else shutil.which("neon")
    if not executable:
        raise ProvisioningTargetError(
            "The authenticated Neon CLI is required to verify the database branch."
        )

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
        raise ProvisioningTargetError(
            "Neon branch verification failed; no account was created."
        ) from None
    if result.returncode != 0:
        raise ProvisioningTargetError(
            "Neon branch verification failed; no account was created."
        )
    try:
        return json.loads(result.stdout)
    except (TypeError, ValueError):
        raise ProvisioningTargetError(
            "Neon returned invalid branch metadata; no account was created."
        ) from None


def verify_configured_database_target(database_url):
    try:
        parsed_url = urlsplit(database_url)
        configured_host = parsed_url.hostname
        configured_database = unquote(parsed_url.path.lstrip("/"))
    except (AttributeError, TypeError, ValueError):
        configured_host = None
        configured_database = None
    if not configured_host or configured_database != DATABASE_NAME:
        raise ProvisioningTargetError(
            "Configured database is not the approved Neon testing target."
        )
    configured_host = configured_host.lower().rstrip(".")

    branches = response_items(
        neon_api_json("/projects/{}/branches".format(NEON_PROJECT_ID)),
        "branches",
    )
    matching_branches = [
        branch for branch in branches
        if branch.get("id") == NEON_BRANCH_ID
        and branch.get("name") == NEON_BRANCH_NAME
        and branch.get("project_id") == NEON_PROJECT_ID
        and branch.get("default") is False
        and branch.get("primary") is False
    ]
    if len(matching_branches) != 1:
        raise ProvisioningTargetError(
            "The approved Neon testing branch could not be verified."
        )

    endpoints = response_items(
        neon_api_json(
            "/projects/{}/branches/{}/endpoints".format(
                NEON_PROJECT_ID, NEON_BRANCH_ID
            )
        ),
        "endpoints",
    )
    matching_hosts = set()
    for endpoint in endpoints:
        if (
            endpoint.get("project_id") != NEON_PROJECT_ID
            or endpoint.get("branch_id") != NEON_BRANCH_ID
            or endpoint.get("type") != "read_write"
            or endpoint.get("disabled")
        ):
            continue
        hosts = endpoint.get("hosts", {})
        if not isinstance(hosts, dict):
            raise ProvisioningTargetError(
                "Neon returned invalid endpoint metadata; no account was created."
            )
        for host in (
            endpoint.get("host"),
            hosts.get("read_write_host"),
            hosts.get("read_write_pooled_host"),
        ):
            if isinstance(host, str) and host:
                matching_hosts.add(host.lower().rstrip("."))

    if configured_host not in matching_hosts:
        raise ProvisioningTargetError(
            "Configured Neon endpoint does not belong to employee-hub-testing."
        )
    return configured_host


def verify_target_database(connection, expected_host):
    if not isinstance(connection, hris_server.PostgresConnection):
        raise ProvisioningTargetError("Admin provisioning requires PostgreSQL.")

    row = connection.execute("SELECT current_database() AS name").fetchone()
    if not row or row.get("name") != DATABASE_NAME:
        raise ProvisioningTargetError(
            "Connected database is not the approved neondb database."
        )

    try:
        connected_host = connection.connection.info.host.lower().rstrip(".")
    except (AttributeError, TypeError):
        raise ProvisioningTargetError(
            "The connected Neon endpoint could not be verified."
        ) from None
    if not connected_host or connected_host != expected_host:
        raise ProvisioningTargetError(
            "Connected Neon endpoint does not match the verified testing endpoint."
        )


def validate_username(username):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,50}", username):
        raise ValueError(
            "Username must be 3-50 lowercase letters, digits, dots, underscores, or hyphens."
        )
    return username


def validate_email(email):
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid work email address.")
    return email


def main():
    if not hris_server.DATABASE_URL:
        raise SystemExit("Set DATABASE_URL to the managed PostgreSQL database.")

    try:
        expected_host = verify_configured_database_target(hris_server.DATABASE_URL)
    except ProvisioningTargetError:
        raise SystemExit(
            "Database target verification failed; no account was created."
        ) from None

    try:
        username = validate_username(input("New HR administrator username: "))
        email = validate_email(input("HR administrator work email: "))
    except ValueError as error:
        raise SystemExit(str(error)) from None

    password = getpass.getpass("New HR administrator password (minimum 16 characters): ")
    if len(password) < 16:
        raise SystemExit("Password must contain at least 16 characters.")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    connection = hris_server.connect_database()
    try:
        verify_target_database(connection, expected_host)
        print(
            "\nTarget verified: Neon project {}, branch {}, database {}.".format(
                NEON_PROJECT_ID, NEON_BRANCH_NAME, DATABASE_NAME
            )
        )
        print("Account: {} <{}> (role: hr_admin).".format(username, email))
        if input("Type CREATE to create this account: ") != "CREATE":
            connection.rollback()
            print("Account creation cancelled.")
            return

        salt, password_hash = hris_server.hash_password(password)
        connection.execute(
            "INSERT INTO users (username, email, role, password_salt, password_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, email, "hr_admin", salt, password_hash),
        )
        connection.commit()
    except hris_server.DATABASE_INTEGRITY_ERRORS:
        connection.rollback()
        raise SystemExit("That username or email is already in use.")
    except hris_server.DATABASE_ERRORS + (ProvisioningTargetError,):
        connection.rollback()
        raise SystemExit("Database target verification or operation failed; no account was created.")
    finally:
        connection.close()

    print("HR administrator created.")


if __name__ == "__main__":
    main()
