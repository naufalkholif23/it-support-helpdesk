import re


def validate_employee(payload, employee_id=None):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    fields = {
        "id": payload.get("id", employee_id),
        "name": payload.get("name"),
        "email": payload.get("email"),
        "department": payload.get("department"),
        "position": payload.get("position"),
        "status": payload.get("status", "active"),
    }
    limits = {"id": 30, "name": 100, "email": 254, "department": 100, "position": 100}
    for field, maximum in limits.items():
        value = fields[field]
        if not isinstance(value, str):
            raise ValueError("{} is required.".format(field))
        value = value.strip()
        if not value or len(value) > maximum:
            raise ValueError("{} must be between 1 and {} characters.".format(field, maximum))
        fields[field] = value

    fields["id"] = fields["id"].upper()
    fields["email"] = fields["email"].lower()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,29}", fields["id"]):
        raise ValueError("ID may contain only letters, numbers, and hyphens.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", fields["email"]):
        raise ValueError("Enter a valid email address.")
    if fields["status"] not in ("active", "inactive"):
        raise ValueError("Status must be active or inactive.")
    return fields
