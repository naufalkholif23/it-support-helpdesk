from . import repository
from ..auth.repository import roles_for_user


def get_profile(user, connect_database, database_lock):
    with database_lock:
        connection = connect_database()
        try:
            profile = repository.get_profile(connection, user["username"])
            if profile:
                profile["account"]["roles"] = roles_for_user(
                    connection,
                    profile["account"]["username"],
                    profile["account"]["role"],
                )
            return profile
        finally:
            connection.close()
