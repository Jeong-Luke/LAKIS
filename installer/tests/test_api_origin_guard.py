import sys
import threading
import unittest
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "src" / "external_ui"
sys.path.insert(0, str(UI_ROOT))

import serve_ui  # noqa: E402


class ApiOriginGuardTests(unittest.TestCase):
    @staticmethod
    def request(host="127.0.0.1:8766", origin=None, fetch_site=None):
        handler = object.__new__(serve_ui.Handler)
        handler.server = SimpleNamespace(server_port=8766)
        headers = Message()
        if host is not None:
            headers["Host"] = host
        if origin is not None:
            headers["Origin"] = origin
        if fetch_site is not None:
            headers["Sec-Fetch-Site"] = fetch_site
        handler.headers = headers
        return handler

    def test_same_origin_and_non_browser_loopback_requests_are_allowed(self):
        self.assertTrue(self.request(origin="http://127.0.0.1:8766")._api_request_allowed())
        self.assertTrue(self.request(host="localhost:8766", origin="http://localhost:8766")._api_request_allowed())
        self.assertTrue(self.request()._api_request_allowed())

    def test_cross_origin_browser_requests_are_rejected(self):
        self.assertFalse(self.request(origin="https://example.com")._api_request_allowed())
        self.assertFalse(self.request(origin="http://127.0.0.1:9999")._api_request_allowed())
        self.assertFalse(self.request(fetch_site="cross-site")._api_request_allowed())

    def test_unapproved_host_is_rejected(self):
        self.assertFalse(self.request(host="attacker.example:8766")._api_request_allowed())
        self.assertFalse(self.request(host=None)._api_request_allowed())

    def test_wildcard_cors_header_is_not_present(self):
        source = (UI_ROOT / "serve_ui.py").read_text(encoding="utf-8")
        self.assertNotIn('Access-Control-Allow-Origin", "*', source)

    def test_link_handler_uses_authenticated_session_instead_of_loopback_host(self):
        previous = serve_ui.LINK_SESSION
        serve_ui.LINK_SESSION = "test-session"
        try:
            request = object.__new__(serve_ui.LinkHandler)
            request.headers = Message()
            request.headers["Host"] = "100.64.0.10:8767"
            request.headers["Cookie"] = "lakis_link=test-session"
            self.assertTrue(request._api_request_allowed())
            request.headers.replace_header("Cookie", "lakis_link=wrong")
            self.assertFalse(request._api_request_allowed())
        finally:
            serve_ui.LINK_SESSION = previous

    @staticmethod
    def serve_once(handler_type):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_desktop_http_api_allows_local_and_rejects_foreign_origin(self):
        server, thread = self.serve_once(serve_ui.Handler)
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/inpaint-model-notice", timeout=5) as response:
                self.assertEqual(response.status, 200)
            request = Request(
                base + "/api/inpaint-model-notice",
                headers={"Origin": "https://example.com"},
            )
            with self.assertRaises(HTTPError) as rejected:
                urlopen(request, timeout=5)
            self.assertEqual(rejected.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_link_http_api_accepts_valid_session_cookie(self):
        previous = serve_ui.LINK_SESSION
        serve_ui.LINK_SESSION = "test-session"
        server, thread = self.serve_once(serve_ui.LinkHandler)
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            request = Request(
                base + "/api/inpaint-model-notice",
                headers={"Cookie": "lakis_link=test-session"},
            )
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            serve_ui.LINK_SESSION = previous


if __name__ == "__main__":
    unittest.main(verbosity=2)
