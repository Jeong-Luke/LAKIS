"""Startup deadlines and failure gates without running an installed ComfyUI."""
from contextlib import ExitStack
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_health as health


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lakis-health-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        for relative in ("python_embeded/python.exe", "ComfyUI/main.py"):
            path = self.candidate / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test program")
        self.profile = self.root / "isolated-profile"
        self.profile.mkdir()
        self.now = 0.0
        self.pip_seconds = 20.0
        self.copy_seconds = 150.0
        self.ready_after = 0.0
        self.spawned_at = None
        self.version = "0.42.0"
        self.nodes = {"RequiredNode": {}}
        self.child = mock.Mock(stdout=None, pid=12345, returncode=None)
        self.child.poll.return_value = None
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(mock.patch.object(health.time, "monotonic", side_effect=lambda: self.now))
        self.stack.enter_context(mock.patch.object(health.time, "sleep", side_effect=self.advance))
        self.stack.enter_context(mock.patch.object(health.tempfile, "mkdtemp", return_value=str(self.profile)))
        self.stack.enter_context(mock.patch.object(health, "_read_required_nodes", return_value={"RequiredNode"}))
        self.stack.enter_context(mock.patch.object(health, "_select_port", return_value=59175))
        self.pip = self.stack.enter_context(mock.patch.object(health.subprocess, "run", side_effect=self.run_pip))
        self.stack.enter_context(mock.patch.object(health, "_isolated_entrypoint", side_effect=self.copy_program))
        self.spawn = self.stack.enter_context(mock.patch.object(health.subprocess, "Popen", side_effect=self.start))
        self.stack.enter_context(mock.patch.object(health, "_fetch_json", side_effect=self.fetch))
        self.owner = self.stack.enter_context(mock.patch.object(health, "_owns_listener", return_value=True))
        self.stack.enter_context(mock.patch("sys.stdout", io.StringIO()))

    def advance(self, seconds):
        self.now += seconds

    def run_pip(self, command, **options):
        self.advance(self.pip_seconds)
        return subprocess.CompletedProcess(command, 0, b"No broken requirements found.\n")

    def copy_program(self, *_):
        self.advance(self.copy_seconds)
        return ["-c", "pass"]

    def start(self, *_args, **_options):
        self.spawned_at = self.now
        return self.child

    def fetch(self, url, timeout):
        if self.now - self.spawned_at < self.ready_after:
            self.advance(timeout)
            raise TimeoutError("not ready")
        if url.endswith("/system_stats"):
            return {"system": {"comfyui_version": self.version}}
        return self.nodes

    def log(self):
        paths = list(self.profile.glob("runtime-health-*.log"))
        self.assertEqual(len(paths), 1)
        return paths[0].read_text(encoding="utf-8")

    def assert_stopped(self):
        self.child.terminate.assert_called_once_with()
        self.child.wait.assert_called_once_with(timeout=5.0)

    def test_preparation_does_not_spend_default_startup_allowance(self):
        # A slow first launch exceeds the old shared 180-second limit, and the
        # whole operation exceeds 600 seconds while startup itself does not.
        self.ready_after = 500.0
        result = health.check_runtime(self.candidate)
        self.assertEqual(result["preparation_seconds"], 170.0)
        self.assertGreaterEqual(result["startup_seconds"], 500.0)
        self.assertLess(result["startup_seconds"], 600.0)
        self.assertGreater(self.now, 600.0)
        self.assertEqual(result["comfyui_version"], "0.42.0")
        self.assertEqual(result["required_node_count"], 1)
        self.assertIn("Isolated file preparation took 150.0s", self.log())
        self.assertIn("startup allowance: 600s", self.log())
        self.assert_stopped()

    def test_explicit_startup_timeout_is_independent_of_preparation(self):
        self.ready_after = 2.0
        result = health.check_runtime(self.candidate, timeout=5.0)
        self.assertEqual(result["preparation_seconds"], 170.0)
        self.assertLess(result["startup_seconds"], 5.0)
        self.assert_stopped()

    def test_preparation_still_has_its_own_deadline(self):
        self.copy_seconds = 161.0
        with self.assertRaisesRegex(RuntimeError, "timed out before ComfyUI startup"):
            health.check_runtime(self.candidate)
        self.spawn.assert_not_called()
        self.assertEqual(self.pip.call_args.kwargs["timeout"], 180.0)
        self.assertIn("Isolated file preparation took 161.0s", self.log())

    def test_hung_startup_is_bounded_and_retains_diagnostics(self):
        self.ready_after = float("inf")
        with self.assertRaisesRegex(RuntimeError, "startup elapsed: 600.0s"):
            health.check_runtime(self.candidate)
        self.assertEqual(self.now - self.spawned_at, 600.0)
        self.assertIn("preparation: 170.0s", self.log())
        self.assertIn("last object_info: TimeoutError: not ready", self.log())
        self.assert_stopped()

    def test_pip_failure_does_not_launch(self):
        self.pip.side_effect = None
        self.pip.return_value = subprocess.CompletedProcess([], 1, b"broken dependency")
        with self.assertRaisesRegex(RuntimeError, "pip check failed with exit code 1"):
            health.check_runtime(self.candidate)
        self.spawn.assert_not_called()
        self.assertIn("broken dependency", self.log())

    def test_pip_timeout_retains_output(self):
        self.pip.side_effect = subprocess.TimeoutExpired("pip", 180, output=b"partial pip output")
        with self.assertRaisesRegex(RuntimeError, "pip check timed out"):
            health.check_runtime(self.candidate)
        self.spawn.assert_not_called()
        self.assertIn("partial pip output", self.log())

    def test_foreign_listener_is_rejected(self):
        self.owner.return_value = False
        with self.assertRaisesRegex(RuntimeError, "endpoint identity mismatch"):
            health.check_runtime(self.candidate)
        self.assert_stopped()

    def test_wrong_comfyui_version_is_rejected(self):
        self.version = "0.21.1"
        with self.assertRaisesRegex(RuntimeError, "version mismatch"):
            health.check_runtime(self.candidate)
        self.assert_stopped()

    def test_missing_required_nodes_are_rejected(self):
        self.nodes = {}
        with self.assertRaisesRegex(RuntimeError, "missing required workflow nodes: RequiredNode"):
            health.check_runtime(self.candidate)
        self.assert_stopped()

    def test_premature_exit_is_rejected(self):
        self.child.poll.return_value = 1
        self.child.returncode = 1
        with self.assertRaisesRegex(RuntimeError, "exited prematurely with code 1"):
            health.check_runtime(self.candidate)
        self.child.terminate.assert_not_called()
        self.child.wait.assert_called_once_with(timeout=5.0)

    def test_profile_remains_isolated_and_no_prompt_is_submitted(self):
        health.check_runtime(self.candidate)
        options = self.spawn.call_args.kwargs
        environment = options["env"]
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                     "LORA_MANAGER_SETTINGS_DIR", "LORA_MANAGER_CACHE_DB",
                     "LORA_MANAGER_RECIPE_CACHE_DB", "WAS_CONFIG_DIR"):
            self.assertTrue(Path(environment[name]).is_relative_to(self.profile))
        self.assertEqual(environment["WAS_BLOCK_AUTO_INSTALL"], "1")
        self.assertEqual(options["cwd"], str(self.profile))
        command = self.spawn.call_args.args[0]
        self.assertIn("--disable-assets", command)
        self.assertIn("--disable-auto-launch", command)
        self.assert_stopped()

    def test_invalid_timeout_rejected_before_launch(self):
        for timeout in (0, -1, float("inf"), float("nan"), "600"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                health.check_runtime(self.candidate, timeout=timeout)
        self.spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
