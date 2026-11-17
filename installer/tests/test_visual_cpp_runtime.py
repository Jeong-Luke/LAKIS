import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer"))
import lakis_cmd_installer as installer
import runtime_install


class VisualCppRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(
            (ROOT / "installer/cmd-installer-manifest.json").read_text(encoding="utf-8")
        )
        self.addCleanup(mock.patch.stopall)
        mock.patch("sys.stdout", io.StringIO()).start()

    def test_dll_probe_requires_a_successful_child_process(self):
        for code in (0, 1):
            with self.subTest(code=code), mock.patch.object(
                installer.subprocess, "run",
                return_value=subprocess.CompletedProcess([], code),
            ) as run:
                self.assertEqual(installer.has_visual_cpp_runtime(), code == 0)
                self.assertEqual(run.call_args.args[0][0], sys.executable)

    def test_dll_probe_timeout_is_not_reported_as_success(self):
        with mock.patch.object(
            installer.subprocess, "run",
            side_effect=subprocess.TimeoutExpired("DLL probe", 30),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                installer.has_visual_cpp_runtime()

    def test_working_runtime_is_left_unchanged_without_a_download(self):
        with mock.patch.object(installer, "has_visual_cpp_runtime", return_value=True), \
             mock.patch.object(installer, "download") as download, \
             mock.patch.object(installer.subprocess, "run") as run:
            installer.ensure_visual_cpp_runtime({}, Path("unused"))
            download.assert_not_called()
            run.assert_not_called()

    def test_missing_runtime_uses_pinned_download_and_checks_installed_dlls(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            executable = cache / "verified.exe"
            record = self.manifest["visual_cpp"]
            with mock.patch.object(
                installer, "has_visual_cpp_runtime", side_effect=[False, True],
            ) as available, mock.patch.object(
                installer, "download", return_value=executable,
            ) as download, mock.patch.object(
                installer.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as run:
                installer.ensure_visual_cpp_runtime(self.manifest, cache)
                download.assert_called_once_with(
                    record["url"], installer.cache_path(cache, record["name"], record["sha256"]),
                    record["sha256"], record["bytes"], display_name=record["name"],
                )
                self.assertEqual(available.call_count, 2)
                command = run.call_args.args[0]
                self.assertEqual(command[:5], [
                    str(executable), "/install", "/quiet", "/norestart", "/log",
                ])
                self.assertEqual(Path(command[5]).parent, cache)
                self.assertTrue(Path(command[5]).is_file())
                self.assertEqual(run.call_count, 1)

    def test_failed_verification_never_executes_the_download(self):
        with mock.patch.object(installer, "has_visual_cpp_runtime", return_value=False), \
             mock.patch.object(installer, "download", side_effect=ValueError("SHA-256 mismatch")), \
             mock.patch.object(installer.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                installer.ensure_visual_cpp_runtime(self.manifest, Path("unused"))
            run.assert_not_called()

    def test_failure_and_reboot_codes_stop_without_retry_or_post_success(self):
        for code, message in ((1603, "설치 실패"), (1223, "설치 실패"),
                              (1638, "설치 실패"), (3010, "재부팅")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                cache = Path(folder)
                with mock.patch.object(
                    installer, "has_visual_cpp_runtime", return_value=False,
                ) as available, mock.patch.object(
                    installer, "download", return_value=cache / "verified.exe",
                ), mock.patch.object(
                    installer.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], code),
                ) as run:
                    with self.assertRaisesRegex(RuntimeError, message):
                        installer.ensure_visual_cpp_runtime(self.manifest, cache)
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(available.call_count, 1)

    def test_start_denial_is_propagated_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            with mock.patch.object(installer, "has_visual_cpp_runtime", return_value=False), \
                 mock.patch.object(installer, "download", return_value=cache / "verified.exe"), \
                 mock.patch.object(installer.subprocess, "run", side_effect=PermissionError("denied")) as run:
                with self.assertRaises(PermissionError):
                    installer.ensure_visual_cpp_runtime(self.manifest, cache)
                self.assertEqual(run.call_count, 1)

    def test_exit_zero_with_missing_dlls_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            with mock.patch.object(installer, "has_visual_cpp_runtime", return_value=False), \
                 mock.patch.object(installer, "download", return_value=cache / "verified.exe"), \
                 mock.patch.object(installer.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaisesRegex(RuntimeError, "필수 DLL"):
                    installer.ensure_visual_cpp_runtime(self.manifest, cache)

    def test_only_the_fixed_microsoft_download_origin_is_allowed(self):
        url = self.manifest["visual_cpp"]["url"]
        installer.validate_download_origin(url, url)
        for destination in (
            url.replace("https:", "http:"),
            url.replace("download.visualstudio.microsoft.com", "download.visualstudio.microsoft.com.evil.invalid"),
            url.replace("https://", "https://user:password@"),
        ):
            with self.subTest(destination=destination), \
                 self.assertRaises(installer.InvalidDownloadOriginError):
                installer.validate_download_origin(url, destination)

    def test_prerequisite_failure_prevents_preparation_and_activation_in_all_modes(self):
        for mode, method in (("fresh", "gui"), ("fresh", "cmd"),
                             ("repair", "gui"), ("update", "updater")):
            with self.subTest(mode=mode, method=method), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "target"
                target.mkdir()
                sentinel = target / "user.txt"
                sentinel.write_bytes(b"unchanged user data")
                with mock.patch.object(runtime_install, "installer_identity",
                                       return_value=({}, None, "8.1.2", "A" * 64)), \
                     mock.patch.object(runtime_install, "_assert_original"), \
                     mock.patch.object(runtime_install, "ensure_visual_cpp_runtime",
                                       side_effect=RuntimeError("prerequisite failed")), \
                     mock.patch.object(runtime_install, "prepare_candidate") as prepare, \
                     mock.patch.object(runtime_install, "activate") as activate:
                    with self.assertRaisesRegex(RuntimeError, "prerequisite failed"):
                        runtime_install.install(self.manifest, target, Path(folder) / "cache", mode, method)
                    prepare.assert_not_called()
                    activate.assert_not_called()
                    self.assertEqual(sentinel.read_bytes(), b"unchanged user data")

    def test_unrelated_target_is_rejected_before_system_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / "user.txt").write_bytes(b"preserve")
            with mock.patch.object(runtime_install, "installer_identity",
                                   return_value=({}, None, "8.1.2", "A" * 64)), \
                 mock.patch.object(runtime_install, "ensure_visual_cpp_runtime") as prerequisite:
                with self.assertRaisesRegex(ValueError, "fresh target is not empty"):
                    runtime_install.install(self.manifest, target, target / "cache", "fresh", "gui")
                prerequisite.assert_not_called()


if __name__ == "__main__":
    unittest.main()
