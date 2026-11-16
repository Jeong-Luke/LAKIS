import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "external_ui" / "launch_lakis.py"
SPEC = importlib.util.spec_from_file_location("lakis_launch_capability", MODULE_PATH)
launch_lakis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(launch_lakis)


class RuntimeCapabilityTests(unittest.TestCase):
    def test_metadata_node_is_not_a_runtime_requirement(self):
        workflow = {
            "metadata": {"class_type": "LAKIS_ExecutionSettings"},
            "real": {"class_type": "Image Saver"},
        }

        required = launch_lakis.required_runtime_node_types(workflow)

        self.assertNotIn("LAKIS_ExecutionSettings", required)
        self.assertIn("Image Saver", required)
        self.assertTrue(launch_lakis.PUBLIC_DYNAMIC_NODE_TYPES <= required)

    def test_missing_dynamic_scope_loader_blocks_runtime_readiness(self):
        workflow = {"real": {"class_type": "Image Saver"}}
        info = {name: {} for name in launch_lakis.required_runtime_node_types(workflow)}
        del info["LAKISScopeUpscaleModelLoader"]
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.read.return_value = json.dumps(info).encode()
        with patch.object(Path, "read_text", return_value=json.dumps(workflow)), \
                patch.object(launch_lakis, "urlopen", return_value=response):
            ready, missing, error = launch_lakis.runtime_capability_check()
        self.assertFalse(ready)
        self.assertEqual(missing, ["LAKISScopeUpscaleModelLoader"])
        self.assertIsNone(error)

        info["LAKISScopeUpscaleModelLoader"] = {}
        response.read.return_value = json.dumps(info).encode()
        with patch.object(Path, "read_text", return_value=json.dumps(workflow)), \
                patch.object(launch_lakis, "urlopen", return_value=response):
            self.assertEqual(launch_lakis.runtime_capability_check(), (True, [], None))


if __name__ == "__main__":
    unittest.main()
