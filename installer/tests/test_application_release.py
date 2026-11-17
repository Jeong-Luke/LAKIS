"""Offline component-pair composition and recovery behavior, never a live install."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer"))
import application_release as app
import runtime_install as install
import runtime_manifest as contract
import runtime_transition as transition
from installer.tests import test_cmd_installer as cmd_tests
from installer.tests import test_setup_source_pin as setup_tests
from installer.tests import test_preview_upgrade as preview_tests


def put(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class ApplicationReleaseTests(unittest.TestCase):
    def setUp(self):
        prerequisite = mock.patch.object(install, "ensure_visual_cpp_runtime")
        prerequisite.start()
        self.addCleanup(prerequisite.stop)

    def fixture(self, root, version="8.1.1", editable_template_policy=None):
        baseline, installer = cmd_tests.CmdInstallerTests()._runtime_candidate(root, version="8.1.0")
        editable = contract.EDITABLE_TEMPLATE_FILES[1]
        retired = "ComfyUI/LAKIS/external_ui/obsolete.py"
        put(baseline, editable, b'{"pristine":"baseline"}')
        put(baseline, retired, b"retired managed code")
        inventory = contract.create_manifest(baseline, "8.1.0", "1" * 40, {
            "comfyui_version": contract.COMFY_VERSION, "comfyui_commit": contract.COMFY_COMMIT})
        baseline_manifest = put(baseline, contract.MANIFEST_NAME, json.dumps(inventory).encode())
        installer["runtime_bundle"]["manifest_sha256"] = install.sha256(baseline_manifest)
        installer["runtime_bundle"]["files"] = len(inventory["files"])
        pristine = root / "reference"
        shutil.copytree(baseline, pristine)
        (pristine / retired).unlink()
        changed = {
            "VERSION": version.encode(),
            editable: ('{"pristine":"' + version + ' shipped default"}').encode(),
            "ComfyUI/LAKIS/external_ui/app.py": b"trusted application code",
        }
        for relative, contents in changed.items():
            put(pristine, relative, contents)
        revision = ("2" if version == "8.1.1" else "3") * 40
        target_inventory = contract.create_manifest(pristine, version, revision, {
            "comfyui_version": contract.COMFY_VERSION, "comfyui_commit": contract.COMFY_COMMIT})
        manifest_path = put(root, "assets/" + contract.MANIFEST_NAME, json.dumps(target_inventory).encode())
        layout = {
            "schema": 1, "product": "LAKIS", "version": version,
            "files": [{"path": key, "size": len(value)} for key, value in changed.items()],
            "retired": [retired],
        }
        if editable_template_policy is not None:
            layout["editable_template_policy"] = editable_template_policy
        layout_path = put(root, "assets/release-layout.json", json.dumps(layout).encode())
        archive = root / "assets/LAKIS_RepairPack.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("ComfyUI/empty/", b"")
            for relative, contents in changed.items():
                bundle.writestr(relative, contents)
        release = {
            "schema": 1, "product": "LAKIS", "version": version, "source_revision": revision,
            "runtime_version": "8.1.0", "runtime_sha256": installer["runtime_bundle"]["sha256"],
            "runtime_manifest_sha256": installer["runtime_bundle"]["manifest_sha256"],
        }
        assets = {"payload": archive, "layout": layout_path, "manifest": manifest_path}
        for name, path in assets.items():
            release[name] = {"name": path.name, "bytes": path.stat().st_size,
                             "sha256": install.sha256(path),
                             "url": f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{version}/{path.name}"}
        installer["application_release"] = release
        cache = root / "cache"
        cache.mkdir()
        return baseline, installer, assets, cache, editable

    def asset_download(self, assets):
        def fetch(url, destination, digest, size, **kwargs):
            return next(path for path in assets.values() if path.name == url.rsplit("/", 1)[1])
        return mock.patch.object(app, "download", side_effect=fetch)

    def existing(self, root, version="8.1.1", *, edited=False):
        target = root / "installed"
        put(target, "VERSION", version.encode())
        put(target, "ComfyUI/LAKIS/STOP_AUTOMATION", b"original identity")
        put(target, "LAKIS.exe", b"original launcher")
        for name in contract.PROTECTED_DIRECTORIES:
            put(target, name + "/user.bin", b"original user data: " + name.encode())
        for name in (*contract.PROTECTED_FILES, *contract.EDITABLE_TEMPLATE_FILES):
            put(target, name, b'{"unknown_setting":"preserve","user_edit":true}')
        if not edited:
            put(target, contract.EDITABLE_TEMPLATE_FILES[1],
                ('{"pristine":"' + version + ' shipped default"}').encode())
        return target

    def test_composes_811_on_810_without_mutating_baseline_and_verifies_exact_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest, assets, cache, editable = self.fixture(root)
            before = snapshot(baseline)
            with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline):
                candidate = install.prepare_candidate(manifest, cache)
            self.assertEqual(snapshot(baseline), before)
            self.assertEqual((candidate / "VERSION").read_bytes(), b"8.1.1")
            self.assertFalse((candidate / "ComfyUI/LAKIS/external_ui/obsolete.py").exists())
            self.assertEqual((candidate / editable).read_bytes(), b'{"pristine":"8.1.1 shipped default"}')
            contract.verify_runtime(candidate, manifest["application_release"]["manifest"]["sha256"], "8.1.1")
            self.assertEqual((candidate / contract.MANIFEST_NAME).read_bytes(), assets["manifest"].read_bytes())
            put(candidate, "ComfyUI/main.py", b"tampered")
            with self.assertRaisesRegex(ValueError, "runtime file mismatch"):
                contract.verify_runtime(candidate, manifest["application_release"]["manifest"]["sha256"], "8.1.1")

    def test_capable_812_repair_and_update_preserve_edited_data_and_pristine_defaults(self):
        for mode, current in (("repair", "8.1.2"), ("update", "8.1.1")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, editable = self.fixture(root, "8.1.2", "preserve-v1")
                target = self.existing(root, current, edited=True)
                original = transition._data_snapshot(target)
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline), \
                     mock.patch.object(install, "prepare_required_models", return_value=None), \
                     mock.patch.object(transition, "check_runtime"), mock.patch.object(transition, "assert_idle"):
                    result = install.install(manifest, target, cache, mode, "gui")
                self.assertEqual(result["status"], "complete")
                self.assertEqual(result["preserved_editable_templates"], sorted(contract.EDITABLE_TEMPLATE_FILES))
                self.assertEqual(transition._data_snapshot(target), original)
                self.assertEqual(transition._data_snapshot(Path(result["backup"])), original)
                self.assertEqual(result["editable_template_policy"], "preserve-v1")
                self.assertEqual((target / "VERSION").read_bytes(), b"8.1.2")
                digest = manifest["application_release"]["manifest"]["sha256"]
                contract.verify_runtime(target, digest, "8.1.2", allow_user_data=True)
                with self.assertRaisesRegex(ValueError, "runtime file mismatch|user data"):
                    contract.verify_runtime(target, digest, "8.1.2")
                put(target, "ComfyUI/LAKIS/external_ui/other.json", b"user-looking code data")
                with self.assertRaisesRegex(ValueError, "unlisted runtime file"):
                    contract.verify_runtime(target, digest, "8.1.2", allow_user_data=True)

    def test_legacy_811_matching_default_preserves_extra_known_templates_and_all_data(self):
        for prepared in (False, True):
            with self.subTest(prepared=prepared), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, editable = self.fixture(root)
                target = self.existing(root)
                before = transition._data_snapshot(target)
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline):
                    candidate = install.prepare_candidate(manifest, cache) if prepared else None
                    with mock.patch.object(install, "prepare_required_models", return_value=None), \
                         mock.patch.object(transition, "check_runtime"), mock.patch.object(transition, "assert_idle"):
                        result = install.install(manifest, target, cache, "repair", "gui", prepared_root=candidate)
                self.assertEqual(result["status"], "complete")
                self.assertEqual(result["editable_template_policy"], "legacy-immutable")
                self.assertEqual(transition._data_snapshot(target), before)
                self.assertEqual(transition._data_snapshot(Path(result["backup"])), before)
                self.assertEqual((target / editable).read_bytes(), b'{"pristine":"8.1.1 shipped default"}')
                self.assertEqual((target / contract.EDITABLE_TEMPLATE_FILES[0]).read_bytes(),
                                 b'{"unknown_setting":"preserve","user_edit":true}')

    def test_legacy_811_conflicting_edit_rejects_before_downloads_or_journal_changes(self):
        for prepared in (False, True):
            with self.subTest(prepared=prepared), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, editable = self.fixture(root)
                target = self.existing(root, edited=True)
                candidate = None
                if prepared:
                    with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline):
                        candidate = install.prepare_candidate(manifest, cache)
                before = snapshot(target)
                journal = transition._journal_path(target)
                transition._write_journal(target, {
                    "schema": 1, "target": str(target), "version": "8.1.0",
                    "manifest_sha256": "A" * 64, "had_original": True,
                    "workspace": f".{target.name}-previous", "phase": "complete",
                })
                previous_journal = journal.read_bytes()
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle") as baseline_download, \
                     mock.patch.object(install, "prepare_required_models") as models, \
                     self.assertRaisesRegex(ValueError, "EDITABLE_TEMPLATE_COMPATIBILITY_REQUIRED"):
                    install.install(manifest, target, cache, "repair", "gui", prepared_root=candidate)
                baseline_download.assert_not_called()
                models.assert_not_called()
                self.assertEqual(snapshot(target), before)
                self.assertEqual(journal.read_bytes(), previous_journal)

    def test_prepare_only_legacy_conflict_checks_small_contracts_before_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest, assets, cache, _ = self.fixture(root)
            target = self.existing(root, edited=True)
            before = snapshot(target)
            with self.asset_download(assets), mock.patch.object(install, "prepare_bundle") as baseline_download, \
                 self.assertRaisesRegex(ValueError, "EDITABLE_TEMPLATE_COMPATIBILITY_REQUIRED"):
                install.prepare_candidate(manifest, cache, target=target, mode="repair")
            baseline_download.assert_not_called()
            self.assertEqual(snapshot(target), before)
            self.assertFalse(transition._journal_path(target).exists())

    def test_legacy_compatibility_is_rechecked_inside_transaction_before_journal_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest, assets, cache, editable = self.fixture(root)
            target = self.existing(root)
            changed = {}
            def concurrent_user_edit(_target, _python):
                put(target, editable, b"concurrent user edit after preflight")
                changed.update(snapshot(target))
            with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline), \
                 mock.patch.object(install, "prepare_required_models", return_value=None), \
                 mock.patch.object(transition, "assert_idle", side_effect=concurrent_user_edit), \
                 mock.patch.object(transition, "check_runtime") as health, \
                 self.assertRaisesRegex(ValueError, "EDITABLE_TEMPLATE_COMPATIBILITY_REQUIRED"):
                install.install(manifest, target, cache, "repair", "gui")
            health.assert_not_called()
            self.assertEqual(snapshot(target), changed)
            self.assertFalse(transition._journal_path(target).exists())

    def test_capable_prepared_root_preserves_edits_but_still_requires_pristine_candidate(self):
        for tampered in (False, True):
            with self.subTest(tampered=tampered), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, editable = self.fixture(root, "8.1.2", "preserve-v1")
                target = self.existing(root, "8.1.1", edited=True)
                before = transition._data_snapshot(target)
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline):
                    candidate = install.prepare_candidate(manifest, cache)
                if tampered:
                    put(candidate, editable, b"unverified candidate template")
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle") as baseline_download, \
                     mock.patch.object(install, "prepare_required_models", return_value=None), \
                     mock.patch.object(transition, "check_runtime"), mock.patch.object(transition, "assert_idle"):
                    if tampered:
                        with self.assertRaisesRegex(ValueError, "runtime file mismatch"):
                            install.install(manifest, target, cache, "update", "gui", prepared_root=candidate)
                        self.assertFalse(transition._journal_path(target).exists())
                    else:
                        result = install.install(manifest, target, cache, "update", "gui", prepared_root=candidate)
                        self.assertEqual(result["editable_template_policy"], "preserve-v1")
                        self.assertEqual((target / "VERSION").read_bytes(), b"8.1.2")
                baseline_download.assert_not_called()
                self.assertEqual(transition._data_snapshot(target), before)

    def test_unknown_layout_policy_fails_before_baseline_or_target_writes(self):
        for policy in ("preserve-v2", True, None):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, manifest, assets, cache, _ = self.fixture(root)
                target = self.existing(root)
                layout = json.loads(assets["layout"].read_bytes())
                layout["editable_template_policy"] = policy
                assets["layout"].write_bytes(json.dumps(layout).encode())
                manifest["application_release"]["layout"].update(
                    bytes=assets["layout"].stat().st_size, sha256=install.sha256(assets["layout"]))
                before = snapshot(target)
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle") as baseline_download, \
                     self.assertRaisesRegex(ValueError, "unsupported application editable-template policy"):
                    install.prepare_candidate(manifest, cache, target=target, mode="repair")
                baseline_download.assert_not_called()
                self.assertEqual(snapshot(target), before)
                self.assertFalse(transition._journal_path(target).exists())

    def test_bad_descriptor_and_asset_contracts_fail_before_target_writes(self):
        cases = (("schema", True), ("version", "8.1.2"), ("source_revision", ""), ("runtime_version", "8.1.1"),
                 ("runtime_sha256", "F" * 64), ("runtime_manifest_sha256", "E" * 64),
                 ("manifest", None), ("payload", {"name": "../escape"}))
        for key, value in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, _ = self.fixture(root)
                target = self.existing(root)
                before = snapshot(target)
                manifest["application_release"][key] = value
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline), \
                     self.assertRaises(ValueError):
                    install.install(manifest, target, cache, "repair", "gui")
                self.assertEqual(snapshot(target), before)
                self.assertFalse(transition._journal_path(target).exists())

    def test_wrong_asset_hash_size_and_untrusted_complete_manifest_fail_without_activation(self):
        for field, change in (("payload", "hash"), ("layout", "size"), ("manifest", "revision"),
                              ("manifest", "runtime"), ("manifest", "omitted")):
            with self.subTest(field=field, change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, _ = self.fixture(root)
                target = self.existing(root)
                before = snapshot(target)
                if change == "hash":
                    manifest["application_release"][field]["sha256"] = "F" * 64
                elif change == "size":
                    manifest["application_release"][field]["bytes"] += 1
                else:
                    metadata = json.loads(assets[field].read_bytes())
                    if change == "revision":
                        metadata["source_revision"] = "3" * 40
                    elif change == "runtime":
                        metadata["runtime"]["comfyui_commit"] = "0" * 40
                    else:
                        metadata["files"] = [row for row in metadata["files"] if row["path"] != "LAKIS.exe"]
                    assets[field].write_bytes(json.dumps(metadata).encode())
                    manifest["application_release"][field].update(
                        bytes=assets[field].stat().st_size, sha256=install.sha256(assets[field]))
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline), \
                     self.assertRaises(ValueError):
                    install.install(manifest, target, cache, "repair", "gui")
                self.assertEqual(snapshot(target), before)
                self.assertFalse(transition._journal_path(target).exists())

    def test_archive_paths_hashes_and_retired_data_conflicts_fail_before_target_writes(self):
        for problem in ("traversal", "link", "extra", "wrong-size", "wrong-bytes", "retire-data"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, _ = self.fixture(root)
                target = self.existing(root)
                before = snapshot(target)
                if problem == "retire-data":
                    layout = json.loads(assets["layout"].read_bytes())
                    layout["retired"] = ["ComfyUI"]
                    assets["layout"].write_bytes(json.dumps(layout).encode())
                    field = "layout"
                else:
                    with zipfile.ZipFile(assets["payload"]) as bundle:
                        contents = [(row.filename, bundle.read(row)) for row in bundle.infolist()]
                    with zipfile.ZipFile(assets["payload"], "w") as bundle:
                        for name, data in contents:
                            if name == "VERSION" and problem == "wrong-size": data += b"x"
                            if name == "VERSION" and problem == "wrong-bytes": data = b"8.1.2"
                            bundle.writestr(name, data)
                        if problem == "link":
                            link = zipfile.ZipInfo("link")
                            link.external_attr = (0o120777 << 16)
                            bundle.writestr(link, b"outside")
                        elif problem in {"extra", "traversal"}:
                            bundle.writestr("../escape" if problem == "traversal" else "arbitrary.py", b"x")
                    field = "payload"
                manifest["application_release"][field].update(
                    bytes=assets[field].stat().st_size, sha256=install.sha256(assets[field]))
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline), \
                     self.assertRaises((ValueError, RuntimeError)):
                    install.install(manifest, target, cache, "repair", "gui")
                self.assertEqual(snapshot(target), before)
                self.assertFalse(transition._journal_path(target).exists())

    def test_bad_pristine_editable_default_and_other_managed_bytes_are_not_exempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest, assets, cache, editable = self.fixture(root)
            put(baseline, editable, b"tampered default")
            with self.asset_download(assets), self.assertRaisesRegex(ValueError, "runtime file mismatch"):
                app.compose(baseline, manifest["runtime_bundle"], manifest["application_release"], cache)

    def test_rollback_and_user_data_added_during_recovery_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest, assets, cache, _ = self.fixture(root, "8.1.2", "preserve-v1")
            target = self.existing(root, "8.1.2", edited=True)
            original = snapshot(target)
            def fail_final(path):
                if path == target:
                    put(path, "ComfyUI/output/added-during-recovery.png", b"new user image")
                    raise RuntimeError("final health fixture failure")
            with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline), \
                 mock.patch.object(install, "prepare_required_models", return_value=None), \
                 mock.patch.object(transition, "check_runtime", side_effect=fail_final), \
                 mock.patch.object(transition, "assert_idle"), self.assertRaisesRegex(RuntimeError, "final health"):
                install.install(manifest, target, cache, "repair", "gui")
            self.assertEqual(snapshot(target), original)
            state = transition._load_journal(target)
            self.assertEqual(state["phase"], "rolled-back")
            failed = target.parent / state["workspace"] / "failed"
            self.assertEqual((failed / "ComfyUI/output/added-during-recovery.png").read_bytes(), b"new user image")

    def test_build_accepts_independently_pinned_historical_app_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest, _, _, _ = self.fixture(root)
            args = preview_tests.InstallerManifestBuildTests().build_inputs(root / "build")
            # The descriptor binds the build's runtime, not the fixture's runtime.
            bundle = json.loads(args[1].read_bytes())
            release = manifest["application_release"]
            release.update(runtime_sha256=bundle["sha256"], runtime_manifest_sha256=bundle["manifest_sha256"])
            descriptor = put(root, "application-release.json", json.dumps(release).encode())
            import build_runtime_installer_manifest
            build_runtime_installer_manifest.build(*args, application_release=descriptor)
            built = json.loads(args[3].read_bytes())
            self.assertEqual(built["version"], "8.1.0")
            self.assertEqual(built["application_release"]["version"], "8.1.1")
            self.assertEqual(built["application_release"]["source_revision"], "2" * 40)

    def test_wrong_existing_version_missing_descriptor_and_unidentified_targets_are_unchanged(self):
        for problem in ("newer", "same-update", "wrong-repair", "missing-descriptor", "unidentified"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                baseline, manifest, assets, cache, _ = self.fixture(root)
                current = {"newer": "8.1.2", "same-update": "8.1.1", "wrong-repair": "8.1.0"}.get(problem, "8.1.1")
                target = self.existing(root, current)
                mode = "update" if problem == "same-update" else "repair"
                if problem == "missing-descriptor":
                    del manifest["application_release"]
                if problem == "unidentified":
                    (target / "VERSION").unlink()
                before = snapshot(target)
                with self.asset_download(assets), mock.patch.object(install, "prepare_bundle", return_value=baseline), \
                     mock.patch.object(install, "prepare_required_models", return_value=None), \
                     self.assertRaises(ValueError):
                    install.install(manifest, target, cache, mode, "gui")
                self.assertEqual(snapshot(target), before)
                self.assertFalse(transition._journal_path(target).exists())

    def test_target_and_asset_symlinks_are_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest, assets, cache, _ = self.fixture(root)
            target = self.existing(root)
            link = root / "linked-installation"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest("Windows symlink permission unavailable: " + str(error))
            before = snapshot(target)
            with self.assertRaisesRegex(RuntimeError, "unsafe reparse path"):
                install.install(manifest, link, cache, "repair", "gui")
            self.assertEqual(snapshot(target), before)
            original_asset = assets["manifest"]
            asset_link = original_asset.parent / "linked-manifest.json"
            asset_link.symlink_to(original_asset)
            assets["manifest"] = asset_link
            before_assets = snapshot(root)
            with mock.patch.object(app, "download", return_value=asset_link), \
                    self.assertRaisesRegex(RuntimeError, "unsafe reparse path"):
                app.compose(baseline, manifest["runtime_bundle"], manifest["application_release"], cache)
            self.assertEqual(snapshot(root), before_assets)

    def test_boolean_application_schema_is_rejected_by_build_and_cli_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest, _, cache, _ = self.fixture(root)
            target = self.existing(root)
            manifest["application_release"]["schema"] = True
            manifest_path = put(root, "installer.json", json.dumps(manifest).encode())
            before = snapshot(target)
            result = subprocess.run([
                sys.executable, "-B", str(ROOT / "installer/runtime_install.py"),
                "--manifest", str(manifest_path), "--target", str(target), "--cache", str(cache),
                "--mode", "repair", "--method", "gui",
            ], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stderr.decode(errors="replace"))
            self.assertIn(b"application release identity mismatch", result.stderr)
            self.assertEqual(snapshot(target), before)
            self.assertEqual(list(cache.iterdir()), [])
            self.assertFalse(transition._journal_path(target).exists())

            args = preview_tests.InstallerManifestBuildTests().build_inputs(root / "build")
            bundle = json.loads(args[1].read_bytes())
            release = manifest["application_release"]
            release.update(runtime_sha256=bundle["sha256"], runtime_manifest_sha256=bundle["manifest_sha256"])
            descriptor = put(root, "boolean-schema-release.json", json.dumps(release).encode())
            import build_runtime_installer_manifest
            with self.assertRaisesRegex(ValueError, "application release identity mismatch"):
                build_runtime_installer_manifest.build(*args, application_release=descriptor)
            self.assertFalse(args[3].exists())


ROUTING_PROBE = r'''
using System;
using System.IO;
using System.Reflection;
internal static class PinProbe {
    private static int Main(string[] args) {
        try {
            string json=File.ReadAllText(args[1]);
            string version=RuntimeBundleInstaller.InstallerTargetVersion(json);
            if(args[0]=="mode") Console.WriteLine(SafeInstaller.ExistingInstallationMode(args[2]));
            else if(args[0]=="flatten") RuntimeBundleInstaller.CreateUpdateManifest(json);
            else Console.WriteLine(version);
            return 0;
        } catch(Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
'''


class SetupApplicationRoutingTests(unittest.TestCase):
    def test_setup_confirmation_uses_validated_app_target_and_legacy_baseline(self):
        probe = r'''
using System;
using System.IO;
internal static class PinProbe {
    private static int Main(string[] args) {
        string root=args[0], expectedVersion=args[1];
        Directory.CreateDirectory(Path.Combine(root,"ComfyUI","LAKIS"));
        File.WriteAllText(Path.Combine(root,"VERSION"),"8.0.0");
        File.WriteAllText(Path.Combine(root,"ComfyUI","LAKIS","STOP_AUTOMATION"),"identity");
        if(SafeInstaller.ExistingInstallationMode(root)!="update")return 10;
        string expected="이 설치를 LAKIS "+expectedVersion+"으로 업데이트할까요?\n\n"+root+
            "\n\nMOSS 모델·VAE·CLIP 약 15.5GB를 추가로 받을 수 있습니다.\n기존 모델, 이미지, 워크플로와 설정은 보존됩니다.";
        if(SafeInstaller.UpdateConfirmation(root)!=expected)return 11;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");
        return 0;
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            _, manifest, _, _, _ = ApplicationReleaseTests().fixture(Path(directory))
            reader = setup_tests.SetupSourcePinTests()
            reader.run_probe(probe, ["8.1.1"], manifest=manifest, runtime_version="8.1.0")
            del manifest["application_release"]
            reader.run_probe(probe, ["8.1.0"], manifest=manifest, runtime_version="8.1.0")

    def test_setup_uses_bound_app_target_and_never_flattens_it_to_a_baseline_update(self):
        compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = ApplicationReleaseTests()
            _, manifest, _, _, _ = fixture.fixture(root)
            embedded = put(root, "manifest.json", json.dumps(manifest).encode())
            probe = put(root, "probe.cs", ROUTING_PROBE.encode())
            output = root / "probe.exe"
            result = subprocess.run([str(compiler), "/nologo", "/target:exe", "/main:PinProbe",
                "/out:" + str(output), *["/reference:" + name for name in (
                    "System.Windows.Forms.dll", "System.Drawing.dll", "System.Web.Extensions.dll",
                    "System.IO.Compression.dll", "System.IO.Compression.FileSystem.dll")],
                *[str(ROOT / "installer" / name) for name in ("SplashArtwork.cs", "UpdateProtocol.cs",
                    "RuntimeBundleInstaller.cs")],
                str(setup_tests.SetupSourcePinTests.source_for_runtime(root, "8.1.0")), str(probe),
                "/resource:" + str(embedded) + ",LAKIS.RuntimeInstallManifest"],
                capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
            for current, expected in (("8.1.1", "repair"), ("8.1.0", "update"), ("8.1.2", None)):
                target = fixture.existing(root / current, current)
                before = snapshot(target)
                result = subprocess.run([str(output), "mode", str(embedded), str(target)], capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0 if expected else 1, result.stderr.decode(errors="replace"))
                if expected:
                    self.assertEqual(result.stdout.decode().strip(), expected)
                self.assertEqual(snapshot(target), before)
            result = subprocess.run([str(output), "flatten", str(embedded)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 1)

    def test_setup_reader_accepts_composition_and_rejects_incomplete_or_unbound_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manifest, _, _, _ = ApplicationReleaseTests().fixture(Path(directory))
            reader = setup_tests.SetupSourcePinTests()
            reader.run_probe(setup_tests.MANIFEST_PROBE, ["accept"], manifest=manifest, runtime_version="8.1.0")
            for field in ("source_revision", "runtime_manifest_sha256", "manifest", "layout"):
                bad = copy.deepcopy(manifest)
                del bad["application_release"][field]
                reader.run_probe(setup_tests.MANIFEST_PROBE, ["reject"], manifest=bad, runtime_version="8.1.0")
            bad = copy.deepcopy(manifest)
            bad["application_release"]["schema"] = True
            reader.run_probe(setup_tests.MANIFEST_PROBE, ["reject"], manifest=bad, runtime_version="8.1.0")

    def test_launcher_rejects_retired_user_data_before_emitting_repair_helper(self):
        compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        probe_source = r'''
using System;
using System.Collections;
using System.IO;
using System.Reflection;
using System.Web.Script.Serialization;
internal static class RetiredProbe {
    private static int Main(string[] args) {
        var flags=BindingFlags.NonPublic|BindingFlags.Static;
        var layoutType=typeof(LakisLauncher).GetNestedType("ReleaseLayout",BindingFlags.NonPublic);
        var form=typeof(LakisLauncher).GetNestedType("StartupForm",BindingFlags.NonPublic);
        string json=File.ReadAllText(args[1]);
        var layout=new JavaScriptSerializer().Deserialize(json,layoutType);
        bool safe=args[2]=="safe" || args[2]=="policy-accept";
        object[] readArgs={args[0],null,null,null};
        bool accepted=(bool)form.GetMethod("TryGetReleaseLayout",flags).Invoke(null,readArgs);
        if(accepted!=safe)return 10;
        if(args[2].StartsWith("policy-"))return 0;
        var check=form.GetMethod("FindLayoutProblems",flags);
        if(safe) {
            var installed=(IList)check.Invoke(null,new object[]{args[0],layout,false});
            if(installed.Count!=1 || !installed[0].ToString().Contains("obsolete.py"))return 11;
            var pristine=(IList)check.Invoke(null,new object[]{args[0],layout,true});
            if(pristine.Count!=2)return 12;
        } else {
            foreach(bool pristine in new[]{false,true}) {
                try { check.Invoke(null,new object[]{args[0],layout,pristine}); return 13; }
                catch(TargetInvocationException error) { if(!(error.InnerException is InvalidDataException))throw; }
            }
            object[] scheduleArgs={args[0],layout,json,null};
            if((bool)form.GetMethod("ScheduleAutomaticRepair",flags).Invoke(null,scheduleArgs))return 14;
            if(String.IsNullOrWhiteSpace((string)scheduleArgs[3]))return 15;
        }
        return 0;
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "installed"
            editable = contract.EDITABLE_TEMPLATE_FILES[1]
            for relative in contract.EDITABLE_TEMPLATE_FILES:
                put(target, relative, b"user-edited template must survive")
            for relative in ("models", "user", "input", "output"):
                put(target, f"ComfyUI/{relative}/user.bin", b"protected user bytes")
            put(target, "VERSION", b"8.1.1")
            obsolete = "ComfyUI/LAKIS/external_ui/obsolete.py"
            put(target, obsolete, b"obsolete managed bytes")
            files = [{"path": editable, "size": 7}]
            for index in range(9):
                relative = f"ComfyUI/LAKIS/external_ui/managed{index}.py"
                put(target, relative, b"managed")
                files.append({"path": relative, "size": 7})
            layout_path = root / "layout.json"
            probe = put(root, "probe.cs", probe_source.encode())
            output = root / "probe.exe"
            result = subprocess.run([str(compiler), "/nologo", "/target:exe", "/main:RetiredProbe",
                "/out:" + str(output), *["/reference:" + name for name in (
                    "System.Windows.Forms.dll", "System.Drawing.dll", "System.Web.Extensions.dll",
                    "System.IO.Compression.dll", "System.IO.Compression.FileSystem.dll")],
                *[str(ROOT / "installer" / name) for name in (
                    "SplashArtwork.cs", "UpdateProtocol.cs", "LAKIS_Launcher.cs")], str(probe)],
                capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))

            requests = []
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass
                def do_GET(self):
                    requests.append(self.path.split("?", 1)[0])
                    raw = layout_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            child_environment = os.environ.copy()
            child_environment["LAKIS_RC_RELEASE_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
            private_temp = root / "repair-temp"
            private_temp.mkdir()
            child_environment["TEMP"] = child_environment["TMP"] = str(private_temp)
            cases = [
                *( (relative, False) for relative in contract.EDITABLE_TEMPLATE_FILES ),
                *( (str(Path(relative).parent).replace("\\", "/"), False)
                   for relative in contract.EDITABLE_TEMPLATE_FILES ),
                ("ComfyUI/models", False), ("ComfyUI/user", False),
                ("ComfyUI/input", False), ("ComfyUI/output", False),
                ("ComfyUI", False), ("ComfyUI/./models", False),
                (obsolete, True),
            ]
            before = snapshot(target)
            try:
                for relative, safe in cases:
                    with self.subTest(retired=relative):
                        layout_path.write_bytes(json.dumps({
                            "schema": 1, "product": "LAKIS", "version": "8.1.1",
                            "files": files, "retired": [relative],
                        }).encode())
                        requests.clear()
                        result = subprocess.run([str(output), str(target), str(layout_path),
                            "safe" if safe else "unsafe"], env=child_environment,
                            capture_output=True, timeout=20)
                        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                        self.assertEqual(requests, ["/release-layout.json"])
                        self.assertEqual(snapshot(target), before)
                        self.assertEqual(list(private_temp.iterdir()), [])
                for policy in ("preserve-v1", "preserve-v2", True, None):
                    with self.subTest(policy=policy):
                        layout_path.write_bytes(json.dumps({
                            "schema": 1, "product": "LAKIS", "version": "8.1.1",
                            "editable_template_policy": policy, "files": files, "retired": [obsolete],
                        }).encode())
                        requests.clear()
                        result = subprocess.run([str(output), str(target), str(layout_path),
                            "policy-accept" if policy == "preserve-v1" else "policy-reject"],
                            env=child_environment, capture_output=True, timeout=20)
                        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                        self.assertEqual(requests, ["/release-layout.json"])
                        self.assertEqual(snapshot(target), before)
                        self.assertEqual(list(private_temp.iterdir()), [])
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)

    def test_launcher_checks_pristine_templates_but_preserves_installed_edits(self):
        compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        probe_source = r'''
using System;
using System.Collections;
using System.IO;
using System.Reflection;
using System.Web.Script.Serialization;
internal static class TemplateProbe {
    private static int Main(string[] args) {
        var layoutType=typeof(LakisLauncher).GetNestedType("ReleaseLayout",BindingFlags.NonPublic);
        var form=typeof(LakisLauncher).GetNestedType("StartupForm",BindingFlags.NonPublic);
        var layout=new JavaScriptSerializer().Deserialize(File.ReadAllText(args[1]),layoutType);
        var check=form.GetMethod("FindLayoutProblems",BindingFlags.NonPublic|BindingFlags.Static);
        foreach(bool pristine in new[]{false,true}) {
            var problems=(IList)check.Invoke(null,new object[]{args[0],layout,pristine});
            if(problems.Count!=(pristine ? 1 : 0))return 10;
        }
        File.WriteAllText(Path.Combine(args[0],"immutable.json"),"changed code");
        if(((IList)check.Invoke(null,new object[]{args[0],layout,false})).Count!=1)return 11;
        return 0;
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            editable = contract.EDITABLE_TEMPLATE_FILES[1]
            put(root, editable, b"user-edited workflow, not pristine")
            put(root, "immutable.json", b"code")
            layout = put(root, "layout.json", json.dumps({"files": [
                {"path": editable, "size": 7}, {"path": "immutable.json", "size": 4}], "retired": []}).encode())
            probe = put(root, "probe.cs", probe_source.encode())
            output = root / "probe.exe"
            result = subprocess.run([str(compiler), "/nologo", "/target:exe", "/main:TemplateProbe",
                "/out:" + str(output), *["/reference:" + name for name in (
                    "System.Windows.Forms.dll", "System.Drawing.dll", "System.Web.Extensions.dll",
                    "System.IO.Compression.dll", "System.IO.Compression.FileSystem.dll")],
                *[str(ROOT / "installer" / name) for name in (
                    "SplashArtwork.cs", "UpdateProtocol.cs", "LAKIS_Launcher.cs")], str(probe)],
                capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
            result = subprocess.run([str(output), str(root), str(layout)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
