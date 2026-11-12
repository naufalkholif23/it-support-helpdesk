import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from .demo import demo_mode_enabled, demo_session_secret
from .permissions import is_demo_user, require_non_demo_user, require_role
from .repository import roles_for_user


SESSION_HOURS = 8
DEMO_SESSION_HOURS = 8
DEMO_SESSION_COOKIE = "hris_demo_session"


from ...api.responses import json_bytes


class SessionHandlerMixin:
    def start_demo_session(self):
        issued_at = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        payload = issued_at + "." + nonce
        secret = demo_session_secret()
        signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        csrf_token = hmac.new(
            secret, ("csrf:" + payload).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        token = payload + "." + signature
        self.send_response(200)
        self.send_header(
            "Set-Cookie",
            "{}={}; HttpOnly; SameSite=Strict; Path=/; Max-Age={}{}".format(
                DEMO_SESSION_COOKIE,
                token,
                DEMO_SESSION_HOURS * 60 * 60,
                "; Secure" if self.secure_cookie_attribute() else "",
            ),
        )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        body = json_bytes({
            "authenticated": True,
            "demoMode": True,
            "user": {"username": "demo.viewer", "role": "demo_viewer"},
            "csrfToken": csrf_token,
        })
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def logout(self):
        user = self.require_user()
        self.require_csrf()
        if is_demo_user(user):
            self.send_response(200)
            self.send_header(
                "Set-Cookie",
                "{}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{}".format(
                    DEMO_SESSION_COOKIE,
                    "; Secure" if self.secure_cookie_attribute() else "",
                ),
            )
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            body = json_bytes({"authenticated": False, "demoMode": True})
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        token = self.cookie_value("hris_session")
        with self.database_lock:
            connection = self.database_connection()
            try:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
                )
                connection.commit()
            finally:
                connection.close()
        self.send_response(200)
        self.send_header(
            "Set-Cookie",
            "hris_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{}".format(
                "; Secure" if self.secure_cookie_attribute() else ""
            ),
        )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json_bytes({"authenticated": False}))

    def current_user(self):
        if demo_mode_enabled():
            token = self.cookie_value(DEMO_SESSION_COOKIE)
            if token:
                secret = demo_session_secret()
                parts = token.split(".")
                if len(parts) == 3 and parts[0].isdigit() and parts[1]:
                    payload = parts[0] + "." + parts[1]
                    signature = hmac.new(
                        secret, payload.encode("utf-8"), hashlib.sha256
                    ).hexdigest()
                    issued_at = int(parts[0])
                    now = int(time.time())
                    if (
                        hmac.compare_digest(parts[2], signature)
                        and issued_at <= now + 60
                        and now - issued_at <= DEMO_SESSION_HOURS * 60 * 60
                    ):
                        csrf_token = hmac.new(
                            secret, ("csrf:" + payload).encode("utf-8"), hashlib.sha256
                        ).hexdigest()
                        return {
                            "username": "demo.viewer",
                            "role": "demo_viewer",
                            "csrfToken": csrf_token,
                        }
        token = self.cookie_value("hris_session")
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.database_lock:
            connection = self.database_connection()
            try:
                row = connection.execute(
                    "SELECT users.username, users.role, sessions.csrf_token, sessions.expires_at "
                    "FROM sessions JOIN users ON users.username = sessions.username "
                    "WHERE sessions.token_hash = ?",
                    (token_hash,),
                ).fetchone()
                if row and row["expires_at"] > datetime.now(timezone.utc).isoformat():
                    return {
                        "username": row["username"],
                        "role": row["role"],
                        "roles": roles_for_user(
                            connection, row["username"], row["role"]
                        ),
                        "csrfToken": row["csrf_token"],
                    }
                if row:
                    connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                    connection.commit()
                    self.expired_session = True
                return None
            finally:
                connection.close()

    def require_user(self):
        user = self.current_user()
        if not user:
            raise LookupError("Sign in to access employee records.")
        return user

    def require_role(self, user, allowed_roles):
        require_role(user, allowed_roles)

    def require_non_demo_user(self, user):
        require_non_demo_user(user)

    def require_csrf(self):
        user = self.current_user()
        supplied = self.headers.get("X-CSRF-Token", "")
        if not user or not hmac.compare_digest(supplied, user["csrfToken"]):
            raise PermissionError("CSRF validation failed.")
