"""Filesystem prerequisites must fail before any installed component is replaced."""
from contextlib import ExitStack
import ctypes
import io
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from installer.tests import test_cmd_installer as fixtures
import runtime_manifest as contract
import runtime_patch
import runtime_transition


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


class UpdateFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lakis-update-filesystem-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate, manifest = fixtures.CmdInstallerTests()._runtime_candidate(
            self.root, version="8.1.2")
        self.manifest_hash = manifest["runtime_bundle"]["manifest_sha256"]
        self.target = self.root / "installed"
        shutil.copytree(self.candidate, self.target)
        (self.target / "VERSION").write_bytes(b"8.1.1")
        for relative in ("ComfyUI/output/keep.png", "ComfyUI/models/loras/user.safetensors",
                         "ComfyUI/user/default/workflows/user.json", ".lakis/settings.json"):
            path = self.target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("user data: " + relative).encode())
        self.before = snapshot(self.target)
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(mock.patch("sys.stdout", io.StringIO()))
        self.stack.enter_context(mock.patch.object(contract, "required_model_specs", return_value={}))
        self.stack.enter_context(mock.patch.object(runtime_patch, "assert_idle"))
        self.health = self.stack.enter_context(mock.patch.object(runtime_patch, "check_runtime"))

    def update(self):
        return runtime_patch.activate(
            self.candidate, self.target, self.manifest_hash, "8.1.2")

    def test_unsupported_volume_query_leaves_installation_and_journal_untouched(self):
        pin = contract._pinned_path
        error = ctypes.WinError(87)

        def unsupported_root(path, **kwargs):
            if path == Path(self.target.anchor):
                raise error
            return pin(path, **kwargs)

        with mock.patch.object(contract, "_pinned_path", side_effect=unsupported_root):
            with self.assertRaisesRegex(RuntimeError, "NTFS") as caught:
                self.update()
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(snapshot(self.target), self.before)
        self.assertFalse(runtime_transition._journal_path(self.target).exists())
        self.assertFalse(any(path.is_dir() for path in self.root.glob(".installed-*")))
        self.health.assert_not_called()

    def test_other_io_errors_are_not_reported_as_unsupported_filesystems(self):
        pin = contract._pinned_path
        error = ctypes.WinError(5)

        def denied_target(path, **kwargs):
            if path == self.target:
                raise error
            return pin(path, **kwargs)

        with mock.patch.object(contract, "_pinned_path", side_effect=denied_target):
            with self.assertRaises(OSError) as caught:
                self.update()
        self.assertIs(caught.exception, error)
        self.assertEqual(snapshot(self.target), self.before)
        self.assertFalse(runtime_transition._journal_path(self.target).exists())
        self.health.assert_not_called()

    def assert_unstable_staging_is_safe(self, kind):
        identity = runtime_patch._identity

        def changed_after_move(path):
            value = identity(path)
            if value and path.parent.name == "stage" and value["kind"] == kind:
                return dict(value, file=value["file"] + 1)
            return value

        with mock.patch.object(runtime_patch, "_identity", side_effect=changed_after_move):
            with self.assertRaisesRegex(RuntimeError, "파일 이동 후 식별번호"):
                self.update()
        self.assertEqual(snapshot(self.target), self.before)
        state = runtime_transition._load_journal(self.target)
        self.assertEqual(state["phase"], "rolled-back")
        self.assertEqual(state["operations"], [])
        retained = self.root / state["workspace"] / "stage"
        self.assertTrue(any(retained.iterdir()))
        self.health.assert_not_called()

    def test_renamed_directory_identity_must_be_stable_before_replacement(self):
        self.assert_unstable_staging_is_safe(stat.S_IFDIR)

    def test_renamed_file_identity_must_be_stable_before_replacement(self):
        self.assert_unstable_staging_is_safe(stat.S_IFREG)

    def test_supported_update_preserves_user_files_and_releases_preflight_handles(self):
        result = self.update()
        self.assertEqual(result["status"], "complete")
        self.assertEqual((self.target / "VERSION").read_bytes(), b"8.1.2")
        for relative, content in self.before.items():
            if contract.protected_path(relative):
                self.assertEqual((self.target / relative).read_bytes(), content)
        # Ancestor/target handles used during preflight must not remain pinned.
        moved = self.root / "moved"
        os.rename(self.target, moved)
        self.assertEqual((moved / "VERSION").read_bytes(), b"8.1.2")

    def test_unknown_recovery_component_still_blocks_without_overwrites(self):
        workspace = self.root / ".installed-recovery"
        paths = runtime_patch._locations(self.target, workspace, 0, {"path": "advanced"})
        paths["backup"].parent.mkdir(parents=True)
        paths["stage"].parent.mkdir(parents=True)
        paths["stage"].mkdir()
        (paths["stage"] / "new.txt").write_bytes(b"new program")
        paths["target"].mkdir()
        (paths["target"] / "old.txt").write_bytes(b"original program")
        operation = {"path": "advanced", "old": runtime_patch._identity(paths["target"]),
                     "new": runtime_patch._identity(paths["stage"])}
        os.rename(paths["target"], paths["backup"])
        os.rename(paths["stage"], self.root / "retained-new-component")
        paths["target"].mkdir()
        (paths["target"] / "unknown.txt").write_bytes(b"unrelated replacement")
        before = snapshot(self.root)
        with self.assertRaisesRegex(RuntimeError, "recovery target identity changed"):
            runtime_patch._check_recovery_locations(self.target, workspace, [operation])
        self.assertEqual(snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
