import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.request import urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).with_name("serve_private_rc.py")


class PrivateRcServerTests(unittest.TestCase):
    def test_serves_exact_assets_and_verified_manifest_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = {
                "schema": 1, "product": "LAKIS", "version": "7.5.0",
                "files": [{"path": "LAKIS.exe", "size": 13}], "retired": ["old.txt"],
            }
            layout_bytes = (json.dumps(layout) + "\n").encode()
            pack = root / "LAKIS_RepairPack.zip"
            with zipfile.ZipFile(pack, "w") as archive:
                archive.writestr("LAKIS.exe", b"candidate-exe")
            pack_bytes = pack.read_bytes()
            (root / "release-layout.json").write_bytes(layout_bytes)
            record = {
                "version": "7.5.0",
                "files": [
                    {"name": "release-layout.json", "sha256": hashlib.sha256(layout_bytes).hexdigest()},
                    {"name": "LAKIS_RepairPack.zip", "sha256": hashlib.sha256(pack_bytes).hexdigest()},
                ],
            }
            (root / "private-rc-build.json").write_text(json.dumps(record), encoding="utf-8")
            process = subprocess.Popen(
                [sys.executable, str(SERVER), str(root)], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                ready = json.loads(process.stdout.readline())
                self.assertEqual("READY", ready["status"])
                base = ready["LAKIS_RC_RELEASE_BASE_URL"]
                self.assertEqual(layout_bytes, urlopen(base + "/release-layout.json").read())
                self.assertEqual(pack_bytes, urlopen(base + "/LAKIS_RepairPack.zip").read())
                manifest = json.loads(urlopen(ready["LAKIS_RC_MANIFEST_URL"]).read())
                self.assertEqual("7.5.0", manifest["version"])
                self.assertEqual(["old.txt"], manifest["delete"])
                item = manifest["files"][0]
                data = urlopen(item["url"]).read()
                self.assertEqual(b"candidate-exe", data)
                self.assertEqual(item["sha256"], hashlib.sha256(data).hexdigest().upper())
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stdout.close()
                process.stderr.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
