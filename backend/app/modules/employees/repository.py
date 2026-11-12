from datetime import datetime, timezone
import json


def employee_summary(connection, include_monthly_records=False, now=None):
    statement = (
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS active, "
        "COALESCE(SUM(CASE WHEN status = 'inactive' THEN 1 ELSE 0 END), 0) AS inactive, "
        "COUNT(DISTINCT department) AS departments"
    )
    parameters = ()
    if include_monthly_records:
        if now is None:
            now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (
            month_start.replace(year=month_start.year + 1, month=1)
            if month_start.month == 12
            else month_start.replace(month=month_start.month + 1)
        )
        statement += (
            ", COALESCE(SUM(CASE WHEN created_at >= ? AND created_at < ? "
            "THEN 1 ELSE 0 END), 0) AS new_this_month"
        )
        parameters = (month_start.isoformat(), next_month.isoformat())
    return dict(connection.execute(statement + " FROM employees", parameters).fetchone())


def list_employees(connection, where, values, sort_column, sort_order, page_size, offset, now):
    total = connection.execute(
        "SELECT COUNT(*) AS count FROM employees" + where, values
    ).fetchone()["count"]
    summary = employee_summary(connection, now=now)
    departments = [
        row["department"]
        for row in connection.execute(
            "SELECT department FROM employees "
            "GROUP BY department ORDER BY LOWER(department), department"
        ).fetchall()
    ]
    positions = [
        row["position"]
        for row in connection.execute(
            "SELECT position FROM employees "
            "GROUP BY position ORDER BY LOWER(position), position"
        ).fetchall()
    ]
    rows = connection.execute(
        "SELECT employee_id AS id, full_name AS name, email, department, position, status, updated_at "
        "FROM employees" + where + " ORDER BY {} {}, LOWER(employee_id) ASC ".format(
            sort_column, sort_order
        ) +
        "LIMIT ? OFFSET ?",
        values + [page_size, offset],
    ).fetchall()
    return {
        "employees": [dict(row) for row in rows],
        "total": total,
        "summary": dict(summary),
        "departments": departments,
        "positions": positions,
    }


def dashboard_summary(connection, now):
    summary = employee_summary(connection, include_monthly_records=True, now=now)
    by_status = connection.execute(
        "SELECT status, COUNT(*) AS total FROM employees "
        "GROUP BY status ORDER BY status"
    ).fetchall()
    by_department = connection.execute(
        "SELECT department, COUNT(*) AS total FROM employees "
        "GROUP BY department ORDER BY total DESC, LOWER(department)"
    ).fetchall()
    return {
        "summary": summary,
        "byStatus": [dict(row) for row in by_status],
        "byDepartment": [dict(row) for row in by_department],
    }


def get_employee(connection, employee_id):
    return connection.execute(
        "SELECT employee_id AS id, full_name AS name, email, department, position, status, updated_at "
        "FROM employees WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()


def create_employee(connection, employee, user, now):
    connection.execute(
        "INSERT INTO employees "
        "(employee_id, full_name, email, department, position, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            employee["id"], employee["name"], employee["email"],
            employee["department"], employee["position"], employee["status"], now, now,
        ),
    )
    connection.execute(
        "INSERT INTO audit_logs (actor, action, employee_id, occurred_at, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            user["username"], "employee.created", employee["id"], now,
            json.dumps({"fields": ["name", "email", "department", "position", "status"]}),
        ),
    )
    connection.commit()


def update_employee(connection, employee_id, employee, user, updated_at, expected_updated_at):
    cursor = connection.execute(
        "UPDATE employees SET employee_id = ?, full_name = ?, email = ?, "
        "department = ?, position = ?, status = ?, updated_at = ? "
        "WHERE employee_id = ?" + (" AND updated_at = ?" if expected_updated_at else ""),
        (
            employee["id"], employee["name"], employee["email"],
            employee["department"], employee["position"], employee["status"],
            updated_at, employee_id,
        ) + ((expected_updated_at,) if expected_updated_at else ()),
    )
    if cursor.rowcount == 0:
        current = connection.execute(
            "SELECT updated_at FROM employees WHERE employee_id = ?",
            (employee_id,),
        ).fetchone()
        connection.rollback()
        return False, bool(current and expected_updated_at)
    connection.execute(
        "INSERT INTO audit_logs (actor, action, employee_id, occurred_at, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            user["username"], "employee.updated", employee_id, updated_at,
            json.dumps({"fields": ["name", "email", "department", "position", "status"]}),
        ),
    )
    connection.commit()
    return True, False


def delete_employee(connection, employee_id, user, occurred_at):
    cursor = connection.execute(
        "DELETE FROM employees WHERE employee_id = ?", (employee_id,)
    )
    if cursor.rowcount == 0:
        connection.rollback()
        return False
    connection.execute(
        "INSERT INTO audit_logs (actor, action, employee_id, occurred_at, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (user["username"], "employee.deleted", employee_id, occurred_at, "{}"),
    )
    connection.commit()
    return True
