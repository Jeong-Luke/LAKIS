import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "src" / "external_ui" / "workflow_bridge.py"
SPEC = importlib.util.spec_from_file_location("lakis_workflow_warmup", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StartupWarmupTests(unittest.TestCase):
    def test_dependency_graph_excludes_unrelated_saver(self):
        graph = {
            "model": {"inputs": {}, "class_type": "ModelLoader"},
            "sample": {"inputs": {"model": ["model", 0]}, "class_type": "Sampler"},
            "decode": {"inputs": {"samples": ["sample", 0]}, "class_type": "VAEDecode"},
            "save": {"inputs": {"images": ["decode", 0]}, "class_type": "SaveImage"},
        }
        warm = MODULE._dependency_only(graph, "decode")
        self.assertEqual(set(warm), {"model", "sample", "decode"})
        self.assertNotIn("save", warm)

    def test_warmup_uses_small_single_step_without_loras(self):
        config = {
            "checkpoint": {"current": "base.safetensors"},
            "vae": {"current": "vae.safetensors"},
            "clip": {"current": "clip.safetensors"},
            "sampler": {"current": "euler"},
            "scheduler": {"current": "normal"},
        }
        with patch.object(MODULE, "workflow_configuration", return_value=config):
            state = MODULE.WorkflowBridge._warmup_application_state()
        self.assertEqual(state["model"]["steps"], 1)
        self.assertEqual((state["output"]["width"], state["output"]["height"]), (256, 256))
        self.assertFalse(state["lora_enabled"])
        self.assertEqual(state["loras"], [])
        self.assertFalse(state["i2i"]["enabled"])

    def test_low_memory_profile_skips_without_building_prompt(self):
        bridge = MODULE.WorkflowBridge()
        with patch.object(bridge, "_vram_total", return_value=6 * 1024 ** 3), \
             patch.object(MODULE, "build_prompt") as build:
            result = bridge.warmup()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "vram_below_8_gib")
        build.assert_not_called()

    def test_real_warmup_graph_has_no_final_or_detail_nodes(self):
        config = {
            "checkpoint": {"current": "base.safetensors", "options": ["base.safetensors"]},
            "vae": {"current": "vae.safetensors", "options": ["vae.safetensors"]},
            "clip": {"current": "clip.safetensors", "options": ["clip.safetensors"]},
            "sampler": {"current": "euler", "options": ["euler"]},
            "scheduler": {"current": "normal", "options": ["normal"]},
            "lora": {"current": [], "profile_index": 0},
        }
        with patch.object(MODULE, "TEMPLATE", REPO / "workflows" / "LAKIS_runtime_api_v7.1.json"), \
             patch.object(MODULE, "workflow_configuration", return_value=config), \
             patch.object(MODULE, "_is_anima_checkpoint", return_value=True):
            state = MODULE.WorkflowBridge._warmup_application_state()
            graph, _ = MODULE.build_prompt(state)
            warm, target = MODULE._warmup_graph(graph, True)
        self.assertIn("890:1365", warm)
        self.assertIn("890:159", warm)
        self.assertIn("890:164", warm)
        self.assertIn("1634:1622", warm)
        self.assertEqual(target, "lakis_startup_warmup_preview")
        self.assertIn(target, warm)
        self.assertIn("lakis_startup_warmup_decode", warm)
        self.assertEqual(warm[target]["class_type"], "PreviewImage")
        self.assertNotIn(MODULE.FINAL_NODE, warm)
        self.assertFalse({"1530:1826", "1836:2069", "1541:1538"} & set(warm))

    def test_lakis_detail_routes_single_pass_detail_into_scope(self):
        config = {
            "checkpoint": {"current": "base.safetensors", "options": ["base.safetensors"]},
            "vae": {"current": "vae.safetensors", "options": ["vae.safetensors"]},
            "clip": {"current": "clip.safetensors", "options": ["clip.safetensors"]},
            "sampler": {"current": "euler", "options": ["euler"]},
            "scheduler": {"current": "normal", "options": ["normal"]},
            "lora": {"current": [], "profile_index": 0},
        }
        with patch.object(MODULE, "TEMPLATE", REPO / "workflows" / "LAKIS_runtime_api_v7.1.json"), \
             patch.object(MODULE, "workflow_configuration", return_value=config), \
             patch.object(MODULE, "_is_anima_checkpoint", return_value=True), \
             patch.object(MODULE, "DEVELOPMENT", False):
            state = MODULE.WorkflowBridge._warmup_application_state()
            state["generation"].update({"mode": "detail", "lakis_mode": True})
            graph, _ = MODULE.build_prompt(state)
        self.assertEqual(graph["lakis:face_scope"]["class_type"], "LAKIS_DETAIL")
        self.assertEqual(graph["1541:1538"]["class_type"], "LAKIS_SCOPE")
        self.assertEqual(graph["1541:1538"]["inputs"]["image"], ["lakis:face_scope", 0])
        self.assertNotIn("1530:1826", graph)
        self.assertNotIn("1836:2069", graph)


if __name__ == "__main__":
    unittest.main(verbosity=2)
