from ..core.exceptions import DatabaseConfigurationError


try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None
    POSTGRES_ERRORS = ()
    POSTGRES_INTEGRITY_ERRORS = ()
else:
    POSTGRES_ERRORS = (psycopg.Error,)
    POSTGRES_INTEGRITY_ERRORS = (psycopg.IntegrityError,)


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        return self.connection.execute(statement.replace("?", "%s"), parameters)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def connect_postgres(database_url, sslmode="require", sslrootcert=None):
    if psycopg is None:
        raise DatabaseConfigurationError(
            "Install the PostgreSQL driver from requirements.txt."
        )
    connection_options = {
        "connect_timeout": 5,
        "row_factory": dict_row,
        "sslmode": sslmode,
    }
    if sslrootcert is not None:
        connection_options["sslrootcert"] = sslrootcert
    connection = psycopg.connect(database_url, **connection_options)
    return PostgresConnection(connection)
