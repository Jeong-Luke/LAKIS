"""Regression tests for per-launch LAKIS external-UI isolation."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPOSITORY_ROOT / "src" / "external_ui" / "launch_lakis.py"
SPEC = importlib.util.spec_from_file_location("lakis_isolation_launcher", LAUNCHER_PATH)
assert SPEC is not None and SPEC.loader is not None
launch_lakis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launch_lakis)


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    @staticmethod
    def poll() -> None:
        return None


class IdentityServer:
    def __init__(self, token: str, installation_id: str) -> None:
        self.payload = {
            "ok": True,
            "product": "LAKIS",
            "protocol": 1,
            "installation_id": installation_id,
            "session_token": token,
            "pid": os.getpid(),
        }
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/api/launcher-identity":
                    self.send_error(404)
                    return
                body = json.dumps(owner.payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class InstallationIsolationTests(unittest.TestCase):
    def test_identity_requires_install_token_protocol_and_pid(self) -> None:
        token = "a" * 64
        valid = {
            "product": "LAKIS",
            "protocol": 1,
            "installation_id": launch_lakis.INSTALLATION_ID,
            "session_token": token,
            "pid": 31415,
        }
        self.assertTrue(launch_lakis.bridge_identity_matches(valid, token, 31415))
        for key, wrong in (
            ("product", "OTHER"),
            ("protocol", 2),
            ("installation_id", "another-install"),
            ("session_token", "b" * 64),
            ("pid", 27182),
        ):
            changed = dict(valid)
            changed[key] = wrong
            self.assertFalse(launch_lakis.bridge_identity_matches(changed, token, 31415))

    def test_ready_handshake_selects_only_the_current_launch(self) -> None:
        stale_token = "c" * 64
        current_token = "d" * 64
        stale = IdentityServer(stale_token, "another-install")
        current = IdentityServer(current_token, launch_lakis.INSTALLATION_ID)
        try:
            self.assertNotEqual(stale.port, current.port)
            self.assertFalse(
                launch_lakis.bridge_identity_matches(
                    stale.payload, current_token, os.getpid()
                )
            )
            with tempfile.TemporaryDirectory(prefix="lakis-isolation-") as temporary:
                ready_path = Path(temporary) / "ready.json"
                ready_path.write_text(
                    json.dumps({**current.payload, "port": current.port}),
                    encoding="utf-8",
                )
                selected = launch_lakis.wait_ui_bridge_ready(
                    ready_path,
                    FakeProcess(os.getpid()),
                    current_token,
                    timeout=3,
                )
            self.assertEqual(selected, f"http://127.0.0.1:{current.port}/")
        finally:
            current.close()
            stale.close()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InstallationIsolationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("INSTALLATION_ISOLATION_OK tests=2")
    raise SystemExit(0 if result.wasSuccessful() else 1)
