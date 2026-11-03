"""Standalone native graph/control parity without inference or user data."""
from copy import deepcopy
import ast
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/runtime"))
sys.path.insert(0, str(ROOT / "src/external_ui"))
from native_workflow import alias_view, native_view, is_link, serialize_native, validate_enum_edges, NAMES
from sync_runtime_workflow import synchronize

CONTROLS = runpy.run_path(str(ROOT / "src/custom_nodes/ComfyUI-LAKIS-Detail/native_controls.py"))
REGISTRY = CONTROLS["NODE_CLASS_MAPPINGS"]

def captured_native_info():
    capture = os.environ.get("LAKIS_OBJECT_INFO")
    if not capture:
        raise unittest.SkipTest("LAKIS_OBJECT_INFO not supplied; installed-schema checks require the capture")
    info = json.loads(Path(capture).read_text(encoding="utf-8"))
    inputs = info["KSampler"]["input"]["required"]
    CONTROLS["bind_sampler_contract"](inputs["sampler_name"][0], inputs["scheduler"][0])
    for name, cls in REGISTRY.items():
        if name == "LAKIS_DiffusionModelLoader":
            schema = info["DiffusionModelLoaderKJ"]["input"]
        elif name == "LAKIS_NativeLLLiteApply":
            schema = CONTROLS["native_lllite_inputs"](info["AnimaLLLiteApply_sdscripts"]["input"])
        else:
            schema = cls.INPUT_TYPES()
        info[name] = {"input": schema, "output": cls.RETURN_TYPES,
                      "output_node": getattr(cls, "OUTPUT_NODE", False)}
    return info


def read(name):
    return json.loads((ROOT / "workflows" / name).read_text(encoding="utf-8"))


def active_nodes(graph):
    """Resolve lazy switches with actual control implementations, not tensors."""
    cache = {}
    def value(key, slot):
        if key not in cache:
            node = graph[key]
            kind, inputs = node["class_type"], node["inputs"]
            args = {k: value(str(v[0]), v[1]) if is_link(v) else v for k, v in inputs.items()}
            if kind in REGISTRY:
                instance = REGISTRY[kind]()
                cache[key] = getattr(instance, instance.FUNCTION)(**args)
            elif kind.startswith("Primitive"):
                cache[key] = (args["value"],)
            elif kind == "EasyUseAnimaPromptStudioAdvanced":
                cache[key] = (None, None, None, None, args["use_anima_mod_guidance"],
                              args["use_negative_anima_mod_guidance"], None, None,
                              args["resolution_custom_width"], args["resolution_custom_height"])
            else:
                raise AssertionError(f"Test cannot evaluate selector {key}: {kind}")
        return cache[key][slot]
    keep = set()
    def visit(key):
        if key in keep:
            return
        keep.add(key)
        node = graph[key]
        inputs = node["inputs"]
        if node["class_type"] == "ComfySwitchNode":
            selector = inputs["switch"]
            selected = value(str(selector[0]), selector[1]) if is_link(selector) else selector
            keys = ["switch", "on_true" if selected else "on_false"]
        elif node["class_type"] == "LAKIS_CompositionPrompt":
            selector = inputs["enabled"]
            keys = ["positive", "enabled"]
            if value(str(selector[0]), selector[1]):
                keys.append("camera")
        else:
            keys = inputs
        for name in keys:
            v = inputs[name]
            if is_link(v):
                visit(str(v[0]))
    visit("775")
    visit("1338")
    return {key: graph[key] for key in keep}


class StandaloneWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = read(NAMES[2])
        cls.graph = alias_view(cls.api)
        cls.ui = read(NAMES[0])

    def test_native_files_and_api_roundtrip(self):
        self.assertEqual(self.ui, read(NAMES[1]))
        self.assertEqual(self.api, synchronize(self.ui, self.api))
        self.assertEqual(self.api, native_view(alias_view(self.api), self.api))
        self.assertEqual(.4, self.ui["version"])
        self.assertEqual(6, len(self.ui["groups"]))
        self.assertTrue(all(isinstance(node["id"], int) for node in self.ui["nodes"]))

    def test_auxiliary_wiring_is_behind_related_aligned_editors(self):
        nodes = self.ui["nodes"]
        editors = [n for n in nodes if not n.get("flags", {}).get("collapsed")]
        auxiliaries = [n for n in nodes if n.get("flags", {}).get("collapsed")]
        by_source = {n["properties"]["lakis_source_id"]: n for n in nodes
                     if "lakis_source_id" in n.get("properties", {})}

        def contains(panel, auxiliary):
            x, y = auxiliary["pos"]
            px, py = panel["pos"]
            pw, ph = panel["size"]
            return px < x and py < y and x + auxiliary["size"][0] <= px + pw and y + 30 <= py + ph

        self.assertTrue(auxiliaries)
        self.assertEqual(list(range(len(nodes))), [n["order"] for n in nodes])
        self.assertLess(max(nodes.index(n) for n in auxiliaries), min(nodes.index(n) for n in editors))
        for auxiliary in auxiliaries:
            self.assertTrue(any(contains(editor, auxiliary) for editor in editors),
                            auxiliary["properties"]["lakis_source_id"])
        for source, owner in (
            ("890:1281", "1925"), ("890:903", "2133"), ("3002", "2135"),
            ("1736:1741", "1744"), ("1634:1622", "1925"), ("1633:1612", "3051"),
            ("1530:1826", "3040"), ("1836:2069", "3040"), ("1541:1538", "3051"),
            ("3015", "3013"), ("3062", "3030"), ("3072", "3032"), ("3003", "775"),
        ):
            self.assertTrue(contains(by_source[owner], by_source[source]), source)
        for source, position, size in (
            ("1925", [440, 80], [600, 740]),
            ("2133", [1100, 80], [680, 1460]),
            ("3030", [3160, 80], [1180, 840]),
            ("3032", [3160, 960], [1180, 840]),
        ):
            self.assertEqual(position, by_source[source]["pos"])
            self.assertEqual(size, by_source[source]["size"])
        for index, first in enumerate(editors):
            x, y = first["pos"]
            w, h = first["size"]
            for second in editors[index + 1:]:
                sx, sy = second["pos"]
                sw, sh = second["size"]
                self.assertTrue(x + w <= sx or sx + sw <= x or y + h <= sy or sy + sh <= y,
                                f"Overlapping editors: {first['id']} and {second['id']}")
        self.assertFalse(any("Auxiliary" in group["title"] for group in self.ui["groups"]))
        self.assertTrue(all(group["bounding"][1] + group["bounding"][3] <= 1880
                            for group in self.ui["groups"]))

    def test_all_api_links_survive_native_serialization(self):
        nodes = {str(n["id"]): n for n in self.ui["nodes"]}
        expected = sum(is_link(v) for n in self.api.values() for v in n["inputs"].values())
        self.assertEqual(expected, len(self.ui["links"]))
        for link_id, source, output, target, input_slot, kind in self.ui["links"]:
            self.assertIn(link_id, nodes[str(source)]["outputs"][output]["links"])
            self.assertEqual(link_id, nodes[str(target)]["inputs"][input_slot]["link"])
            self.assertIsInstance(kind, str)
        studio = nodes["2133"]
        self.assertEqual([], studio["inputs"])
        self.assertEqual(3001, studio["properties"]["lakis_canvas_node_id"])
        for key in ("3030", "3032"):
            self.assertEqual(["3001", 0], self.graph[key]["inputs"]["width"])
            self.assertEqual(["3001", 1], self.graph[key]["inputs"]["height"])

    def test_canvas_is_the_only_generation_size_authority(self):
        studio = self.api["2133"]["inputs"]
        self.assertEqual(1024, studio["resolution_custom_width"])
        self.assertEqual(1536, studio["resolution_custom_height"])
        self.assertFalse(any(value in (["2133", 8], ["2133", 9])
                             for node in self.api.values() for value in node["inputs"].values()))
        saved = deepcopy(self.ui)
        studio_ui = next(node for node in saved["nodes"] if node["id"] == 2133)
        names = studio_ui["properties"]["lakis_widget_names"]
        # Deliberately stale display copies cannot rewire any generation size.
        studio_ui["widgets_values"][names.index("resolution_custom_width")] = 256
        studio_ui["widgets_values"][names.index("resolution_custom_height")] = 256
        canvas_ui = next(node for node in saved["nodes"] if node["id"] == 3001)
        canvas_ui["widgets_values"] = [736, 1008]
        synced = alias_view(synchronize(saved, self.api))
        self.assertEqual({"width": 736, "height": 1008}, synced["3001"]["inputs"])
        self.assertEqual(256, synced["2133"]["inputs"]["resolution_custom_width"])
        for key in ("1736:1987", "1736:1741", "3030", "3032"):
            self.assertEqual(["3001", 0], synced[key]["inputs"]["width"])
            self.assertEqual(["3001", 1], synced[key]["inputs"]["height"])
        self.assertEqual((736, 1008), REGISTRY["LAKIS_Canvas"]().resolve(**synced["3001"]["inputs"]))

    def test_context_sockets_follow_the_complete_rgthree_contract(self):
        # context_utils._create_context_data defines this order. rgthree's
        # loadedGraphNode / matchLocalSlotsToServer reconciles against the
        # whole list, including unconnected leading and intermediate sockets.
        fields = ("base_ctx", "model", "clip", "vae", "positive", "negative",
                  "latent", "images", "seed", "steps", "step_refiner", "cfg",
                  "ckpt_name", "sampler", "scheduler", "clip_width", "clip_height",
                  "text_pos_g", "text_pos_l", "text_neg_g", "text_neg_l", "mask", "control_net")
        by_source = {}
        for node in self.ui["nodes"]:
            if node["type"] not in {"Context Big (rgthree)", "Context (rgthree)"}:
                continue
            by_source[node["properties"]["lakis_source_id"]] = node
            expected = fields if node["type"] == "Context Big (rgthree)" else fields[:9]
            self.assertEqual(list(expected), [entry["name"] for entry in node["inputs"]])
            self.assertEqual([], node["widgets_values"], "forceInput context fields are sockets, not widgets")
            for entry in node["inputs"]:
                self.assertNotIn("widget", entry)
        root = by_source["890:857"]
        self.assertIsNone(root["inputs"][0]["link"], "base_ctx must retain slot 0 when unconnected")
        self.assertIsNone(root["inputs"][7]["link"], "images must retain its intermediate slot")
        for name, slot in (("negative", 5), ("step_refiner", 10), ("cfg", 11)):
            entry = root["inputs"][slot]
            self.assertEqual(name, entry["name"])
            link = next(link for link in self.ui["links"] if link[0] == entry["link"])
            self.assertEqual((root["id"], slot), (link[3], link[4]))
            self.assertEqual([str(link[1]), link[2]], self.api[str(root["id"])]["inputs"][name])

    def test_unconnected_schema_sockets_preserve_converted_widget_link_slots(self):
        prompt = {
            "215": {"class_type": "FixtureSource", "inputs": {},
                    "_meta": {"lakis_source_id": "215"}},
            "4101": {"class_type": "FixtureTarget",
                     "inputs": {"seed": ["215", 0], "cfg": ["215", 1]},
                     "_meta": {"lakis_source_id": "890:857"}},
        }
        info = {
            "FixtureSource": {"input": {"required": {}}, "output": ["INT", "FLOAT"]},
            "FixtureTarget": {
                "input": {
                    "required": {
                        "leading": ("IMAGE",),
                        "seed": ("INT", {"default": 7, "control_after_generate": True}),
                        "middle": ("VAE",),
                        "force_count": ("INT", {"forceInput": True}),
                        "cfg": ("FLOAT", {"default": 5.}),
                    },
                    "optional": {"context": ("RGTHREE_CONTEXT",),
                                 "note": ("STRING", {"default": "ordinary unconnected widget"})},
                },
                "output": ["IMAGE"],
            },
        }
        ui = serialize_native(prompt, info)
        node = next(node for node in ui["nodes"] if node["id"] == 4101)
        expected_names = ["leading", "seed", "middle", "force_count", "cfg", "context"]
        self.assertEqual(expected_names, [entry["name"] for entry in node["inputs"]])
        for slot in (0, 2, 3, 5):
            self.assertIsNone(node["inputs"][slot]["link"])
            self.assertNotIn("widget", node["inputs"][slot])
        self.assertEqual({"name": "seed"}, node["inputs"][1]["widget"])
        self.assertEqual({"name": "cfg"}, node["inputs"][4]["widget"])
        self.assertEqual(["seed", "control_after_generate", "cfg"], node["properties"]["lakis_widget_names"])
        self.assertEqual([7, "fixed", 5.], node["widgets_values"])
        self.assertEqual([[1, 215, 0, 4101, 1, "INT"], [2, 215, 1, 4101, 4, "FLOAT"]], ui["links"])
        # A provider restoring its full native socket order is now a no-op;
        # resolving the stored slots still targets seed and cfg, not neighbours.
        restored = [next(entry for entry in node["inputs"] if entry["name"] == name) for name in expected_names]
        self.assertEqual(["seed", "cfg"], [restored[link[4]]["name"] for link in ui["links"]])

    def test_no_dangling_links_or_cycles_including_inactive_branches(self):
        done, pending = set(), set()
        def visit(key):
            self.assertNotIn(key, pending, f"cycle at {key}")
            if key in done:
                return
            self.assertIn(key, self.api)
            pending.add(key)
            for v in self.api[key]["inputs"].values():
                if is_link(v):
                    visit(str(v[0]))
            pending.remove(key)
            done.add(key)
        for key in self.api:
            visit(key)

    def test_empty_metadata_survives_native_socket_serialization(self):
        p = self.graph
        source, slot = p["3082"]["inputs"]["on_false"]
        self.assertEqual(0, slot)
        self.assertEqual("PrimitiveString", p[source]["class_type"])
        self.assertEqual("", p[source]["inputs"]["value"])
        self.assertEqual(["3082", 0], p["775"]["inputs"]["custom"])

    def test_v3_combo_choices_remain_editable_widgets(self):
        prompt = {
            "4101": {"class_type": "FixtureTarget", "inputs": {"mode": "Chess"},
                     "_meta": {"lakis_source_id": "890:857"}},
        }
        info = {
            "FixtureTarget": {
                "input": {"required": {"mode": ("COMBO", {"options": ["Linear", "Chess"]})}},
                "output": ["STRING"],
            },
        }
        ui = serialize_native(prompt, info)
        node = next(node for node in ui["nodes"] if node["id"] == 4101)
        self.assertEqual(["Chess"], node["widgets_values"])
        self.assertEqual(["mode"], node["properties"]["lakis_widget_names"])

    def test_socket_only_literals_are_rejected_instead_of_lost(self):
        prompt = {
            "4101": {"class_type": "FixtureTarget", "inputs": {"on_false": ""},
                     "_meta": {"lakis_source_id": "890:857"}},
        }
        info = {
            "FixtureTarget": {
                "input": {"required": {"on_false": ("COMFY_MATCHTYPE_V3", {"lazy": True})}},
                "output": ["STRING"],
            },
        }
        with self.assertRaisesRegex(ValueError, "4101.on_false"):
            serialize_native(prompt, info)

    def test_terminal_save_display_and_initial_turbo_contracts(self):
        p = self.graph
        self.assertEqual("Image Saver", p["775"]["class_type"])
        self.assertTrue(p["775"]["inputs"]["show_preview"])
        self.assertEqual(p["775"]["inputs"]["images"], p["1338"]["inputs"]["images"])
        self.assertEqual(p["775"]["inputs"]["images"], p["921"]["inputs"]["image"])
        self.assertEqual(["3003", 0], p["775"]["inputs"]["images"])
        self.assertTrue(p["1634:1721"]["inputs"]["enabled"])
        self.assertTrue(p["1634:1721"]["inputs"]["one_sampler_only"])
        self.assertNotIn("1633:1723", p)
        self.assertEqual("anima-turbo-lora-v0.2.safetensors", p["3005"]["inputs"]["lora_name"])
        self.assertFalse(p["775"]["inputs"]["download_civitai_data"])
        self.assertNotIn("VRAM_Debug", {n["class_type"] for n in p.values()})

    def test_fast_excludes_every_detailer_upscaler_and_detector(self):
        p = active_nodes(deepcopy(self.graph))
        types = {n["class_type"] for n in p.values()}
        self.assertFalse(types & {"DetailerForEach", "LAKIS_DETAIL", "SAM3_Detect",
                                  "UltimateSDUpscale", "LAKIS_SCOPE", "AnimaLLLiteApply_sdscripts",
                                  "LAKIS_NativeLLLiteApply"})
        self.assertIn("3005", p)
        self.assertIn("1634:1721", p)
        self.assertIn("1633:1612", p)

    def test_detail_uses_legacy_face_eye_usdu(self):
        p = deepcopy(self.graph)
        p["3000"]["inputs"]["mode"] = "DETAIL"
        active = active_nodes(p)
        self.assertTrue({"1530:1826", "1836:2069", "1541:1538"} <= set(active))
        self.assertNotIn("3040", active)
        self.assertNotIn("3051", active)

    def test_lakis_detail_uses_single_face_pass_and_scope(self):
        p = deepcopy(self.graph)
        p["3000"]["inputs"]["mode"] = "LAKIS DETAIL"
        active = active_nodes(p)
        self.assertTrue({"3040", "3051"} <= set(active))
        self.assertFalse({"1530:1826", "1836:2069", "1541:1538"} & set(active))

    def test_inpaint_is_independent_and_bypasses_normal_generation(self):
        p = deepcopy(self.graph)
        p["3000"]["inputs"].update(mode="LAKIS DETAIL", i2i=True, composition=True, inpaint=True, pose=True)
        active = active_nodes(p)
        self.assertTrue({"3011", "3012", "3013", "3015", "3017", "3019", "3023", "3025"} <= set(active))
        self.assertFalse({"1744", "1634:1622", "1633:1612", "3030", "3040", "3051", "1541:1538"} & set(active))
        self.assertEqual(["3013", 0], p["3020"]["inputs"]["text"])
        self.assertEqual(["3013", 1], p["3021"]["inputs"]["text"])

    def test_pose_uses_both_stages_without_camera_or_source_edits(self):
        p = deepcopy(self.graph)
        p["3000"]["inputs"].update(pose=True, composition=True)
        active = active_nodes(p)
        self.assertTrue({"3030", "3032", "3060", "3061", "3062", "3070", "3071", "3072"} <= set(active))
        self.assertNotIn("2135", active)
        self.assertNotIn("1744", active)

    def test_only_save_and_preview_are_executable_output_roots(self):
        info = captured_native_info()
        self.assertTrue(info["easy showAnything"]["output_node"], "captured provider output-root evidence")
        roots = {key for key, node in self.api.items() if info[node["class_type"]].get("output_node", False)}
        self.assertEqual({"775", "1338"}, roots)
        for source in ("1634:1623", "1530:1825", "1836:2068", "1541:1537"):
            self.assertNotIn(source, self.graph)
        for consumer, context in (("1634:1622", "1634:1624"), ("1541:1538", "1541:1539"),
                                  ("3040", "1530:1833"), ("3051", "1541:1539")):
            self.assertEqual([context, 14], self.graph[consumer]["inputs"]["scheduler"])

    def test_impact_adapters_bridge_only_the_two_legacy_detailers(self):
        info = captured_native_info()
        schema = info["ImpactSchedulerAdapter"]
        base = schema["input"]["required"]["scheduler"]
        self.assertTrue(base[1]["defaultInput"])
        self.assertIn("None", schema["input"]["required"]["extra_scheduler"][0])
        extended = info["DetailerForEach"]["input"]["required"]["scheduler"][0]
        self.assertEqual(extended, schema["output"][0])
        self.assertEqual(info["KSampler"]["input"]["required"]["scheduler"][0], base[0])
        self.assertFalse(schema["output_node"])
        self.assertEqual({"3041", "3042"}, {
            key for key, node in self.graph.items() if node["class_type"] == "ImpactSchedulerAdapter"})
        for adapter, detailer, context in (
            ("3041", "1530:1826", "1530:1833"), ("3042", "1836:2069", "1836:2075"),
        ):
            self.assertEqual({"scheduler": [context, 14], "extra_scheduler": "None"},
                             self.graph[adapter]["inputs"])
            self.assertEqual([adapter, 0], self.graph[detailer]["inputs"]["scheduler"])

    def test_enum_edges_match_complete_source_and_target_choices(self):
        info = captured_native_info()
        validate_enum_edges(self.api, info)
        # An old frozen output list must be rejected, even when all its
        # remaining values are a subset of the receiving enum.
        stale = deepcopy(info)
        stale["LAKIS_SourceSampler"]["output"] = list(stale["LAKIS_SourceSampler"]["output"])
        stale["LAKIS_SourceSampler"]["output"][2] = info["KSampler"]["input"]["required"]["sampler_name"][0][:-1]
        with self.assertRaisesRegex(ValueError, "Enum contract mismatch"):
            validate_enum_edges(self.api, stale)
        stale_input = deepcopy(info)
        stale_input["LAKIS_SourceSampler"]["input"]["required"]["sampler"] = (
            info["KSampler"]["input"]["required"]["sampler_name"][0][:-1], {"forceInput": True})
        with self.assertRaisesRegex(ValueError, "Enum contract mismatch"):
            validate_enum_edges(self.api, stale_input)
        # Bypassing either adapter with the base enum must also fail.
        bypassed = deepcopy(self.api)
        detailer = next(key for key, node in bypassed.items()
                        if node["_meta"]["lakis_source_id"] == "1530:1826")
        context = next(key for key, node in bypassed.items()
                       if node["_meta"]["lakis_source_id"] == "1530:1833")
        bypassed[detailer]["inputs"]["scheduler"] = [context, 14]
        with self.assertRaisesRegex(ValueError, "Enum contract mismatch"):
            validate_enum_edges(bypassed, info)
        # V3 and legacy representations of the same options are equivalent.
        v3 = deepcopy(info)
        v3["LAKIS_SourceSampler"]["input"]["required"]["sampler"] = (
            "COMBO", {"options": info["KSampler"]["input"]["required"]["sampler_name"][0], "forceInput": True})
        validate_enum_edges(self.api, v3)

    def test_inactive_controlnet_weights_have_no_static_filename_enum(self):
        info = captured_native_info()
        absent = deepcopy(info["AnimaLLLiteApply_sdscripts"]["input"])
        absent["required"]["lllite_name"] = ([],)
        schema = CONTROLS["native_lllite_inputs"](absent)
        self.assertEqual("STRING", schema["required"]["lllite_name"][0])
        self.assertEqual(([],), absent["required"]["lllite_name"], "upstream schema stays untouched")
        native = [n for n in self.api.values() if n["class_type"] == "LAKIS_NativeLLLiteApply"]
        self.assertEqual(5, len(native))
        self.assertEqual(("MODEL",), REGISTRY["LAKIS_NativeLLLiteApply"].RETURN_TYPES)
        self.assertTrue(all(isinstance(n["inputs"]["lllite_name"], str) for n in native))
        active = active_nodes(deepcopy(self.graph))
        self.assertFalse(any(n["class_type"] == "LAKIS_NativeLLLiteApply" for n in active.values()))

    def test_all_reachable_inputs_match_runtime_without_checkpoint_inventory(self):
        info = captured_native_info()
        info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0].clear()
        self.assertNotIn("893:891", self.graph)
        self.assertNotIn("CheckpointLoaderSimple", {node["class_type"] for node in self.api.values()})
        self.assertEqual("Context (rgthree)", self.graph["893:892"]["class_type"])
        self.assertEqual({"base_ctx": ["890:857", 0]}, self.graph["893:892"]["inputs"])
        for consumer in ("1530:1821", "1836:2064"):
            self.assertEqual(["893:892", 0], self.graph[consumer]["inputs"]["base_ctx"])

        # The API file is the complete dependency closure, including inactive
        # branches; validate it without mode-based pruning.
        for key, node in self.api.items():
            with self.subTest(node=key, kind=node["class_type"]):
                schema = info[node["class_type"]]["input"]
                specs = {**schema.get("required", {}), **schema.get("optional", {})}
                for name, spec in specs.items():
                    if name not in node["inputs"]:
                        if name in schema.get("required", {}) and spec[0] != "COMFY_AUTOGROW_V3":
                            self.fail(f"Missing required input {key}.{name}")
                        continue
                    v = node["inputs"][name]
                    if is_link(v):
                        outputs = info[self.api[str(v[0])]["class_type"]]["output"]
                        self.assertLess(v[1], len(outputs))
                        received = outputs[v[1]]
                        if isinstance(spec[0], list) and received not in ("*", "COMFY_MATCHTYPE_V3"):
                            self.assertIsInstance(received, (list, tuple),
                                                  f"{key}.{name} requires an actual enum contract")
                        received = "COMBO" if isinstance(received, list) else received
                        expected = "COMBO" if isinstance(spec[0], list) else spec[0]
                        if not ({received, expected} & {"*", "COMFY_MATCHTYPE_V3", "COMFY_AUTOGROW_V3"}):
                            self.assertTrue(set(received.split(",")) & set(expected.split(",")),
                                            f"{key}.{name}: {received} -> {expected}")
                        continue
                    kind = spec[0]
                    if kind == "BOOLEAN":
                        self.assertIsInstance(v, bool)
                    elif kind in ("INT", "FLOAT"):
                        self.assertIsInstance(v, int if kind == "INT" else (int, float))
                        self.assertNotIsInstance(v, bool)
                        opts = spec[1] if len(spec) > 1 else {}
                        if "min" in opts:
                            self.assertGreaterEqual(v, opts["min"])
                        if "max" in opts:
                            self.assertLessEqual(v, opts["max"])
                    elif isinstance(kind, list) or kind == "COMBO":
                        # File inventories are installation-specific. Other
                        # choices must match the captured installed schema.
                        if name not in {"model_name", "vae_name", "clip_name", "ckpt_name", "lora_name", "lllite_name"}:
                            choices = kind if isinstance(kind, list) else opts.get("options")
                            self.assertIsInstance(choices, (list, tuple))
                            self.assertIn(v, choices)
        validate_enum_edges(self.api, info)

    def test_sampler_contracts_bind_to_captured_comfy_enums(self):
        info = captured_native_info()
        sampler = info["KSampler"]["input"]["required"]["sampler_name"][0]
        scheduler = info["KSampler"]["input"]["required"]["scheduler"][0]
        self.assertEqual(sampler, REGISTRY["LAKIS_GenerationControls"].RETURN_TYPES[11])
        source = REGISTRY["LAKIS_SourceSampler"]
        self.assertEqual((sampler, scheduler), source.RETURN_TYPES[2:])
        self.assertEqual(sampler, source.INPUT_TYPES()["required"]["sampler"][0])
        self.assertEqual(scheduler, source.INPUT_TYPES()["required"]["scheduler"][0])
        context = info["Context Big (rgthree)"]["input"]["optional"]
        self.assertEqual(context["sampler"][0], source.RETURN_TYPES[2])
        self.assertEqual(context["scheduler"][0], source.RETURN_TYPES[3])

    def test_implicit_seed_control_preserves_following_numeric_and_combo_widgets(self):
        prompt = {"3040": {"class_type": "SeedFixture", "inputs": {
            "seed": 123, "steps": 8, "sampler": "euler", "denoise": .24, "noise_seed": 9},
            "_meta": {"lakis_source_id": "3040"}}}
        info = {"SeedFixture": {"input": {"required": {
            "steps": ("INT", {"default": 1}), "seed": ("INT", {"default": 0}),
            "sampler": (["euler", "heun"],), "denoise": ("FLOAT", {"default": .5}),
            "noise_seed": ("INT", {"default": 0, "control_after_generate": False}),
        }}, "input_order": {"required": ["seed", "steps", "sampler", "denoise", "noise_seed"]},
            "output": ["IMAGE"]}}
        ui = serialize_native(prompt, info)
        node = next(n for n in ui["nodes"] if n["id"] == 3040)
        names = ["seed", "control_after_generate", "steps", "sampler", "denoise", "noise_seed"]
        self.assertEqual(names, node["properties"]["lakis_widget_names"])
        self.assertEqual([123, "fixed", 8, "euler", .24, 9], node["widgets_values"])
        restored = dict(zip(names, node["widgets_values"]))
        for name, value in prompt["3040"]["inputs"].items():
            self.assertEqual(value, restored[name])

    def test_frontend_widget_sequence_preserves_every_api_primitive(self):
        info = captured_native_info()
        by_id = {str(n["id"]): n for n in self.ui["nodes"]}
        for key, api in self.api.items():
            schema = info[api["class_type"]]
            names = []
            for group in ("required", "optional"):
                declarations = schema["input"].get(group, {})
                for name in schema.get("input_order", {}).get(group, declarations):
                    spec = declarations[name]
                    kind, opts = spec[0], spec[1] if len(spec) > 1 else {}
                    combo = isinstance(kind, list) or kind == "COMBO"
                    if opts.get("forceInput") or not (combo or kind in ("INT", "FLOAT", "BOOLEAN", "STRING")):
                        continue
                    names.append(name)
                    # Independent frontend 1.55.18 useIntWidget rule, including
                    # rgthree Seed's explicit onNodeCreated removal.
                    control = opts.get("control_after_generate",
                                       name in ("seed", "noise_seed") if kind == "INT" else False)
                    if control and api["class_type"] != "Seed (rgthree)":
                        prefix = str(opts["control_prefix"]) + " " if opts.get("control_prefix") else ""
                        names.append(control if isinstance(control, str) else prefix + "control_after_generate")
                        if combo:
                            names.append(opts.get("control_filter_list", prefix + "control_filter_list"))
            ui = by_id[key]
            self.assertEqual(names[:len(ui["widgets_values"])], ui["properties"]["lakis_widget_names"], key)
            actual = dict(zip(names, ui["widgets_values"]))
            for name, expected in api["inputs"].items():
                if not is_link(expected) and name in names:
                    self.assertIn(name, actual, f"{key}.{name}")
                    self.assertEqual(expected, actual[name], f"{key}.{name}")


class NativeControls(unittest.TestCase):
    def test_sampler_contract_observes_late_registration(self):
        capture = os.environ.get("LAKIS_OBJECT_INFO")
        if not capture:
            self.skipTest("LAKIS_OBJECT_INFO required for enum registration regression")
        info = json.loads(Path(capture).read_text(encoding="utf-8"))
        sampler = info["KSampler"]["input"]["required"]["sampler_name"][0]
        scheduler = info["KSampler"]["input"]["required"]["scheduler"][0]
        self.assertIn("er_sde_cns", sampler)
        controls = runpy.run_path(str(ROOT / "src/custom_nodes/ComfyUI-LAKIS-Detail/native_controls.py"))
        controls["bind_sampler_contract"](sampler, scheduler)
        source = controls["NODE_CLASS_MAPPINGS"]["LAKIS_SourceSampler"]
        generation = controls["NODE_CLASS_MAPPINGS"]["LAKIS_GenerationControls"]
        sampler.append("test_sampler_registered_after_binding")
        scheduler.append("test_scheduler_registered_after_binding")
        self.assertIs(sampler, source.INPUT_TYPES()["required"]["sampler"][0])
        self.assertIs(scheduler, source.INPUT_TYPES()["required"]["scheduler"][0])
        self.assertIs(sampler, source.RETURN_TYPES[2])
        self.assertIs(scheduler, source.RETURN_TYPES[3])
        self.assertIs(sampler, generation.RETURN_TYPES[11])
        self.assertEqual("test_sampler_registered_after_binding", generation.RETURN_TYPES[11][-1])
        self.assertEqual("test_scheduler_registered_after_binding", source.RETURN_TYPES[3][-1])

    def test_installed_impact_scheduler_adapter_preserves_base_selection(self):
        source = os.environ.get("LAKIS_IMPACT_SOURCE")
        if not source:
            self.skipTest("LAKIS_IMPACT_SOURCE required for installed adapter execution check")
        info = captured_native_info()
        schema = info["ImpactSchedulerAdapter"]
        base = schema["input"]["required"]["scheduler"][0]
        extended = info["DetailerForEach"]["input"]["required"]["scheduler"][0]
        # Execute only the installed provider's real adapter class, without
        # importing model-loading code or replacing its implementation.
        tree = ast.parse(Path(source).read_text(encoding="utf-8"))
        adapter = next(node for node in tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "ImpactSchedulerAdapter")
        namespace = {
            "comfy": types.SimpleNamespace(samplers=types.SimpleNamespace(
                KSampler=types.SimpleNamespace(SCHEDULERS=base))),
            "core": types.SimpleNamespace(get_schedulers=lambda: extended),
        }
        exec(compile(ast.Module(body=[adapter], type_ignores=[]), source, "exec"), namespace)
        provider = namespace["ImpactSchedulerAdapter"]
        self.assertEqual(schema["output"][0], provider.RETURN_TYPES[0])
        self.assertIs(base, provider.INPUT_TYPES()["required"]["scheduler"][0])
        for selected in base:
            self.assertEqual((selected,), provider().doit(selected, "None"))

    def test_native_lllite_rejects_active_missing_weight_before_provider(self):
        provider = Mock()
        nodes = types.SimpleNamespace(NODE_CLASS_MAPPINGS={"AnimaLLLiteApply_sdscripts": provider})
        folders = types.SimpleNamespace(get_filename_list=Mock(return_value=[]))
        with patch.dict(sys.modules, {"nodes": nodes, "folder_paths": folders}):
            with self.assertRaisesRegex(ValueError, "missing.safetensors.*not installed.*turn that control OFF"):
                REGISTRY["LAKIS_NativeLLLiteApply"]().apply(lllite_name="missing.safetensors")
        folders.get_filename_list.assert_called_once_with("controlnet")
        provider.assert_not_called()

    def test_native_lllite_preserves_provider_schema_and_delegates(self):
        provider = Mock()
        provider.FUNCTION = "apply"
        model = object()
        provider.apply.return_value = (model,)
        cls = Mock(return_value=provider)
        original = {"required": {"model": ("MODEL",), "lllite_name": (["present.safetensors"],),
                                 "image": ("IMAGE",), "strength": ("FLOAT", {"default": 1.})},
                    "optional": {"mask": ("MASK",)}}
        cls.INPUT_TYPES.return_value = original
        nodes = types.SimpleNamespace(NODE_CLASS_MAPPINGS={"AnimaLLLiteApply_sdscripts": cls})
        folders = types.SimpleNamespace(get_filename_list=Mock(return_value=["present.safetensors"]))
        inputs = {"model": model, "lllite_name": "present.safetensors", "image": object(),
                  "strength": 1., "start_percent": 0., "end_percent": 1.,
                  "preserve_wrapper": True, "mask": object()}
        wrapper = REGISTRY["LAKIS_NativeLLLiteApply"]
        with patch.dict(sys.modules, {"nodes": nodes, "folder_paths": folders}):
            schema = wrapper.INPUT_TYPES()
            self.assertEqual("STRING", schema["required"]["lllite_name"][0])
            self.assertEqual(original["optional"], schema["optional"])
            self.assertEqual(original["required"]["strength"], schema["required"]["strength"])
            self.assertEqual((["present.safetensors"],), original["required"]["lllite_name"])
            self.assertEqual((model,), wrapper().apply(**inputs))
            provider.apply.assert_called_once_with(**inputs)
            provider.apply.side_effect = FileNotFoundError("provider path/file check failed")
            with self.assertRaisesRegex(FileNotFoundError, "provider path/file"):
                wrapper().apply(**inputs)

    def test_mode_source_exclusivity_and_highrez(self):
        c = REGISTRY["LAKIS_GenerationControls"]()
        self.assertEqual((False, False, False), c.resolve("FAST", True, False, False, False, .5)[:3])
        self.assertEqual((True, True, False), c.resolve("DETAIL", True, False, False, False, .5)[:3])
        self.assertEqual((False, True, True), c.resolve("LAKIS DETAIL", True, False, False, False, .5)[:3])
        result = c.resolve("FAST", True, True, True, True, .5)
        self.assertEqual((False, False, True, False), result[3:7])
        result = c.resolve("DETAIL", True, True, False, True, .4)
        self.assertEqual((False, True, False, False), result[3:7])
        self.assertEqual((16, 6., "euler", .31), result[9:])
        self.assertEqual((3, 1., "gradient_estimation", .2), c.resolve("FAST", True, False, False, False, .5)[9:])

    def test_canvas_spectrum_alignment(self):
        self.assertEqual((736, 1008), REGISTRY["LAKIS_Canvas"]().resolve(728, 1001))

    def test_camera_lazy_contract(self):
        c = REGISTRY["LAKIS_CompositionPrompt"]()
        self.assertEqual([], c.check_lazy_status("scene", False))
        self.assertEqual(["camera"], c.check_lazy_status("scene", True))
        self.assertEqual(("scene",), c.combine("scene", False, "close up"))
        self.assertEqual(("scene, close up",), c.combine("scene", True, "close up"))

    def test_remove_ignores_prompts_has_denoise_floor_and_lora_gate(self):
        c = REGISTRY["LAKIS_InpaintPrompt"]()
        positive, negative, denoise, feather, color, loras, grow = c.resolve("remove", "do not leak", "nor this", .2, 8)
        self.assertNotIn("do not leak", positive)
        self.assertNotIn("nor this", negative)
        self.assertEqual((.72, 16, .8, False, 16), (denoise, feather, color, loras, grow))
        self.assertEqual(([],), REGISTRY["LAKIS_LoraGate"]().resolve(["a"], True, True, loras))

    def test_disabled_source_never_calls_image_loader(self):
        import torch  # Initialize before patch.dict snapshots sys.modules.
        with patch.dict(sys.modules, {"nodes": None}):
            image, mask = REGISTRY["LAKIS_OptionalImage"]().load(False, "missing.png", "red")
        self.assertEqual((1, 64, 64, 3), tuple(image.shape))
        self.assertEqual((1, 64, 64), tuple(mask.shape))

    def test_enabled_source_reuses_comfy_image_and_mask_loaders(self):
        import torch  # Keep native modules outside the mocked module scope.
        pixels, alpha, red = object(), object(), object()
        image_loader = Mock()
        image_loader.load_image.return_value = (pixels, alpha)
        mask_loader = Mock()
        mask_loader.load_image_mask.return_value = (red,)
        nodes = types.SimpleNamespace(LoadImage=Mock(return_value=image_loader),
                                      LoadImageMask=Mock(return_value=mask_loader))
        with patch.dict(sys.modules, {"nodes": nodes}):
            self.assertEqual((pixels, red), REGISTRY["LAKIS_OptionalImage"]().load(True, "mask.png", "red"))
            self.assertEqual((pixels, alpha), REGISTRY["LAKIS_OptionalImage"]().load(True, "source.png", "alpha"))
        mask_loader.load_image_mask.assert_called_once_with("mask.png", "red")

    def test_model_wrapper_forwards_the_proven_loader_and_exposes_selected_name(self):
        model = object()
        provider = Mock()
        provider.FUNCTION = "loadmodel"
        provider.loadmodel.return_value = (model,)
        cls = Mock(return_value=provider)
        cls.INPUT_TYPES.return_value = {"required": {"model_name": (["anima.safetensors"],)}}
        nodes = types.SimpleNamespace(NODE_CLASS_MAPPINGS={"DiffusionModelLoaderKJ": cls})
        wrapper = REGISTRY["LAKIS_DiffusionModelLoader"]
        with patch.dict(sys.modules, {"nodes": nodes}):
            self.assertEqual(cls.INPUT_TYPES(), wrapper.INPUT_TYPES())
            self.assertEqual((model, "anima.safetensors"),
                             wrapper().load(model_name="anima.safetensors", weight_dtype="bf16"))
        provider.loadmodel.assert_called_once_with(model_name="anima.safetensors", weight_dtype="bf16")


class NativeBridge(unittest.TestCase):
    def test_ui_configures_native_controls_without_replacing_graph_branches(self):
        import workflow_bridge as bridge
        api = read(NAMES[2])
        aliases = alias_view(api)
        info = {
            "DiffusionModelLoaderKJ": {"input": {"required": {
                "model_name": [[aliases["890:1365"]["inputs"]["model_name"]]]}}},
            "VAELoader": {"input": {"required": {"vae_name": [[aliases["890:159"]["inputs"]["vae_name"]]]}}},
            "CLIPLoader": {"input": {"required": {"clip_name": [[aliases["890:164"]["inputs"]["clip_name"]]]}}},
        }
        with tempfile.TemporaryDirectory(prefix="lakis-native-") as tmp:
            root = Path(tmp)
            with patch.multiple(bridge, TEMPLATE=ROOT / "workflows" / NAMES[2], COMFY_ROOT=root,
                                OUTPUT_ROOT=root / "output", OUTPUT_LOCATION_PATH=root / "location.json",
                                LEGACY_OUTPUT_LOCATION_PATH=root / "old-location.json"), \
                 patch.object(bridge, "_wait_for_comfy_object_info", return_value=info), \
                 patch.object(bridge, "_comfy_object_info", return_value=info), \
                 patch.object(bridge, "_preferred_upscaler", return_value=None), \
                 patch.object(bridge, "_live_lora_inventory", return_value=[]):
                result, report = bridge.build_prompt({
                    "generation": {"mode": "lakis_detail"}, "loras": [],
                    "composition_enabled": False, "output": {"seed": 42, "width": 1024, "height": 768}})
            self.assertTrue(report["native_workflow"])
            self.assertEqual(set(api), set(result) - {"lakis:configured_output_path"})
            self.assertEqual({k: n["class_type"] for k, n in api.items()},
                             {k: result[k]["class_type"] for k in api})
            self.assertEqual("LAKIS DETAIL", result["3000"]["inputs"]["mode"])
            self.assertEqual(768, result["3001"]["inputs"]["height"])
            self.assertEqual(["3003", 0], result["775"]["inputs"]["images"])


if __name__ == "__main__":
    unittest.main()
