def list_items(connection, active_only=False):
    query = (
        'SELECT id, title, description, category, icon, target_url AS "targetUrl", '
        'display_order AS "displayOrder", visibility, status, created_by AS "createdBy", '
        'created_at AS "createdAt", updated_at AS "updatedAt" '
        "FROM quick_access_items"
    )
    parameters = ()
    if active_only:
        query += " WHERE status = ? AND visibility = ? AND target_url IS NOT NULL"
        parameters = ("active", "employees")
    query += " ORDER BY display_order, LOWER(title), id"
    return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def get_item(connection, item_id, active_only=False):
    query = (
        'SELECT id, title, description, category, icon, target_url AS "targetUrl", '
        'display_order AS "displayOrder", visibility, status, created_by AS "createdBy", '
        'created_at AS "createdAt", updated_at AS "updatedAt" '
        "FROM quick_access_items WHERE id = ?"
    )
    parameters = [item_id]
    if active_only:
        query += " AND status = ? AND visibility = ? AND target_url IS NOT NULL"
        parameters.extend(("active", "employees"))
    row = connection.execute(query, tuple(parameters)).fetchone()
    return dict(row) if row else None


def create_item(connection, item, now):
    connection.execute(
        "INSERT INTO quick_access_items "
        "(id, title, description, category, icon, target_url, display_order, "
        "visibility, status, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item["id"],
            item["title"],
            item["description"],
            item["category"],
            item["icon"],
            item["targetUrl"],
            item["displayOrder"],
            item["visibility"],
            item["status"],
            item["createdBy"],
            now,
            now,
        ),
    )


def update_item(connection, item_id, item, now):
    cursor = connection.execute(
        "UPDATE quick_access_items SET title = ?, description = ?, category = ?, "
        "icon = ?, target_url = ?, display_order = ?, visibility = ?, status = ?, "
        "updated_at = ? WHERE id = ?",
        (
            item["title"],
            item["description"],
            item["category"],
            item["icon"],
            item["targetUrl"],
            item["displayOrder"],
            item["visibility"],
            item["status"],
            now,
            item_id,
        ),
    )
    return cursor.rowcount > 0


def set_status(connection, item_id, status, now):
    cursor = connection.execute(
        "UPDATE quick_access_items SET status = ?, updated_at = ? "
        "WHERE id = ? AND (? != 'active' OR target_url IS NOT NULL)",
        (status, now, item_id, status),
    )
    return cursor.rowcount > 0


def delete_item(connection, item_id):
    cursor = connection.execute(
        "DELETE FROM quick_access_items WHERE id = ?", (item_id,)
    )
    return cursor.rowcount > 0
