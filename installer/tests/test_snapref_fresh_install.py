"""Disposable fresh-install fixtures; no network, runtime launch or desktop input."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from installer.tests import test_application_release as release
import install_snapref_experiment as official


VERSION = "8.1.3.2"
HELPER = "ComfyUI/LAKIS/install_snapref.py"
NODE = "ComfyUI/custom_nodes/snapref"
MODEL = f"ComfyUI/models/loras/{official.WEIGHT_NAME}"


class SnapRefFreshInstallTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="lakis-fresh-snapref-")))
        self.weight = b"fixture weight"
        self.expected_hash = hashlib.sha256(self.weight).hexdigest()
        self.publisher = {official.WEIGHT_URL: self.weight}
        self.node_files = {}
        sources, notices = {}, {}
        for name, (source, _) in official.SOURCE_FILES.items():
            data = f"fixture source: {source}\n".encode()
            self.node_files[name] = data
            self.publisher[f"https://raw.githubusercontent.com/ArcAnima/SnapRef/{official.SOURCE_REVISION}/{source}"] = data
            sources[name] = (source, hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest())
        for name, (source, _) in official.WEIGHT_NOTICES.items():
            data = f"fixture publisher terms: {source}\n".encode()
            self.node_files[name] = data
            self.publisher[f"https://huggingface.co/0ppxnhximxr/snapref-v2a/raw/{official.WEIGHT_REVISION}/{source}"] = data
            notices[name] = (source, hashlib.sha256(data).hexdigest())

        # Supply the real publisher reader and verifier, but with pins for tiny
        # responses. The helper bytes themselves are pinned by the app manifest.
        helper = Path(official.__file__).read_bytes() + (
            f"\nSOURCE_FILES = {sources!r}\nWEIGHT_NOTICES = {notices!r}\n"
            f"WEIGHT_SIZE = {len(self.weight)}\nWEIGHT_SHA256 = {self.expected_hash!r}\n"
        ).encode()
        self.fixture = release.ApplicationReleaseTests()
        self.baseline, self.manifest, assets, self.cache, _ = self.fixture.fixture(
            self.root, VERSION, "preserve-v1", extra_payload={HELPER: helper})

        engine, transition = release.install, release.transition
        self.enterContext(self.fixture.asset_download(assets))
        self.enterContext(mock.patch.object(engine, "prepare_bundle", return_value=self.baseline))
        self.enterContext(mock.patch.object(engine, "prepare_default_data", side_effect=self.defaults))
        self.enterContext(mock.patch.object(engine, "ensure_visual_cpp_runtime"))
        self.enterContext(mock.patch.object(engine, "ensure_webview2_runtime"))
        self.enterContext(mock.patch.object(transition, "assert_idle"))
        self.enterContext(mock.patch.object(transition, "check_runtime"))
        opener = mock.Mock()
        opener.open.side_effect = lambda url, **_: io.BytesIO(self.publisher[url])
        self.requests = opener.open
        self.enterContext(mock.patch("urllib.request.build_opener", return_value=opener))
        self.output = self.enterContext(mock.patch("sys.stdout", io.StringIO()))

    @staticmethod
    def defaults(candidate, manifest, cache, method, include_animesharp):
        seed = candidate.parent / "defaults"
        release.put(seed, ".lakis/install-method.txt", method.encode())
        release.put(seed, "ComfyUI/user/default/workflows/my.json", b"fixture workflow")
        return seed

    def assert_provisioned(self, target, method):
        payload = release.snapshot(target)
        self.assertEqual(payload["VERSION"], VERSION.encode())
        self.assertEqual(payload[MODEL], self.weight)
        self.assertEqual(payload[".lakis/install-method.txt"], method.encode())
        self.assertEqual(payload["ComfyUI/user/default/workflows/my.json"], b"fixture workflow")
        for name, data in self.node_files.items():
            self.assertEqual(payload[f"{NODE}/{name}"], data)
        self.assertFalse(any("snapref-use-consent" in name for name in payload))

    def test_gui_and_cmd_share_automatic_install_and_reuse_verified_weight(self):
        gui = self.root / "gui-target"
        result = release.install.install(self.manifest, gui, self.cache, "fresh", "gui")
        self.assertEqual(result["status"], "complete")
        self.assert_provisioned(gui, "gui")
        self.assertEqual(
            {call.args[0] for call in self.requests.call_args_list}, set(self.publisher))
        self.assertIn("[SnapRef] 공식 가중치 다운로드", self.output.getvalue())

        self.requests.reset_mock()
        cmd = release.cmd_tests.module
        manifest_path = release.put(self.root, "installer.json", json.dumps(self.manifest).encode())
        portable = self.root / "bootstrap"
        release.put(portable, "python_embeded/python.exe", b"bootstrap identity")
        target = self.root / "cmd-target"
        with mock.patch.object(cmd, "create_desktop_shortcut", return_value=self.root / "test.lnk"):
            cmd.install(manifest_path, portable, target, self.cache, dry_run=False)
        self.assert_provisioned(target, "cmd")
        self.assertEqual(
            {call.args[0] for call in self.requests.call_args_list},
            self.publisher.keys() - {official.WEIGHT_URL})
        self.assertIn("[SnapRef] 검증된 가중치 재사용", self.output.getvalue())

    def test_bad_cache_and_bad_publisher_weight_do_not_promote_target(self):
        cached = release.install.cache_path(self.cache, official.WEIGHT_NAME, self.expected_hash)
        bad = b"x" * len(self.weight)
        cached.write_bytes(bad)
        self.publisher[official.WEIGHT_URL] = bad
        target = self.root / "empty-target"
        target.mkdir()
        with self.assertRaisesRegex(ValueError, "size/SHA-256 verification failed"):
            release.install.install(self.manifest, target, self.cache, "fresh", "gui")
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(cached.read_bytes(), bad)
        self.assertEqual(list(self.cache.glob(".lakis-snapref-*")), [])
        self.publisher[official.WEIGHT_URL] = self.weight
        release.install.install(self.manifest, target, self.cache, "fresh", "gui")
        self.assertEqual(cached.read_bytes(), self.weight)
        self.assert_provisioned(target, "gui")

    def test_existing_target_is_rejected_before_download_and_repair_keeps_data(self):
        target = self.fixture.existing(self.root, VERSION, edited=True)
        before = release.snapshot(target)
        with self.assertRaisesRegex(ValueError, "fresh target is not empty"):
            release.install.install(self.manifest, target, self.cache, "fresh", "gui")
        self.assertEqual(release.snapshot(target), before)
        original_data = release.transition._data_snapshot(target)
        with mock.patch.object(release.install, "prepare_required_models", return_value=None):
            result = release.install.install(self.manifest, target, self.cache, "repair", "gui")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(release.transition._data_snapshot(target), original_data)
        self.requests.assert_not_called()

    def test_tampered_helper_is_not_executed(self):
        candidate = release.install.prepare_candidate(self.manifest, self.cache)
        release.put(candidate, HELPER, b"raise AssertionError('tampered helper ran')")
        with self.assertRaisesRegex(ValueError, "SnapRef helper integrity mismatch"):
            release.install.prepare_fresh_snapref(
                candidate, self.root / "seed", self.cache,
                self.manifest["application_release"]["manifest"]["sha256"])
        self.requests.assert_not_called()

    def test_setup_detects_composed_release_for_existing_options_dialog(self):
        probe = r'''
using System;
internal static class PinProbe {
    private static int Main(string[] args) {
        if (SafeInstaller.FreshIncludesSnapRef() != (args[1] == "yes")) return 10;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");
        return 0;
    }
}
'''
        reader = release.setup_tests.SetupSourcePinTests()
        kwargs = {"runtime_version": self.manifest["version"]}
        reader.run_probe(probe, ["yes"], manifest=self.manifest, **kwargs)
        del self.manifest["application_release"]
        reader.run_probe(probe, ["no"], manifest=self.manifest, **kwargs)


if __name__ == "__main__":
    unittest.main()
