import json


def create_ticket(connection, ticket, actor, now):
    connection.execute(
        "INSERT INTO helpdesk_tickets "
        "(ticket_id, subject, description, category, priority, reporter_username, "
        "reporter_name, reporter_email, department, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?, ?)",
        (
            ticket["id"], ticket["subject"], ticket["description"], ticket["category"],
            ticket["priority"], actor["username"], ticket["name"], ticket["email"],
            ticket["department"], now, now,
        ),
    )
    add_event(
        connection, ticket["id"], actor["username"], "created",
        {"status": "Open"}, now,
    )
    connection.commit()


def list_tickets(connection, user, staff, filters):
    conditions = []
    values = []
    if not staff:
        conditions.append("reporter_username = ?")
        values.append(user["username"])
    if filters.get("status"):
        conditions.append("status = ?")
        values.append(filters["status"])
    if filters.get("category"):
        conditions.append("category = ?")
        values.append(filters["category"])
    if filters.get("priority"):
        conditions.append("priority = ?")
        values.append(filters["priority"])
    if filters.get("search"):
        conditions.append(
            "(LOWER(ticket_id) LIKE LOWER(?) OR LOWER(subject) LIKE LOWER(?) "
            "OR LOWER(description) LIKE LOWER(?) OR LOWER(reporter_name) LIKE LOWER(?))"
        )
        pattern = "%" + filters["search"] + "%"
        values.extend([pattern] * 4)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = connection.execute(
        "SELECT ticket_id AS id, subject, description, category, priority, "
        "reporter_username, reporter_name AS name, reporter_email AS email, department, "
        "status, assigned_to AS pic, resolution, created_at AS createdAt, updated_at AS updatedAt "
        "FROM helpdesk_tickets" + where + " ORDER BY updated_at DESC, ticket_id",
        values,
    ).fetchall()
    return [dict(row) for row in rows]


def get_ticket(connection, ticket_id):
    row = connection.execute(
        "SELECT ticket_id AS id, subject, description, category, priority, "
        "reporter_username, reporter_name AS name, reporter_email AS email, department, "
        "status, assigned_to AS pic, resolution, created_at AS createdAt, updated_at AS updatedAt "
        "FROM helpdesk_tickets WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()
    if not row:
        return None
    ticket = dict(row)
    ticket["comments"] = [
        dict(item)
        for item in connection.execute(
            "SELECT author_username AS author, body, created_at AS createdAt "
            "FROM helpdesk_ticket_comments WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
    ]
    ticket["timeline"] = [
        dict(item)
        for item in connection.execute(
            "SELECT actor_username AS actor, event_type AS type, details, "
            "occurred_at AS at FROM helpdesk_ticket_events "
            "WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
    ]
    for event in ticket["timeline"]:
        event["details"] = json.loads(event["details"])
    return ticket


def update_ticket(connection, ticket_id, changes, actor, now):
    current = connection.execute(
        "SELECT status, assigned_to, resolution FROM helpdesk_tickets WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()
    if not current:
        return False
    updated = {
        "status": changes.get("status", current["status"]),
        "assigned_to": changes.get("pic", current["assigned_to"]),
        "resolution": changes.get("resolution", current["resolution"]),
    }
    connection.execute(
        "UPDATE helpdesk_tickets SET status = ?, assigned_to = ?, resolution = ?, "
        "updated_at = ? WHERE ticket_id = ?",
        (updated["status"], updated["assigned_to"], updated["resolution"], now, ticket_id),
    )
    if any(updated[key] != current[key] for key in updated):
        add_event(connection, ticket_id, actor["username"], "updated", updated, now)
    if changes.get("comment"):
        add_comment(connection, ticket_id, actor["username"], changes["comment"], now)
    connection.commit()
    return True


def add_comment(connection, ticket_id, username, body, now):
    connection.execute(
        "INSERT INTO helpdesk_ticket_comments "
        "(ticket_id, author_username, body, created_at) VALUES (?, ?, ?, ?)",
        (ticket_id, username, body, now),
    )
    add_event(
        connection, ticket_id, username, "commented", {"comment": body}, now
    )


def add_event(connection, ticket_id, username, event_type, details, now):
    connection.execute(
        "INSERT INTO helpdesk_ticket_events "
        "(ticket_id, actor_username, event_type, details, occurred_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ticket_id, username, event_type, json.dumps(details), now),
    )


def dashboard_summary(connection):
    rows = connection.execute(
        "SELECT status, COUNT(*) AS total FROM helpdesk_tickets GROUP BY status"
    ).fetchall()
    counts = {row["status"]: row["total"] for row in rows}
    return {
        "total": sum(counts.values()),
        "byStatus": counts,
        "byCategory": [
            dict(row)
            for row in connection.execute(
                "SELECT category, COUNT(*) AS total FROM helpdesk_tickets "
                "GROUP BY category ORDER BY total DESC, category"
            ).fetchall()
        ],
    }
