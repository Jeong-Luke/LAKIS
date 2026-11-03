"""Serialize a saved LAKIS v8 native graph to its matching API prompt.

Defaults target the packaged v8 assets, never the user's v7.4 workflow. Numeric
links, converted widgets and named widget snapshots are preserved. Legacy v7.4
widget synchronization is available only through --legacy and explicit paths.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path


_SCRIPT_ROOT = Path(__file__).resolve().parent
_PACKAGE_ROOT = _SCRIPT_ROOT.parent
ROOT = _PACKAGE_ROOT.parent if _PACKAGE_ROOT.name == "src" else _SCRIPT_ROOT
WORKFLOW_ROOT = ROOT / "workflows" if _PACKAGE_ROOT.name == "src" else ROOT / "external_ui/workflows"
UI_WORKFLOW = WORKFLOW_ROOT / "LAKIS_custom_v8.0_editable.json"
API_WORKFLOW = WORKFLOW_ROOT / "LAKIS_runtime_api_v8.0.json"
WIDGET_INPUTS = {
    "1925": ("style_prompt", "profile_index", "profile_count", "lora_name", "loras", "profile_data"),
    "2133": ("use_naia", "consume_naia_on_queue", "use_anima_mod_guidance", "resolution_bucket",
             "resolution_size", "resolution_custom_width", "resolution_custom_height",
             "pin_trigger_tags_to_front", "advanced_fields", "use_negative_anima_mod_guidance",
             "wildcard_mode", "wildcard_seed", "wildcard_seed_after_generate"),
    "2135": ("pos_x", "pos_y", "pos_z", "roll", "config", "frame_y"),
}
def synchronize(ui, api, *, legacy=False):
    result = deepcopy(api)
    nodes = {str(node["id"]): node for node in ui["nodes"]}
    links = {str(link[0]): link for link in ui.get("links", [])}
    if legacy:
        for key, names in WIDGET_INPUTS.items():
            node = nodes[key]
            if node["type"] != result[key]["class_type"]:
                raise ValueError(f"Node class mismatch for {key}")
            values = node.get("widgets_values", [])
            if len(values) < len(names):
                raise ValueError(f"Not enough widget values for {key}")
            result[key]["inputs"].update(zip(names, values))
        return result
    expected = set(result)
    actual = {key for key, node in nodes.items() if node["type"] != "PreviewMonitor"}
    if actual != expected:
        raise ValueError(f"Native graph nodes changed: missing={sorted(expected-actual)}, new={sorted(actual-expected)}")
    for key, node in nodes.items():
        if node["type"] == "PreviewMonitor":
            continue
        target = result[key]
        if node["type"] != target["class_type"]:
            raise ValueError(f"Node class mismatch for {key}")
        properties = node.get("properties", {})
        names = properties.get("lakis_widget_names", [])
        values = node.get("widgets_values", [])
        if len(values) != len(names) and not properties.get("lakis_widget_values"):
            raise ValueError(f"Ambiguous widget serialization for {key}; save with the LAKIS extension")
        widgets = properties.get("lakis_widget_values", dict(zip(names, values)))
        for name, value in widgets.items():
            if name in target["inputs"]:
                target["inputs"][name] = value
        for entry in node.get("inputs", []):
            name = entry["name"]
            if entry.get("link") is None:
                if isinstance(target["inputs"].get(name), list):
                    raise ValueError(f"Required native link was disconnected: {key}.{name}")
                continue
            link = links[str(entry["link"])]
            if str(link[3]) != key:
                raise ValueError(f"Wrong native link target: {link[0]}")
            if name not in target["inputs"]:
                raise ValueError(f"Unknown native input: {key}.{name}")
            target["inputs"][name] = [str(link[1]), link[2]]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", type=Path, default=UI_WORKFLOW)
    parser.add_argument("--api", type=Path, default=API_WORKFLOW)
    parser.add_argument("--legacy", action="store_true")
    args = parser.parse_args()
    if args.legacy and (args.ui == UI_WORKFLOW or args.api == API_WORKFLOW):
        parser.error("--legacy requires explicit --ui and --api paths")
    result = synchronize(json.loads(args.ui.read_text(encoding="utf-8")),
                         json.loads(args.api.read_text(encoding="utf-8")), legacy=args.legacy)
    temporary = args.api.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.api)
    print(f"Synchronized {len(result)} native nodes")


if __name__ == "__main__":
    main()
