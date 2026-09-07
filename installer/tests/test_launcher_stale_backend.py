import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "src" / "external_ui" / "launch_lakis.py"
SPEC = importlib.util.spec_from_file_location("lakis_launch_recovery", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeProcess:
    def __init__(self, pid, executable, command):
        self.pid = pid
        self._executable = executable
        self._command = command

    def exe(self):
        return self._executable

    def cmdline(self):
        return list(self._command)


class LauncherStaleBackendTests(unittest.TestCase):
    def setUp(self):
        self.original_psutil = MODULE.psutil
        self.original_fetch_json = MODULE.fetch_json
        self.pid = 4242
        self.process = FakeProcess(
            self.pid,
            str(MODULE.PYTHON),
            [str(MODULE.PYTHON), "-s", str(MODULE.COMFY_MAIN), "--port", str(MODULE.COMFY_PORT)],
        )
        connection = SimpleNamespace(
            laddr=SimpleNamespace(port=MODULE.COMFY_PORT),
            status="LISTEN",
            pid=self.pid,
        )
        MODULE.psutil = SimpleNamespace(
            CONN_LISTEN="LISTEN",
            Error=Exception,
            net_connections=lambda kind: [connection],
            Process=lambda pid: self.process,
        )
        MODULE.fetch_json = lambda url, timeout=1.0: {
            "system": {"argv": [str(MODULE.COMFY_MAIN)]}
        }
        self.state = {
            "installation_id": MODULE.INSTALLATION_ID,
            "comfyui_started_by_lakis": True,
            "comfyui_owned_pid": self.pid,
        }

    def tearDown(self):
        MODULE.psutil = self.original_psutil
        MODULE.fetch_json = self.original_fetch_json

    def test_exact_owned_backend_is_recoverable(self):
        self.assertIs(MODULE.find_owned_stale_backend(self.state), self.process)

    def test_other_installation_is_never_recovered(self):
        self.state["installation_id"] = "another-installation"
        self.assertIsNone(MODULE.find_owned_stale_backend(self.state))

    def test_unrecorded_pid_is_never_recovered(self):
        self.state["comfyui_owned_pid"] = self.pid + 1
        self.assertIsNone(MODULE.find_owned_stale_backend(self.state))

    def test_other_comfyui_main_is_never_recovered(self):
        MODULE.fetch_json = lambda url, timeout=1.0: {
            "system": {"argv": [str(MODULE.COMFY_MAIN.parent / "other-main.py")]}
        }
        self.assertIsNone(MODULE.find_owned_stale_backend(self.state))

    def test_wrong_python_or_command_is_never_recovered(self):
        self.process._executable = str(MODULE.PYTHON.parent / "other-python.exe")
        self.assertIsNone(MODULE.find_owned_stale_backend(self.state))
        self.process._executable = str(MODULE.PYTHON)
        self.process._command = [str(MODULE.PYTHON), "-s", "other-main.py", "--port", str(MODULE.COMFY_PORT)]
        self.assertIsNone(MODULE.find_owned_stale_backend(self.state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
