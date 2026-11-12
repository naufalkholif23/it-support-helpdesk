import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import repository


STATUSES = {"draft", "active", "inactive"}
VISIBILITIES = {"employees", "hr_admin"}
GOOGLE_FORM_HOSTS = {"docs.google.com", "forms.google.com", "forms.gle"}


def list_items(connect_database, database_lock, active_only=False):
    with database_lock:
        connection = connect_database()
        try:
            return repository.list_items(connection, active_only=active_only)
        finally:
            connection.close()


def get_item(item_id, connect_database, database_lock, active_only=False):
    with database_lock:
        connection = connect_database()
        try:
            return repository.get_item(connection, item_id, active_only=active_only)
        finally:
            connection.close()


def create_item(payload, user, connect_database, database_lock):
    item = _validated_item(payload)
    item["id"] = secrets.token_hex(12)
    item["createdBy"] = user["username"]
    now = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            repository.create_item(connection, item, now)
            connection.commit()
            return repository.get_item(connection, item["id"])
        finally:
            connection.close()


def update_item(item_id, payload, connect_database, database_lock):
    item = _validated_item(payload)
    now = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            if not repository.update_item(connection, item_id, item, now):
                return None
            connection.commit()
            return repository.get_item(connection, item_id)
        finally:
            connection.close()


def set_status(item_id, status, connect_database, database_lock):
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("Status is invalid.")
    now = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            existing = repository.get_item(connection, item_id)
            if not existing:
                return None
            if status == "active":
                if not existing["targetUrl"]:
                    raise ValueError(
                        "A Google Forms URL is required before activation."
                    )
                _validate_google_forms_url(existing["targetUrl"])
            if not repository.set_status(connection, item_id, status, now):
                raise ValueError("A Google Forms URL is required before activation.")
            connection.commit()
            return repository.get_item(connection, item_id)
        finally:
            connection.close()


def delete_item(item_id, connect_database, database_lock):
    with database_lock:
        connection = connect_database()
        try:
            deleted = repository.delete_item(connection, item_id)
            if deleted:
                connection.commit()
            return deleted
        finally:
            connection.close()


def _validated_item(payload):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    title = _required_text(payload, "title", 120)
    description = _required_text(payload, "description", 500)
    category = _required_text(payload, "category", 80)
    icon = _required_text(payload, "icon", 60)
    if not re.fullmatch(r"fa-[a-z0-9-]+", icon):
        raise ValueError("Icon must be a Font Awesome class beginning with fa-.")
    target_url = payload.get("targetUrl")
    if target_url in ("", None):
        target_url = None
    elif not isinstance(target_url, str) or len(target_url) > 2048:
        raise ValueError("Google Forms URL must be a valid HTTPS URL.")
    else:
        target_url = _validate_google_forms_url(target_url)

    raw_display_order = payload.get("displayOrder", 0)
    if isinstance(raw_display_order, bool):
        raise ValueError("Display order must be a non-negative integer.")
    if isinstance(raw_display_order, int):
        display_order = raw_display_order
    elif isinstance(raw_display_order, str) and re.fullmatch(r"\d+", raw_display_order):
        display_order = int(raw_display_order)
    else:
        raise ValueError("Display order must be a non-negative integer.")
    if display_order < 0 or display_order > 10000:
        raise ValueError("Display order must be a non-negative integer.")

    visibility = payload.get("visibility", "employees")
    if not isinstance(visibility, str) or visibility not in VISIBILITIES:
        raise ValueError("Visibility is invalid.")
    status = payload.get("status", "draft")
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("Status is invalid.")
    if status == "active" and not target_url:
        raise ValueError("A Google Forms URL is required before activation.")

    return {
        "title": title,
        "description": description,
        "category": category,
        "icon": icon,
        "targetUrl": target_url,
        "displayOrder": display_order,
        "visibility": visibility,
        "status": status,
    }


def _required_text(payload, field, maximum):
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError("{} is required.".format(field))
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError("{} must be between 1 and {} characters.".format(field, maximum))
    return value


def _validate_google_forms_url(value):
    try:
        normalized = value.strip()
        if any(character.isspace() for character in normalized):
            raise ValueError
        parsed = urlsplit(normalized)
        hostname = (parsed.hostname or "").lower()
        valid_short_link = (
            hostname == "forms.gle"
            and bool(re.fullmatch(r"/[A-Za-z0-9_-]+/?", parsed.path))
        )
        valid_full_link = (
            hostname in {"docs.google.com", "forms.google.com"}
            and bool(re.search(r"/forms/(?:u/\d+/)?d/(?:e/)?[^/]+", parsed.path))
        )
        if (
            parsed.scheme != "https"
            or hostname not in GOOGLE_FORM_HOSTS
            or not (valid_short_link or valid_full_link)
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not parsed.netloc
        ):
            raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("Enter a valid HTTPS Google Forms URL.")
    return normalized
