import re


def validate_login_identifier(identifier):
    if not isinstance(identifier, str):
        raise ValueError("Email and password are required.")
    identifier = identifier.strip().lower()
    if (
        len(identifier) <= 254
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", identifier)
    ):
        return "email", identifier
    if re.fullmatch(r"[a-z0-9._-]{3,50}", identifier):
        return "username", identifier
    raise ValueError("Enter a valid work email address or username.")
