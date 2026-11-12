import getpass
import json
import os
import re
import shutil
import subprocess
from urllib.parse import parse_qsl, unquote, urlsplit

import hris_server
from backend.app.database.postgres import connect_postgres


ALLOWED_TARGET_VARIABLES = {
    "project_id": "HRIS_ADMIN_ALLOWED_NEON_PROJECT_ID",
    "branch_id": "HRIS_ADMIN_ALLOWED_NEON_BRANCH_ID",
    "branch_name": "HRIS_ADMIN_ALLOWED_NEON_BRANCH_NAME",
    "database_name": "HRIS_ADMIN_ALLOWED_NEON_DATABASE_NAME",
}


class ProvisioningTargetError(RuntimeError):
    pass


def load_allowed_target(environ=None):
    environment = os.environ if environ is None else environ
    missing = [
        variable for variable in ALLOWED_TARGET_VARIABLES.values()
        if not environment.get(variable, "").strip()
    ]
    if missing:
        raise ProvisioningTargetError(
            "Explicit allowed permanent Neon database target configuration is required."
        )

    target = {
        key: environment[variable].strip()
        for key, variable in ALLOWED_TARGET_VARIABLES.items()
    }
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+", target["project_id"])
        or not re.fullmatch(r"[A-Za-z0-9_-]+", target["branch_id"])
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,62}", target["branch_name"])
        or not re.fullmatch(r"[A-Za-z0-9_-]+", target["database_name"])
    ):
        raise ProvisioningTargetError(
            "Allowed target contains an invalid Neon project, branch, or database identifier."
        )
    return target


def response_items(response, key):
    if not isinstance(response, dict):
        raise ProvisioningTargetError(
            "Neon returned invalid target metadata; no account was created."
        )
    items = response.get(key)
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ProvisioningTargetError(
            "Neon returned invalid target metadata; no account was created."
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
            "Neon target verification failed; no account was created."
        ) from None
    if result.returncode != 0:
        raise ProvisioningTargetError(
            "Neon target verification failed; no account was created."
        )
    try:
        return json.loads(result.stdout)
    except (TypeError, ValueError):
        raise ProvisioningTargetError(
            "Neon returned invalid target metadata; no account was created."
        ) from None


def parse_database_target(database_url, expected_database_name):
    try:
        parsed_url = urlsplit(database_url)
        configured_host = parsed_url.hostname
        configured_database = unquote(parsed_url.path.lstrip("/"))
        port = parsed_url.port
        query_parameters = parse_qsl(parsed_url.query, keep_blank_values=True)
    except (AttributeError, TypeError, ValueError):
        configured_host = None
        configured_database = None
        port = None
        parsed_url = None
        query_parameters = []
    query_names = [name.lower() for name, _ in query_parameters]
    query_values = {
        name.lower(): value.lower() for name, value in query_parameters
    }
    if (
        not parsed_url
        or parsed_url.scheme not in ("postgres", "postgresql")
        or not configured_host
        or configured_database != expected_database_name
        or parsed_url.fragment
        or (port is not None and port != 5432)
        or len(query_names) != len(set(query_names))
        or any(name not in {"sslmode", "channel_binding"} for name in query_names)
        or query_values.get("sslmode") not in (None, "require", "verify-full")
        or query_values.get("channel_binding") not in (
            None, "require", "prefer", "disable"
        )
    ):
        raise ProvisioningTargetError(
            "DATABASE_URL does not match the explicitly allowed PostgreSQL target."
        )
    return configured_host.lower().rstrip(".")


def verify_configured_database_target(database_url, target, api_json=None):
    configured_host = parse_database_target(database_url, target["database_name"])
    get_json = neon_api_json if api_json is None else api_json
    branches = response_items(
        get_json("/projects/{}/branches".format(target["project_id"])),
        "branches",
    )
    matching_branches = [
        branch for branch in branches
        if branch.get("id") == target["branch_id"]
        and branch.get("name") == target["branch_name"]
        and branch.get("project_id") == target["project_id"]
        and any(
            branch.get(field) is True
            for field in ("default", "primary")
        )
        and all(
            field not in branch or isinstance(branch[field], bool)
            for field in ("default", "primary")
        )
    ]
    if len(matching_branches) != 1:
        raise ProvisioningTargetError(
            "The exact allowlisted Neon default/primary branch could not be verified."
        )

    endpoints = response_items(
        get_json(
            "/projects/{}/branches/{}/endpoints".format(
                target["project_id"], target["branch_id"]
            )
        ),
        "endpoints",
    )
    matching_hosts = set()
    for endpoint in endpoints:
        if (
            endpoint.get("project_id") != target["project_id"]
            or endpoint.get("branch_id") != target["branch_id"]
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
            "DATABASE_URL endpoint does not belong to the exact allowlisted Neon branch."
        )
    return configured_host


def verify_target_database(connection, target, expected_host):
    if not isinstance(connection, hris_server.PostgresConnection):
        raise ProvisioningTargetError("Admin provisioning requires PostgreSQL.")

    row = connection.execute("SELECT current_database() AS name").fetchone()
    if not row or row.get("name") != target["database_name"]:
        raise ProvisioningTargetError(
            "Connected database does not match the explicitly allowed target."
        )

    try:
        connected_host = connection.connection.info.host.lower().rstrip(".")
    except (AttributeError, TypeError):
        raise ProvisioningTargetError(
            "The connected Neon endpoint could not be verified."
        ) from None
    if not connected_host or connected_host != expected_host:
        raise ProvisioningTargetError(
            "Connected endpoint does not match the verified permanent database endpoint."
        )


def ensure_account_does_not_exist(connection, username, email):
    existing = connection.execute(
        "SELECT username FROM users "
        "WHERE LOWER(username) = ? OR LOWER(email) = ? LIMIT 1",
        (username, email),
    ).fetchone()
    if existing:
        raise ProvisioningTargetError(
            "An account with that username or email already exists; no account was changed."
        )


def connect_verified_database(database_url):
    return connect_postgres(database_url, sslmode="verify-full")


def confirmation_phrase(target):
    return (
        "CREATE PERMANENT EMPLOYEE HUB DATABASE {}/{}/{}/{} "
        "I HAVE VERIFIED THIS TARGET IS CORRECT AND AUTHORIZED"
    ).format(
        target["project_id"],
        target["branch_id"],
        target["branch_name"],
        target["database_name"],
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
        raise SystemExit(
            "Set DATABASE_URL to the explicitly allowlisted permanent Neon database."
        )
    try:
        target = load_allowed_target()
        expected_host = verify_configured_database_target(
            hris_server.DATABASE_URL, target
        )
    except ProvisioningTargetError:
        raise SystemExit(
            "Database target verification failed; no account was created."
        ) from None

    try:
        username = validate_username(input("New HR administrator username: "))
        email = validate_email(input("HR administrator work email: "))
    except ValueError as error:
        raise SystemExit(str(error)) from None

    connection = None
    try:
        connection = connect_verified_database(hris_server.DATABASE_URL)
        verify_target_database(connection, target, expected_host)
        ensure_account_does_not_exist(connection, username, email)
        print(
            "\nVerified permanent Employee Hub database: Neon project {}, "
            "branch {} ({}) and database {}.".format(
                target["project_id"],
                target["branch_id"],
                target["branch_name"],
                target["database_name"],
            )
        )
        print("Account to create: {} <{}> (role: hr_admin).".format(username, email))
        print(
            "Confirm that this is the intended permanent Employee Hub database, "
            "that the target identity is correct, and that you are authorized "
            "to create its first HR administrator."
        )
        expected_confirmation = confirmation_phrase(target)
        if input("Type {} to continue: ".format(expected_confirmation)) != expected_confirmation:
            connection.rollback()
            print("Account creation cancelled.")
            return

        password = getpass.getpass(
            "New HR administrator password (minimum 16 characters): "
        )
        if len(password) < 16:
            raise SystemExit("Password must contain at least 16 characters.")
        password_confirmation = getpass.getpass("Confirm password: ")
        if password != password_confirmation:
            raise SystemExit("Passwords do not match.")

        salt, password_hash = hris_server.hash_password(password)
        connection.execute(
            "INSERT INTO users (username, email, role, password_salt, password_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, email, "hr_admin", salt, password_hash),
        )
        connection.commit()
    except hris_server.DATABASE_INTEGRITY_ERRORS:
        if connection:
            connection.rollback()
        raise SystemExit("That username or email is already in use; no account was changed.")
    except ProvisioningTargetError as error:
        if connection:
            connection.rollback()
        raise SystemExit(str(error)) from None
    except SystemExit:
        if connection:
            connection.rollback()
        raise
    except hris_server.DATABASE_ERRORS:
        if connection:
            connection.rollback()
        raise SystemExit(
            "Database target verification or operation failed; no account was created."
        ) from None
    finally:
        if connection:
            connection.close()

    print("HR administrator created.")


if __name__ == "__main__":
    main()
