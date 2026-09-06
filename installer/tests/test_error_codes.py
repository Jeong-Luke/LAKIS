import asyncio
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src" / "external_ui"))

import workflow_bridge


class ErrorCodeTests(unittest.TestCase):
    def structured(self, node_id, node_type="TestNode", message="boom"):
        return workflow_bridge.GenerationExecutionError(
            {"exception_type": "TestError", "exception_message": message},
            node_id=node_id, node_type=node_type,
            failure_stage=workflow_bridge.NODE_LABELS.get(node_id, "처리"),
        )

    def test_each_major_generation_stage_has_a_stable_code(self):
        expected = {
            "890:1365": "LKS-MOD-1001", "890:159": "LKS-MOD-1002",
            "890:164": "LKS-MOD-1003", "2133": "LKS-GEN-1201",
            "1744": "LKS-I2I-1001", "1736:1741": "LKS-I2I-1002",
            "1634:1622": "LKS-GEN-1301", "1635": "LKS-GEN-1302",
            "1633:1794": "LKS-GEN-1401", "1633:1612": "LKS-GEN-1402",
            "1530:1826": "LKS-GEN-1501", "1836:2069": "LKS-GEN-1502",
            "1541:1538": "LKS-GEN-1601", "775": "LKS-GEN-1701",
        }
        for node_id, code in expected.items():
            with self.subTest(node_id=node_id):
                self.assertEqual(code, workflow_bridge.WorkflowBridge._public_error(self.structured(node_id))[0])

    def test_root_cause_codes_override_stage_code(self):
        error = self.structured("1634:1622", message="CUDA out of memory")
        self.assertEqual("LKS-GEN-1005", workflow_bridge.WorkflowBridge._public_error(error)[0])
        error = self.structured("1634:1622", message="NaN detected")
        self.assertEqual("LKS-GEN-1006", workflow_bridge.WorkflowBridge._public_error(error)[0])
        self.assertEqual("LKS-GEN-1007", workflow_bridge.WorkflowBridge._public_error(asyncio.TimeoutError())[0])
        stalled = workflow_bridge.GenerationStallError(
            node_id="1634:1622", node_type="KSampler", failure_stage="Initial", inactive_seconds=301
        )
        self.assertEqual("LKS-GEN-1009", workflow_bridge.WorkflowBridge._public_error(stalled)[0])

    def test_unfinished_generation_journal_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "generation-runtime-journal.json"
            journal.write_text(json.dumps({
                "state": "running", "request_id": "req-1", "prompt_id": "prompt-1",
                "stage": "Initial", "last_node_id": "1634:1622",
                "last_node_type": "KSampler", "diagnostic_context": {"model": {"steps": 30}},
            }), encoding="utf-8")
            with patch.object(workflow_bridge, "GENERATION_JOURNAL_PATH", journal):
                bridge = workflow_bridge.WorkflowBridge()
            snapshot = bridge.status.snapshot()
            self.assertEqual("error", snapshot["state"])
            self.assertEqual("LKS-GEN-1008", snapshot["error_code"])
            self.assertEqual("1634:1622", snapshot["error_node_id"])
            self.assertFalse(journal.exists())

    def test_validation_codes(self):
        cases = {
            "Unknown diffusion model: x": "LKS-MOD-1101",
            "FAST workflow requires an Anima-compatible diffusion model": "LKS-MOD-1102",
            "Unknown VAE: x": "LKS-MOD-1103",
            "Unknown CLIP: x": "LKS-MOD-1104",
            "i2i 입력 이미지를 다시 선택해 주세요.": "LKS-I2I-1101",
            "Unsupported sampler": "LKS-CFG-1101",
            "Unsupported scheduler": "LKS-CFG-1102",
            "advanced node settings must be an object": "LKS-CFG-1103",
        }
        for message, code in cases.items():
            with self.subTest(message=message):
                self.assertEqual(code, workflow_bridge.WorkflowBridge._public_error(ValueError(message))[0])

    def test_setting_error_preserves_live_node_declaration(self):
        prompt = json.loads((REPOSITORY_ROOT / "workflows" / "LAKIS_runtime_api_v7.1.json").read_text(encoding="utf-8"))
        node = prompt["890:905"]
        class_type = node["class_type"]
        field = next(
            name for name, value in node["inputs"].items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        )
        schema = {class_type: {"input": {"required": {
            field: ["FLOAT", {"min": 0.0, "max": 100.0, "step": 0.1}]
        }}}}
        with patch.object(workflow_bridge, "_comfy_object_info", return_value=schema):
            with self.assertRaises(workflow_bridge.SettingsValidationError) as raised:
                workflow_bridge._apply_advanced_node_overrides(
                    prompt, {"890:905": {field: 125.0}}
                )
        report = raised.exception.diagnostic()
        self.assertEqual("890:905", report["setting_node_id"])
        self.assertEqual(field, report["setting_name"])
        self.assertEqual(125.0, report["received_value"])
        self.assertEqual(100.0, report["node_declaration"]["max"])


if __name__ == "__main__":
    unittest.main()
