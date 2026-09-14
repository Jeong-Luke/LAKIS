from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src" / "external_ui"))

import serve_ui  # noqa: E402


CHECKPOINT = "fnMomentAnimaTurbo_v40NoTurbo.safetensors"


def graph(*, sam=False, lllite=False, loras=None):
    value = {
        "890:1365": {
            "class_type": "DiffusionModelLoaderKJ",
            "inputs": {"model_name": CHECKPOINT},
        },
        "1925": {
            "class_type": "EasyUseAnimaLoraPreset",
            "inputs": {"loras": json.dumps(loras or [])},
        },
    }
    if sam:
        value["893:891"] = {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"},
        }
    if lllite:
        value["lllite"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "anima-lllite-inpainting-v2.safetensors", "strength_model": 1},
        }
    return value


class LibraryMetadataTests(unittest.TestCase):
    def assert_checkpoint(self, value):
        self.assertEqual(CHECKPOINT, serve_ui._prompt_graph_metadata(value)["checkpoint"])

    def test_case_a_checkpoint_only(self):
        self.assert_checkpoint(graph())

    def test_case_b_checkpoint_and_sam3(self):
        self.assert_checkpoint(graph(sam=True))

    def test_case_c_checkpoint_and_lllite(self):
        self.assert_checkpoint(graph(lllite=True))

    def test_case_d_checkpoint_sam3_and_lllite(self):
        self.assert_checkpoint(graph(sam=True, lllite=True))

    def test_case_e_enabled_lora(self):
        metadata = serve_ui._prompt_graph_metadata(graph(loras=[{"name": "enabled.safetensors", "on": True, "strength": 0.7}]))
        self.assertEqual([{"name": "enabled.safetensors", "strength": 0.7}], metadata["loras"])

    def test_case_f_disabled_lora(self):
        rows = [
            {"name": "enabled.safetensors", "on": True, "strength": 0.7},
            {"name": "disabled.safetensors", "on": False, "strength": 1.0},
        ]
        self.assertEqual([{"name": "enabled.safetensors", "strength": 0.7}], serve_ui._prompt_graph_metadata(graph(loras=rows))["loras"])

    def test_case_g_delete_mode_lora_stack_is_disabled(self):
        rows = [{"name": "ui-enabled.safetensors", "on": False, "strength": 1.0}]
        self.assertEqual([], serve_ui._prompt_graph_metadata(graph(loras=rows))["loras"])


if __name__ == "__main__":
    unittest.main()
