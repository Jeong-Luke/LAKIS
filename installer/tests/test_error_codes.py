import asyncio
import json
from pathlib import Path
import struct
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

    def test_stale_generation_allowance_is_removed_on_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowance = root / "allow-next.json"
            journal = root / "generation-runtime-journal.json"
            allowance.write_text('{"stale": true}', encoding="utf-8")
            with patch.object(workflow_bridge, "ALLOW_FILE", allowance), patch.object(
                workflow_bridge, "GENERATION_JOURNAL_PATH", journal
            ):
                workflow_bridge.WorkflowBridge()
            self.assertFalse(allowance.exists())

    def test_generation_allowance_conflict_has_documented_code(self):
        error_codes = (REPOSITORY_ROOT / "ERROR_CODES.md").read_text(encoding="utf-8")
        serve_ui = (REPOSITORY_ROOT / "src" / "external_ui" / "serve_ui.py").read_text(encoding="utf-8")
        self.assertIn("LKS-GEN-1010", error_codes)
        self.assertIn('"error_code": "LKS-GEN-1010"', serve_ui)

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

    @staticmethod
    def write_safetensors_header(path, tensors):
        header = json.dumps(tensors, separators=(",", ":")).encode("utf-8")
        path.write_bytes(struct.pack("<Q", len(header)) + header)

    def test_anima_checkpoint_detection_uses_tensor_architecture_without_filename_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "screenChantvMerge_v11.safetensors"
            tensors = {
                name: {"dtype": "BF16", "shape": shape, "data_offsets": [0, 0]}
                for name, shape in workflow_bridge.ANIMA_TENSOR_SIGNATURE.items()
            }
            self.write_safetensors_header(model, tensors)
            with patch.object(workflow_bridge, "_model_roots", return_value=[root]):
                self.assertTrue(workflow_bridge._is_anima_checkpoint(model.name))

    def test_anima_checkpoint_detection_accepts_wrapped_tensor_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "creator_merge_v2.safetensors"
            tensors = {
                "model.diffusion_model." + name.removeprefix("net."): {
                    "dtype": "BF16", "shape": shape, "data_offsets": [0, 0]
                }
                for name, shape in workflow_bridge.ANIMA_TENSOR_SIGNATURE.items()
            }
            self.write_safetensors_header(model, tensors)
            with patch.object(workflow_bridge, "_model_roots", return_value=[root]):
                self.assertTrue(workflow_bridge._is_anima_checkpoint(model.name))

    def test_non_anima_or_invalid_safetensors_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            other = root / "other_model.safetensors"
            invalid = root / "broken_model.safetensors"
            self.write_safetensors_header(other, {
                "net.x_embedder.proj.1.weight": {
                    "dtype": "BF16", "shape": [1024, 16], "data_offsets": [0, 0]
                }
            })
            invalid.write_bytes(struct.pack("<Q", 999_999_999))
            with patch.object(workflow_bridge, "_model_roots", return_value=[root]):
                self.assertFalse(workflow_bridge._is_anima_checkpoint(other.name))
                self.assertFalse(workflow_bridge._is_anima_checkpoint(invalid.name))

    def test_anima_filename_does_not_bypass_architecture_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mislabeled = root / "not_really_anima_model.safetensors"
            self.write_safetensors_header(mislabeled, {
                "net.x_embedder.proj.1.weight": {
                    "dtype": "BF16", "shape": [1024, 16], "data_offsets": [0, 0]
                }
            })
            with patch.object(workflow_bridge, "_model_roots", return_value=[root]):
                self.assertFalse(workflow_bridge._is_anima_checkpoint(mislabeled.name))

    def test_missing_runtime_nodes_have_a_specific_code_and_sorted_detail(self):
        error = workflow_bridge.MissingRuntimeNodesError(["ZNode", "ANode", "ZNode"])
        code, message = workflow_bridge.WorkflowBridge._public_error(error)
        self.assertEqual("LKS-NODE-1201", code)
        self.assertIn("사용자 노드", message)
        self.assertEqual(("ANode", "ZNode"), error.node_types)
        self.assertIn("ANode, ZNode", str(error))

    def test_specific_runtime_and_final_output_failures_have_distinct_codes(self):
        cases = [
            (workflow_bridge.InvalidGenerationRequestError("bad json"), "LKS-CFG-1001"),
            (workflow_bridge.InvalidGenerationRequestError("empty", reason="empty_body"), "LKS-CFG-1002"),
            (workflow_bridge.InvalidGenerationRequestError("large", reason="body_too_large"), "LKS-CFG-1003"),
            (workflow_bridge.MissingRuntimeNodesError(["AnimaLLLiteApply_sdscripts"]), "LKS-NODE-1202"),
            (workflow_bridge.MissingRuntimeNodesError(["LAKIS_LocalInpaintPrepare"]), "LKS-NODE-1203"),
            (workflow_bridge.MissingRuntimeNodesError(["Image Saver"]), "LKS-NODE-1204"),
            (workflow_bridge.FinalOutputNotFoundError("not found"), "LKS-GEN-1702"),
            (self.structured("775", message="Permission denied"), "LKS-GEN-1703"),
            (self.structured("775", message="No space left on device"), "LKS-GEN-1704"),
            (self.structured("1541:1538", message="CUDA error: unknown error"), "LKS-GEN-1004"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, workflow_bridge.WorkflowBridge._public_error(error)[0])

    def test_local_inpaint_stages_have_distinct_codes(self):
        expected = {
            "lakis:inpaint_mask_loader": "LKS-INP-1001",
            "lakis:inpaint_v2_prepare": "LKS-INP-1002",
            "lakis:inpaint_encode": "LKS-INP-1003",
            "lakis:inpaint_lllite": "LKS-INP-1004",
            "lakis:inpaint_color_match": "LKS-INP-1005",
            "lakis:inpaint_final_composite": "LKS-INP-1006",
        }
        for node_id, code in expected.items():
            with self.subTest(node_id=node_id):
                error = self.structured(node_id, node_type="InpaintNode")
                self.assertEqual(code, workflow_bridge.WorkflowBridge._public_error(error)[0])

    def test_runtime_node_preflight_checks_every_unique_prompt_type(self):
        prompt = {
            "1": {"class_type": "Present", "inputs": {}},
            "2": {"class_type": "MissingB", "inputs": {}},
            "3": {"class_type": "MissingA", "inputs": {}},
            "4": {"class_type": "MissingB", "inputs": {}},
        }
        self.assertEqual(
            ["MissingA", "MissingB"],
            workflow_bridge._missing_runtime_node_types(prompt, {"Present": {}}),
        )

    def test_setting_error_preserves_live_node_declaration(self):
        prompt = json.loads((REPOSITORY_ROOT / "workflows" / "LAKIS_runtime_api_v7.4.json").read_text(encoding="utf-8"))
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

    @staticmethod
    def live_schema(checkpoints, loras=()):
        return {
            "DiffusionModelLoaderKJ": {"input": {"required": {"model_name": [list(checkpoints), {}]}}},
            "VAELoader": {"input": {"required": {"vae_name": [["qwen_image_vae.safetensors"], {}]}}},
            "CLIPLoader": {"input": {"required": {"clip_name": [["qwen_3_06b_base.safetensors"], {}]}}},
            "LoraLoader": {"input": {"required": {"lora_name": [list(loras), {}]}}},
        }

    def test_model_inventory_uses_active_runtime_not_foreign_filesystem(self):
        schema = self.live_schema(["anima_baseV10.safetensors"])
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory)
            (foreign / "foreign.safetensors").write_bytes(b"foreign")
            with patch.object(workflow_bridge, "_comfy_object_info", return_value=schema), patch.object(
                workflow_bridge, "_model_roots", return_value=[foreign]
            ):
                inventory = workflow_bridge.model_inventory()
        self.assertEqual(["anima_baseV10.safetensors"], inventory["checkpoint"])

    def test_registered_shared_model_is_visible_but_unregistered_file_is_not(self):
        schema = self.live_schema(["anima_baseV10.safetensors", "shared\\registered.safetensors"])
        with tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory)
            (foreign / "unregistered.safetensors").write_bytes(b"foreign")
            with patch.object(workflow_bridge, "_comfy_object_info", return_value=schema), patch.object(
                workflow_bridge, "_model_roots", return_value=[foreign]
            ):
                inventory = workflow_bridge.model_inventory()
        self.assertIn("shared\\registered.safetensors", inventory["checkpoint"])
        self.assertNotIn("unregistered.safetensors", inventory["checkpoint"])

    def test_ic_light_weights_are_hidden_from_checkpoint_selector(self):
        schema = self.live_schema([
            "IC-Light\\iclight_sd15_fbc.safetensors",
            "IC-Light/iclight_sd15_fc.safetensors",
            "iclight_sd15_fc.safetensors",
            "anima_baseV10.safetensors",
            "shared\\novaAnimeAM_v40.safetensors",
        ])
        with patch.object(workflow_bridge, "_comfy_object_info", return_value=schema):
            inventory = workflow_bridge.model_inventory()
        self.assertEqual(
            ["anima_baseV10.safetensors", "shared\\novaAnimeAM_v40.safetensors"],
            inventory["checkpoint"],
        )

    def test_persisted_live_model_is_preserved_and_stale_model_falls_back(self):
        schema = self.live_schema(["anima_baseV10.safetensors", "other.safetensors"])
        base_saved = {
            "output": {}, "generation": {}, "camera": {}, "node_overrides": {},
            "composition_enabled": True, "wildcard_enabled": False,
        }
        with patch.object(workflow_bridge, "TEMPLATE", REPOSITORY_ROOT / "workflows" / "LAKIS_runtime_api_v7.4.json"), patch.object(
            workflow_bridge, "_comfy_object_info", return_value=schema
        ), patch.object(
            workflow_bridge, "_saved_lora_configuration", return_value={"current": [], "options": [], "enabled": True}
        ), patch.object(workflow_bridge, "load_external_prompt_state", return_value={}), patch.object(
            workflow_bridge, "load_external_prompt_enabled", return_value={}
        ), patch.object(workflow_bridge, "load_external_prompt_bundle", return_value={}):
            with patch.object(workflow_bridge, "load_external_generation_state", return_value={
                **base_saved, "model": {"checkpoint": "other.safetensors"}
            }):
                self.assertEqual("other.safetensors", workflow_bridge.workflow_configuration()["checkpoint"]["current"])
            with patch.object(workflow_bridge, "load_external_generation_state", return_value={
                **base_saved, "model": {"checkpoint": "foreign.safetensors"}
            }):
                self.assertEqual("anima_baseV10.safetensors", workflow_bridge.workflow_configuration()["checkpoint"]["current"])

    def test_lora_inventory_uses_active_runtime_enum(self):
        schema = self.live_schema(["anima_baseV10.safetensors"], ["characters\\new_lora.safetensors"])
        with patch.object(workflow_bridge, "_comfy_object_info", return_value=schema):
            inventory = workflow_bridge.lora_inventory()
        self.assertEqual(["characters\\new_lora.safetensors"], inventory["options"])
        self.assertEqual(1, inventory["count"])


if __name__ == "__main__":
    unittest.main()
