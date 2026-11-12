from datetime import datetime, timezone

from . import repository


def get_summary(connect_database, database_lock):
    with database_lock:
        connection = connect_database()
        try:
            return repository.dashboard_summary(
                connection, datetime.now(timezone.utc)
            )
        finally:
            connection.close()
