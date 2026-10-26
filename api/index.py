from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from hris_server import HRISHandler


VERCEL_ROUTE_PARAMETER = "__vercel_route"


def routed_request_path(path):
    parsed = urlsplit(path)
    route = None
    forwarded_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == VERCEL_ROUTE_PARAMETER and route is None:
            route = value
        elif key != VERCEL_ROUTE_PARAMETER:
            forwarded_query.append((key, value))

    if route is None or not route:
        return path

    api_path = "/api/" + route.lstrip("/")
    query = urlencode(forwarded_query)
    return urlunsplit(("", "", api_path, query, ""))


class handler(HRISHandler):
    def _restore_api_path(self):
        self.path = routed_request_path(self.path)

    def do_GET(self):
        self._restore_api_path()
        super().do_GET()

    def do_POST(self):
        self._restore_api_path()
        super().do_POST()

    def do_PUT(self):
        self._restore_api_path()
        super().do_PUT()

    def do_DELETE(self):
        self._restore_api_path()
        super().do_DELETE()
