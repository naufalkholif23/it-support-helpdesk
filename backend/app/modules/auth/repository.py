def roles_for_user(connection, username, primary_role):
    rows = connection.execute(
        "SELECT role FROM user_roles WHERE username = ? ORDER BY role",
        (username,),
    ).fetchall()
    return [primary_role] + [row["role"] for row in rows if row["role"] != primary_role]
