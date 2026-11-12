def get_profile(connection, username):
    account = connection.execute(
        "SELECT username, email, role FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if not account:
        return None
    employee = connection.execute(
        "SELECT employees.employee_id AS id, employees.full_name AS name, "
        "employees.email, employees.department, employees.position, employees.status, "
        "employees.created_at AS createdAt, employees.updated_at AS updatedAt "
        "FROM user_employee_links "
        "JOIN employees ON employees.employee_id = user_employee_links.employee_id "
        "WHERE user_employee_links.username = ?",
        (username,),
    ).fetchone()
    return {
        "account": dict(account),
        "employee": dict(employee) if employee else None,
    }
