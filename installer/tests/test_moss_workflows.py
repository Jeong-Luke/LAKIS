"""Focused MOSS workflow resource, graph, and prompt-contract checks."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/runtime"))
sys.path.insert(0, str(ROOT / "src/external_ui"))
import moss_features
import moss_workflows
from native_workflow import validate_enum_edges


def _node_info(required=(), optional=(), output=(), output_names=()):
    required = dict(required)
    optional = dict(optional)
    return {
        "input": {"required": required, "optional": optional},
        "input_order": {
            "required": list(required),
            "optional": list(optional),
        },
        "output": list(output),
        "output_name": list(output_names),
    }


def installed_info():
    combo = lambda *values: (list(values),)
    socket = lambda kind: (kind,)
    scalar = lambda kind, **options: (kind, options)
    samplers = ["euler", "heun"]
    schedulers = ["sgm_uniform", "karras"]
    info = {
        "UNet loader with Name (Image Saver)": _node_info(
            [("unet_name", combo("moss_image_sft_int8_convrot.safetensors")),
             ("weight_dtype", combo("default", "fp8_e4m3fn"))],
            output=("MODEL", "STRING"), output_names=("model", "filename")),
        "ModelSamplingAuraFlow": _node_info(
            [("model", socket("MODEL")),
             ("shift", scalar("FLOAT", min=0.0, max=100.0))],
            [("sampling", combo("flow", "img_to_img_velocity"))],
            output=("MODEL",), output_names=("MODEL",)),
        "SkipLayerGuidanceDiTSimple": _node_info(
            [("model", socket("MODEL")),
             ("double_layers", scalar("STRING")),
             ("single_layers", scalar("STRING")),
             ("start_percent", scalar("FLOAT", min=0.0, max=1.0)),
             ("end_percent", scalar("FLOAT", min=0.0, max=1.0))],
            output=("MODEL",), output_names=("MODEL",)),
        "CLIPLoader": _node_info(
            [("clip_name", combo("qwen3.5_9b_int8_convrot.safetensors")),
             ("type", combo("moss_image"))],
            [("device", combo("default", "cpu"))],
            output=("CLIP",), output_names=("CLIP",)),
        "CLIPTextEncode": _node_info(
            [("text", scalar("STRING", multiline=True)),
             ("clip", socket("CLIP"))],
            output=("CONDITIONING",), output_names=("CONDITIONING",)),
        "EmptyFlux2LatentImage": _node_info(
            [("width", scalar("INT", min=16, max=16384, step=16)),
             ("height", scalar("INT", min=16, max=16384, step=16)),
             ("batch_size", scalar("INT", min=1, max=4096))],
            output=("LATENT",), output_names=("LATENT",)),
        "KSampler": _node_info(
            [("model", socket("MODEL")),
             ("seed", scalar("INT", control_after_generate=True)),
             ("steps", scalar("INT", min=1, max=10000)),
             ("cfg", scalar("FLOAT", min=0.0, max=100.0)),
             ("sampler_name", combo(*samplers)),
             ("scheduler", combo(*schedulers)),
             ("positive", socket("CONDITIONING")),
             ("negative", socket("CONDITIONING")),
             ("latent_image", socket("LATENT")),
             ("denoise", scalar("FLOAT", min=0.0, max=1.0))],
            output=("LATENT",), output_names=("LATENT",)),
        "VAEDecode": _node_info(
            [("samples", socket("LATENT")), ("vae", socket("VAE"))],
            output=("IMAGE",), output_names=("IMAGE",)),
        "VAELoader": _node_info(
            [("vae_name", combo("flux2-vae.safetensors"))],
            output=("VAE",), output_names=("VAE",)),
        "PrimitiveStringMultiline": _node_info(
            [("value", scalar("STRING", multiline=True))],
            output=("STRING",), output_names=("STRING",)),
        "PrimitiveInt": _node_info(
            [("value", scalar("INT", min=-2**63, max=2**63 - 1,
                              control_after_generate="fixed"))],
            output=("INT",), output_names=("INT",)),
        "PrimitiveFloat": _node_info(
            [("value", scalar("FLOAT", min=-2**63, max=2**63 - 1, step=0.1))],
            output=("FLOAT",), output_names=("FLOAT",)),
        "Sampler Selector (Image Saver)": _node_info(
            [("sampler_name", combo(*samplers))],
            output=(samplers, "STRING"), output_names=("sampler", "sampler_name")),
        "Scheduler Selector (Image Saver)": _node_info(
            [("scheduler", combo(*schedulers))],
            output=(schedulers, "STRING"), output_names=("scheduler", "scheduler_name")),
        "Image Saver": _node_info(
            [("images", socket("IMAGE")),
             ("filename", scalar("STRING")),
             ("path", scalar("STRING")),
             ("extension", combo("png", "jpeg", "jpg", "webp"))],
            [("steps", scalar("INT")),
             ("cfg", scalar("FLOAT")),
             ("modelname", scalar("STRING")),
             ("sampler_name", scalar("STRING")),
             ("scheduler_name", scalar("STRING")),
             ("positive", scalar("STRING")),
             ("negative", scalar("STRING")),
             ("seed_value", scalar("INT")),
             ("width", scalar("INT")),
             ("height", scalar("INT")),
             ("lossless_webp", scalar("BOOLEAN")),
             ("quality_jpeg_or_webp", scalar("INT")),
             ("optimize_png", scalar("BOOLEAN")),
             ("counter", scalar("INT")),
             ("denoise", scalar("FLOAT")),
             ("clip_skip", scalar("INT")),
             ("time_format", scalar("STRING")),
             ("save_workflow_as_json", scalar("BOOLEAN")),
             ("embed_workflow", scalar("BOOLEAN")),
             ("additional_hashes", scalar("STRING")),
             ("download_civitai_data", scalar("BOOLEAN")),
             ("easy_remix", scalar("BOOLEAN")),
             ("show_preview", scalar("BOOLEAN")),
             ("custom", scalar("STRING"))],
            output=("STRING", "STRING"),
            output_names=("hashes", "a1111_params")),
    }
    return info


def _api_from_editable(workflow):
    links = {link[0]: link for link in workflow["links"]}
    graph = {}
    for node in workflow["nodes"]:
        source_id = node.get("properties", {}).get("lakis_source_id")
        if source_id is None:
            continue
        names = node["properties"].get("lakis_widget_names", [])
        values = node.get("widgets_values", [])
        inputs = {name: value for name, value in zip(names, values) if name != "fixed"}
        for socket in node.get("inputs", []):
            link_id = socket.get("link")
            if link_id is not None:
                link = links[link_id]
                inputs[socket["name"]] = [str(link[1]), link[2]]
        graph[str(source_id)] = {
            "class_type": node["properties"]["Node name for S&R"],
            "inputs": inputs,
        }
    return graph


def _without_metadata(graph):
    return {
        str(key): {
            "class_type": node["class_type"],
            "inputs": deepcopy(node["inputs"]),
        }
        for key, node in graph.items()
    }


def _resolve_input(graph, node_id, name):
    value = graph[str(node_id)]["inputs"][name]
    while isinstance(value, list) and len(value) == 2 and type(value[1]) is int:
        source = graph[str(value[0])]
        class_type = source["class_type"]
        if class_type == "UNet loader with Name (Image Saver)":
            value = source["inputs"]["unet_name"]
        elif class_type == "Sampler Selector (Image Saver)":
            value = source["inputs"]["sampler_name"]
        elif class_type == "Scheduler Selector (Image Saver)":
            value = source["inputs"]["scheduler"]
        else:
            value = source["inputs"]["value"]
    return value


class MossWorkflows(unittest.TestCase):
    def test_module_resolves_source_and_installed_resources_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_module = root / "repo" / "src" / "external_ui" / "moss_workflows.py"
            installed_module = root / "ComfyUI" / "LAKIS" / "external_ui" / "moss_workflows.py"
            with patch.object(moss_workflows, "__file__", str(source_module)):
                self.assertEqual(
                    moss_workflows.workflow_path(),
                    root / "repo" / "workflows" / moss_workflows.API_NAME,
                )
                self.assertEqual(
                    moss_workflows.workflow_path(editable=True),
                    root / "repo" / "workflows" / moss_workflows.EDITABLE_NAME,
                )
            with patch.object(moss_workflows, "__file__", str(installed_module)):
                self.assertEqual(
                    moss_workflows.workflow_path(),
                    installed_module.parent / "workflows" / moss_workflows.API_NAME,
                )
                self.assertEqual(
                    moss_workflows.workflow_path(editable=True),
                    installed_module.parent / "workflows" / moss_workflows.EDITABLE_NAME,
                )
                with self.assertRaises(FileNotFoundError):
                    moss_workflows.load_api()

    def test_loaders_read_both_resources_without_mutating_them(self):
        api_path = ROOT / "workflows" / moss_workflows.API_NAME
        editable_path = ROOT / "workflows" / moss_workflows.EDITABLE_NAME
        before = {path: path.read_bytes() for path in (api_path, editable_path)}
        api = moss_workflows.load_api()
        editable = moss_workflows.load_editable()
        self.assertEqual(api, json.loads(before[api_path]))
        self.assertEqual(editable, json.loads(before[editable_path]))
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_api_and_editable_graphs_preserve_working_moss_contract(self):
        api = moss_workflows.load_api()
        editable = moss_workflows.load_editable()
        expected_ids = {str(value) for value in range(1, 11)} | {
            str(value) for value in range(12, 21)
        } | {"775"}
        self.assertEqual(set(api), expected_ids)
        self.assertEqual(_api_from_editable(editable), _without_metadata(api))

        expected_types = {
            "1": "UNet loader with Name (Image Saver)",
            "2": "ModelSamplingAuraFlow",
            "3": "SkipLayerGuidanceDiTSimple",
            "4": "CLIPLoader",
            "5": "CLIPTextEncode",
            "6": "CLIPTextEncode",
            "7": "EmptyFlux2LatentImage",
            "8": "KSampler",
            "9": "VAEDecode",
            "10": "VAELoader",
            "775": "Image Saver",
            "12": "PrimitiveStringMultiline",
            "13": "PrimitiveStringMultiline",
            "14": "PrimitiveInt",
            "15": "PrimitiveInt",
            "16": "PrimitiveFloat",
            "17": "PrimitiveInt",
            "18": "PrimitiveInt",
            "19": "Sampler Selector (Image Saver)",
            "20": "Scheduler Selector (Image Saver)",
        }
        self.assertEqual(
            {key: node["class_type"] for key, node in api.items()},
            expected_types,
        )
        self.assertEqual(api["2"]["inputs"]["model"], ["1", 0])
        self.assertEqual(api["2"]["inputs"]["shift"], 5.0)
        self.assertEqual(api["3"]["inputs"], {
            "model": ["2", 0],
            "double_layers": "",
            "single_layers": "22",
            "start_percent": 0.0,
            "end_percent": 0.5,
        })
        self.assertEqual(api["1"]["inputs"], {
            "unet_name": "moss_image_sft_int8_convrot.safetensors",
            "weight_dtype": "default",
        })
        self.assertEqual(api["4"]["inputs"], {
            "clip_name": "qwen3.5_9b_int8_convrot.safetensors",
            "type": "moss_image",
            "device": "default",
        })
        self.assertEqual(api["10"]["inputs"]["vae_name"], "flux2-vae.safetensors")
        self.assertEqual(api["7"]["inputs"], {
            "width": ["17", 0], "height": ["18", 0], "batch_size": 1,
        })
        self.assertEqual(
            {key: api["8"]["inputs"][key] for key in (
                "seed", "control_after_generate", "steps", "cfg",
                "sampler_name", "scheduler", "denoise")},
            {
                "seed": ["14", 0], "control_after_generate": "fixed",
                "steps": ["15", 0], "cfg": ["16", 0],
                "sampler_name": ["19", 0], "scheduler": ["20", 0],
                "denoise": 1.0,
            },
        )
        self.assertEqual(api["775"]["inputs"]["images"], ["9", 0])
        self.assertEqual(api["775"]["inputs"]["path"], "")
        for saver_key, source in (
            ("positive", "12"), ("negative", "13"), ("seed_value", "14"),
            ("steps", "15"), ("cfg", "16"), ("width", "17"), ("height", "18"),
        ):
            self.assertEqual(api["775"]["inputs"][saver_key], [source, 0])
        self.assertEqual(api["775"]["inputs"]["modelname"], ["1", 1])
        self.assertEqual(api["775"]["inputs"]["sampler_name"], ["19", 1])
        self.assertEqual(api["775"]["inputs"]["scheduler_name"], ["20", 1])
        self.assertEqual(api["19"]["inputs"], {"sampler_name": "euler"})
        self.assertEqual(api["20"]["inputs"], {"scheduler": "sgm_uniform"})
        self.assertEqual(api["1"]["class_type"], "UNet loader with Name (Image Saver)")
        validate_enum_edges(api, installed_info())
        self.assertEqual(json.loads(api["775"]["inputs"]["custom"]), {"generation_engine": "moss"})
        self.assertEqual(_resolve_input(api, "5", "text"), _resolve_input(api, "775", "positive"))
        self.assertEqual(_resolve_input(api, "6", "text"), _resolve_input(api, "775", "negative"))
        self.assertEqual(_resolve_input(api, "8", "seed"), _resolve_input(api, "775", "seed_value"))
        self.assertEqual(_resolve_input(api, "8", "steps"), _resolve_input(api, "775", "steps"))
        self.assertEqual(_resolve_input(api, "8", "cfg"), _resolve_input(api, "775", "cfg"))
        self.assertEqual(_resolve_input(api, "7", "width"), _resolve_input(api, "775", "width"))
        self.assertEqual(_resolve_input(api, "7", "height"), _resolve_input(api, "775", "height"))
        self.assertEqual(_resolve_input(api, "8", "sampler_name"), _resolve_input(api, "775", "sampler_name"))
        self.assertEqual(_resolve_input(api, "8", "scheduler"), _resolve_input(api, "775", "scheduler_name"))
        self.assertEqual(_resolve_input(api, "1", "unet_name"), _resolve_input(api, "775", "modelname"))
        for node in api.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and type(value[1]) is int:
                    self.assertIn(str(value[0]), api)

        classes = {node["class_type"] for node in api.values()}
        self.assertEqual(classes - {"LoraLoaderModelOnly"}, set(expected_types.values()))
        self.assertFalse(any("anima" in value.lower() for value in json.dumps(api).split('"')))
        self.assertNotIn("LoraLoaderModelOnly", classes)
        self.assertEqual(api["2"]["inputs"]["model"], ["1", 0])
        self.assertFalse(any(
            isinstance(value, str) and Path(value).is_absolute()
            for node in api.values() for value in node["inputs"].values()
        ))

        for node_id in ("12", "13"):
            layout = json.loads(api[node_id]["inputs"]["value"])
            self.assertEqual(layout["summary"]["caption"], "")
            self.assertEqual(layout["items"][0]["label"], "character")
            self.assertEqual(layout["items"][0]["caption"], "")
            self.assertEqual(layout["items"][0]["bbox"], [-410, -410, 410, 410])
            self.assertEqual(layout["bbox_coord_space"], "abs_centralized")
            self.assertEqual(layout["bbox_format"], "yxyx")

        self.assertEqual(editable["extra"]["lakis_terminal_image"], 775)
        self.assertEqual(
            {node["properties"]["lakis_source_id"] for node in editable["nodes"]
             if node.get("properties", {}).get("lakis_source_id")},
            expected_ids,
        )
        ui_nodes = {node["id"]: node for node in editable["nodes"]}
        for link_id, source_id, source_slot, target_id, target_slot, _ in editable["links"]:
            self.assertIn(source_id, ui_nodes)
            self.assertIn(target_id, ui_nodes)
            self.assertIn(link_id, ui_nodes[source_id]["outputs"][source_slot]["links"])
            self.assertEqual(ui_nodes[target_id]["inputs"][target_slot]["link"], link_id)

    def test_schema_conversion_preserves_graph_and_native_widget_order(self):
        api = moss_workflows.load_api()
        before = deepcopy(api)
        editable = moss_workflows.convert_api_to_editable(api, installed_info())
        self.assertEqual(api, before)
        self.assertEqual(_api_from_editable(editable), _without_metadata(api))

        nodes = {node["id"]: node for node in editable["nodes"]}
        native_info = installed_info()
        validate_enum_edges(_api_from_editable(editable), native_info)
        self.assertEqual(
            nodes[8]["properties"]["lakis_widget_names"],
            ["seed", "control_after_generate", "steps", "cfg", "sampler_name",
             "scheduler", "denoise"],
        )
        self.assertEqual(
            [entry["name"] for entry in nodes[8]["inputs"]],
            ["model", "seed", "steps", "cfg", "sampler_name", "scheduler",
             "positive", "negative", "latent_image"],
        )
        self.assertEqual(nodes[5]["properties"]["lakis_widget_names"], ["text"])
        self.assertEqual([entry["name"] for entry in nodes[5]["inputs"]], ["text", "clip"])
        self.assertEqual(
            [entry["name"] for entry in nodes[775]["inputs"]],
            ["images", "steps", "cfg", "modelname", "sampler_name",
             "scheduler_name", "positive", "negative", "seed_value", "width", "height"],
        )
        self.assertEqual(nodes[775]["properties"]["lakis_widget_names"][0:4],
                         ["filename", "path", "extension", "steps"])
        self.assertEqual(nodes[14]["properties"]["lakis_widget_names"], ["value", "fixed"])
        self.assertEqual(nodes[12]["pos"], [40, 1230])
        self.assertEqual([output["type"] for output in nodes[1]["outputs"]], ["MODEL", "STRING"])
        self.assertEqual(
            [(output["name"], output["type"]) for output in nodes[19]["outputs"]],
            [("sampler", "COMBO"), ("sampler_name", "STRING")],
        )
        self.assertEqual(
            [(output["name"], output["type"]) for output in nodes[20]["outputs"]],
            [("scheduler", "COMBO"), ("scheduler_name", "STRING")],
        )
        ui_links = {(link[1], link[2], link[3], link[4], link[5])
                    for link in editable["links"]}
        self.assertIn((19, 0, 8, 4, "COMBO"), ui_links)
        self.assertIn((19, 1, 775, 4, "STRING"), ui_links)
        self.assertIn((20, 0, 8, 5, "COMBO"), ui_links)
        self.assertIn((20, 1, 775, 5, "STRING"), ui_links)
        self.assertIn((1, 1, 775, 3, "STRING"), ui_links)
        self.assertEqual(editable["extra"]["lakis_native_version"], "8.1")
        with self.assertRaisesRegex(ValueError, "object-info"):
            moss_workflows.convert_api_to_editable(api)

    def test_supplied_model_only_lora_is_preserved_without_a_default_example(self):
        api = moss_workflows.load_api()
        adapter_name = "inventory-supplied-moss-adapter.safetensors"
        api["22"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": adapter_name,
                "strength_model": 0.65,
            },
        }
        api["2"]["inputs"]["model"] = ["22", 0]
        info = installed_info()
        info["LoraLoaderModelOnly"] = _node_info(
            [("model", ("MODEL",)),
             ("lora_name", ([adapter_name],)),
             ("strength_model", ("FLOAT", {"min": -100.0, "max": 100.0}))],
            output=("MODEL",), output_names=("MODEL",),
        )
        editable = moss_workflows.convert_api_to_editable(api, info)
        self.assertEqual(_api_from_editable(editable), _without_metadata(api))
        self.assertNotIn(
            "LoraLoaderModelOnly",
            {node["class_type"] for node in moss_workflows.load_api().values()},
        )

    def test_changed_controls_drive_generation_and_saved_metadata(self):
        api = moss_workflows.load_api()
        changed = {
            "12": '{"summary":{"caption":"new global café"},"items":[{"label":"character","caption":"exact regional text","bbox":[-410,-410,410,410]}],"bbox_coord_space":"abs_centralized","bbox_format":"yxyx"}',
            "13": '{"summary":{"caption":"new negative"},"items":[{"label":"character","caption":"avoid blur","bbox":[-410,-410,410,410]}],"bbox_coord_space":"abs_centralized","bbox_format":"yxyx"}',
            "14": 54821,
            "15": 37,
            "16": 4.25,
            "17": 768,
            "18": 1152,
            "checkpoint": "alternate_moss_checkpoint.safetensors",
            "19": "heun",
            "20": "karras",
        }
        for node_id, value in changed.items():
            if node_id in ("checkpoint",):
                api["1"]["inputs"]["unet_name"] = value
            elif node_id == "19":
                api[node_id]["inputs"]["sampler_name"] = value
            elif node_id == "20":
                api[node_id]["inputs"]["scheduler"] = value
            else:
                api[node_id]["inputs"]["value"] = value

        def assert_saved_values(graph):
            expected = {
                ("5", "text"): changed["12"],
                ("6", "text"): changed["13"],
                ("8", "seed"): changed["14"],
                ("8", "steps"): changed["15"],
                ("8", "cfg"): changed["16"],
                ("7", "width"): changed["17"],
                ("7", "height"): changed["18"],
                ("8", "sampler_name"): changed["19"],
                ("8", "scheduler"): changed["20"],
                ("1", "unet_name"): changed["checkpoint"],
                ("775", "positive"): changed["12"],
                ("775", "negative"): changed["13"],
                ("775", "seed_value"): changed["14"],
                ("775", "steps"): changed["15"],
                ("775", "cfg"): changed["16"],
                ("775", "width"): changed["17"],
                ("775", "height"): changed["18"],
                ("775", "sampler_name"): changed["19"],
                ("775", "scheduler_name"): changed["20"],
                ("775", "modelname"): changed["checkpoint"],
            }
            for (node_id, input_name), value in expected.items():
                self.assertEqual(_resolve_input(graph, node_id, input_name), value)

        assert_saved_values(api)
        converted = moss_workflows.convert_api_to_editable(api, installed_info())
        decoded = _api_from_editable(converted)
        self.assertEqual(decoded, _without_metadata(api))
        validate_enum_edges(decoded, installed_info())
        assert_saved_values(decoded)
        self.assertEqual(moss_workflows.load_api()["14"]["inputs"]["value"], 0)

    def test_layout_json_preserves_global_region_coordinates_and_exact_text(self):
        positive_global = 'global "café" prompt'
        positive_region = 'regional character: "quoted" 雪'
        text_in_image = 'sign says "exact phrase" 東京'
        negative_global = "negative global — keep exact spacing"
        negative_region = 'no "blur" or artifacts 雪'

        positive = json.loads(moss_features.compile_layout(
            positive_global,
            [
                {"label": "character", "caption": positive_region,
                 "bbox": [100, 100, 900, 900]},
                {"label": "text", "caption": "sign", "text": text_in_image,
                 "bbox": [200, 200, 800, 800]},
            ],
            1024,
            1024,
        ))
        negative = json.loads(moss_features.compile_layout(
            negative_global,
            [{"label": "object", "caption": negative_region,
              "bbox": [100, 100, 900, 900]}],
            1024,
            1024,
        ))
        self.assertEqual(positive["summary"]["caption"], positive_global)
        self.assertEqual(positive["items"][0]["caption"], positive_region)
        self.assertEqual(positive["items"][0]["bbox"], [-410, -410, 410, 410])
        self.assertEqual(positive["items"][1]["text"], text_in_image)
        self.assertEqual(positive["items"][1]["bbox"], [-308, -308, 308, 308])
        self.assertEqual(negative["summary"]["caption"], negative_global)
        self.assertEqual(negative["items"][0]["caption"], negative_region)
        self.assertEqual(negative["items"][0]["bbox"], [-410, -410, 410, 410])


if __name__ == "__main__":
    unittest.main()
