from .schema import apply_sqlite_migrations, apply_sqlite_schema
from .seed import (
    seed_development_employees,
    seed_development_users,
    seed_quick_access_items,
)


def initialize_database(
    connect_database, database_lock, database_url=None, demo_password=None
):
    if database_url:
        raise RuntimeError(
            "PostgreSQL schemas must be installed using the checked-in migration."
        )
    with database_lock:
        connection = connect_database()
        try:
            apply_sqlite_schema(connection)
            apply_sqlite_migrations(connection)
            seed_development_users(connection, demo_password=demo_password)
            seed_development_employees(connection)
            seed_quick_access_items(connection)
            connection.commit()
        finally:
            connection.close()
