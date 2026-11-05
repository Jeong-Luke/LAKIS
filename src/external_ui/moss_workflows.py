"""Load and convert the canonical integrated MOSS ComfyUI workflows."""

from copy import deepcopy
import json
from pathlib import Path
import sys


_MODULE_FILE = Path(__file__).resolve()
sys.path.insert(0, str(_MODULE_FILE.parents[1] / "runtime"))
sys.path.insert(0, str(_MODULE_FILE.parent / "runtime"))
from native_workflow import serialize_native


API_NAME = "LAKIS_MOSS_runtime_api_v8.1.json"
EDITABLE_NAME = "LAKIS_MOSS_custom_v8.1_editable.json"

_TITLES = {
    "1": "MOSS · Diffusion loader",
    "2": "MOSS · Sampling Shift",
    "3": "MOSS · Layer guidance",
    "4": "MOSS · Text encoder loader",
    "5": "MOSS · Positive prompt JSON",
    "6": "MOSS · Negative prompt JSON",
    "7": "MOSS · Resolution",
    "8": "MOSS · Sampler",
    "9": "MOSS · Decode",
    "10": "MOSS · VAE loader",
    "775": "LAKIS Final Saver · MOSS",
    "12": "MOSS · Positive prompt JSON",
    "13": "MOSS · Negative prompt JSON",
    "14": "MOSS · Seed",
    "15": "MOSS · Steps",
    "16": "MOSS · CFG",
    "17": "MOSS · Width",
    "18": "MOSS · Height",
    "19": "MOSS · Sampler",
    "20": "MOSS · Scheduler",
}

_SIZES = {
    "1": [420, 210],
    "2": [320, 150],
    "3": [420, 250],
    "4": [420, 190],
    "5": [720, 390],
    "6": [720, 390],
    "7": [420, 160],
    "8": [480, 490],
    "9": [320, 160],
    "10": [420, 140],
    "775": [560, 740],
    "12": [720, 390],
    "13": [720, 390],
    "14": [230, 130],
    "15": [230, 130],
    "16": [230, 130],
    "17": [230, 130],
    "18": [230, 130],
    "19": [250, 130],
    "20": [250, 130],
}

_POSITIONS = {
    "4": [40, 340],
    "5": [500, 340],
    "6": [500, 790],
    "7": [40, 790],
    "8": [1320, 340],
    "9": [1830, 340],
    "10": [40, 590],
    "775": [2200, 340],
    "12": [40, 1230],
    "13": [800, 1230],
    "14": [40, 1660],
    "15": [300, 1660],
    "16": [560, 1660],
    "17": [820, 1660],
    "18": [1080, 1660],
    "19": [1340, 1660],
    "20": [1620, 1660],
}


def workflow_path(editable=False):
    """Return the packaged resource path or the repository's canonical path."""
    module_file = Path(__file__).resolve()
    if module_file.parents[1].name == "src":
        resource_dir = module_file.parents[2] / "workflows"
    else:
        resource_dir = module_file.parent / "workflows"
    return resource_dir / (EDITABLE_NAME if editable else API_NAME)


def _load(editable=False):
    path = workflow_path(editable=editable)
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"MOSS workflow resource must contain a JSON object: {path}")
    return value


def load_api():
    """Read the canonical API prompt graph; missing resources are not rebuilt."""
    return _load()


def load_editable():
    """Read the canonical ComfyUI-native editable workflow."""
    return _load(editable=True)


def _input_slot(graph, node_id, name):
    inputs = graph[node_id]["inputs"]
    value = inputs[name]
    if isinstance(value, list) and len(value) == 2:
        source = graph.get(str(value[0]), {})
        field = {
            "PrimitiveStringMultiline": ("value", (0,)),
            "PrimitiveInt": ("value", (0,)),
            "PrimitiveFloat": ("value", (0,)),
            "Sampler Selector (Image Saver)": ("sampler_name", (0, 1)),
            "Scheduler Selector (Image Saver)": ("scheduler", (0, 1)),
            "UNet loader with Name (Image Saver)": ("unet_name", (1,)),
        }.get(source.get("class_type"))
        if field and value[1] in field[1]:
            return source["inputs"], field[0]
    return inputs, name


def get_input(graph, node_id, name):
    inputs, key = _input_slot(graph, node_id, name)
    return inputs[key]


def set_input(graph, node_id, name, value):
    """Update a shared scalar control without breaking its generation/Saver links."""
    inputs, key = _input_slot(graph, node_id, name)
    inputs[key] = value


def convert_api_to_editable(api=None, info=None):
    """Serialize an API graph using installed ComfyUI object-info schemas.

    ``info`` is the installed ``/object_info`` mapping used by the runtime.
    The serializer's stock arranger is LAKIS-graph-specific, so temporary
    source IDs keep its schema-aware widget/link serializer usable here; the
    resulting workflow is then given MOSS-specific positions and source IDs.
    """
    if info is None:
        raise ValueError("Installed ComfyUI object-info is required for native workflow conversion.")
    prompt = deepcopy(load_api() if api is None else api)
    if not isinstance(prompt, dict):
        raise ValueError("MOSS API workflow must be a node mapping.")
    if any(not str(key).isdecimal() for key in prompt):
        raise ValueError("MOSS native workflow conversion requires numeric ComfyUI node IDs.")
    if "3999" in prompt or 3999 in prompt:
        raise ValueError("ComfyUI node ID 3999 is reserved for the native preview monitor.")

    for key, node in prompt.items():
        metadata = node.setdefault("_meta", {})
        metadata.setdefault("title", _TITLES.get(str(key), node["class_type"]))
        metadata["lakis_source_id"] = f"890:moss:{key}"

    workflow = serialize_native(prompt, info)
    lora_ids = sorted(
        (str(key) for key, node in prompt.items()
         if node["class_type"] == "LoraLoaderModelOnly"),
        key=int,
    )
    lora_count = len(lora_ids)
    positions = {
        **_POSITIONS,
        "1": [40, 80],
        "2": [500 + 360 * lora_count, 80],
        "3": [900 + 360 * lora_count, 80],
    }
    for index, key in enumerate(lora_ids):
        positions[key] = [500 + 360 * index, 80]

    for node in workflow["nodes"]:
        if node["type"] == "PreviewMonitor":
            node.update(pos=[2860, 80], size=[660, 760], flags={})
            continue
        key = str(node["id"])
        node["properties"]["lakis_source_id"] = key
        node["pos"] = positions.get(key, [40, 1030 + 210 * int(key)])
        node["size"] = _SIZES.get(key, [340, 200])
        node["flags"] = {}

    workflow["groups"] = []
    workflow["extra"]["lakis_native_version"] = "8.1"
    workflow["extra"]["lakis_terminal_image"] = 775
    return workflow
