import os
from http.server import ThreadingHTTPServer


HOST = "0.0.0.0"
LOCAL_TEST_PORT = 8000


def server_bindings(environ=None, allow_local_default=False):
    environment = os.environ if environ is None else environ
    raw_port = environment.get("PORT")
    if raw_port is None and allow_local_default:
        raw_port = str(LOCAL_TEST_PORT)
    if raw_port is None or not raw_port.strip():
        raise RuntimeError("PORT is required to start the Render web service.")
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        raise RuntimeError("PORT must be an integer from 1 to 65535.") from None
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be an integer from 1 to 65535.")
    return HOST, port


def validate_deployment_configuration():
    os.environ["HRIS_DEPLOYMENT"] = "render"
    from backend.app.database.connection import (
        validate_postgres_database_url,
        validate_postgres_sslrootcert,
    )
    from backend.app.modules.auth.origin import validate_render_allowed_origins

    validate_postgres_database_url(
        os.environ.get("DATABASE_URL", ""),
        os.environ.get("HRIS_POSTGRES_EXPECTED_HOSTNAME", ""),
        os.environ.get("HRIS_POSTGRES_EXPECTED_DATABASE", ""),
    )
    validate_postgres_sslrootcert(
        os.environ.get("HRIS_POSTGRES_SSLROOTCERT", "")
    )
    host, port = server_bindings()
    validate_render_allowed_origins()
    return host, port


def main():
    host, port = validate_deployment_configuration()

    from hris_server import DATABASE_URL, HRISHandler

    if DATABASE_URL != os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError(
            "The application database configuration does not match the Render environment."
        )

    server = ThreadingHTTPServer((host, port), HRISHandler)
    print("Suryanesia Employee Hub listening on {}:{}".format(host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Render web service.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
