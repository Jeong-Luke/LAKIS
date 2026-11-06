"""Compile and exercise the production native updater's bridge contracts."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer"))
import build_updater_bridge as native


class NativeEngineBridgeTests(unittest.TestCase):
    def test_native_continuation_contract(self):
        with tempfile.TemporaryDirectory(prefix="lakis-native-bridge-") as temporary:
            root = Path(temporary)
            native.compile_native(
                root / "LAKIS.exe", [ROOT / "installer/LAKIS_Launcher.cs"])
            native.compile_native(
                root / "LAKIS_Updater.exe", [ROOT / "installer/LAKIS_Updater.cs"])
            shutil.copyfile(root / "LAKIS_Updater.exe", root / "LAKIS_Patcher.exe")
            for name, defines in (
                ("NativeEngineBridgeContract.exe", ()),
                ("NativeEngineBridgeRuntimeContract.exe", ("LAKIS_RUNTIME_BRIDGE",)),
            ):
                harness = root / name
                native.compile_native(
                    harness,
                    [ROOT / "installer/LAKIS_Updater.cs",
                     ROOT / "installer/tests/NativeEngineBridgeContract.cs"],
                    main="NativeEngineBridgeContract",
                    defines=defines,
                )
                result = subprocess.run(
                    [str(harness), str(root)], check=True, capture_output=True, text=True)
                self.assertIn("PASS: manifest version routing", result.stdout)


if __name__ == "__main__":
    unittest.main()
