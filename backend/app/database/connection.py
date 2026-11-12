import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from ..core.exceptions import DatabaseConfigurationError
from .postgres import (
    POSTGRES_ERRORS,
    POSTGRES_INTEGRITY_ERRORS,
    PostgresConnection,
    connect_postgres,
    dict_row,
    psycopg,
)
from .sqlite import connect_sqlite


DATABASE_ERRORS = (sqlite3.Error, DatabaseConfigurationError) + POSTGRES_ERRORS
DATABASE_INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + POSTGRES_INTEGRITY_ERRORS

_ALLOWED_DATABASE_URL_PARAMETERS = {
    "sslmode": {"require", "verify-full"},
    "channel_binding": {"require"},
}
_RENDER_DATABASE_NAME = "neondb"


def validate_postgres_database_url(
    database_url, expected_hostname=None, expected_database=None
):
    if not isinstance(database_url, str) or not database_url.strip():
        raise DatabaseConfigurationError(
            "DATABASE_URL is required for the Render deployment."
        )
    try:
        parsed = urlsplit(database_url.strip())
        port = parsed.port
        query_parameters = parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True
        )
        database_name = unquote(parsed.path[1:], errors="strict")
    except (UnicodeError, ValueError):
        raise DatabaseConfigurationError(
            "DATABASE_URL must be a valid PostgreSQL connection URL."
        ) from None
    if (
        parsed.scheme not in ("postgres", "postgresql")
        or not parsed.hostname
        or not parsed.path.startswith("/")
        or parsed.path.count("/") != 1
        or not database_name
        or not parsed.username
        or not parsed.password
        or parsed.fragment
        or (port is not None and port != 5432)
    ):
        raise DatabaseConfigurationError(
            "DATABASE_URL must be a valid PostgreSQL connection URL."
        )

    seen_parameters = set()
    for key, value in query_parameters:
        if key in seen_parameters or key not in _ALLOWED_DATABASE_URL_PARAMETERS:
            raise DatabaseConfigurationError(
                "DATABASE_URL contains an unsupported connection parameter."
            )
        seen_parameters.add(key)
        if value not in _ALLOWED_DATABASE_URL_PARAMETERS[key]:
            raise DatabaseConfigurationError(
                "DATABASE_URL contains an unsupported connection parameter."
            )

    if not isinstance(expected_hostname, str) or not expected_hostname.strip():
        raise DatabaseConfigurationError(
            "HRIS_POSTGRES_EXPECTED_HOSTNAME is required for Render."
        )
    if not isinstance(expected_database, str) or not expected_database.strip():
        raise DatabaseConfigurationError(
            "HRIS_POSTGRES_EXPECTED_DATABASE is required for Render."
        )
    expected_hostname = expected_hostname.strip()
    try:
        expected_host = urlsplit("//" + expected_hostname)
        if (
            not expected_host.hostname
            or expected_host.port is not None
            or expected_host.path
            or expected_host.query
            or expected_host.fragment
            or expected_host.username is not None
            or expected_host.password is not None
        ):
            raise ValueError
    except ValueError:
        raise DatabaseConfigurationError(
            "HRIS_POSTGRES_EXPECTED_HOSTNAME must be a hostname only."
        ) from None
    if expected_database.strip() != _RENDER_DATABASE_NAME:
        raise DatabaseConfigurationError(
            "HRIS_POSTGRES_EXPECTED_DATABASE must identify the configured Employee Hub database."
        )
    if (
        parsed.hostname.lower() != expected_host.hostname.lower()
        or database_name != expected_database.strip()
    ):
        raise DatabaseConfigurationError(
            "DATABASE_URL does not match the configured Employee Hub database target."
        )
    return database_url.strip()


def validate_postgres_sslrootcert(sslrootcert):
    if not isinstance(sslrootcert, str) or not sslrootcert.strip():
        raise DatabaseConfigurationError(
            "HRIS_POSTGRES_SSLROOTCERT is required for the Render deployment."
        )
    try:
        certificate_path = Path(sslrootcert.strip())
        if not certificate_path.is_file():
            raise OSError
        with certificate_path.open("rb"):
            pass
    except (OSError, ValueError):
        raise DatabaseConfigurationError(
            "HRIS_POSTGRES_SSLROOTCERT must point to a readable CA bundle file."
        ) from None
    return str(certificate_path)


def connect_database(
    database_url,
    database_path,
    vercel=False,
    render=False,
    expected_hostname=None,
    expected_database=None,
    sslrootcert=None,
):
    if render:
        database_url = validate_postgres_database_url(
            database_url, expected_hostname, expected_database
        )
        sslrootcert = validate_postgres_sslrootcert(sslrootcert)
        return connect_postgres(
            database_url, sslmode="verify-full", sslrootcert=sslrootcert
        )
    if vercel and not database_url:
        raise DatabaseConfigurationError("DATABASE_URL is required on Vercel.")
    if database_url:
        return connect_postgres(database_url)
    return connect_sqlite(database_path)
