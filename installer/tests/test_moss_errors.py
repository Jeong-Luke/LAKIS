"""Behavioral MOSS error classification; no backend requests or user state."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/external_ui"))
import moss_errors
import moss_mode
import workflow_bridge as bridge
from installer.tests.test_moss_mode import schema, state


class MossErrorTests(unittest.TestCase):
    def build(self, value, info=None):
        return moss_mode.build_prompt(
            value,
            schema() if info is None else info, Path("test-output"), 2**53 - 1,
        )

    def test_validation_categories_preserve_public_codes_and_input(self):
        cases = [
            ({"model": {**moss_mode.MODEL, "checkpoint": "anima.safetensors"}}, "LKS-MOSS-1002"),
            ({"loras": [{"name": "anima.safetensors", "enabled": True, "strength": 1}]}, "LKS-MOSS-1003"),
            ({"model": {**moss_mode.MODEL, "sampler": "unsupported"}}, "LKS-MOSS-1004"),
            ({"model": {**moss_mode.MODEL, "scheduler": "unsupported"}}, "LKS-MOSS-1005"),
            ({"moss_node_overrides": {"moss:2": {"shift": -1}}}, "LKS-MOSS-1006"),
            ({"moss_regions": {"enabled": True, "regions": [{"id": "a", "label": "text",
                "caption": "sign", "bbox": [0, 0, 100, 100]}]}}, "LKS-MOSS-1007"),
            ({"i2i": {"enabled": True}}, "LKS-MOSS-1008"),
            ({"output": {"width": 1025, "height": 1024, "seed": 42}}, "LKS-MOSS-1009"),
        ]
        for change, expected in cases:
            value = {**state(), **change}
            before = copy.deepcopy(value)
            with self.subTest(expected=expected):
                with self.assertRaises(moss_errors.MossValidationError) as raised:
                    self.build(value)
                code, message = bridge.WorkflowBridge._public_error(raised.exception)
                self.assertEqual(expected, code)
                self.assertNotIn("anima.safetensors", message)
                self.assertEqual(value, before)
                self.assertEqual("moss", raised.exception.diagnostic()["generation_engine"])

    def test_missing_runtime_and_models_are_distinct(self):
        info = schema()
        del info["EmptyFlux2LatentImage"]
        with self.assertRaises(moss_errors.MossValidationError) as raised:
            self.build(state(), info)
        self.assertEqual("LKS-MOSS-1001", raised.exception.code)
        info = schema()
        info["VAELoader"]["input"]["required"]["vae_name"][0] = []
        with self.assertRaises(moss_errors.MossValidationError) as raised:
            self.build(state(), info)
        self.assertEqual("LKS-MOSS-1002", raised.exception.code)

    def test_stage_errors_are_engine_scoped_and_common_causes_take_priority(self):
        for node_type, expected in {
            "UNETLoader": "LKS-MOSS-1101", "CLIPLoader": "LKS-MOSS-1102",
            "VAELoader": "LKS-MOSS-1103", "CLIPTextEncode": "LKS-MOSS-1201",
            "KSampler": "LKS-MOSS-1202", "VAEDecode": "LKS-MOSS-1203",
            "Image Saver": "LKS-MOSS-1204", "LoraLoaderModelOnly": "LKS-MOSS-1205",
            "SkipLayerGuidanceDiTSimple": "LKS-MOSS-1206",
            "EmptyFlux2LatentImage": "LKS-MOSS-1207",
        }.items():
            error = bridge.GenerationExecutionError(
                {"exception_message": "test failure"}, node_id="775",
                node_type=node_type, failure_stage="test",
            )
            with self.subTest(node_type=node_type):
                self.assertEqual(expected, bridge.WorkflowBridge._public_error(error, engine="moss")[0])
                self.assertEqual("LKS-GEN-1701", bridge.WorkflowBridge._public_error(error, engine="anima")[0])
        for message, expected in (
            ("CUDA out of memory", "LKS-GEN-1005"),
            ("Permission denied", "LKS-GEN-1703"),
            ("No space left on device", "LKS-GEN-1704"),
        ):
            error = bridge.GenerationExecutionError(
                {"exception_message": message}, node_id="775",
                node_type="Image Saver", failure_stage="test",
            )
            self.assertEqual(expected, bridge.WorkflowBridge._public_error(error, engine="moss")[0])

    def test_rejection_output_and_unknown_errors_keep_engine_identity(self):
        for error, expected in (
            (bridge.PromptRejectedError(400, {"node_errors": {}}), "LKS-MOSS-1011"),
            (bridge.FinalOutputNotFoundError("missing"), "LKS-MOSS-1208"),
            (RuntimeError("unknown"), "LKS-MOSS-1901"),
        ):
            self.assertEqual(expected, bridge.WorkflowBridge._public_error(error, engine="moss")[0])
        diagnostic = bridge.WorkflowBridge._diagnostic_context(state())
        self.assertEqual("moss", diagnostic["generation"]["engine"])

    def test_public_catalog_is_documented_and_no_lora_stays_valid(self):
        documentation = (ROOT / "ERROR_CODES.md").read_text(encoding="utf-8")
        for code in moss_errors.MESSAGES:
            self.assertIn(code, documentation)
        graph, result = self.build(state())
        self.assertEqual(0, result["enabled_lora_count"])
        self.assertFalse(any(n["class_type"] == "LoraLoaderModelOnly" for n in graph.values()))


if __name__ == "__main__":
    unittest.main()
