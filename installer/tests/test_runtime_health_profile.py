"""Health probes must never reuse a profile or alter existing user profiles."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_health as health


class HealthProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="health-profile-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.root = self.work / "installation"
        for relative in ("python_embeded/python.exe", "ComfyUI/main.py",
                         "ComfyUI/user/runtime-health-profile/lora-manager/recipes.db",
                         "ComfyUI/user/runtime-health-profile/lora-manager/models.db",
                         "ComfyUI/user/default/settings.json"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("preserve:" + relative).encode())
        self.user = self.root / "ComfyUI/user"
        self.before = self.snapshot()
        allocate = tempfile.mkdtemp
        self.allocation = mock.patch.object(health.tempfile, "mkdtemp",
            side_effect=lambda **kwargs: allocate(dir=self.work, **kwargs))
        self.allocation.start()
        self.addCleanup(self.allocation.stop)

    def snapshot(self, root=None):
        root = self.user if root is None else root
        return {path.relative_to(root): (path.read_bytes(), path.stat().st_ino)
                for path in root.rglob("*") if path.is_file()}

    def test_failed_checks_keep_distinct_profiles_and_diagnostics_outside_user_data(self):
        profiles = []
        with mock.patch.object(health, "_read_required_nodes", return_value={"RequiredNode"}), \
             mock.patch.object(health.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1, b"fixture pip rejection")) as run:
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, "pip check failed"):
                    health.check_runtime(self.root)
                profile = Path(run.call_args.kwargs["env"]["USERPROFILE"])
                profiles.append(profile)
                self.assertNotIn(self.root, profile.parents)
                logs = list(profile.glob("runtime-health-*.log"))
                self.assertEqual(len(logs), 1)
                self.assertIn(b"fixture pip rejection", logs[0].read_bytes())
                self.assertEqual(self.snapshot(), self.before)
        self.assertNotEqual(profiles[0], profiles[1])

    def test_startup_isolates_model_scanners_and_keeps_database_lock_check(self):
        child = mock.Mock()
        child.poll.return_value = None
        child.stdout = io.BytesIO()
        child.pid = 123
        with mock.patch.object(health, "_read_required_nodes", return_value={"RequiredNode"}), \
             mock.patch.object(health.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"pip passed")), \
             mock.patch.object(health.subprocess, "Popen", return_value=child) as start, \
             mock.patch.object(health, "_start_log_reader"), \
             mock.patch.object(health, "_finish_log_reader", return_value=None), \
             mock.patch.object(health, "_stop_child") as stop, \
             mock.patch.object(health, "_select_port", return_value=8123), \
             mock.patch.object(health, "_owns_listener", return_value=True), \
             mock.patch.object(health, "_fetch_json", side_effect=[
                 {"system": {"comfyui_version": "0.42.0"}}, {"RequiredNode": {}},
             ]):
            result = health.check_runtime(self.root)
        command = start.call_args.args[0]
        profile = Path(command[command.index("--user-directory") + 1])
        database = command[command.index("--database-url") + 1]
        self.assertNotIn(self.root, profile.parents)
        self.assertEqual(database, "sqlite:///" + (self.user / "comfyui.db").resolve().as_posix())
        self.assertEqual(start.call_args.kwargs["env"]["LORA_MANAGER_RECIPE_CACHE_DB"],
                         str(profile / "lora-manager/recipes.db"))
        self.assertEqual(Path(result["log_path"]).parent, profile)
        self.assertEqual(result["comfyui_version"], "0.42.0")
        self.assertEqual(self.snapshot(), self.before)
        for option in ("--base-directory", "--models-directory",
                       "--input-directory", "--output-directory", "--temp-directory"):
            directory = Path(command[command.index(option) + 1])
            self.assertTrue(directory == profile or profile in directory.parents)
            self.assertTrue(directory.is_dir())
        self.assertIn("--disable-assets", command)
        self.assertEqual(start.call_args.kwargs["cwd"], str(profile))
        self.assertFalse((self.root / "ComfyUI/input").exists())
        self.assertFalse((self.root / "ComfyUI/output").exists())
        self.assertFalse((self.root / "ComfyUI/temp").exists())
        stop.assert_called_once_with(child)

    def test_entrypoint_cannot_automatically_load_installed_extra_model_paths(self):
        comfy = self.root / "ComfyUI"
        (comfy / "extra_model_paths.yaml").write_text("external user models", encoding="utf-8")
        entry = comfy / "main.py"
        entry.write_text(
            "import json, pathlib, sys\n"
            "here = pathlib.Path(__file__).parent\n"
            "config = pathlib.Path(sys.argv[sys.argv.index('--extra-model-paths-config') + 1])\n"
            "print(json.dumps({'automatic_paths': (here / 'extra_model_paths.yaml').exists(), "
            "'custom_paths': json.loads(config.read_text()), 'source_path': sys.path[0]}))\n",
            encoding="utf-8",
        )
        profile = self.work / "isolated"
        profile.mkdir()
        command = health._isolated_entrypoint(comfy, profile)
        result = subprocess.run([sys.executable, *command], cwd=profile,
                                capture_output=True, text=True, check=True, timeout=10)
        observed = json.loads(result.stdout)
        self.assertFalse(observed["automatic_paths"])
        isolated_comfy = profile / "ComfyUI"
        self.assertEqual(observed["custom_paths"], {
            "runtime_health": {"custom_nodes": str(isolated_comfy / "custom_nodes")},
        })
        self.assertEqual(observed["source_path"], str(isolated_comfy))
        self.assertEqual((isolated_comfy / "main.py").read_bytes(), entry.read_bytes())
        self.assertEqual((comfy / "extra_model_paths.yaml").read_text(), "external user models")

    def test_file_relative_node_writes_cannot_reach_installed_code_or_user_data(self):
        comfy = self.root / "ComfyUI"
        (comfy / "folder_paths.py").write_text("from pathlib import Path\n", encoding="utf-8")
        node = comfy / "custom_nodes/comfyui-custom-scripts/probe.py"
        node.parent.mkdir(parents=True)
        node.write_text(
            "from pathlib import Path\n"
            "import folder_paths\n"
            "here = Path(__file__)\n"
            "(here.parent / 'pysssss.json').write_text('probe config')\n"
            "wildcard = Path(folder_paths.__file__).parent / 'models/wildcards/probe.txt'\n"
            "wildcard.parent.mkdir(parents=True, exist_ok=True)\n"
            "wildcard.write_text('probe wildcard')\n"
            "here.write_text('probe rewrote its own program copy')\n",
            encoding="utf-8",
        )
        (comfy / "main.py").write_text(
            "import pathlib, runpy\n"
            "runpy.run_path(str(pathlib.Path(__file__).parent / "
            "'custom_nodes/comfyui-custom-scripts/probe.py'))\n",
            encoding="utf-8",
        )
        excluded = (
            "models/wildcards/owned.txt", "input/owned.png", "output/owned.png",
            "temp/owned.tmp", "extra_model_paths.yaml",
            "custom_nodes/comfyui-custom-scripts/pysssss.json",
            "__pycache__/owned.pyc",
        )
        for relative in excluded:
            path = comfy / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"existing user or generated content")
        before = self.snapshot(self.root)
        profile = self.work / "isolated"
        profile.mkdir()
        command = health._isolated_entrypoint(comfy, profile)
        copied = profile / "ComfyUI"
        for relative in excluded:
            self.assertFalse((copied / relative).exists(), relative)
        self.assertFalse((copied / "user").exists())
        self.assertEqual((copied / "main.py").read_bytes(), (comfy / "main.py").read_bytes())
        self.assertNotEqual((copied / "main.py").stat().st_ino,
                            (comfy / "main.py").stat().st_ino)
        subprocess.run([sys.executable, *command], cwd=profile,
                       capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(self.snapshot(self.root), before)
        self.assertEqual((copied / "models/wildcards/probe.txt").read_text(), "probe wildcard")
        self.assertEqual((copied / "custom_nodes/comfyui-custom-scripts/pysssss.json").read_text(),
                         "probe config")
        self.assertEqual((copied / "custom_nodes/comfyui-custom-scripts/probe.py").read_text(),
                         "probe rewrote its own program copy")


if __name__ == "__main__":
    unittest.main()
