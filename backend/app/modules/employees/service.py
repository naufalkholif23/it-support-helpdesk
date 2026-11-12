from datetime import datetime, timezone

from . import repository
from .validators import validate_employee


def list_employees(query, connect_database, database_lock):
    search = query.get("search", [""])[0].strip()[:100]
    department = query.get("department", [""])[0].strip()[:100]
    position = query.get("position", [""])[0].strip()[:100]
    status = query.get("status", [""])[0].strip().lower()
    sort_by = query.get("sortBy", ["name"])[0].strip().lower()
    sort_order = query.get("sortOrder", ["asc"])[0].strip().lower()
    try:
        page = max(1, int(query.get("page", ["1"])[0]))
        page_size = min(100, max(1, int(query.get("pageSize", ["25"])[0])))
    except ValueError:
        raise ValueError("Page and pageSize must be integers.")
    if status and status not in ("active", "inactive"):
        raise ValueError("Status must be active or inactive.")
    sort_columns = {
        "name": "LOWER(full_name)",
        "id": "LOWER(employee_id)",
        "department": "LOWER(department)",
        "position": "LOWER(position)",
        "status": "status",
    }
    if sort_by not in sort_columns or sort_order not in ("asc", "desc"):
        raise ValueError("Sort field or direction is invalid.")

    conditions = []
    values = []
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(
            "(LOWER(employee_id) LIKE LOWER(?) ESCAPE '\\' "
            "OR LOWER(full_name) LIKE LOWER(?) ESCAPE '\\' "
            "OR LOWER(email) LIKE LOWER(?) ESCAPE '\\' "
            "OR LOWER(department) LIKE LOWER(?) ESCAPE '\\' "
            "OR LOWER(position) LIKE LOWER(?) ESCAPE '\\')"
        )
        values.extend([pattern] * 5)
    if department:
        conditions.append("department = ?")
        values.append(department)
    if position:
        conditions.append("position = ?")
        values.append(position)
    if status:
        conditions.append("status = ?")
        values.append(status)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""

    with database_lock:
        connection = connect_database()
        try:
            result = repository.list_employees(
                connection,
                where,
                values,
                sort_columns[sort_by],
                sort_order.upper(),
                page_size,
                (page - 1) * page_size,
                datetime.now(timezone.utc),
            )
        finally:
            connection.close()
    result.update({"page": page, "pageSize": page_size})
    return result


def get_employee(employee_id, connect_database, database_lock):
    with database_lock:
        connection = connect_database()
        try:
            row = repository.get_employee(connection, employee_id)
        finally:
            connection.close()
    return dict(row) if row else None


def create_employee(payload, user, connect_database, database_lock):
    employee = validate_employee(payload)
    now = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            repository.create_employee(connection, employee, user, now)
        finally:
            connection.close()
    return employee


def update_employee(
    employee_id, payload, user, connect_database, database_lock
):
    employee = validate_employee(payload, employee_id)
    expected_updated_at = payload.get("updated_at")
    if expected_updated_at is not None and (
        not isinstance(expected_updated_at, str) or not expected_updated_at
    ):
        raise ValueError("updated_at must be a non-empty string.")
    updated_at = datetime.now(timezone.utc).isoformat()
    with database_lock:
        connection = connect_database()
        try:
            updated, conflict = repository.update_employee(
                connection,
                employee_id,
                employee,
                user,
                updated_at,
                expected_updated_at,
            )
        finally:
            connection.close()
    if not updated:
        if conflict:
            return 409, {"error": "Employee record changed. Reload it before saving."}
        return 404, {"error": "Employee not found."}
    employee["updated_at"] = updated_at
    return 200, {"employee": employee}


def delete_employee(employee_id, user, connect_database, database_lock):
    with database_lock:
        connection = connect_database()
        try:
            deleted = repository.delete_employee(
                connection,
                employee_id,
                user,
                datetime.now(timezone.utc).isoformat(),
            )
        finally:
            connection.close()
    return deleted
