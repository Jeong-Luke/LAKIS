"""Independent ANIMA box compilation and prompt override integration."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/external_ui"))
import anima_regions
import anima_reference
import workflow_bridge as bridge


def schema():
    names = ("ComfyCoupleBasePrompt", "ComfyCoupleRegionPainter", "ComfyCoupleMask",
             "SolidMask", "MaskComposite", "CLIPTextEncode", "ConditioningSetMask", "ConditioningCombine")
    return {name: {"input": {"required": {}}} for name in names}


def graph():
    return {
        "1634:1721": {"inputs": {"model": ["base", 0]}},
        "1634:1622": {"inputs": {"positive": ["positive", 0], "negative": ["negative", 0]}},
        "1633:1612": {"inputs": {"model": ["highrez", 0],
                               "positive": ["hr_positive", 0], "negative": ["hr_negative", 0]}},
    }


def state():
    return {"anima_regions": {"enabled": True, "future": "keep", "regions": [{
        "id": "left", "label": "character", "caption": "a person in red",
        "negative_prompt": "blue clothes", "bbox": [0, 0, 500, 1000],
        "future": {"keep": True},
    }, {
        "id": "right", "label": "text", "caption": "a sign", "text": "LAKIS",
        "bbox": [500, 0, 1000, 1000],
    }]}}


class AnimaRegionsTests(unittest.TestCase):
    def test_boxes_connect_both_stages_without_pose_or_model_file_dependencies(self):
        value = state()
        before = copy.deepcopy(value)
        prompt = graph()
        result = anima_regions.apply(prompt, value, schema(), 128, 192)
        self.assertEqual(result["anima_region_stages"], ["initial", "highrez"])
        for stage, owner, sampler in (("initial", "1634:1721", "1634:1622"),
                                      ("highrez", "1633:1612", "1633:1612")):
            node = "lakis:anima_regions:" + stage
            self.assertEqual(prompt[owner]["inputs"]["model"], [node, 0])
            self.assertEqual(prompt[sampler]["inputs"]["positive"], [node, 1])
            self.assertEqual(prompt[sampler]["inputs"]["negative"], [node, 2])
            self.assertEqual(prompt[node]["inputs"]["model_type"], "anima")
        painter = prompt["lakis:anima_regions:painter"]["inputs"]
        self.assertNotIn("region_painter", painter)
        layers = json.loads(painter["paint_data"])["layers"]
        self.assertIn('text: "LAKIS"', layers[1]["prompt"])
        for index, layer in enumerate(layers):
            with Image.open(io.BytesIO(base64.b64decode(layer["mask"].split(",", 1)[1]))) as image:
                alpha = image.getchannel("A")
                self.assertEqual(alpha.getbbox(), ((0, 0, 64, 192), (64, 0, 128, 192))[index])
        negative = prompt["lakis:anima_regions:negative:0:text"]["inputs"]
        self.assertEqual(negative["text"], "blue clothes")
        self.assertEqual(value, before)
        self.assertEqual(anima_regions.normalize(value["anima_regions"])["future"], "keep")

    def test_disabled_boxes_are_a_noop_and_conflicts_fail_without_mutation(self):
        value = state()
        value["anima_regions"]["enabled"] = False
        original = graph()
        prompt = copy.deepcopy(original)
        self.assertFalse(anima_regions.apply(prompt, value, {}, 128, 192)["anima_regions_enabled"])
        self.assertEqual(prompt, original)
        for conflict in ({"i2i": {"enabled": True}}, {"inpaint": {"enabled": True}}):
            current = {**state(), **conflict}
            prompt = graph()
            with self.assertRaises(ValueError):
                anima_regions.apply(prompt, current, schema(), 128, 192)
            self.assertEqual(prompt, original)

    def test_boxes_use_main_text_and_upstream_pose_models_without_old_pose_prompts(self):
        value = {**state(), "scene_controls": {"enabled": True, "toyxyz_enabled": True}}
        before = copy.deepcopy(value)
        prompt = graph()
        prompt["pose:painter"] = {
            "class_type": "ComfyCoupleRegionPainter",
            "inputs": {"paint_data": '{"layers":[{"id":"person","prompt":"person in a coat"}]}'},
        }
        original_paint = prompt["pose:painter"]["inputs"]["paint_data"]
        for stage, owner in (("initial", "1634:1721"), ("highrez", "1633:1612")):
            prompt[owner]["inputs"]["model"] = ["pose:" + stage, 0]
        report = anima_regions.apply(prompt, value, schema(), 128, 192)
        self.assertTrue(report["anima_regions_with_pose"])
        self.assertEqual(prompt["lakis:anima_regions:painter"]["inputs"]["region"], ["lakis:anima_regions:base", 0])
        self.assertEqual(prompt["lakis:anima_regions:base"]["inputs"]["base_prompt_text"], ["890:2012", 0])
        self.assertEqual(prompt["pose:painter"]["inputs"]["paint_data"], original_paint)
        self.assertEqual(sum(node.get("class_type") == "ComfyCoupleMask" for node in prompt.values()), 2)
        for stage, owner, sampler in (("initial", "1634:1721", "1634:1622"),
                                      ("highrez", "1633:1612", "1633:1612")):
            node = "lakis:anima_regions:" + stage
            self.assertEqual(prompt[node]["inputs"]["model"], ["pose:" + stage, 0])
            self.assertEqual(prompt[sampler]["inputs"]["positive"], [node, 1])
            self.assertEqual(prompt["lakis:anima_regions:" + stage + ":negative:0"]["inputs"]["conditioning_1"],
                             ["negative" if stage == "initial" else "hr_negative", 0])
        self.assertEqual(value, before)

    def test_legacy_pose_only_keeps_global_conditioning_and_does_not_require_old_painting(self):
        for pose_only in (True, False):
            with self.subTest(pose_only=pose_only):
                value = {"scene_controls": {
                    "enabled": True, "toyxyz_enabled": True, "pose_data": '{"version":1}',
                    "toyxyz_render_data": json.dumps({"version": 1, "region_painter": {"width": 128, "height": 192}}),
                    "toyxyz_paint_data": "" if pose_only else json.dumps({
                        "version": 1, "width": 128, "height": 192, "layers": [],
                        "base": {"prompt": "pose-only base"}, "background": {"prompt": "pose-only background"},
                    }),
                }}
                before = copy.deepcopy(value)
                prompt = graph()
                original = copy.deepcopy(prompt)
                inventory = ["anima_3dpose_6200.safetensors"]
                if not pose_only:
                    inventory.append("anima_regional_4335.safetensors")
                info = {**schema(), "ToyxyzPose3DEditor": {},
                        "AnimaLLLiteApply_sdscripts": {"input": {"required": {"lllite_name": [inventory]}}}}
                with patch.object(bridge.scene_controls, "model_status", return_value={"valid": True}):
                    report = bridge.scene_controls.apply_scene_controls(
                        prompt, value, info, Path("fixture-root"), 128, 192, pose_only=pose_only)
                self.assertTrue(all(report["scene_prompt_contract"].values()))
                self.assertEqual(report["region_enabled"], not pose_only)
                for stage, owner, sampler in (("initial", "1634:1721", "1634:1622"),
                                              ("highrez", "1633:1612", "1633:1612")):
                    if pose_only:
                        self.assertEqual(prompt[owner]["inputs"]["model"], ["lakis:pose_" + stage, 0])
                        for branch in ("positive", "negative"):
                            self.assertEqual(prompt[sampler]["inputs"][branch], original[sampler]["inputs"][branch])
                self.assertEqual("lakis:toyxyz_painter" in prompt, not pose_only)
                self.assertEqual(value, before)

    def test_invalid_boxes_and_missing_nodes_are_rejected(self):
        for bbox in ([500, 0, 0, 1000], [0, 0, 1001, 1000], [False, 0, 1000, 1000]):
            value = state()
            value["anima_regions"]["regions"][0]["bbox"] = bbox
            with self.assertRaises(ValueError):
                anima_regions.apply(graph(), value, schema(), 128, 192)
        with self.assertRaisesRegex(ValueError, "ComfyCoupleRegionPainter"):
            anima_regions.apply(graph(), state(), {}, 128, 192)

    def test_composition_is_independent_and_negative_only_regions_do_not_replace_positive(self):
        value = state()
        value["composition_enabled"] = True
        value["anima_regions"]["regions"] = [value["anima_regions"]["regions"][0]]
        value["anima_regions"]["regions"][0]["caption"] = ""
        prompt = graph()
        original_positive = copy.deepcopy(prompt["1634:1622"]["inputs"]["positive"])
        anima_regions.apply(prompt, value, schema(), 128, 192)
        self.assertEqual(prompt["1634:1622"]["inputs"]["positive"], original_positive)
        self.assertNotEqual(prompt["1634:1622"]["inputs"]["negative"], ["negative", 0])


class PromptOverrideIntegrationTests(unittest.TestCase):
    def test_old_prompt_is_ignored_but_other_overrides_and_naia_survive(self):
        old = [{"id": "old", "pane": "positive", "type": "general", "text": "old character"},
               {"id": "naia", "type": "naia", "text": "edited", "future": {"keep": True}}]
        template = {"2133": {"class_type": "EasyUseAnimaPromptStudioAdvanced", "inputs": {
            "advanced_fields": json.dumps([{"id": "positive_general_kr_camera_bridge", "text": "current camera"}]),
            "resolution_custom_width": 1024,
        }}}
        requested = {"2133": {"advanced_fields": json.dumps(old), "resolution_custom_width": 896}}
        with (patch.object(bridge, "_comfy_object_info", return_value={}),
              patch.object(bridge, "TEMPLATE", SimpleNamespace(read_text=lambda **kwargs: json.dumps(template)))):
            cleaned = bridge._clean_advanced_node_overrides(requested)
            self.assertEqual(json.loads(cleaned["2133"]["advanced_fields"]), [old[1]])
            for text in ("new character", "", "another character"):
                prompt = copy.deepcopy(template)
                bridge._inject_prompts(prompt, {"general": text, "negative": "new negative"})
                bridge._apply_advanced_node_overrides(prompt, cleaned)
                fields = {item["id"]: item for item in json.loads(prompt["2133"]["inputs"]["advanced_fields"])}
                self.assertEqual(fields["positive_general_lakis_external"]["text"], text)
                self.assertEqual(fields["negative_general_lakis_external"]["text"], "new negative")
                self.assertEqual(fields["positive_general_kr_camera_bridge"]["text"], "current camera")
                self.assertEqual(fields["naia"], old[1])
                self.assertEqual(prompt["2133"]["inputs"]["resolution_custom_width"], 896)
                self.assertNotIn("old character", str(fields))

    def test_stale_only_override_is_not_persisted(self):
        old = json.dumps([{"id": "old", "pane": "positive", "type": "general", "text": "stale"}])
        template = {"2133": {"inputs": {"advanced_fields": old}, "class_type": "EasyUseAnimaPromptStudioAdvanced"}}
        with (patch.object(bridge, "_comfy_object_info", return_value={}),
              patch.object(bridge, "TEMPLATE", SimpleNamespace(read_text=lambda **kwargs: json.dumps(template)))):
            self.assertEqual(bridge._clean_advanced_node_overrides({"2133": {"advanced_fields": old}}), {})


class NativeRegionIntegrationTests(unittest.TestCase):
    def test_legacy_graph_keeps_region_controls_reachable_after_final_only_pruning(self):
        template_path = ROOT / "workflows/LAKIS_runtime_api_v7.4.json"
        original = template_path.read_bytes()
        template = json.loads(original)
        configuration = {"lora": {"current": []}}
        for key, node, field in (("checkpoint", "890:1365", "model_name"),
                                  ("vae", "890:159", "vae_name"),
                                  ("clip", "890:164", "clip_name"),
                                  ("sampler", "890:905", "sampler_name"),
                                  ("scheduler", "890:905", "scheduler")):
            configuration[key] = {"options": [template[node]["inputs"][field]]}
        info = schema()
        value = {**state(), "generation": {"engine": "anima", "mode": "fast"},
                 "prompt": {"general": "new global setting", "negative": "blurry"},
                 "loras": [], "composition_enabled": False,
                 "output": {"seed": 42, "width": 512, "height": 768}}
        with (patch.object(bridge, "TEMPLATE", template_path),
              patch.object(bridge, "_wait_for_comfy_object_info", return_value=info),
              patch.object(bridge, "_comfy_object_info", return_value=info),
              patch.object(bridge, "workflow_configuration", return_value=configuration),
              patch.object(bridge, "_validate_live_prompt_models", return_value=None),
              patch.object(bridge, "_is_anima_checkpoint", return_value=True),
              patch.object(bridge, "_preferred_upscaler", return_value=None),
              patch.object(bridge, "configured_output_root", return_value=Path("fixture-output")),
              patch.object(bridge, "_live_lora_inventory", return_value=[])):
            result, report = bridge.build_prompt(value)
        self.assertTrue(report["anima_regions_enabled"])
        self.assertIn("775", result)
        for stage, owner in (("initial", "1634:1721"), ("highrez", "1633:1612")):
            self.assertEqual(result[owner]["inputs"]["model"], ["lakis:anima_regions:" + stage, 0])
        self.assertEqual(original, template_path.read_bytes())

    def test_native_graph_wires_boxes_to_initial_and_highrez_and_keeps_main_prompt(self):
        template_path = ROOT / "workflows/LAKIS_runtime_api_v8.0.json"
        original = template_path.read_bytes()
        api = json.loads(original)
        aliases = bridge._native_alias_view(api)
        info = schema()
        for kind, field, name in (
            ("DiffusionModelLoaderKJ", "model_name", aliases["890:1365"]["inputs"]["model_name"]),
            ("VAELoader", "vae_name", aliases["890:159"]["inputs"]["vae_name"]),
            ("CLIPLoader", "clip_name", aliases["890:164"]["inputs"]["clip_name"]),
            ("LoraLoaderModelOnly", "lora_name", "anima-turbo-lora-v0.2.safetensors"),
        ):
            info[kind] = {"input": {"required": {field: [[name]]}}}
        value = {**state(), "generation": {"engine": "anima", "mode": "fast"},
                 "prompt": {"general": "new global setting", "negative": "new negative"},
                 "loras": [], "composition_enabled": True,
                 "output": {"seed": 42, "width": 512, "height": 768},
                 "node_overrides": {"2133": {"advanced_fields": json.dumps([{
                     "id": "old", "pane": "positive", "type": "general", "text": "old character",
                 }])}}}
        with (patch.object(bridge, "TEMPLATE", template_path),
              patch.object(bridge, "_wait_for_comfy_object_info", return_value=info),
              patch.object(bridge, "_comfy_object_info", return_value=info),
              patch.object(bridge, "_preferred_upscaler", return_value=None),
              patch.object(bridge, "configured_output_root", return_value=Path("fixture-output")),
              patch.object(bridge, "_live_lora_inventory", return_value=[])):
            result, report = bridge.build_prompt(value)
            joint = copy.deepcopy(value)
            joint["composition_enabled"] = False
            joint["scene_controls"] = {
                "enabled": True, "toyxyz_enabled": True, "pose_data": '{"version":1}',
                "toyxyz_render_data": json.dumps({"version": 1, "region_painter": {"width": 512, "height": 768}}),
                "toyxyz_paint_data": json.dumps({"version": 1, "width": 512, "height": 768,
                                               "base": {"prompt": ""}, "background": {"prompt": ""}, "layers": []}),
            }
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": "1"}):
                root = Path(tmp)
                image = root / "input" / ("LAKIS_reference_" + "1" * 64 + ".png")
                image.parent.mkdir()
                Image.new("RGB", (8, 8), "white").save(image)
                joint["anima_reference"] = {"enabled": True, "image_name": image.name, "strength": 0}
                with (patch.object(bridge, "COMFY_ROOT", root),
                      patch.object(anima_reference, "configuration", return_value={"ready": True})):
                    negative_only = copy.deepcopy(value["anima_regions"])
                    negative_only["regions"] = [negative_only["regions"][0]]
                    negative_only["regions"][0]["caption"] = ""
                    variants = (
                        ("boxes", value["anima_regions"], True),
                        ("empty", {"enabled": True, "regions": []}, False),
                        ("negative", negative_only, False),
                        ("disabled", {**value["anima_regions"], "enabled": False}, False),
                    )
                    for mode in ("fast", "detail", "lakis_detail"):
                        for name, boxes, positive_boxes in variants:
                            with self.subTest(mode=mode, boxes=name):
                                joint["generation"]["mode"] = mode
                                joint["anima_regions"] = copy.deepcopy(boxes)
                                joint["scene_controls"]["toyxyz_paint_data"] = (
                                    "" if boxes["enabled"] else json.dumps({
                                        "version": 1, "width": 512, "height": 768,
                                        "base": {"prompt": "pose-only main"}, "background": {"prompt": "pose-only background"},
                                        "layers": [],
                                    }))
                                before_joint = copy.deepcopy(joint)
                                joint_result, joint_report = bridge.build_prompt(joint)
                                self.assertEqual(joint, before_joint)
                                view = bridge._native_alias_view(joint_result)

                                def linked_ids(value):
                                    if isinstance(value, list):
                                        if len(value) == 2 and isinstance(value[0], str) and value[0] in joint_result:
                                            yield value[0]
                                        else:
                                            for item in value:
                                                yield from linked_ids(item)
                                    elif isinstance(value, dict):
                                        for item in value.values():
                                            yield from linked_ids(item)

                                def active_nodes(inputs):
                                    pending = list(linked_ids(inputs))
                                    visited = set()
                                    while pending:
                                        identifier = pending.pop()
                                        if identifier in visited:
                                            continue
                                        visited.add(identifier)
                                        node = joint_result[identifier]
                                        inputs = node["inputs"]
                                        if node["class_type"] == "ComfySwitchNode" and inputs.get("switch") == ["3000", 6]:
                                            inputs = {"switch": inputs["switch"], "selected": inputs["on_true"]}
                                        pending.extend(linked_ids(inputs))
                                    return visited

                                self.assertTrue(joint_report["scene_controls_enabled"])
                                self.assertTrue(joint_report["anima_reference_enabled"])
                                for stage, owner, sampler, pose_node in (
                                        ("initial", "1634:1721", "1634:1622", "3060"),
                                        ("highrez", "1633:1612", "1633:1612", "3070")):
                                    reachable = active_nodes({
                                        "model": view[owner]["inputs"]["model"],
                                        "positive": view[sampler]["inputs"]["positive"],
                                        "negative": view[sampler]["inputs"]["negative"],
                                    })
                                    self.assertIn(pose_node, reachable)
                                    self.assertIn("3030", reachable)
                                    self.assertEqual("3032" in reachable, not boxes["enabled"])
                                    self.assertEqual(any(
                                        joint_result[node].get("inputs", {}).get("lllite_name") == "anima_regional_4335.safetensors"
                                        for node in reachable), not boxes["enabled"])
                                    count = sum(joint_result[node]["class_type"] == "ComfyCoupleMask" for node in reachable)
                                    self.assertEqual(count, 1 if positive_boxes or not boxes["enabled"] else 0)
                                    self.assertEqual(joint_result["lakis:anima_reference:" + stage]["class_type"], "SnapRef")
                                self.assertEqual(joint_result["775"], result["775"])
        result = bridge._native_alias_view(result)
        self.assertTrue(report["native_workflow"])
        self.assertTrue(report["anima_regions_enabled"])
        for owner in ("1634:1721", "1633:1612"):
            self.assertTrue(result[owner]["inputs"]["model"][0].startswith("lakis:anima_regions:"))
        fields = json.loads(result["2133"]["inputs"]["advanced_fields"])
        self.assertIn("new global setting", [item.get("text") for item in fields])
        self.assertNotIn("old character", str(fields))
        self.assertEqual(original, template_path.read_bytes())


class RegionPersistenceTests(unittest.TestCase):
    def test_save_preserves_other_data_and_limits_counts_to_1000(self):
        original = {"future": {"keep": True}, "authentication": "fixture-only",
                    "moss_regions": {"enabled": True, "regions": []}}
        written = []
        model = {"steps": 30, "cfg": 5.0, "sampler": "euler", "scheduler": "normal"}
        output = {"width": 512, "height": 768, "seed": 42}
        with (patch.object(bridge, "_load_external_ui_payload", side_effect=lambda: copy.deepcopy(original)),
              patch.object(bridge, "_write_external_ui_payload", side_effect=lambda value: written.append(copy.deepcopy(value))),
              patch.object(bridge, "_clean_generation_model_output", return_value=(model, output))):
            for count in (1, 21, 999, 1000):
                bridge.save_external_generation_state.__wrapped__(
                    model, output, loras=[], anima_regions=state()["anima_regions"],
                    continuous={"enabled": True, "count": count})
                self.assertEqual(written[-1]["anima_regions"], state()["anima_regions"])
                self.assertEqual(written[-1]["continuous"]["count"], count)
                for key in original:
                    self.assertEqual(written[-1][key], original[key])
            for count in (0, -1, 1001, 1000000, True, 1.5, float("inf"), 1 << 53):
                before = len(written)
                with self.assertRaises(ValueError):
                    bridge.save_external_generation_state.__wrapped__(
                        model, output, loras=[], continuous={"enabled": True, "count": count})
                self.assertEqual(len(written), before)

    def test_generation_rejects_invalid_counts_before_lock_or_allowance(self):
        uninitialized = object.__new__(bridge.WorkflowBridge)
        for count in (0, -1, 1001, 1000000, True, 1.5, float("inf"), "1000"):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "1~1000"):
                uninitialized.start({"continuous": {"enabled": True, "count": count}})
        for count in (1, 999, 1000):
            bridge._validate_continuous_settings({"enabled": True, "count": count})
        bridge._validate_continuous_settings(None)
        with self.assertRaises(ValueError):
            uninitialized.start({"continuous": []})

    def test_old_prompt_override_migration_is_selective_and_idempotent(self):
        payload = {
            "future": {"keep": True}, "authentication": "fixture-only",
            "anima_regions": state()["anima_regions"],
            "node_overrides": {"2133": {"advanced_fields": json.dumps([
                {"id": "old", "pane": "positive", "type": "general", "text": "old character"},
                {"id": "naia", "type": "naia", "text": "preserve"},
            ])}},
        }
        written = []
        def store(value):
            payload.clear()
            payload.update(copy.deepcopy(value))
            written.append(copy.deepcopy(value))
        with (patch.object(bridge, "TEMPLATE", ROOT / "workflows/LAKIS_runtime_api_v8.0.json"),
              patch.object(bridge, "_load_external_ui_payload", side_effect=lambda: copy.deepcopy(payload)),
              patch.object(bridge, "_write_external_ui_payload", side_effect=store),
              patch.object(bridge, "_comfy_object_info", return_value={})):
            first = bridge.load_external_generation_state.__wrapped__()
            second = bridge.load_external_generation_state.__wrapped__()
        self.assertEqual(first, second)
        self.assertEqual(len(written), 1)
        self.assertEqual(payload["future"], {"keep": True})
        self.assertEqual(payload["authentication"], "fixture-only")
        self.assertEqual(payload["anima_regions"], state()["anima_regions"])
        self.assertEqual(json.loads(payload["node_overrides"]["2133"]["advanced_fields"]),
                         [{"id": "naia", "type": "naia", "text": "preserve"}])


if __name__ == "__main__":
    unittest.main()
