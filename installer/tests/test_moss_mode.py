"""Integrated MOSS graphs and state isolation, without model inference."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))
import moss_mode
import moss_workflows
import workflow_bridge as bridge


def schema():
    info = {name: {"input": {"required": {}}} for name in moss_mode.REQUIRED_NODES}
    for key, node, field in moss_mode.LOADERS:
        info[node]["input"]["required"][field] = [[moss_mode.MODEL[key]]]
    info["UNet loader with Name (Image Saver)"]["input"]["required"]["unet_name"][0] += ["anima.safetensors", "moss/custom.safetensors"]
    info["UNet loader with Name (Image Saver)"]["input"]["required"]["weight_dtype"] = [["default", "fp8_e4m3fn"]]
    info["CLIPLoader"]["input"]["required"].update(type=[["moss_image"]], device=[["default", "cpu"]])
    info["KSampler"]["input"]["required"].update(sampler_name=[["euler", "heun"]], scheduler=[["sgm_uniform", "simple"]])
    info["ModelSamplingAuraFlow"]["input"]["required"]["shift"] = ["FLOAT", {"min": 0, "max": 100}]
    info["SkipLayerGuidanceDiTSimple"]["input"]["required"] = {
        "double_layers": ["STRING"], "single_layers": ["STRING"],
        "start_percent": ["FLOAT", {"min": 0, "max": 1}],
        "end_percent": ["FLOAT", {"min": 0, "max": 1}],
    }
    info["LoraLoaderModelOnly"] = {"input": {"required": {"lora_name": [["anima.safetensors", "moss/style.safetensors"]]}}}
    info["LoraLoader"] = copy.deepcopy(info["LoraLoaderModelOnly"])
    return info


def state():
    return {
        "generation": {"engine": "moss", "mode": "moss", "lakis_mode": False},
        "model": dict(moss_mode.MODEL),
        "output": {"width": 1024, "height": 1520, "seed": 42},
        "prompt": {"general": "a ceramic cup", "negative": "blurry"},
        "loras": [{"name": "", "enabled": True, "strength": 1.0}], "lora_enabled": True,
        "composition_enabled": False, "moss_node_overrides": {},
        "moss_regions": {"enabled": False, "regions": []},
    }


class MossGraphTests(unittest.TestCase):
    def build(self, value):
        original = moss_workflows.workflow_path().read_bytes()
        result = moss_mode.build_prompt(value, schema(), Path("fixture-output"), 2**53 - 1,
                                       camera_prompt_builder=lambda inputs: "from above")
        self.assertEqual(moss_workflows.workflow_path().read_bytes(), original)
        return result

    def test_choices_capabilities_and_engine_lora_isolation(self):
        config = moss_mode.configuration(schema(), composition_available=True)
        self.assertTrue(config["ready"])
        self.assertEqual(config["inventory"]["sampler"], ["euler", "heun"])
        self.assertNotIn("anima.safetensors", config["inventory"]["checkpoint"])
        self.assertTrue(config["capabilities"]["regions"])
        self.assertFalse(config["capabilities"]["i2i"])
        with patch.object(bridge, "_comfy_object_info", return_value=schema()):
            self.assertEqual(bridge.lora_inventory("moss")["options"], ["moss/style.safetensors"])
            self.assertEqual(bridge.lora_inventory("anima")["options"], ["anima.safetensors"])

    def test_blank_lora_generates_one_graph_with_the_existing_final_saver(self):
        graph, preflight = self.build(state())
        self.assertEqual(graph["775"]["class_type"], "Image Saver")
        self.assertEqual(graph["775"]["inputs"]["images"], ["9", 0])
        self.assertEqual(graph["775"]["inputs"]["extension"], "png")
        self.assertEqual(graph["7"]["inputs"]["batch_size"], 1)
        self.assertEqual(preflight["enabled_lora_count"], 0)
        self.assertNotIn("11", graph)
        self.assertFalse(any(n["class_type"] == "LoraLoaderModelOnly" for n in graph.values()))
        moss_mode.validate_models(graph, schema())

    def test_moss_startup_restores_its_own_loras_without_reading_anima_workflow_presets(self):
        selected = [{"name": "moss/style.safetensors", "enabled": True, "strength": .7}]
        with (
            patch.object(bridge, "_comfy_object_info", return_value=schema()),
            patch.object(bridge, "_load_external_ui_payload", return_value={"lora": {"current": selected, "enabled": True}}),
            patch.object(bridge, "SAVED_WORKFLOW", Path("must-not-be-read.json")),
        ):
            config = bridge._saved_lora_configuration("moss")
        self.assertEqual(config["current"], selected)
        self.assertEqual(config["options"], ["moss/style.safetensors"])
        self.assertIsNot(config["current"], selected)

    def test_workflow_configuration_exposes_moss_defaults_and_both_advanced_setting_groups(self):
        saved = {
            "generation": {"engine": "moss", "mode": "fast", "profiles": {}},
            "model": {}, "output": {}, "moss_node_overrides": {"moss:2": {"shift": 4.25}},
            "moss_regions": {"enabled": True, "regions": []},
        }
        anima_advanced = {"model": [{"id": "anima-fixture", "fields": []}]}
        with (
            patch.object(bridge, "TEMPLATE", ROOT / "workflows" / "LAKIS_runtime_api_v7.4.json"),
            patch.object(bridge, "_comfy_object_info", return_value=schema()),
            patch.object(bridge, "_live_model_inventories", return_value={"checkpoint": [], "clip": [], "vae": []}),
            patch.object(bridge, "load_external_generation_state", return_value=saved),
            patch.object(bridge, "_load_external_ui_payload", return_value={}),
            patch.object(bridge, "load_external_prompt_state", return_value={}),
            patch.object(bridge, "load_external_prompt_enabled", return_value={}),
            patch.object(bridge, "load_external_prompt_bundle", return_value={}),
            patch.object(bridge, "advanced_node_configuration", return_value=anima_advanced),
        ):
            result = bridge.workflow_configuration(schema())
        self.assertEqual(result["sampler"]["current"], "euler")
        self.assertEqual(result["scheduler"]["current"], "sgm_uniform")
        self.assertEqual(result["generation_state"]["model"], moss_mode.MODEL)
        self.assertEqual(result["generation_state"]["output"]["width"], 1024)
        self.assertEqual(result["generation_state"]["moss_regions"], saved["moss_regions"])
        self.assertEqual(result["advanced_nodes_by_engine"]["anima"], anima_advanced)
        fields = result["advanced_nodes_by_engine"]["moss"]["model"]
        self.assertEqual(sum(len(node["fields"]) for node in fields), 7)

    def test_regions_lora_sampling_and_composition_reach_the_graph(self):
        value = state()
        value["model"].update(checkpoint="moss/custom.safetensors", sampler="heun", scheduler="simple")
        value["composition_enabled"] = True
        value["moss_node_overrides"] = {"moss:2": {"shift": 4.25}}
        value["loras"] = [{"name": "moss/style.safetensors", "enabled": True, "strength": .8}]
        value["moss_regions"] = {"enabled": True, "regions": [{
            "id": "sign", "label": "text", "caption": "a sign", "negative_prompt": "cracks",
            "text": "안녕하세요", "bbox": [100, 200, 800, 900],
        }]}
        original = copy.deepcopy(value)
        graph, preflight = self.build(value)
        positive = json.loads(moss_workflows.get_input(graph, "5", "text"))
        negative = json.loads(moss_workflows.get_input(graph, "6", "text"))
        self.assertEqual(positive["summary"]["caption"], "a ceramic cup, from above")
        self.assertEqual(positive["items"][0]["text"], "안녕하세요")
        self.assertEqual(negative["items"][0]["caption"], "cracks")
        self.assertEqual(moss_workflows.get_input(graph, "8", "sampler_name"), "heun")
        self.assertEqual(moss_workflows.get_input(graph, "8", "scheduler"), "simple")
        self.assertEqual(graph["2"]["inputs"]["shift"], 4.25)
        lora_node = graph[graph["2"]["inputs"]["model"][0]]
        self.assertEqual(lora_node["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(lora_node["inputs"]["lora_name"], "moss/style.safetensors")
        self.assertEqual(moss_workflows.get_input(graph, "775", "sampler_name"), "heun")
        self.assertEqual(moss_workflows.get_input(graph, "775", "positive"),
                         moss_workflows.get_input(graph, "5", "text"))
        self.assertEqual(moss_workflows.get_input(graph, "775", "negative"),
                         moss_workflows.get_input(graph, "6", "text"))
        self.assertEqual(preflight["enabled_lora_count"], 1)
        self.assertEqual(value, original)

    def test_missing_moss_workflow_is_reported_without_using_anima(self):
        with patch.object(moss_workflows, "workflow_path", return_value=Path("missing-moss.json")):
            with self.assertRaises(moss_mode.MossValidationError) as raised:
                moss_mode.build_prompt(state(), schema(), Path("fixture-output"), 2**53 - 1)
        self.assertEqual(raised.exception.code, "LKS-MOSS-1010")

    def test_moss_bridge_does_not_read_anima_template(self):
        with patch.object(bridge, "TEMPLATE", Path("missing-anima.json")), \
                patch.object(bridge, "_wait_for_comfy_object_info", return_value=schema()), \
                patch.object(bridge, "configured_output_root", return_value=Path("fixture-output")):
            graph, _ = bridge.build_prompt(state())
        self.assertEqual(moss_workflows.get_input(graph, "775", "seed_value"), 42)

    def test_locked_or_foreign_inputs_fail_before_submission(self):
        for change in (
            {"i2i": {"enabled": True}},
            {"inpaint": {"enabled": True}},
            {"scene_controls": {"enabled": True}},
            {"node_overrides": {"2135": {"pos_x": .2}}},
            {"loras": [{"name": "anima.safetensors", "enabled": True, "strength": 1}]},
            {"moss_detail": {"enabled": True}},
            {"prompt": {"general": "__unresolved__"}},
            {"composition_enabled": True, "camera": {"x": float("nan")}},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.build({**state(), **change})

    def test_live_revalidation_rejects_a_removed_moss_lora(self):
        value = state()
        value["loras"] = [{"name": "moss/style.safetensors", "enabled": True, "strength": 1}]
        graph, _ = self.build(value)
        info = schema()
        info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"] = [[]]
        with self.assertRaises(ValueError):
            moss_mode.validate_models(graph, info)

    def test_model_shape_and_sampling_boundaries(self):
        for model in ({"sampler": "not_supported"}, {"scheduler": "not_supported"}, {"cfg": True}):
            value = state()
            value["model"].update(model)
            with self.assertRaises(ValueError):
                self.build(value)
        value = state()
        value["output"].update(width=1536, height=1536)
        with self.assertRaises(ValueError):
            self.build(value)


class MossStateTests(unittest.TestCase):
    def test_moss_fields_and_inactive_anima_profile_survive_save_reload_and_legacy_save(self):
        with tempfile.TemporaryDirectory(prefix="lakis-moss-state-") as directory:
            root = Path(directory)
            with (
                patch.multiple(bridge, UI_STATE_PATH=root / "state.json", LEGACY_UI_STATE_PATH=root / "legacy.json",
                               UNSCOPED_UI_STATE_PATH=root / "global.json"),
                patch.object(bridge, "_enum_options", side_effect=lambda node, field, *args: schema()["KSampler"]["input"]["required"][field][0]),
                patch.object(bridge, "_clean_advanced_node_overrides", side_effect=lambda raw, **kwargs: raw),
            ):
                value = state()
                anima = {"model": {**value["model"], "checkpoint": "anima.safetensors"},
                         "output": {**value["output"], "seed_mode": "current", "aspect_locked": True},
                         "prompt": {"general": "keep ANIMA"}, "future": {"keep": True}}
                generation = {"engine": "moss", "mode": "fast", "profiles": {"anima": anima}}
                regions = {"enabled": True, "regions": [], "future_region_setting": {"keep": True}}
                bridge.save_external_generation_state(
                    value["model"], value["output"], generation=generation,
                    moss_regions=regions, moss_node_overrides={"moss:2": {"shift": 4.25}},
                    i2i={"enabled": False, "image_name": "kept.png"}, continuous={"enabled": True, "count": 2},
                )
                loaded = bridge.load_external_generation_state()
                self.assertEqual(loaded["moss_regions"], regions)
                self.assertEqual(loaded["moss_node_overrides"]["moss:2"]["shift"], 4.25)
                self.assertEqual(loaded["generation"]["profiles"]["anima"], anima)
                self.assertEqual(loaded["i2i"]["image_name"], "kept.png")
                bridge.save_external_generation_state(
                    value["model"], value["output"], generation={"engine": "moss", "mode": "fast"})
                reloaded = bridge.load_external_generation_state()
                self.assertEqual(reloaded["moss_regions"], regions)
                self.assertEqual(reloaded["generation"]["profiles"]["anima"], anima)


if __name__ == "__main__":
    unittest.main()
