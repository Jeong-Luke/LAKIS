"""Real authenticated loopback download responses; no production user data."""
from email.message import Message
from http.server import ThreadingHTTPServer
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))
import serve_ui


class MobileImageDownload(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lakis-mobile-download-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "output"
        self.root.mkdir()
        self.name = "한글 이미지.png"
        self.payload = b"\x89PNG\r\n\x1a\noriginal-image-metadata-bytes"
        (self.root / self.name).write_bytes(self.payload)
        p = patch.object(serve_ui, "_history_roots", return_value=[("configured", self.root)])
        p.start(); self.addCleanup(p.stop)
        p = patch.object(serve_ui, "LINK_SESSION", "download-test-session")
        p.start(); self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), serve_ui.LinkHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path, authenticated=True):
        headers = {"Cookie": "lakis_link=download-test-session"} if authenticated else {}
        return urlopen(Request(self.base + path, headers=headers), timeout=5)

    def test_original_bytes_and_unicode_filename_are_downloaded(self):
        with self.get("/api/history-image?id=" + quote(self.name) + "&download=1") as response:
            self.assertEqual(self.payload, response.read())
            self.assertEqual("image/png", response.headers.get_content_type())
            self.assertEqual("attachment; filename*=UTF-8''" + quote(self.name, safe=""),
                             response.headers["Content-Disposition"])

    def test_normal_image_display_remains_inline(self):
        with self.get("/api/history-image?id=" + quote(self.name)) as response:
            self.assertEqual(self.payload, response.read())
            self.assertIsNone(response.headers["Content-Disposition"])

    def test_download_keeps_link_authentication(self):
        with self.get("/api/history-image?id=" + quote(self.name) + "&download=1", False) as response:
            self.assertEqual("text/html", response.headers.get_content_type())
            self.assertIsNone(response.headers["Content-Disposition"])
            self.assertNotIn(self.payload, response.read())

    def test_download_cannot_escape_output_root(self):
        (self.root.parent / "outside.png").write_bytes(b"private")
        with self.assertRaises(HTTPError) as rejected:
            self.get("/api/history-image?id=../outside.png&download=1")
        self.assertEqual(404, rejected.exception.code)

    def test_comfy_proxy_download_preserves_original_bytes(self):
        upstream = io.BytesIO(self.payload)
        upstream.headers = Message()
        upstream.headers["Content-Type"] = "image/png"
        with patch.object(serve_ui, "urlopen", return_value=upstream) as fetch:
            with self.get("/api/comfy-view?filename=final.png&type=output&download=1") as response:
                self.assertEqual(self.payload, response.read())
                self.assertEqual("attachment; filename*=UTF-8''final.png",
                                 response.headers["Content-Disposition"])
        self.assertNotIn("download=", fetch.call_args.args[0].full_url)


if __name__ == "__main__":
    unittest.main()
