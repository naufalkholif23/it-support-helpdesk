import io
import unittest

from backend.app.api.responses import (
    HttpUtilitiesMixin,
    format_integrity_message,
    json_bytes,
    parse_cookie_header,
    read_json_request,
)
from backend.app.modules.auth import service as auth_service
from backend.app.modules.auth import session as auth_session
from hris_server import HRISHandler
from http.server import SimpleHTTPRequestHandler


class RecordingBase:
    def __init__(self):
        self.headers = []
        self.response_status = None
        self.wfile = io.BytesIO()
        self.base_end_headers_called = False

    def send_header(self, name, value):
        self.headers.append((name, value))

    def send_response(self, status):
        self.response_status = status

    def end_headers(self):
        self.base_end_headers_called = True


class RecordingHandler(HttpUtilitiesMixin, RecordingBase):
    def __init__(self):
        RecordingBase.__init__(self)


class HttpUtilityTests(unittest.TestCase):
    def test_handler_uses_http_mixin_before_http_server_base(self):
        handler_mro = HRISHandler.__mro__
        self.assertLess(
            handler_mro.index(HttpUtilitiesMixin),
            handler_mro.index(SimpleHTTPRequestHandler),
        )
        self.assertIs(HRISHandler.end_headers, HttpUtilitiesMixin.end_headers)
        self.assertIs(HRISHandler.send_json, HttpUtilitiesMixin.send_json)
        self.assertIs(HRISHandler.read_json_body, HttpUtilitiesMixin.read_json_body)
        self.assertIs(HRISHandler.cookie_value, HttpUtilitiesMixin.cookie_value)
        self.assertIs(HRISHandler.integrity_message, HttpUtilitiesMixin.integrity_message)
        self.assertIs(HRISHandler.redirect, HttpUtilitiesMixin.redirect)

    def test_json_response_preserves_utf8_body_status_and_headers(self):
        handler = RecordingHandler()
        payload = {"message": "Suryanesia – Employee Hub"}

        handler.send_json(207, payload)

        body = handler.wfile.getvalue()
        headers = dict(handler.headers)
        self.assertEqual(handler.response_status, 207)
        self.assertEqual(body, json_bytes(payload))
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Content-Length"], str(len(body)))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "same-origin")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(handler.base_end_headers_called)
        self.assertEqual(auth_service.json_bytes, json_bytes)
        self.assertEqual(auth_session.json_bytes, json_bytes)

    def test_redirect_preserves_status_destination_and_empty_body_length(self):
        handler = RecordingHandler()

        handler.redirect("/employee-hub#home")

        headers = dict(handler.headers)
        self.assertEqual(handler.response_status, 302)
        self.assertEqual(headers["Location"], "/employee-hub#home")
        self.assertEqual(headers["Content-Length"], "0")
        self.assertEqual(handler.wfile.getvalue(), b"")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(handler.base_end_headers_called)

    def test_request_body_parser_accepts_json_and_rejects_invalid_lengths_or_data(self):
        self.assertEqual(
            read_json_request(io.BytesIO(b'{"ok":1}'), {"Content-Length": "8"}),
            {"ok": 1},
        )
        invalid_requests = (
            (b"", {"Content-Length": "invalid"}, "Invalid content length."),
            (b"", {"Content-Length": "0"}, "between 1 and 16384 bytes"),
            (b"x" * 16385, {"Content-Length": "16385"}, "between 1 and 16384 bytes"),
            (b"{", {"Content-Length": "1"}, "valid JSON"),
            (b"\xff", {"Content-Length": "1"}, "valid JSON"),
        )
        for body, headers, message in invalid_requests:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    read_json_request(io.BytesIO(body), headers)

    def test_cookie_and_integrity_message_helpers(self):
        self.assertEqual(parse_cookie_header("", "hris_session"), "")
        self.assertEqual(
            parse_cookie_header("other=value; hris_session=token=value", "hris_session"),
            "token=value",
        )
        self.assertEqual(
            format_integrity_message("UNIQUE constraint failed: employees.email"),
            "Email is already assigned to another employee.",
        )
        self.assertEqual(
            format_integrity_message("duplicate employee_id"),
            "Employee ID already exists.",
        )
        self.assertEqual(
            format_integrity_message("unrecognized conflict"),
            "The record conflicts with an existing record.",
        )


if __name__ == "__main__":
    unittest.main()
