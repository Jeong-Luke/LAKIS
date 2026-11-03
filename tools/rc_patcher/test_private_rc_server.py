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
        import os

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = {
                "schema": 1, "product": "LAKIS", "version": "8.0.2",
                "files": [{"path": "LAKIS.exe", "size": 13},
                          {"path": "VERSION", "size": 5}], "retired": ["old.txt"],
            }
            layout_bytes = (json.dumps(layout) + "\n").encode()
            pack = root / "LAKIS_RepairPack.zip"
            with zipfile.ZipFile(pack, "w") as archive:
                archive.writestr("LAKIS.exe", b"candidate-exe")
                archive.writestr("VERSION", b"8.0.2")
            pack_bytes = pack.read_bytes()
            (root / "release-layout.json").write_bytes(layout_bytes)
            record = {
                "version": "8.0.2",
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
                self.assertRegex(base, r"\Ahttp://127\.0\.0\.1:[0-9]+\Z")
                self.assertEqual(base + "/update-latest.json", ready["LAKIS_RC_MANIFEST_URL"])
                self.assertEqual(layout_bytes, urlopen(base + "/release-layout.json").read())
                self.assertEqual(pack_bytes, urlopen(base + "/LAKIS_RepairPack.zip").read())
                manifest_bytes = urlopen(ready["LAKIS_RC_MANIFEST_URL"]).read()
                manifest = json.loads(manifest_bytes)
                self.assertEqual(2, manifest["schema"])
                self.assertEqual("file-patch", manifest["kind"])
                self.assertEqual("8.0.2", manifest["version"])
                self.assertEqual("8.0.0", manifest["minimum_version"])
                self.assertEqual("8.0.0", manifest["minimum_updater_version"])
                self.assertEqual(["old.txt"], manifest["delete"])
                self.assertEqual(["LAKIS.exe"], [entry["path"] for entry in manifest["files"]])
                item = manifest["files"][0]
                self.assertEqual(base + "/files/LAKIS.exe", item["url"])
                data = urlopen(item["url"]).read()
                self.assertEqual(b"candidate-exe", data)
                self.assertEqual(item["sha256"], hashlib.sha256(data).hexdigest().upper())

                manifest_path = root / "served-manifest.json"
                manifest_path.write_bytes(manifest_bytes)
                probe = root / "ProtocolProbe.cs"
                probe.write_text(
                    'using System;\nusing System.IO;\n'
                    'class ProtocolProbe {\n'
                    '  static void Main(string[] args) {\n'
                    '    foreach (string current in new[] { "8.0.0", "8.0.1" }) {\n'
                    '      var manifest = UpdateProtocol.Read(File.ReadAllText(args[0]));\n'
                    '      UpdateProtocol.ValidateForInstallation(manifest, current);\n'
                    '      Console.WriteLine("ACCEPTED " + current + " -> " + manifest.version);\n'
                    '    }\n'
                    '  }\n'
                    '}\n', encoding="utf-8",
                )
                executable = root / "ProtocolProbe.exe"
                compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
                compiled = subprocess.run(
                    [str(compiler), "/nologo", "/target:exe", "/out:" + str(executable),
                     "/reference:System.Web.Extensions.dll",
                     str(ROOT / "installer/UpdateProtocol.cs"), str(probe)],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
                accepted = subprocess.run(
                    [str(executable), str(manifest_path)],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
                self.assertEqual(
                    ["ACCEPTED 8.0.0 -> 8.0.2", "ACCEPTED 8.0.1 -> 8.0.2"],
                    accepted.stdout.splitlines(),
                )
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stdout.close()
                process.stderr.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
