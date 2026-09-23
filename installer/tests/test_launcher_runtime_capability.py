import importlib.util
from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()
