"""Filesystem and interrupted-transaction checks; no real installation is used."""
import ctypes
from ctypes import wintypes
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_patch as patcher
import runtime_manifest as contract
import runtime_transition as transition
import lakis_cmd_installer as installer


class RuntimeComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lakis-component-test-")
        self.root = Path(self.temp.name)
        self.target = self.root / "LAKIS"
        self.candidate = self.root / "candidate"
        self.target.mkdir()
        self.candidate.mkdir()
        payload = {name: ("new:" + name).encode() for name in contract.REQUIRED_FILES}
        payload.update({
            "VERSION": b"8.0.0",
            "python_embeded/Lib/site-packages/fixture/new.py": b"new-library",
            "ComfyUI/custom_nodes/was-ns/node.py": b"new-node",
            "ComfyUI/custom_nodes/managed-node/node.py": b"managed-node",
        })
        manifest = {
            "schema": 1, "product": "LAKIS", "version": "8.0.0",
            "source_revision": "8e059898ddb608bd1ee4e8bc9e98de5f2ebc241c",
            "runtime": {"comfyui_version": contract.COMFY_VERSION, "comfyui_commit": contract.COMFY_COMMIT},
            "files": [],
        }
        for relative, data in payload.items():
            file = self.candidate / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
            manifest["files"].append({"path": relative, "size": len(data),
                                      "sha256": hashlib.sha256(data).hexdigest().upper()})
        raw = json.dumps(manifest).encode()
        (self.candidate / contract.MANIFEST_NAME).write_bytes(raw)
        self.manifest_hash = hashlib.sha256(raw).hexdigest().upper()
        old = {
            "VERSION": b"7.5.4", "LAKIS.exe": b"old-launcher",
            "ComfyUI/main.py": b"old-main", "ComfyUI/LAKIS/STOP_AUTOMATION": b"stop",
            "python_embeded/python.exe": b"old-python",
            "python_embeded/Lib/retired.py": b"old-owned-library",
            "ComfyUI/custom_nodes/was-ns/node.py": b"old-node",
            "ComfyUI/custom_nodes/was-ns/styles.json": b'{"user":true}',
            "ComfyUI/custom_nodes/user-added-node/node.py": b"user-node",
            "ComfyUI/models/checkpoints/fixture.bin": b"model-must-not-be-read",
            "ComfyUI/models/loras/fixture.bin": b"lora-must-not-be-read",
            "ComfyUI/input/input.png": b"user-input", "ComfyUI/output/output.png": b"user-output",
            "ComfyUI/user/default/workflows/user.json": b"user-workflow",
            "user-extra.txt": b"unowned-root-file",
        }
        for relative, data in old.items():
            file = self.target / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        self.db = self.target / "ComfyUI/user/comfyui.db"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("create table fixture(value integer)")
            db.execute("insert into fixture values (42)")
        self.original = self.snapshot(self.target)
        self.model = self.target / "ComfyUI/models/checkpoints/fixture.bin"
        self.model_identity = self.model.stat().st_ino
        self.idle = mock.patch.object(patcher, "assert_idle")
        self.health = mock.patch.object(patcher, "check_runtime", return_value={"comfyui_version": "0.42.0"})
        self.idle.start()
        self.health.start()
        self.output = mock.patch("sys.stdout", new=io.StringIO())
        self.output.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.idle.stop)
        self.addCleanup(self.health.stop)
        self.addCleanup(self.output.stop)

    @staticmethod
    def snapshot(root):
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def activate(self):
        return patcher.activate(self.candidate, self.target, self.manifest_hash, "8.0.0")

    def assert_original(self):
        self.assertEqual(self.snapshot(self.target), self.original)
        self.assertEqual(self.model.stat().st_ino, self.model_identity)

    def test_native_license_files_cannot_be_omitted_from_a_runtime(self):
        manifest_path = self.candidate / contract.MANIFEST_NAME
        original = manifest_path.read_bytes()
        for relative in (
            "third_party_licenses/Microsoft-WebView2-SDK-1.0.4191.47-LICENSE.txt",
            "third_party_licenses/NVIDIA-CUDA-13.0.0-EULA.md",
            "third_party_licenses/NVIDIA-cuDNN-9.24.0-EULA.md",
        ):
            with self.subTest(relative=relative):
                document = json.loads(original)
                license_path = self.candidate / relative
                license_bytes = license_path.read_bytes()
                license_path.unlink()
                try:
                    with self.assertRaisesRegex(ValueError, "incomplete runtime"):
                        contract.create_manifest(
                            self.candidate, document["version"],
                            document["source_revision"], document["runtime"],
                        )
                    # A correctly hashed manifest must not be able to remove
                    # a mandatory notice from the runtime's file contract.
                    document["files"] = [
                        row for row in document["files"] if row["path"] != relative
                    ]
                    raw = json.dumps(document).encode()
                    manifest_path.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, "incomplete runtime"):
                        contract.verify_runtime(
                            self.candidate, hashlib.sha256(raw).hexdigest(), "8.0.0"
                        )
                finally:
                    license_path.write_bytes(license_bytes)
                    manifest_path.write_bytes(original)
        self.assert_original()

    def test_component_partition_never_contains_protected_or_generated_paths(self):
        manifest = json.loads((self.candidate / contract.MANIFEST_NAME).read_bytes())
        plan = patcher.component_plan(manifest)
        roots = [group["path"] for group in plan]
        self.assertIn("python_embeded", roots)
        self.assertNotIn("ComfyUI", roots)
        self.assertNotIn("ComfyUI/custom_nodes", roots)
        self.assertNotIn("ComfyUI/custom_nodes/was-ns", roots)
        self.assertEqual(sum(len(group["rows"]) for group in plan), len(manifest["files"]))
        for root in roots:
            for protected in (*contract.PROTECTED_DIRECTORIES, *contract.PROTECTED_FILES, *contract.GENERATED_PATHS):
                self.assertFalse(protected.casefold() == root.casefold() or
                                 protected.casefold().startswith(root.casefold() + "/"))

    def test_success_preserves_locked_model_identity_and_unowned_files(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        handle = create(str(self.model), 0x80000000, 0, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            result = self.activate()
        finally:
            close(handle)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(all(value >= 0 for value in result["timings"].values()))
        self.assertLessEqual(sum(result["timings"].values()), result["elapsed_seconds"])
        self.assertEqual((self.target / "VERSION").read_bytes(), b"8.0.0")
        self.assertEqual(self.model.stat().st_ino, self.model_identity)
        for relative, data in self.original.items():
            if contract.protected_path(relative.replace("\\", "/")) or relative == "user-extra.txt" or "user-added-node" in relative:
                self.assertEqual((self.target / relative).read_bytes(), data, relative)
        self.assertFalse((self.target / "python_embeded/Lib/retired.py").exists())
        state = transition._load_journal(self.target)
        self.assertEqual(state["schema"], 2)
        self.assertTrue(Path(result["backup"]).is_dir())
        with mock.patch.object(transition, "assert_idle"):
            restored = transition.recover(self.target, self.candidate / "python_embeded/python.exe")
        self.assertEqual(restored["status"], "rolled-back")
        self.assert_original()

    def test_bad_candidate_is_rejected_before_original_changes(self):
        (self.candidate / "ComfyUI/main.py").write_bytes(b"tampered")
        with mock.patch.object(patcher, "assert_idle") as idle, \
                mock.patch.object(patcher, "check_runtime") as health:
            with self.assertRaisesRegex(ValueError, "runtime file mismatch"):
                self.activate()
            idle.assert_not_called()
            health.assert_not_called()
        self.assert_original()

    def test_missing_unlisted_and_protected_payloads_never_activate(self):
        selected = self.candidate / "ComfyUI/main.py"
        original = selected.read_bytes()
        cases = (
            (selected, None, "missing runtime files"),
            (self.candidate / "unexpected.py", b"unlisted", "unlisted runtime file"),
            (self.candidate / "ComfyUI/models/foreign.bin", b"user-data", "user data"),
        )
        for path, data, message in cases:
            with self.subTest(message=message):
                if data is None:
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                try:
                    with mock.patch.object(patcher, "assert_idle") as idle:
                        with self.assertRaisesRegex(ValueError, message):
                            self.activate()
                        idle.assert_not_called()
                    self.assert_original()
                finally:
                    if data is None:
                        selected.write_bytes(original)
                    else:
                        path.unlink()

    def test_post_activation_verification_still_restores_tampered_program(self):
        def tamper(root):
            (root / "ComfyUI/main.py").write_bytes(b"changed-after-staging")
        with mock.patch.object(patcher, "check_runtime", side_effect=tamper):
            with self.assertRaisesRegex(ValueError, "runtime file mismatch"):
                self.activate()
        self.assert_original()
        self.assertEqual(transition._load_journal(self.target)["phase"], "rolled-back")

    def test_source_version_must_have_bridge(self):
        (self.target / "VERSION").write_text("7.5.3")
        with self.assertRaisesRegex(ValueError, "7.5.4"):
            self.activate()
        self.assertEqual((self.target / "VERSION").read_text(), "7.5.3")
        self.assertFalse(transition._journal_path(self.target).exists())

    def test_prepare_failure_retains_original_without_reading_user_model(self):
        with mock.patch.object(patcher, "_copy_verified", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.activate()
        self.assert_original()
        self.assertEqual(transition._load_journal(self.target)["phase"], "rolled-back")

    @staticmethod
    def windows_access_error(code):
        error = PermissionError(13, "injected Windows file-access refusal")
        error.winerror = code
        return error

    def test_transient_staging_move_refusal_can_finish_without_changing_user_data(self):
        rename = patcher.os.rename
        attempts = 0

        def temporary_refusal(source, destination):
            nonlocal attempts
            if Path(source).parent.name == "payload" and Path(source).name == "python_embeded":
                attempts += 1
                if attempts == 1:
                    raise self.windows_access_error(5)
            return rename(source, destination)

        with mock.patch.object(patcher.os, "rename", side_effect=temporary_refusal), \
                mock.patch.object(patcher.time, "sleep") as sleep:
            result = self.activate()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(attempts, 2)
        sleep.assert_called_once_with(0.2)
        self.assertEqual(self.model.read_bytes(), b"model-must-not-be-read")
        self.assertEqual(self.model.stat().st_ino, self.model_identity)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("select value from fixture").fetchall(), [(42,)])
            self.assertEqual(db.execute("pragma integrity_check").fetchall(), [("ok",)])

    def test_permanent_staging_refusal_is_bounded_and_security_blocks_are_not_retried(self):
        rename = patcher.os.rename
        for code, expected_attempts in ((5, 5), (225, 1), (226, 1)):
            with self.subTest(winerror=code):
                attempts = 0

                def refusal(source, destination):
                    nonlocal attempts
                    if Path(source).parent.name == "payload" and Path(source).name == "python_embeded":
                        attempts += 1
                        raise self.windows_access_error(code)
                    return rename(source, destination)

                with mock.patch.object(patcher.os, "rename", side_effect=refusal), \
                        mock.patch.object(patcher.time, "sleep") as sleep, \
                        mock.patch.object(patcher, "check_runtime") as health:
                    with self.assertRaises(PermissionError):
                        self.activate()
                self.assertEqual(attempts, expected_attempts)
                self.assertEqual(sleep.call_count, expected_attempts - 1)
                self.assertLessEqual(sum(call.args[0] for call in sleep.call_args_list), 2.0)
                health.assert_not_called()
                self.assert_original()
                self.assertEqual(transition._load_journal(self.target)["phase"], "rolled-back")

    def test_staging_retry_rejects_replaced_source_or_new_destination(self):
        rename = patcher.os.rename
        for changed in ("source", "destination"):
            with self.subTest(changed=changed):
                blocked = {}

                def refusal(source, destination):
                    if Path(source).parent.name == "payload" and Path(source).name == "python_embeded":
                        blocked.update(source=Path(source), destination=Path(destination))
                        raise self.windows_access_error(5)
                    return rename(source, destination)

                def replace_staging_path(_delay):
                    path = blocked[changed]
                    if changed == "source":
                        rename(path, path.with_name("retained-source"))
                    path.mkdir()
                    (path / "do-not-overwrite.txt").write_bytes(b"preserve replacement")

                with mock.patch.object(patcher.os, "rename", side_effect=refusal), \
                        mock.patch.object(patcher.time, "sleep", side_effect=replace_staging_path), \
                        mock.patch.object(patcher, "check_runtime") as health:
                    with self.assertRaisesRegex(RuntimeError, "staging component changed"):
                        self.activate()
                self.assertEqual((blocked[changed] / "do-not-overwrite.txt").read_bytes(),
                                 b"preserve replacement")
                health.assert_not_called()
                self.assert_original()
                self.assertEqual(transition._load_journal(self.target)["phase"], "rolled-back")

    def test_inflight_preparation_finishes_before_failure_recovery(self):
        slow, failed = (self.candidate / name for name in ("LAKIS.exe", "LAKIS_Updater.exe"))
        started, failure, finished = threading.Event(), threading.Event(), threading.Event()
        copy_file, restore = contract._stream_digest, patcher.restore

        def controlled_copy(stream, destination=None):
            if os.path.samefile(stream.fileno(), slow):
                started.set()
                self.assertTrue(failure.wait(5), "second file did not reach its injected failure")
                try:
                    return copy_file(stream, destination)
                finally:
                    finished.set()
            if os.path.samefile(stream.fileno(), failed):
                self.assertTrue(started.wait(5), "in-flight file did not start")
                failure.set()
                raise OSError("parallel staging failure")
            return copy_file(stream, destination)

        def checked_restore(*args):
            self.assertTrue(finished.is_set(), "recovery overlapped an in-flight stage write")
            return restore(*args)

        with mock.patch.object(contract, "_stream_digest", side_effect=controlled_copy), \
                mock.patch.object(patcher, "restore", side_effect=checked_restore):
            with self.assertRaisesRegex(OSError, "parallel staging failure"):
                self.activate()
        self.assert_original()
        self.assertEqual(transition._load_journal(self.target)["phase"], "rolled-back")

    def test_health_failure_restores_database_and_retains_failed_database(self):
        def migrate_then_fail(root):
            with closing(sqlite3.connect(root / "ComfyUI/user/comfyui.db")) as db, db:
                db.execute("insert into fixture values (99)")
            raise RuntimeError("startup failed")
        with mock.patch.object(patcher, "check_runtime", side_effect=migrate_then_fail):
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                self.activate()
        self.assert_original()
        state = transition._load_journal(self.target)
        archived = self.target.parent / state["workspace"] / "database/failed/comfyui.db"
        with closing(sqlite3.connect(archived)) as db:
            self.assertEqual(db.execute("select value from fixture order by value").fetchall(), [(42,), (99,)])

    def test_new_outputs_survive_explicit_rollback(self):
        self.activate()
        new_output = self.target / "ComfyUI/output/after-update.png"
        new_output.write_bytes(b"new-image")
        with mock.patch.object(transition, "assert_idle"):
            transition.recover(self.target, self.candidate / "python_embeded/python.exe")
        self.assertEqual(new_output.read_bytes(), b"new-image")
        self.assertEqual(self.model.stat().st_ino, self.model_identity)

    def test_crash_after_each_component_rename_can_resume_rollback(self):
        real_rename = patcher.os.rename
        manifest = json.loads((self.candidate / contract.MANIFEST_NAME).read_bytes())
        plan = patcher.component_plan(manifest) + [{"path": contract.MANIFEST_NAME}]
        rename_count = sum(1 + int((self.target / group["path"]).exists()) for group in plan)
        for crash_at in range(1, rename_count + 1):
            with self.subTest(rename=crash_at):
                calls = 0
                def interrupted(source, destination):
                    nonlocal calls
                    real_rename(source, destination)
                    if self.target not in Path(source).parents and self.target not in Path(destination).parents:
                        return
                    calls += 1
                    if calls == crash_at:
                        raise SystemExit("simulated process termination")
                with mock.patch.object(patcher.os, "rename", side_effect=interrupted):
                    with self.assertRaises(SystemExit):
                        self.activate()
                with mock.patch.object(transition, "assert_idle"):
                    transition.recover(self.target, self.candidate / "python_embeded/python.exe")
                self.assert_original()

    def test_interrupted_recovery_is_idempotent(self):
        self.activate()
        real_rename = patcher.os.rename
        def interrupted(source, destination):
            real_rename(source, destination)
            raise SystemExit("simulated recovery interruption")
        with mock.patch.object(patcher.os, "rename", side_effect=interrupted):
            with self.assertRaises(SystemExit):
                with mock.patch.object(transition, "assert_idle"):
                    transition.recover(self.target, self.candidate / "python_embeded/python.exe")
        with mock.patch.object(transition, "assert_idle"):
            transition.recover(self.target, self.candidate / "python_embeded/python.exe")
            transition.recover(self.target, self.candidate / "python_embeded/python.exe")
        self.assert_original()

    def test_unknown_replacement_is_not_overwritten_during_recovery(self):
        self.activate()
        installed = self.target / "LAKIS.exe"
        installed.rename(self.target / "retained-new-launcher.exe")
        installed.write_bytes(b"foreign-launcher")
        before = self.snapshot(self.target)
        with mock.patch.object(transition, "assert_idle"):
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                transition.recover(self.target, self.candidate / "python_embeded/python.exe")
        self.assertEqual(self.snapshot(self.target), before)

    def test_journal_cannot_target_user_data(self):
        self.activate()
        state = transition._load_journal(self.target)
        state["operations"][0]["path"] = "ComfyUI/models"
        with self.assertRaisesRegex(ValueError, "user data"):
            patcher.validate_state(self.target, state)

    def test_idle_probe_opens_only_explicit_database_paths(self):
        completed = mock.Mock(stdout=b"[]")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        handle = create(str(self.model), 0x80000000, 0, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with mock.patch.object(transition.subprocess, "run", return_value=completed):
                transition.assert_idle(self.target, self.candidate / "python_embeded/python.exe", file_paths=[self.db])
        finally:
            close(handle)

    def test_runtime_entry_count_does_not_raise_the_default_node_zip_limit(self):
        archive = self.root / "runtime.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("first.txt", b"first")
            bundle.writestr("second.txt", b"second")
        with mock.patch.object(installer, "ZIP_MAX_ENTRIES", 1):
            with self.assertRaisesRegex(RuntimeError, "too many entries"):
                installer.extract_zip(archive, self.root / "ordinary")
            installer.extract_zip(archive, self.root / "runtime", expected_entries=2)
            with self.assertRaisesRegex(RuntimeError, "entry count mismatch"):
                installer.extract_zip(archive, self.root / "wrong-count", expected_entries=3)
        self.assertEqual((self.root / "runtime/second.txt").read_bytes(), b"second")
        self.assertFalse((self.root / "ordinary").exists())
        self.assertFalse((self.root / "wrong-count").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
