import json


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def parse_cookie_header(cookie_header, name):
    if not cookie_header:
        return ""
    for part in cookie_header.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == name:
            return value
    return ""


def format_integrity_message(error):
    message = str(error)
    if "employees.email" in message or "idx_employees_email_lower" in message:
        return "Email is already assigned to another employee."
    if (
        "employees.employee_id" in message
        or "employees_pkey" in message
        or "employee_id" in message
    ):
        return "Employee ID already exists."
    return "The record conflicts with an existing record."


def read_json_request(rfile, headers, max_length=16384):
    try:
        length = int(headers.get("Content-Length", "0"))
    except (ValueError, TypeError):
        raise ValueError("Invalid content length.")
    if length < 1 or length > max_length:
        raise ValueError(f"Request body must be between 1 and {max_length} bytes.")
    try:
        return json.loads(rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Request body must contain valid JSON.")


class HttpUtilitiesMixin:
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def redirect(self, destination):
        self.send_response(302)
        self.send_header("Location", destination)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        return read_json_request(self.rfile, self.headers)

    def cookie_value(self, name):
        return parse_cookie_header(self.headers.get("Cookie", ""), name)

    def integrity_message(self, error):
        return format_integrity_message(error)
