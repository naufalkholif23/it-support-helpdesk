import secrets
from datetime import datetime, timezone

from . import repository
from ..auth.permissions import require_role


HELPDESK_STAFF_ROLES = {"it_support", "hr_admin", "system_admin"}
TICKET_CATEGORIES = {
    "IT Support", "Hardware", "Software", "Network",
    "Account & Access", "HR", "Other",
}
TICKET_PRIORITIES = {"Low", "Medium", "High", "Critical"}
TICKET_STATUSES = {"Open", "In Progress", "Pending", "Resolved", "Closed"}


def is_staff(user):
    return bool(HELPDESK_STAFF_ROLES.intersection(user.get("roles", [user.get("role")])))


def list_tickets(user, connect_database, database_lock, query):
    filters = {
        "search": _query_value(query, "search")[:100],
        "status": _query_value(query, "status"),
        "category": _query_value(query, "category"),
        "priority": _query_value(query, "priority"),
    }
    if filters["status"] and filters["status"] not in TICKET_STATUSES:
        raise ValueError("Status is invalid.")
    if filters["category"] and filters["category"] not in TICKET_CATEGORIES:
        raise ValueError("Category is invalid.")
    if filters["priority"] and filters["priority"] not in TICKET_PRIORITIES:
        raise ValueError("Priority is invalid.")
    with database_lock:
        connection = connect_database()
        try:
            return repository.list_tickets(connection, user, is_staff(user), filters)
        finally:
            connection.close()


def get_ticket(ticket_id, user, connect_database, database_lock):
    with database_lock:
        connection = connect_database()
        try:
            ticket = repository.get_ticket(connection, ticket_id.strip().upper())
        finally:
            connection.close()
    if ticket and not is_staff(user) and ticket["reporter_username"] != user["username"]:
        return None
    return ticket


def create_ticket(payload, user, connect_database, database_lock):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    ticket = {
        "subject": _required_text(payload, "subject", 160),
        "description": _required_text(payload, "description", 4000),
        "category": _required_text(payload, "category", 40),
        "priority": _required_text(payload, "priority", 10),
        "name": _required_text(payload, "name", 100),
        "email": _required_text(payload, "email", 254).lower(),
        "department": _required_text(payload, "department", 80),
    }
    if ticket["category"] not in TICKET_CATEGORIES:
        raise ValueError("Category is invalid.")
    if ticket["priority"] not in TICKET_PRIORITIES:
        raise ValueError("Priority is invalid.")
    if "@" not in ticket["email"] or any(character.isspace() for character in ticket["email"]):
        raise ValueError("Enter a valid email address.")
    ticket["id"] = None
    now = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            for _ in range(10):
                ticket["id"] = "IT-{}-{}".format(
                    datetime.now(timezone.utc).strftime("%Y%m%d"),
                    secrets.token_hex(2).upper(),
                )
                if not connection.execute(
                    "SELECT 1 FROM helpdesk_tickets WHERE ticket_id = ?",
                    (ticket["id"],),
                ).fetchone():
                    break
            else:
                raise RuntimeError("Unable to allocate a unique ticket ID.")
            repository.create_ticket(connection, ticket, user, now)
            return repository.get_ticket(connection, ticket["id"])
        finally:
            connection.close()


def update_ticket(ticket_id, payload, user, connect_database, database_lock):
    require_role(user, HELPDESK_STAFF_ROLES)
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    changes = {}
    if "status" in payload:
        status = payload["status"]
        if status not in TICKET_STATUSES:
            raise ValueError("Status is invalid.")
        changes["status"] = status
    if "pic" in payload:
        changes["pic"] = _optional_text(payload["pic"], "Assignee", 100)
    if "resolution" in payload:
        changes["resolution"] = _optional_text(payload["resolution"], "Resolution", 2000)
    if "comment" in payload:
        changes["comment"] = _optional_text(payload["comment"], "Comment", 2000)
    if not changes:
        raise ValueError("At least one ticket update is required.")
    now = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            if not repository.update_ticket(
                connection, ticket_id.strip().upper(), changes, user, now
            ):
                return None
            return repository.get_ticket(connection, ticket_id.strip().upper())
        finally:
            connection.close()


def add_comment(ticket_id, body, user, connect_database, database_lock):
    comment = _required_text({"comment": body}, "comment", 2000)
    now = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            ticket = repository.get_ticket(connection, ticket_id.strip().upper())
            if not ticket or (
                not is_staff(user)
                and ticket["reporter_username"] != user["username"]
            ):
                return None
            repository.add_comment(
                connection, ticket["id"], user["username"], comment, now
            )
            connection.commit()
            return repository.get_ticket(connection, ticket["id"])
        finally:
            connection.close()


def dashboard_summary(user, connect_database, database_lock):
    require_role(user, HELPDESK_STAFF_ROLES)
    with database_lock:
        connection = connect_database()
        try:
            return repository.dashboard_summary(connection)
        finally:
            connection.close()


def _query_value(query, key):
    value = query.get(key, [""])
    return value[0].strip() if value else ""


def _required_text(payload, field, maximum):
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError("{} is required.".format(field))
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError("{} must be between 1 and {} characters.".format(field, maximum))
    return value


def _optional_text(value, field, maximum):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("{} must be text.".format(field))
    value = value.strip()
    if len(value) > maximum:
        raise ValueError("{} must not exceed {} characters.".format(field, maximum))
    return value or None
