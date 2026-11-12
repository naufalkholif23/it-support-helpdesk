READ_ROLES = {"hr_admin", "system_admin"}
WRITE_ROLES = {"hr_admin", "system_admin"}


def is_demo_user(user):
    return bool(user and user.get("role") == "demo_viewer")


def require_role(user, allowed_roles):
    roles = user.get("roles", [user["role"]])
    if not set(roles).intersection(allowed_roles):
        raise PermissionError("Your account is not authorized for this action.")


def require_non_demo_user(user):
    if is_demo_user(user):
        raise PermissionError("Demo mode is read-only.")
