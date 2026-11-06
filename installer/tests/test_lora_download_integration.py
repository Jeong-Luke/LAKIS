"""Exercise the bundled downloader with a local, non-inference LoRA fixture."""

import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lora_manager as lm
from test_moss_mode import schema, state
import moss_mode
import workflow_bridge as bridge


HEADER = json.dumps({"__metadata__": {"fixture": "download-path-only"}}).encode("utf-8")
FIXTURE = struct.pack("<Q", len(HEADER)) + HEADER
DIGEST = hashlib.sha256(FIXTURE).hexdigest()


def download_worker(root, engine, url, source):
    root = Path(root)
    loras = root / "models" / "loras"
    pool = lm.ManagerPool(root, [loras])
    settings = pool.prepare_profile(engine)
    os.environ.update(lm.manager_environment(settings))
    upstream = runpy.run_path(source)
    from py.services import download_manager
    from py.services.downloader import get_downloader
    from py.services.lora_scanner import LoraScanner

    lm.scope_scanner(LoraScanner, engine, [loras])
    filename = f"{engine}-download-fixture.safetensors"
    version = {
        "id": 92001 if engine == "anima" else 92002,
        "modelId": 91001 if engine == "anima" else 91002,
        "name": "Local test fixture",
        "baseModel": "Anima" if engine == "anima" else "MOSS",
        "model": {"id": 91001, "type": "LORA", "name": "Local fixture", "tags": []},
        "files": [{
            "id": 93001, "name": filename, "type": "Model", "primary": True,
            "sizeKB": len(FIXTURE) / 1024, "downloadUrl": url,
            "hashes": {"SHA256": DIGEST},
        }],
        "images": [], "trainedWords": [],
    }
    provider = Mock()
    provider.get_model_version = AsyncMock(return_value=version)

    async def run():
        manager = download_manager.DownloadManager()
        try:
            with patch.object(download_manager, "get_default_metadata_provider",
                              AsyncMock(return_value=provider)):
                result = await manager._execute_original_download(
                    None, None, None, "", None, True,
                )
            assert result.get("success"), result
            matches = list((loras / engine).rglob(filename))
            assert len(matches) == 1, matches
            downloaded = matches[0]
            assert downloaded.read_bytes() == FIXTURE
            relative = downloaded.relative_to(loras).as_posix()

            scanner = await manager._get_lora_scanner()
            cache = await scanner.get_cached_data(force_refresh=True, rebuild_cache=True)
            assert any(Path(item["file_path"]).resolve() == downloaded.resolve()
                       for item in cache.raw_data), cache.raw_data
            assert all(lm.file_matches_engine(item["file_path"], engine, [loras])
                       for item in cache.raw_data)

            info = schema()
            names = [path.relative_to(loras).as_posix() for path in loras.rglob("*.safetensors")]
            for node in ("LoraLoader", "LoraLoaderModelOnly"):
                info[node]["input"]["required"]["lora_name"][0] = names
            selected = [{"name": relative, "enabled": True, "strength": 0.7}]
            with patch.object(bridge, "_comfy_object_info", return_value=info):
                assert relative in bridge.lora_inventory(engine)["options"]
                other = "moss" if engine == "anima" else "anima"
                assert relative not in bridge.lora_inventory(other)["options"]
                if engine == "moss":
                    value = state()
                    value["loras"] = selected
                    graph, _ = moss_mode.build_prompt(value, info, Path("fixture-output"), 2**53 - 1)
                    moss_mode.validate_models(graph, info)
                    assert any(node.get("inputs", {}).get("lora_name") == relative
                               for node in graph.values())
                else:
                    graph = {"1925": {"inputs": {"profile_index": 1, "profile_data": "{}"}}}
                    bridge._inject_loras(graph, selected)
                    rows = json.loads(graph["1925"]["inputs"]["loras"])
                    assert rows[0]["name"] == relative and rows[0]["on"]
            print(json.dumps({"engine": engine, "downloaded": relative,
                              "sha256": DIGEST, "listed": True, "request_applied": True}))
        finally:
            await (await get_downloader()).close()
            await upstream["StandaloneLoraManager"]._cleanup(None)
            manager._archive_executor.shutdown(wait=True)

    asyncio.run(run())


@unittest.skipUnless(os.environ.get("LAKIS_LORA_MANAGER_TEST_SOURCE"), "Set the bundled standalone.py path for isolated integration")
class DownloadIntegrationTests(unittest.TestCase):
    def test_default_downloads_reach_the_correct_library_and_generation_request(self):
        class Publisher(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(FIXTURE)))
                self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                self.wfile.write(FIXTURE)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Publisher)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="lakis-lora-download-") as directory:
                url = f"http://127.0.0.1:{server.server_port}/fixture.safetensors"
                for engine in lm.ENGINES:
                    result = subprocess.run(
                        [sys.executable, "-s", str(Path(__file__).resolve()), "--worker",
                         directory, engine, url, os.environ["LAKIS_LORA_MANAGER_TEST_SOURCE"]],
                        capture_output=True, text=True, encoding="utf-8",
                        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                        timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout[-6000:] + result.stderr[-6000:])
                    receipts = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"engine":')]
                    self.assertEqual(len(receipts), 1)
                    receipt = receipts[0]
                    relative = Path(receipt.pop("downloaded"))
                    self.assertFalse(relative.is_absolute())
                    self.assertEqual(relative.parts[0], engine)
                    self.assertNotIn("..", relative.parts)
                    self.assertEqual(relative.name, f"{engine}-download-fixture.safetensors")
                    self.assertEqual(receipt, {
                        "engine": engine,
                        "sha256": DIGEST, "listed": True, "request_applied": True,
                    })
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        download_worker(*sys.argv[2:])
    else:
        unittest.main()
