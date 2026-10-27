"""Real Windows handle lifetime and authenticated-file regression tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

import test_runtime_patch as component_tests
import runtime_manifest as contract


class PinnedRuntimePathsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = component_tests.RuntimeComponentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_full_manifest_still_requires_every_hash_and_file(self):
        root = self.fixture.candidate
        expected = self.fixture.manifest_hash
        manifest = contract.verify_runtime(root, expected, "8.0.0")
        self.assertEqual(len(manifest["files"]), len(list(contract.runtime_files(root, allow_user_data=False))))
        path = root / "ComfyUI/main.py"
        original = path.read_bytes()
        path.write_bytes(b"x" * len(original))
        with self.assertRaisesRegex(ValueError, "runtime file mismatch"):
            contract.verify_runtime(root, expected, "8.0.0")
        path.write_bytes(original)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing runtime files"):
            contract.verify_runtime(root, expected, "8.0.0")

    def test_file_and_all_parents_cannot_change_while_yielded(self):
        root = self.fixture.candidate
        scope = "python_embeded/Lib/site-packages/fixture/new.py"
        iterator = contract.runtime_files(root, allow_user_data=False, scopes=[scope])
        relative, path = next(iterator)
        self.assertEqual(relative, scope)
        try:
            with self.assertRaises(OSError):
                path.write_bytes(b"tamper")
            for parent in (path.parent, root / "python_embeded", root):
                with self.subTest(parent=parent), self.assertRaises(OSError):
                    os.rename(parent, parent.with_name(parent.name + "-moved"))
            self.assertEqual(path.read_bytes(), b"new-library")
        finally:
            iterator.close()
        path.write_bytes(b"released")
        self.assertEqual(path.read_bytes(), b"released")

    def test_existing_writer_prevents_verification(self):
        path = self.fixture.candidate / "ComfyUI/main.py"
        with path.open("r+b"), self.assertRaises(OSError) as raised:
            list(contract.runtime_files(self.fixture.candidate, allow_user_data=False,
                                        scopes=["ComfyUI/main.py"]))
        self.assertEqual(raised.exception.filename, str(path))

    def test_batch_retains_parents_after_traversal_leaves_each_scope(self):
        root = self.fixture.candidate
        scopes = ["ComfyUI/main.py", "python_embeded/Lib/site-packages/fixture/new.py"]
        iterator = contract._runtime_file_batches(root, allow_user_data=False,
                                                  scopes=scopes, batch_size=8)
        batch = next(iterator)
        self.assertEqual([relative for relative, _ in batch], scopes)
        try:
            for _, path in batch:
                with self.subTest(parent=path.parent), self.assertRaises(OSError):
                    os.rename(path.parent, path.parent.with_name(path.parent.name + "-moved"))
        finally:
            iterator.close()
        original = root / "ComfyUI"
        moved = root / "ComfyUI-moved"
        os.rename(original, moved)
        os.rename(moved, original)

    def test_parallel_hash_keeps_file_and_ancestors_locked(self):
        root = self.fixture.candidate
        selected = root / "ComfyUI/main.py"
        entered, release = threading.Event(), threading.Event()
        errors = []
        original = contract.hashlib.file_digest

        def slow_hash(stream, algorithm):
            if os.path.samefile(stream.fileno(), selected):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("test did not release hash worker")
            return original(stream, algorithm)

        def verify():
            try:
                contract.verify_runtime(root, self.fixture.manifest_hash, "8.0.0")
            except Exception as error:
                errors.append(error)

        with mock.patch.object(contract.hashlib, "file_digest", side_effect=slow_hash):
            worker = threading.Thread(target=verify)
            worker.start()
            try:
                self.assertTrue(entered.wait(10))
                with self.assertRaises(OSError):
                    selected.write_bytes(b"tamper")
                with self.assertRaises(OSError):
                    os.rename(root / "ComfyUI", root / "renamed")
            finally:
                release.set()
                worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_junction_in_managed_scope_or_root_is_rejected(self):
        external = self.fixture.root / "outside"
        external.mkdir()
        (external / "secret.bin").write_bytes(b"must-not-be-read")
        for name in ("ComfyUI/linked", "root-link"):
            link = self.fixture.candidate / name
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)],
                           check=True, capture_output=True)
            try:
                selected = link if name == "root-link" else self.fixture.candidate
                with self.assertRaisesRegex(RuntimeError, "reparse"):
                    list(contract.runtime_files(selected, allow_user_data=False))
            finally:
                link.rmdir()
        self.assertEqual((external / "secret.bin").read_bytes(), b"must-not-be-read")

    def test_protected_directory_is_not_opened_and_is_rejected_in_payload(self):
        root = self.fixture.candidate
        models = root / "ComfyUI/models"
        models.mkdir()
        model = models / "locked.bin"
        model.write_bytes(b"model")
        with model.open("r+b"):
            rows = list(contract.runtime_files(root, allow_user_data=True))
            self.assertFalse(any("models" in relative for relative, _ in rows))
            with self.assertRaisesRegex(ValueError, "user data"):
                list(contract.runtime_files(root, allow_user_data=False))

    def test_created_manifest_keeps_canonical_order_and_exact_digests(self):
        root = self.fixture.candidate
        original = json.loads((root / contract.MANIFEST_NAME).read_bytes())
        result = contract.create_manifest(root, "8.0.0", original["source_revision"], original["runtime"])
        self.assertEqual(result["files"], sorted(original["files"], key=lambda row: row["path"]))
        for row in result["files"]:
            self.assertEqual(row["sha256"], hashlib.sha256((root / row["path"]).read_bytes()).hexdigest().upper())

    def test_staging_verifies_and_persists_the_same_locked_bytes(self):
        root = self.fixture.candidate
        stage = self.fixture.root / "stage"
        selected = root / "ComfyUI/main.py"
        original_digest = contract._stream_digest
        seen = []

        def checked_digest(stream, destination=None):
            if os.path.samefile(stream.fileno(), selected):
                with self.assertRaises(OSError):
                    selected.write_bytes(b"tamper")
                with self.assertRaises(OSError):
                    os.rename(selected.parent, root / "moved")
            seen.append(destination)
            return original_digest(stream, destination)

        with mock.patch.object(contract, "_stream_digest", side_effect=checked_digest):
            manifest = contract.verify_runtime(root, self.fixture.manifest_hash, "8.0.0", stage_root=stage)
        self.assertEqual(len(seen), len(manifest["files"]))
        for entry in manifest["files"]:
            self.assertEqual((stage / entry["path"]).read_bytes(), (root / entry["path"]).read_bytes())
        self.assertFalse((stage / contract.MANIFEST_NAME).exists())

    def test_staging_rejects_untrusted_manifest_without_creating_payload(self):
        root = self.fixture.candidate
        stage = self.fixture.root / "stage"
        with self.assertRaisesRegex(ValueError, "manifest hash mismatch"):
            contract.verify_runtime(root, "0" * 64, "8.0.0", stage_root=stage)
        self.assertFalse(stage.exists())

    def test_staging_rejects_an_existing_writer_and_junction(self):
        root = self.fixture.candidate
        selected = root / "ComfyUI/main.py"
        with selected.open("r+b"), self.assertRaises(OSError):
            contract.verify_runtime(root, self.fixture.manifest_hash, "8.0.0",
                                    stage_root=self.fixture.root / "writer-stage")
        external = self.fixture.root / "external"
        external.mkdir()
        sentinel = external / "secret.bin"
        sentinel.write_bytes(b"external")
        link = root / "linked"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)],
                       check=True, capture_output=True)
        try:
            with self.assertRaisesRegex(RuntimeError, "reparse"):
                contract.verify_runtime(root, self.fixture.manifest_hash, "8.0.0",
                                        stage_root=self.fixture.root / "junction-stage")
        finally:
            link.rmdir()
        self.assertEqual(sentinel.read_bytes(), b"external")


if __name__ == "__main__":
    unittest.main()
