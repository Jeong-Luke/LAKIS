from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_UI_ROOT = REPOSITORY_ROOT / "src" / "external_ui"
RUNTIME_WORKFLOW = REPOSITORY_ROOT / "workflows" / "LAKIS_runtime_api_v7.1.json"
sys.path.insert(0, str(EXTERNAL_UI_ROOT))

try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    sys.modules["aiohttp"] = types.ModuleType("aiohttp")

import workflow_bridge  # noqa: E402


class LegacyGenerationStateTests(unittest.TestCase):
    def test_v733_numeric_strings_are_migrated_without_discarding_valid_fields(self) -> None:
        legacy = {
            "version": 3,
            "generation": {"lakis_mode": "false", "upscale_engine": "lakis_scope"},
            "model": {"steps": "30", "cfg": "5"},
            "output": {"width": "1024", "height": "1600", "seed": "42", "aspect_locked": "false"},
            "camera": {"pos_x": "0.25", "pos_y": "-0.5", "roll": "0"},
            "composition_enabled": "true",
            "node_overrides": {
                "890:1365": {"model_name": "anima_baseV10.safetensors"},
                "1530:1826": {"denoise": "0.3", "cycle": "3"},
                "1836:2069": {"denoise": "0.25", "cycle": 3},
                "1541:1538": {"denoise": "not-a-number", "batch_size": 1},
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "external_ui_user_state.json"
            state_path.write_text(json.dumps(legacy), encoding="utf-8")
            with (
                patch.object(workflow_bridge, "UI_STATE_PATH", state_path),
                patch.object(workflow_bridge, "LEGACY_UI_STATE_PATH", Path(temporary) / "missing-legacy"),
                patch.object(workflow_bridge, "UNSCOPED_UI_STATE_PATH", Path(temporary) / "missing-global"),
                patch.object(workflow_bridge, "TEMPLATE", RUNTIME_WORKFLOW),
                patch.object(workflow_bridge, "AUDIT_PATH", Path(temporary) / "audit.jsonl"),
                patch.object(workflow_bridge, "_comfy_object_info", return_value={}),
            ):
                state = workflow_bridge.load_external_generation_state()

        self.assertIs(False, state["generation"]["lakis_mode"])
        self.assertEqual({"x": 0.25, "y": -0.5, "roll": 0.0}, state["camera"])
        self.assertIs(True, state["composition_enabled"])
        self.assertNotIn("890:1365", state["node_overrides"])
        self.assertEqual(0.3, state["node_overrides"]["1530:1826"]["denoise"])
        self.assertEqual(3, state["node_overrides"]["1530:1826"]["cycle"])
        self.assertEqual(1, state["node_overrides"]["1541:1538"]["batch_size"])
        self.assertNotIn("denoise", state["node_overrides"]["1541:1538"])

    def test_boolean_text_is_not_interpreted_by_python_truthiness(self) -> None:
        self.assertIs(False, workflow_bridge._coerce_bool("false", True))
        self.assertIs(True, workflow_bridge._coerce_bool("true", False))
        self.assertIs(False, workflow_bridge._coerce_bool("unknown", False))

    def test_reported_settings_build_a_prompt_and_keep_model_settings_authoritative(self) -> None:
        state = {
            "generation": {"mode": "detail", "lakis_mode": False, "upscale_engine": "ultimate"},
            "model": {
                "checkpoint": "oneObsessionAnima_v40.safetensors",
                "vae": "qwen_image_vae.safetensors",
                "clip": "qwen_3_06b_base.safetensors",
                "sampler": "euler_ancestral",
                "scheduler": "normal",
                "steps": "30",
                "cfg": "5",
            },
            "output": {"width": "1024", "height": "1600", "seed": "42"},
            "prompt": {},
            "loras": [],
            "lora_enabled": "false",
            "camera": {"pos_x": "0", "pos_y": "0", "pos_z": "0", "roll": "0", "frame_y": "0"},
            "composition_enabled": False,
            "i2i": {"enabled": "false", "denoise": "0.5"},
            "node_overrides": {
                "890:1365": {"model_name": "anima_baseV10.safetensors"},
                "1530:1826": {"denoise": "0.3", "cycle": "3"},
                "1541:1538": {"denoise": 0.12, "batch_size": 1, "tiled_decode": False},
            },
        }
        configuration = {
            "checkpoint": {"options": ["oneObsessionAnima_v40.safetensors"]},
            "vae": {"options": ["qwen_image_vae.safetensors"]},
            "clip": {"options": ["qwen_3_06b_base.safetensors"]},
            "sampler": {"options": list(workflow_bridge.SAMPLER_OPTIONS)},
            "scheduler": {"options": list(workflow_bridge.SCHEDULER_OPTIONS)},
            "lora": {"current": []},
        }
        with (
            patch.object(workflow_bridge, "TEMPLATE", RUNTIME_WORKFLOW),
            patch.object(workflow_bridge, "workflow_configuration", return_value=configuration),
            patch.object(workflow_bridge, "_model_files", return_value=[]),
            patch.object(workflow_bridge, "_preferred_upscaler", return_value=None),
            patch.object(workflow_bridge, "_comfy_object_info", return_value={}),
        ):
            prompt, assertions = workflow_bridge.build_prompt(state)

        self.assertEqual("oneObsessionAnima_v40.safetensors", prompt["890:1365"]["inputs"]["model_name"])
        self.assertEqual(0.3, prompt["1530:1826"]["inputs"]["denoise"])
        self.assertEqual(3, prompt["1530:1826"]["inputs"]["cycle"])
        self.assertEqual("1024x1600", assertions["resolution"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
