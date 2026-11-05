"""Backend-free tests for the pure integrated MOSS feature helpers."""

import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))

import moss_features as features  # noqa: E402
import moss_sampling  # noqa: E402


CHECKPOINT = "moss_image_sft_int8_convrot.safetensors"
OTHER_CHECKPOINT = "moss_image_custom.safetensors"
MOSS_LORA = "moss/style.safetensors"
ALL_NODES = {"LoraLoaderModelOnly"}


def options_raw(*, checkpoint=CHECKPOINT, loras=None, regions=None,
                i2i=None, detail=None):
    return {
        "checkpoint": checkpoint,
        "i2i": {"enabled": False} if i2i is None else i2i,
        "loras": [] if loras is None else loras,
        "regions": (
            {"enabled": False, "regions": []}
            if regions is None else regions
        ),
        "detail": (
            {"enabled": False, "scope": "image", "scope_enabled": False}
            if detail is None else detail
        ),
    }


def validate(raw=None, *, width=1024, height=1024, nodes=ALL_NODES):
    return features.validate_options(
        options_raw() if raw is None else raw,
        checkpoints=[CHECKPOINT, OTHER_CHECKPOINT],
        loras=[MOSS_LORA, "moss/second.safetensors"],
        width=width,
        height=height,
        available_nodes=nodes,
    )


def base_params(prompt="a moss garden", *, width=1024, height=1024, seed=937):
    return {
        "prompt": prompt,
        "negative_prompt": "blurry",
        "width": width,
        "height": height,
        "steps": 50,
        "cfg": 3.0,
        "seed": seed,
    }


def base_graph():
    """Minimal MOSS graph with LAKIS Final Saver 775 and no SaveImage 11."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": CHECKPOINT, "weight_dtype": "default"}},
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {
            "model": ["1", 0], "shift": 5.0}},
        "3": {"class_type": "SkipLayerGuidanceDiTSimple", "inputs": {
            "model": ["2", 0], "double_layers": "", "single_layers": "22",
            "start_percent": 0.0, "end_percent": 0.5}},
        "4": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3.5_9b_int8_convrot.safetensors",
            "type": "moss_image", "device": "default"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["4", 0], "text": "a moss garden"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["4", 0], "text": "blurry"}},
        "7": {"class_type": "EmptyFlux2LatentImage", "inputs": {
            "width": 1024, "height": 1024, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["3", 0], "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["7", 0], "seed": 937,
            "control_after_generate": "fixed", "steps": 50, "cfg": 3.0,
            "sampler_name": "euler", "scheduler": "sgm_uniform", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {
            "samples": ["8", 0], "vae": ["10", 0]}},
        "10": {"class_type": "VAELoader", "inputs": {
            "vae_name": "flux2-vae.safetensors"}},
        "775": {"class_type": "Image Saver", "inputs": {
            "images": ["9", 0], "filename": "LAKIS_MOSS_937",
            "path": "output/LAKIS"}},
    }


def nodes_of(graph, class_type):
    return [(node_id, node) for node_id, node in graph.items()
            if node["class_type"] == class_type]


class ValidateOptionsTests(unittest.TestCase):
    def test_blank_disabled_lora_rows_are_ignored_and_never_applied(self):
        for name in ("", "   "):
            raw = options_raw(loras=[{"name": name, "enabled": False}])
            original = copy.deepcopy(raw)
            options = validate(raw, nodes=set())
            self.assertEqual(options["loras"], [])
            self.assertEqual(raw, original)
            graph = features.augment_workflow(base_graph(), base_params(), options)
            self.assertEqual(nodes_of(graph, "LoraLoaderModelOnly"), [])
            raw["loras"][0]["enabled"] = True
            with self.assertRaisesRegex(ValueError, "name"):
                validate(raw)

    def test_active_loras_require_exact_moss_inventory_and_safe_relative_names(self):
        for name, inventory, message in (
            ("moss/missing.safetensors", [MOSS_LORA], "현재 MOSS LoRA 목록"),
            ("flux/style.safetensors", ["flux/style.safetensors"], "moss/ 계열"),
        ):
            raw = options_raw(loras=[{
                "name": name, "strength": 1, "enabled": True,
            }])
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                features.validate_options(
                    raw, checkpoints=[CHECKPOINT], loras=inventory,
                    width=1024, height=1024, available_nodes=ALL_NODES,
                )

        unsafe_names = (
            "moss/../other/style.safetensors",
            r"moss\..\other\style.safetensors",
            r"\moss\style.safetensors",
            r"C:\moss\style.safetensors",
            "moss//style.safetensors",
        )
        for name in unsafe_names:
            raw = options_raw(loras=[{
                "name": name, "strength": 1, "enabled": True,
            }])
            with self.subTest(name=name), self.assertRaises(ValueError):
                features.validate_options(
                    raw, checkpoints=[CHECKPOINT], loras=[name],
                    width=1024, height=1024, available_nodes=ALL_NODES,
                )

    def test_disabled_lora_selections_are_preserved_without_inventory_match(self):
        selection = {
            "name": "another-family/remembered.safetensors",
            "strength": -0.5,
            "enabled": False,
        }
        options = validate(options_raw(loras=[selection]))
        self.assertEqual(options["loras"], [{
            "name": selection["name"],
            "strength": -0.5,
            "enabled": False,
        }])
        graph = features.augment_workflow(base_graph(), base_params(), options)
        self.assertEqual(nodes_of(graph, "LoraLoaderModelOnly"), [])

    def test_checkpoint_and_enabled_lora_strength_bounds(self):
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            validate(options_raw(checkpoint="moss/not-installed.safetensors"))
        for strength in (-2.0, 2):
            options = validate(options_raw(loras=[{
                "name": MOSS_LORA, "strength": strength, "enabled": True,
            }]))
            self.assertEqual(options["loras"][0]["strength"], float(strength))
        for strength in (-2.01, 2.01, True, float("nan"), float("inf")):
            with self.subTest(strength=strength), self.assertRaises(ValueError):
                validate(options_raw(loras=[{
                    "name": MOSS_LORA, "strength": strength, "enabled": True,
                }]))
        with self.assertRaisesRegex(ValueError, "LoraLoaderModelOnly"):
            validate(options_raw(loras=[{
                "name": MOSS_LORA, "strength": 1, "enabled": True,
            }]), nodes=set())

    def test_fast_preview_rejects_enabled_i2i_detail_and_scope(self):
        for raw in (
            options_raw(i2i={"enabled": True}),
            options_raw(detail={"enabled": True, "scope_enabled": False}),
            options_raw(detail={"enabled": False, "scope_enabled": True}),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate(raw)

    def test_regions_normalize_to_the_prototype_schema(self):
        region = {
            "id": "headline",
            "type": "text",
            "label": "text",
            "caption": 'sign says "hello"',
            "text": "MOSS",
            "negative_prompt": "garbled letters",
            "bbox": [100, 125, 900, 875],
        }
        raw = options_raw(regions={"enabled": True, "regions": [region]})
        original = copy.deepcopy(raw)
        options = validate(raw, width=1536, height=1024)
        self.assertEqual(raw, original)
        self.assertEqual(options["regions"], {
            "enabled": True,
            "regions": [{
                "id": "headline",
                "label": "text",
                "caption": 'sign says "hello"',
                "bbox": [100, 125, 900, 875],
                "negative_prompt": "garbled letters",
                "text": "MOSS",
            }],
        })

    def test_region_bounds_and_text_constraints(self):
        invalid_boxes = (
            [600, 100, 500, 200], [-1, 0, 100, 100],
            [0, 0, 1001, 100], [0, 0, float("nan"), 100],
            [0, 200, 100, 200],
        )
        for bbox in invalid_boxes:
            raw = options_raw(regions={"enabled": True, "regions": [{
                "id": "r1", "label": "object", "caption": "box", "bbox": bbox,
            }]})
            with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                validate(raw)

        for width, height in ((0, 1024), (1024, -1), (True, 1024), (1024.0, 1024)):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                validate(width=width, height=height)

        invalid_text = "x" * 2001
        raw = options_raw(regions={"enabled": True, "regions": [{
            "id": "too-long", "label": "object", "caption": invalid_text,
            "bbox": [0, 0, 1000, 1000],
        }]})
        with self.assertRaisesRegex(ValueError, "caption"):
            validate(raw)


class CompileLayoutTests(unittest.TestCase):
    def test_centered_native_yxyx_coordinates_and_text_escaping(self):
        region = {
            "id": "text-id",
            "label": "text",
            "caption": 'a "quoted" sign',
            "text": 'KEEP\\this\nexactly',
            "bbox": [100, 125, 900, 875],
        }
        serialized = features.compile_layout("  wide scene  ", [region], 1536, 1024)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["summary"], {"caption": "wide scene"})
        self.assertEqual(parsed["items"], [{
            "label": "text",
            "caption": 'a "quoted" sign',
            "text": 'KEEP\\this\nexactly',
            "bbox": [-384, -615, 384, 615],
        }])
        self.assertEqual(parsed["bbox_coord_space"], "abs_centralized")
        self.assertEqual(parsed["bbox_format"], "yxyx")
        self.assertNotIn("text-id", serialized)
        self.assertIn("\\n", serialized)

    def test_inactive_or_empty_layout_returns_prompt_unchanged(self):
        prompt = "  preserve this exactly\n"
        self.assertEqual(features.compile_layout(
            prompt, {"enabled": False, "regions": [{"invalid": True}]}, 1024, 1024,
        ), prompt)
        self.assertEqual(features.compile_layout(prompt, [], 1024, 1024), prompt)


class AugmentWorkflowTests(unittest.TestCase):
    def test_loras_and_regional_text_preserve_links_and_final_saver(self):
        graph = base_graph()
        saver = copy.deepcopy(graph["775"])
        snapshot = copy.deepcopy(graph)
        regions = [
            {"id": "cup", "label": "object", "caption": "cup",
             "bbox": [0, 0, 500, 500], "negative_prompt": "cracks"},
            {"id": "person", "label": "character", "caption": "gardener",
             "bbox": [500, 0, 1000, 1000]},
        ]
        options = validate(options_raw(
            checkpoint=OTHER_CHECKPOINT,
            loras=[
                {"name": MOSS_LORA, "strength": 0.7, "enabled": True},
                {"name": "remembered/offline.safetensors", "strength": 0.2,
                 "enabled": False},
                {"name": "moss/second.safetensors", "strength": -0.4,
                 "enabled": True},
            ],
            regions={"enabled": True, "regions": regions},
        ))
        params = base_params()
        result = features.augment_workflow(graph, params, options)

        self.assertEqual(result["1"]["inputs"]["unet_name"], OTHER_CHECKPOINT)
        loaders = nodes_of(result, "LoraLoaderModelOnly")
        self.assertEqual(len(loaders), 2)
        first_id, first = loaders[0]
        second_id, second = loaders[1]
        self.assertEqual(first["inputs"], {
            "model": ["1", 0], "lora_name": MOSS_LORA, "strength_model": 0.7,
        })
        self.assertEqual(second["inputs"], {
            "model": [first_id, 0], "lora_name": "moss/second.safetensors",
            "strength_model": -0.4,
        })
        self.assertEqual(result["2"]["inputs"]["model"], [second_id, 0])
        self.assertEqual(result["3"]["inputs"]["model"], ["2", 0])
        self.assertEqual(result["8"]["inputs"]["model"], ["3", 0])
        self.assertEqual(json.loads(result["5"]["inputs"]["text"])["items"][0]["caption"], "cup")
        negative_layout = json.loads(result["6"]["inputs"]["text"])
        self.assertEqual(negative_layout["summary"], {"caption": "blurry"})
        self.assertEqual(
            negative_layout["items"],
            [{"label": "object", "caption": "cracks", "bbox": [-512, -512, 0, 0]}],
        )
        self.assertEqual(result["775"], saver)
        self.assertNotIn("11", result)
        self.assertEqual(graph, snapshot)

    def test_precompiled_positive_layout_is_not_nested(self):
        graph = base_graph()
        regions = [{
            "id": "tree", "label": "object", "caption": "tree",
            "bbox": [0, 0, 1000, 1000],
        }]
        options = validate(options_raw(
            regions={"enabled": True, "regions": regions},
        ))
        params = base_params()
        params["prompt"] = features.compile_layout(
            params["prompt"], options["regions"], params["width"], params["height"])
        graph["5"]["inputs"]["text"] = params["prompt"]
        result = features.augment_workflow(graph, params, options)
        self.assertEqual(
            json.loads(result["5"]["inputs"]["text"])["summary"],
            {"caption": "a moss garden"},
        )
        self.assertEqual(
            json.loads(result["5"]["inputs"]["text"])["items"][0]["caption"],
            "tree",
        )

    def test_disabled_features_return_an_equal_new_graph_without_saveimage(self):
        graph = base_graph()
        snapshot = copy.deepcopy(graph)
        result = features.augment_workflow(graph, base_params(), validate())
        self.assertEqual(result, snapshot)
        self.assertIsNot(result, graph)
        self.assertNotIn("11", result)


def sampling_schema():
    return {
        "KSampler": {"input": {"required": {
            "sampler_name": [["euler", "heun", "dpmpp_2m"]],
            "scheduler": [["sgm_uniform", "simple", "normal"]],
        }}},
        "UNETLoader": {"input": {"required": {
            "weight_dtype": [["default", "fp8_e4m3fn"]],
        }}},
        "ModelSamplingAuraFlow": {"input": {"required": {
            "shift": ["FLOAT", {"default": 1.73, "min": 0.0, "max": 100.0, "step": 0.01}],
        }}},
        "SkipLayerGuidanceDiTSimple": {"input": {"required": {
            "double_layers": ["STRING", {"default": "7, 8, 9"}],
            "single_layers": ["STRING", {"default": "7, 8, 9"}],
            "start_percent": ["FLOAT", {"min": 0.0, "max": 1.0, "step": 0.001}],
            "end_percent": ["FLOAT", {"min": 0.0, "max": 1.0, "step": 0.001}],
        }}},
        "CLIPLoader": {"input": {"optional": {"device": [["default", "cpu"]]}}},
    }


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.graph = base_graph()
        self.schema = sampling_schema()

    def test_configuration_uses_live_schema_bounds_and_workflow_defaults(self):
        config = moss_sampling.configuration(self.schema, self.graph)
        fields = {
            node["id"]: {field["name"]: field for field in node["fields"]}
            for node in config["model"]
        }
        self.assertEqual(fields["moss:2"]["shift"]["value"], 5.0)
        self.assertEqual(fields["moss:2"]["shift"]["max"], 100.0)
        self.assertEqual(fields["moss:3"]["single_layers"]["value"], "22")
        self.assertEqual(fields["moss:4"]["device"]["options"], ["default", "cpu"])
        self.assertNotIn("unet_name", fields["moss:1"])
        self.assertNotIn("moss:11", fields)
        self.assertEqual(moss_sampling.sampling_choices(self.schema)["sampler"],
                         ["euler", "heun", "dpmpp_2m"])

    def test_sampling_settings_apply_without_changing_links_or_final_saver(self):
        snapshot = copy.deepcopy(self.graph)
        settings = moss_sampling.normalize({
            "sampler": "heun", "scheduler": "simple",
            "node_overrides": {
                "moss:2": {"shift": 4.25},
                "moss:3": {"start_percent": 0.1, "end_percent": 0.6},
            },
        }, self.schema, self.graph)
        moss_sampling.apply(self.graph, settings)
        self.assertEqual(self.graph["8"]["inputs"]["sampler_name"], "heun")
        self.assertEqual(self.graph["8"]["inputs"]["scheduler"], "simple")
        self.assertEqual(self.graph["2"]["inputs"]["shift"], 4.25)
        self.assertEqual(self.graph["3"]["inputs"]["end_percent"], 0.6)
        for node in ("5", "6", "7", "9", "10", "775"):
            self.assertEqual(self.graph[node], snapshot[node])
        self.assertEqual(self.graph["8"]["inputs"]["model"], snapshot["8"]["inputs"]["model"])
        self.assertEqual(self.graph["8"]["inputs"]["denoise"], 1.0)

    def test_invalid_sampler_overrides_and_arbitrary_nodes_are_rejected(self):
        invalid = [
            {"sampler": "missing"}, {"scheduler": "missing"},
            {"node_overrides": {"moss:11": {"filename_prefix": "../escape"}}},
            {"node_overrides": {"moss:2": {"model": ["11", 0]}}},
            {"node_overrides": {"moss:1": {"weight_dtype": "unknown"}}},
            {"node_overrides": {"moss:3": {"start_percent": 0.9}}},
        ]
        for value in (True, float("nan"), float("inf"), -0.1, 100.1, "5"):
            invalid.append({"node_overrides": {"moss:2": {"shift": value}}})
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                moss_sampling.normalize(raw, self.schema, self.graph)


if __name__ == "__main__":
    unittest.main()
