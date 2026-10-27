import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))

import serve_ui


class GenerationRequestTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="lakis-generation-request-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in (
            ("AUDIT_PATH", self.root / "audit.jsonl"),
            ("UI_STATE_PATH", self.root / "state" / "external_ui_user_state.json"),
            ("USER_WILDCARD_ROOT", self.root / "wildcards"),
            ("BUILTIN_WILDCARD_ROOT", self.root / "built-in"),
        ):
            replacement = patch.object(serve_ui, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        start = patch.object(
            serve_ui.GENERATION_BRIDGE, "start",
            return_value={"ok": True, "request_id": "isolated-no-gpu"},
        )
        self.start = start.start()
        self.addCleanup(start.stop)

    def serve(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), serve_ui.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(stop)
        return server.server_port

    def post(self, port, path, payload=None, content_length=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        headers = {"Content-Type": "application/json"}
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_saved_two_person_scene_over_one_mb_is_accepted_for_generation(self):
        port = self.serve()
        scene = {
            "enabled": True, "toyxyz_enabled": True,
            "pose_data": json.dumps({"version": 1, "people": ["first", "second"]}),
            "toyxyz_render_data": json.dumps({
                "version": 1, "region_painter": {"width": 1024, "height": 1024},
                "image": "a" * 600_000,
            }),
            "toyxyz_paint_data": json.dumps({
                "version": 1, "width": 1024, "height": 1024,
                "layers": [
                    {"id": "first", "visible": True, "prompt": "coat", "mask": "b" * 600_000},
                    {"id": "second", "visible": True, "prompt": "dress", "mask": "c" * 600_000},
                ],
                "base": {"prompt": ""}, "background": {"prompt": "park"},
            }),
        }
        status, saved = self.post(port, "/api/scene-controls", scene)
        self.assertEqual(status, 200)
        self.assertTrue(saved["ok"])
        payload = {
            "scene_controls": saved["state"],
            "generation": {"mode": "detail"},
            "inpaint": {"enabled": False},
        }
        self.assertGreater(len(json.dumps(payload).encode("utf-8")), 1_000_000)
        status, accepted = self.post(port, "/api/generate", payload)
        self.assertEqual(status, 202)
        self.assertTrue(accepted["ok"])
        self.start.assert_called_once_with(payload)

    def test_generation_over_45_mb_is_rejected_before_start(self):
        status, rejected = self.post(
            self.serve(), "/api/generate", content_length=45_000_001,
        )
        self.assertEqual(status, 409)
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error_code"], "LKS-CFG-1003")
        self.start.assert_not_called()

    def test_other_json_requests_keep_the_one_mb_limit(self):
        request = object.__new__(serve_ui.Handler)
        request.headers = {"Content-Length": "1000001"}
        request.rfile = io.BytesIO()
        with self.assertRaisesRegex(ValueError, "body exceeds 1000000 bytes"):
            request._read_json()
        self.assertEqual(request.rfile.tell(), 0)

    def test_scene_prompt_keys_share_seed_selection_and_exclusions_with_global_prompt(self):
        serve_ui.USER_WILDCARD_ROOT.mkdir()
        (serve_ui.USER_WILDCARD_ROOT / "outfit.txt").write_text("coat\ndress\n", encoding="utf-8")
        (serve_ui.USER_WILDCARD_ROOT / "background.txt").write_text("park\n", encoding="utf-8")
        options = {"enabled": True, "seed": 719, "excluded": {"outfit": ["dress"]}}
        global_result = serve_ui.resolve_wildcard_payload({
            **options, "prompt": {"general": "__outfit__"},
        })
        scene_result = serve_ui.resolve_wildcard_payload({
            **options,
            "prompt": {"0": "__outfit__", "1": "__outfit__", "2": "", "3": "__background__"},
        })
        self.assertEqual(global_result["prompt"]["general"], "coat")
        self.assertEqual(scene_result["prompt"], {"0": "coat", "1": "coat", "2": "", "3": "park"})
        self.assertEqual(scene_result["selections"][0], global_result["selections"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
