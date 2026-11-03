import getpass
import re

import hris_server


def main():
    if not hris_server.DATABASE_URL:
        raise SystemExit("Set DATABASE_URL to the managed PostgreSQL database.")

    username = input("New HR administrator username: ").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,50}", username):
        raise SystemExit("Username must be 3-50 lowercase letters, digits, dots, underscores, or hyphens.")

    email = input("HR administrator work email: ").strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise SystemExit("Enter a valid work email address.")

    password = getpass.getpass("New HR administrator password (minimum 16 characters): ")
    if len(password) < 16:
        raise SystemExit("Password must contain at least 16 characters.")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    salt, password_hash = hris_server.hash_password(password)
    connection = hris_server.connect_database()
    try:
        connection.execute(
            "INSERT INTO users (username, email, role, password_salt, password_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, email, "hr_admin", salt, password_hash),
        )
        connection.commit()
    except hris_server.DATABASE_INTEGRITY_ERRORS:
        raise SystemExit("That username or email is already in use.")
    finally:
        connection.close()

    print("HR administrator created.")


if __name__ == "__main__":
    main()
