"""Fresh runtime extraction preserves ZIP validation and Windows path locks."""
from contextlib import contextmanager
from pathlib import Path
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

import lakis_cmd_installer as installer
import runtime_install as runtime
import test_runtime_patch as component_tests


class RuntimeExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "runtime.zip"
        self.destination = self.root / "candidate"

    def write_zip(self, rows, compression=zipfile.ZIP_DEFLATED):
        with zipfile.ZipFile(self.archive, "w", compression=compression) as bundle:
            for name, data in rows:
                bundle.writestr(name, data)

    def extract(self, count):
        runtime.extract_runtime_zip(self.archive, self.destination, expected_entries=count)

    def test_all_bytes_and_empty_directories_across_batches(self):
        rows = [("empty/", b""), ("nested/", b"")]
        rows += [(f"nested/dir{index % 7}/file{index}.bin",
                  bytes(range(256)) * (index + 1)) for index in range(145)]
        rows.append(("zero.bin", b""))
        self.write_zip(rows)
        self.extract(len(rows))
        self.assertTrue((self.destination / "empty").is_dir())
        for name, data in rows:
            if not name.endswith("/"):
                self.assertEqual((self.destination / name).read_bytes(), data)

    def test_existing_destination_is_never_merged_or_overwritten(self):
        self.write_zip([("keep.txt", b"replacement")])
        self.destination.mkdir()
        sentinel = self.destination / "keep.txt"
        sentinel.write_bytes(b"user-data")
        identity = sentinel.stat().st_ino
        with self.assertRaises(FileExistsError):
            self.extract(1)
        self.assertEqual(sentinel.read_bytes(), b"user-data")
        self.assertEqual(sentinel.stat().st_ino, identity)

    def test_invalid_paths_duplicates_and_collisions_fail_before_root_creation(self):
        cases = [
            [("../outside", b"bad")], [("/absolute", b"bad")],
            [("folder\\..\\escape", b"bad")], [("file:stream", b"bad")],
            [("NUL", b"bad")], [("folder/trailing. ", b"bad")],
            [("control\x01.txt", b"bad")],
            [("valid.txt", b"good"), ("../outside", b"bad")],
            [("same.txt", b"one"), ("SAME.txt", b"two")],
            [("file", b"one"), ("file/child", b"two")],
            [("file/child", b"one"), ("FILE", b"two")],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.write_zip(rows)
                with self.assertRaises(RuntimeError):
                    self.extract(len(rows))
                self.assertFalse(self.destination.exists())

    def test_zip_symlink_is_rejected_before_root_creation(self):
        entry = zipfile.ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.write_zip([(entry, b"outside")])
        with self.assertRaisesRegex(RuntimeError, "unsafe ZIP link"):
            self.extract(1)
        self.assertFalse(self.destination.exists())

    def test_size_ratio_and_entry_limits_still_fail_before_writes(self):
        self.write_zip([("small", b"one"), ("large", b"x" * 4096)])
        for limit, value in (("ZIP_MAX_BYTES", 4), ("ZIP_MAX_FILE_BYTES", 4),
                             ("ZIP_MAX_RATIO", 1)):
            with self.subTest(limit=limit), mock.patch.object(installer, limit, value):
                with self.assertRaisesRegex(RuntimeError, "ZIP_RESOURCE_LIMIT"):
                    self.extract(2)
                self.assertFalse(self.destination.exists())
        with self.assertRaisesRegex(RuntimeError, "entry count mismatch"):
            self.extract(1)
        for count in (0, -1, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.extract(count)
        self.assertFalse(self.destination.exists())

    def test_corrupt_crc_fails_extraction(self):
        self.write_zip([("payload.bin", b"CRC_fixture")], compression=zipfile.ZIP_STORED)
        raw = self.archive.read_bytes()
        self.archive.write_bytes(raw.replace(b"CRC_fixture", b"BAD_fixture", 1))
        with self.assertRaises(zipfile.BadZipFile):
            self.extract(1)

    def test_existing_archive_writer_prevents_extraction(self):
        self.write_zip([("payload.bin", b"content")])
        with self.archive.open("r+b"), self.assertRaises(OSError):
            self.extract(1)
        self.assertFalse(self.destination.exists())

    def test_file_inserted_after_preflight_is_not_overwritten(self):
        self.write_zip([("payload.bin", b"replacement")])
        external = self.root / "external.bin"
        external.write_bytes(b"must-preserve")
        original = runtime.zipfile.ZipFile.open

        def open_entry(bundle, entry, *args, **kwargs):
            os.link(external, self.destination / "payload.bin")
            return original(bundle, entry, *args, **kwargs)

        with mock.patch.object(runtime.zipfile.ZipFile, "open", open_entry):
            # Windows may reject the hard-link insertion itself under the
            # pinned ancestry; otherwise exclusive file creation rejects it.
            with self.assertRaises(OSError):
                self.extract(1)
        self.assertEqual(external.read_bytes(), b"must-preserve")

    def test_directory_replaced_by_junction_before_pin_is_rejected(self):
        self.write_zip([("nested/payload.bin", b"replacement")])
        external = self.root / "external"
        external.mkdir()
        sentinel = external / "payload.bin"
        sentinel.write_bytes(b"must-preserve")
        junction = self.destination / "nested"
        original = runtime._pinned_path

        @contextmanager
        def pin(path, **options):
            if path == junction:
                path.rmdir()
                subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(external)],
                               check=True, capture_output=True)
            with original(path, **options) as result:
                yield result

        try:
            with mock.patch.object(runtime, "_pinned_path", pin):
                with self.assertRaisesRegex(RuntimeError, "unsafe reparse"):
                    self.extract(1)
            self.assertEqual(sentinel.read_bytes(), b"must-preserve")
            self.assertEqual([path.name for path in external.iterdir()], ["payload.bin"])
        finally:
            junction.rmdir()

    def test_junction_parent_is_rejected_without_external_writes(self):
        self.write_zip([("payload.bin", b"content")])
        external = self.root / "external"
        external.mkdir()
        junction = self.root / "junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(external)],
                       check=True, capture_output=True)
        try:
            with self.assertRaisesRegex(RuntimeError, "unsafe reparse"):
                runtime.extract_runtime_zip(self.archive, junction / "candidate",
                                            expected_entries=1)
            self.assertEqual(list(external.iterdir()), [])
        finally:
            junction.rmdir()

    def test_worker_failure_waits_for_other_workers_before_unlocking_parents(self):
        self.write_zip([("broken.bin", b"bad"), ("nested/slow.bin", b"good")])
        entered, release = threading.Event(), threading.Event()
        errors = []
        original = runtime.shutil.copyfileobj

        def copy(incoming, outgoing, length):
            if incoming.name == "broken.bin":
                raise RuntimeError("injected worker failure")
            entered.set()
            if not release.wait(10):
                raise RuntimeError("worker was not released")
            return original(incoming, outgoing, length)

        def extract():
            try:
                self.extract(2)
            except Exception as error:
                errors.append(error)

        with mock.patch.object(runtime.shutil, "copyfileobj", side_effect=copy):
            worker = threading.Thread(target=extract)
            worker.start()
            try:
                self.assertTrue(entered.wait(10))
                self.assertTrue(worker.is_alive())
                for path in (self.destination / "nested", self.destination, self.root):
                    with self.subTest(path=path), self.assertRaises(OSError):
                        os.rename(path, path.with_name(path.name + "-moved"))
                with self.assertRaises(OSError):
                    self.archive.write_bytes(b"tamper")
            finally:
                release.set()
                worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertEqual([str(error) for error in errors], ["injected worker failure"])
        self.assertEqual((self.destination / "nested/slow.bin").read_bytes(), b"good")
        moved = self.destination.with_name("released")
        os.rename(self.destination, moved)
        os.rename(moved, self.destination)

    def test_preparation_still_checks_manifest_hashes_after_extraction(self):
        fixture = component_tests.RuntimeComponentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        rows = [(path.relative_to(fixture.candidate).as_posix(), path.read_bytes())
                for path in fixture.candidate.rglob("*") if path.is_file()]
        self.write_zip(rows)
        size = self.archive.stat().st_size
        bundle = {
            "schema": 2, "product": "LAKIS", "version": "8.0.0",
            "comfyui_version": "0.42.0", "name": "runtime.zip",
            "bytes": size, "files": len(rows) - 1,
            "sha256": installer.sha256(self.archive),
            "manifest_sha256": fixture.manifest_hash,
            "parts": [{
                "name": "runtime.zip.part001", "bytes": size,
                "sha256": installer.sha256(self.archive),
                "url": "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/runtime.zip.part001",
            }],
        }
        with mock.patch.object(runtime, "download_bundle", return_value=self.archive):
            candidate = runtime.prepare_bundle(bundle, "8.0.0", self.root)
        self.assertEqual((candidate / "ComfyUI/main.py").read_bytes(),
                         (fixture.candidate / "ComfyUI/main.py").read_bytes())
        rows = [(name, b"tampered" if name == "ComfyUI/main.py" else data)
                for name, data in rows]
        self.write_zip(rows)
        with mock.patch.object(runtime, "download_bundle", return_value=self.archive):
            with self.assertRaisesRegex(ValueError, "runtime file mismatch"):
                runtime.prepare_bundle(bundle, "8.0.0", self.root)


if __name__ == "__main__":
    unittest.main()
