import copy
import hashlib
import io
import json
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from private_draft_relay import PrivateDraftRelay, range_offset, validate_assets


class PrivateDraftRelayTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"frozen-runtime-part"
        self.part = {
            "name": "runtime.zip.part001", "bytes": len(self.payload),
            "sha256": hashlib.sha256(self.payload).hexdigest().upper(),
        }
        self.bundle = {"parts": [self.part]}
        self.release = {
            "id": 42, "tag_name": "private-test", "draft": True, "published_at": None,
            "assets": [{
                "id": 43, "name": self.part["name"], "state": "uploaded",
                "size": self.part["bytes"], "digest": "sha256:" + self.part["sha256"].lower(),
            }],
        }

    def test_frozen_private_asset_is_accepted(self):
        assets = validate_assets(self.release, self.bundle, "private-test")
        self.assertEqual(assets[self.part["name"]]["id"], 43)

    def test_public_or_different_draft_is_rejected(self):
        for changes in ({"draft": False}, {"published_at": "published"},
                        {"tag_name": "different"}):
            with self.subTest(changes=changes):
                changed = {**self.release, **changes}
                with self.assertRaises(ValueError):
                    validate_assets(changed, self.bundle, "private-test")

    def test_asset_mismatch_is_rejected(self):
        for changes in ({"size": 1}, {"digest": "sha256:" + "0" * 64},
                        {"state": "starter"}, {"name": "different"}):
            changed = copy.deepcopy(self.release)
            changed["assets"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_assets(changed, self.bundle, "private-test")

    def test_duplicate_asset_is_rejected(self):
        changed = copy.deepcopy(self.release)
        changed["assets"].append(copy.deepcopy(changed["assets"][0]))
        with self.assertRaises(ValueError):
            validate_assets(changed, self.bundle, "private-test")

    def test_ranges(self):
        self.assertEqual(range_offset(None, 10), 0)
        self.assertEqual(range_offset("bytes=4-", 10), 4)
        for value in ("bytes=10-", "bytes=-1-", "bytes=0-3", "bytes=1-,3-", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                range_offset(value, 10)

    def exercise_stream(self, offset, payload=None, code=0):
        content = self.payload if payload is None else payload

        class Process:
            def __init__(self, *args, **kwargs):
                self.stdout = io.BytesIO(content)
                self.stderr = io.BytesIO()

            def wait(self, **kwargs):
                return code

            def poll(self):
                return code

        with patch("private_draft_relay.github_json", return_value=self.release):
            relay = PrivateDraftRelay("owner/repo", 42, "private-test", self.bundle)
        worker = threading.Thread(target=relay.server.serve_forever, daemon=True)
        worker.start()
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        request = Request(
            f"http://127.0.0.1:{relay.server.server_port}/{self.part['name']}",
            headers=headers)
        try:
            with patch("private_draft_relay.subprocess.Popen", Process):
                with urlopen(request, timeout=5) as response:
                    body = response.read()
                    status = response.status
                    content_range = response.headers.get("Content-Range")
                relay.server.shutdown()
                relay.server.server_close()
                worker.join()
        finally:
            if worker.is_alive():
                relay.server.shutdown()
                relay.server.server_close()
                worker.join()
        return relay, body, status, content_range

    def test_complete_transfer(self):
        relay, body, status, _ = self.exercise_stream(0)
        self.assertEqual((body, status), (self.payload, 200))
        relay.verify_complete(self.bundle)

    def test_range_returns_only_remaining_bytes(self):
        relay, body, status, content_range = self.exercise_stream(4)
        self.assertEqual((body, status), (self.payload[4:], 206))
        self.assertEqual(content_range, f"bytes 4-{len(self.payload)-1}/{len(self.payload)}")
        self.assertEqual(relay.events[0]["upstream_bytes"], len(self.payload))
        with self.assertRaises(RuntimeError):
            relay.verify_complete(self.bundle)

    def test_invalid_upstream_digest_is_not_a_success(self):
        relay, _, _, _ = self.exercise_stream(0, b"x" * len(self.payload))
        self.assertEqual(relay.events[0]["status"], "failed")
        with self.assertRaises(RuntimeError):
            relay.verify_complete(self.bundle)

    def test_cli_failure_is_not_a_success(self):
        relay, _, _, _ = self.exercise_stream(0, code=1)
        self.assertEqual(relay.events[0]["exit_code"], 1)
        with self.assertRaises(RuntimeError):
            relay.verify_complete(self.bundle)


if __name__ == "__main__":
    unittest.main()
