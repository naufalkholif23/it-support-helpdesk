import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from .demo import demo_mode_enabled
from .password import hash_password
from .repository import roles_for_user
from .session import SESSION_HOURS, DEMO_SESSION_COOKIE
from .validators import validate_login_identifier


from ...api.responses import json_bytes


class AuthServiceMixin:
    def login(self, payload):
        identifier = payload.get("email") if isinstance(payload, dict) else None
        password = payload.get("password") if isinstance(payload, dict) else None
        identifier_type, identifier = validate_login_identifier(identifier)
        if not isinstance(password, str) or not password:
            raise ValueError("Email and password are required.")
        column = "email" if identifier_type == "email" else "username"
        with self.database_lock:
            connection = self.database_connection()
            try:
                row = connection.execute(
                    "SELECT username, role, password_salt, password_hash "
                    "FROM users WHERE LOWER({}) = ?".format(column),
                    (identifier,),
                ).fetchone()
                roles = (
                    roles_for_user(connection, row["username"], row["role"])
                    if row
                    else []
                )
            finally:
                connection.close()
        if not row:
            self.send_json(401, {"error": "Invalid email or password."})
            return
        _, candidate_hash = hash_password(password, bytes.fromhex(row["password_salt"]))
        if not hmac.compare_digest(candidate_hash, row["password_hash"]):
            self.send_json(401, {"error": "Invalid email or password."})
            return

        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
        with self.database_lock:
            connection = self.database_connection()
            try:
                connection.execute(
                    "INSERT INTO sessions (token_hash, username, csrf_token, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(), row["username"], csrf_token, expires_at),
                )
                connection.commit()
            finally:
                connection.close()
        self.send_response(200)
        self.send_header(
            "Set-Cookie",
            "hris_session={}; HttpOnly; SameSite=Strict; Path=/; Max-Age={}{}".format(
                token,
                SESSION_HOURS * 60 * 60,
                "; Secure" if self.secure_cookie_attribute() else "",
            ),
        )
        if demo_mode_enabled():
            self.send_header(
                "Set-Cookie",
                "{}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{}".format(
                    DEMO_SESSION_COOKIE,
                    "; Secure" if self.secure_cookie_attribute() else "",
                ),
            )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json_bytes({
            "authenticated": True,
            "user": {
                "username": row["username"],
                "role": row["role"],
                "roles": roles,
            },
            "csrfToken": csrf_token,
        }))
