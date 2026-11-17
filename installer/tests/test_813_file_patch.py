"""Offline contract tests; set LAKIS_813_BASELINE and LAKIS_813_CANDIDATE for native tests."""
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import time
import unittest
from urllib.parse import unquote, urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_813_file_patch as candidate
from runtime_manifest import validate_runtime_manifest


class CandidateInputTests(unittest.TestCase):
    def test_baseline_hash_gate_rejects_an_altered_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp)
            (baseline / candidate.LAYOUT).write_bytes(b"x" * candidate.BASE_ASSETS[candidate.LAYOUT][0])
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                candidate.read_baseline(baseline)

    def test_rejects_non_release_paths(self):
        for path in ("../VERSION", "ComfyUI/models/weight", ".lakis/marker",
                     "ComfyUI/user/settings.json", "RUNTIME_SHA256SUMS.json",
                     "ComfyUI/LAKIS/external_ui/__pycache__/app.pyc"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                candidate.managed_path(path)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


@contextmanager
def serve(directory, port):
    with ThreadingHTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=directory)) as http:
        worker = Thread(target=http.serve_forever)
        worker.start()
        try:
            yield
        finally:
            http.shutdown()
            worker.join()


@unittest.skipUnless(os.environ.get("LAKIS_813_BASELINE") and os.environ.get("LAKIS_813_CANDIDATE"),
                     "set the pinned baseline and a completed local candidate")
class PublicBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(cls.enterClassContext(tempfile.TemporaryDirectory(prefix="lakis-813-packaging-test-")))
        cls.site = Path(os.environ["LAKIS_813_CANDIDATE"]) / "www"
        cls.baseline = candidate.load_application(candidate.read_baseline(Path(os.environ["LAKIS_813_BASELINE"])))
        cls.patch = json.loads((cls.site / candidate.PATCH).read_bytes())
        cls.layout = json.loads((cls.site / candidate.LAYOUT).read_bytes())
        cls.inventory = json.loads((cls.site / candidate.MANIFEST_NAME).read_bytes())
        with zipfile.ZipFile(cls.site / candidate.PACK) as pack:
            cls.packed = {entry.filename: pack.read(entry) for entry in pack.infolist()}
            if len(cls.packed) != len(pack.infolist()):
                raise ValueError("duplicate repair ZIP entry")
        cls.files = {entry["path"]: entry for entry in cls.patch["files"]}
        cls.port = urlsplit(cls.patch["files"][0]["url"]).port
        cls.enterClassContext(serve(cls.site, cls.port))
        cls.tmp = cls.work / "temp"
        cls.tmp.mkdir()
        cls.env = {**os.environ, "TEMP": str(cls.tmp), "TMP": str(cls.tmp),
                   "LAKIS_RC_RELEASE_BASE_URL": f"http://127.0.0.1:{cls.port}",
                   "LAKIS_RC_MANIFEST_URL": f"http://127.0.0.1:{cls.port}/{candidate.PATCH}"}
        cls.probe = cls.work / "probe.exe"
        subprocess.run([
            str(candidate.compiler()), "/nologo", "/target:exe", f"/out:{cls.probe}",
            f"/win32icon:{candidate.ROOT / candidate.ICON}", "/reference:System.Windows.Forms.dll",
            str(Path(__file__).with_name("FilePatch813NativeProbe.cs")),
        ], check=True, timeout=60)
        cls.stock_launcher = cls.work / "public-launcher.exe"
        cls.stock_launcher.write_bytes(cls.baseline[3]["LAKIS.exe"])
        cls.stock_updater = cls.work / "public-updater.exe"
        cls.stock_updater.write_bytes(cls.baseline[3]["LAKIS_Updater.exe"])

    def run_native(self, executable, *args):
        return subprocess.run([str(executable), *map(str, args)], env=self.env, cwd=self.work,
                              capture_output=True, timeout=30, check=True)

    def materialize(self, name, files):
        root = self.work / name
        for path, data in files.items():
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        return root

    def test_patch_repair_and_inventory_agree_byte_for_byte(self):
        self.assertEqual((2, "file-patch", "8.1.3", "8.1.2", "8.1.0"),
                         tuple(self.patch[key] for key in (
                             "schema", "kind", "version", "minimum_version", "minimum_updater_version")))
        self.assertEqual([], self.patch["delete"])
        self.assertNotIn("runtime_bundle", self.patch)
        self.assertEqual(len(self.files), len(self.patch["files"]))
        self.assertEqual(self.packed[candidate.ALIASES[0]], self.packed[candidate.ALIASES[1]])
        self.assertEqual({path: len(data) for path, data in self.packed.items()},
                         {row["path"]: row["size"] for row in self.layout["files"]})
        self.assertEqual(self.baseline[0]["retired"], self.layout["retired"])
        self.assertEqual("preserve-v1", self.layout["editable_template_policy"])
        expected = dict(self.baseline[2])
        prior = self.baseline[3]
        self.assertEqual(set(self.files) | {"VERSION"},
                         {path for path, data in self.packed.items() if prior.get(path) != data})
        self.assertFalse(prior.keys() - self.packed.keys())
        self.assertEqual(b"8.1.3", self.packed["VERSION"])
        for path, entry in self.files.items():
            url = urlsplit(entry["url"])
            self.assertEqual(("http", "127.0.0.1", self.port), (url.scheme, url.hostname, url.port))
            self.assertEqual(f"/files/{path}", unquote(url.path))
            data = (self.site / "files" / path).read_bytes()
            self.assertEqual(self.packed[path], data)
            self.assertEqual(entry["sha256"], candidate.sha256(data))
        for path, data in self.packed.items():
            expected[path.casefold()] = candidate.row(path, data)
        actual = validate_runtime_manifest(self.inventory, "8.1.3")
        self.assertEqual(expected, actual)
        self.assertEqual(self.baseline[1]["runtime"], self.inventory["runtime"])
        for line in (self.site / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
            sha, relative = line.split("  ", 1)
            self.assertEqual(sha, candidate.sha256((self.site / relative).read_bytes()))

    def test_stock_apply_and_candidate_legacy_finish_for_both_aliases(self):
        for alias in candidate.ALIASES:
            with self.subTest(alias=alias):
                baseline = self.baseline[3]
                # Omitting the desktop host prevents the real shortcut writer
                # from touching the Windows desktop. No UI or Python is started.
                fixture = {path: data for path, data in baseline.items() if path != "LAKIS_Desktop.exe"}
                fixture[alias] = self.probe.read_bytes()
                fixture["ComfyUI/models/keep.txt"] = b"owned by user"
                fixture["ComfyUI/user/workflows/keep.json"] = b"my workflow"
                root = self.materialize(alias + " test install", fixture)
                output = self.run_native(root / alias, "apply", self.stock_updater, root,
                                         self.site / candidate.PATCH)
                pending = Path(os.fsdecode(output.stdout.strip()))
                self.assertEqual(self.tmp, pending.parent)
                self.assertEqual(b"8.1.2", (root / "VERSION").read_bytes())
                self.assertEqual(self.probe.read_bytes(), (root / alias).read_bytes())
                self.assertEqual(self.packed[alias], pending.read_bytes())
                for path in self.files.keys() - {alias}:
                    self.assertEqual(self.packed[path], (root / path).read_bytes())
                # Simulate the legacy PID handoff after the invoking alias has exited.
                self.run_native(pending, "--finish-self-update", root, "8.1.3", 2147483647, "--headless")
                (root / "LAKIS_Desktop.exe").write_bytes(baseline["LAKIS_Desktop.exe"])
                for path, data in self.packed.items():
                    self.assertEqual(data, (root / path).read_bytes(), path)
                for path in ("ComfyUI/models/keep.txt", "ComfyUI/user/workflows/keep.json"):
                    self.assertEqual(fixture[path], (root / path).read_bytes())
                self.assertEqual(b"", self.run_native(
                    self.probe, "check", self.stock_launcher, root).stdout)

    def test_production_launcher_repairs_detectable_damage_and_preserves_user_bytes(self):
        root = self.materialize("repair test install", self.packed)
        check = lambda: self.run_native(self.probe, "check", self.stock_launcher, root).stdout
        self.assertEqual(b"", check())
        changed = next(path for path in self.files if path.endswith(".js"))
        file = root / changed
        data = self.packed[changed]
        # Launcher checks sizes. The offline runtime inventory detects byte
        # changes even when the native size check cannot.
        file.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        self.assertEqual(b"", check())
        inventory_rows = {row["path"]: row for row in self.inventory["files"]}
        self.assertNotEqual(inventory_rows[changed]["sha256"], candidate.sha256(file.read_bytes()))
        file.unlink()
        alias = root / candidate.ALIASES[0]
        alias.write_bytes(b"truncated")
        retired = root / self.layout["retired"][0]
        retired.parent.mkdir(parents=True, exist_ok=True)
        retired.write_bytes(b"obsolete")
        editable = root / "ComfyUI/LAKIS/external_ui/workflows/LAKIS_custom_v8.0_editable.json"
        editable.write_bytes(b"edited workflow")
        user = root / "ComfyUI/user/session.json"
        user.parent.mkdir(parents=True)
        user.write_bytes(b"user state")
        model = root / "ComfyUI/models/keep.txt"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"model sentinel")
        # The real repair script will restart the root's launcher. Keep its
        # size valid but substitute a probe that cannot start the runtime.
        stub = self.probe.read_bytes().ljust(len(self.packed["LAKIS.exe"]), b"\0")
        (root / "LAKIS.exe").write_bytes(stub)
        problems = check()
        for relative in (changed, candidate.ALIASES[0], self.layout["retired"][0]):
            self.assertIn(relative.encode("ascii"), problems)
        self.run_native(self.probe, "repair", self.stock_launcher, root)
        deadline = time.monotonic() + 25
        while not (root / "probe-relaunched").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue((root / "probe-relaunched").is_file(), "repair did not relaunch the probe")
        self.assertFalse(retired.exists())
        self.assertEqual(data, file.read_bytes())
        self.assertEqual(self.packed[candidate.ALIASES[0]], alias.read_bytes())
        self.assertEqual(b"edited workflow", editable.read_bytes())
        self.assertEqual(b"user state", user.read_bytes())
        self.assertEqual(b"model sentinel", model.read_bytes())
        self.assertEqual(b"8.1.3", (root / ".lakis/release-layout-repair.attempt").read_bytes())
        self.assertEqual(b"", check())


if __name__ == "__main__":
    unittest.main()
