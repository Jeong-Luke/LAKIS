"""Synchronize LAKIS UI-node settings into the packaged API prompt."""

from __future__ import annotations

import json
from pathlib import Path


COMFY_ROOT = Path(__file__).resolve().parents[1]
UI_WORKFLOW = COMFY_ROOT / "user" / "default" / "workflows" / "LAKIS_custom_v7.1.json"
API_WORKFLOW = COMFY_ROOT / "LAKIS" / "workflows" / "LAKIS_runtime_api_v7.1.json"

WIDGET_INPUTS = {
    "1925": (
        "style_prompt", "profile_index", "profile_count", "lora_name", "loras", "profile_data",
    ),
    "2133": (
        "use_naia", "consume_naia_on_queue", "use_anima_mod_guidance", "resolution_bucket",
        "resolution_size", "resolution_custom_width", "resolution_custom_height",
        "pin_trigger_tags_to_front", "advanced_fields", "use_negative_anima_mod_guidance",
        "wildcard_mode", "wildcard_seed", "wildcard_seed_after_generate",
    ),
    "2135": ("pos_x", "pos_y", "pos_z", "roll", "config", "frame_y"),
}


def main() -> None:
    ui = json.loads(UI_WORKFLOW.read_text(encoding="utf-8"))
    api = json.loads(API_WORKFLOW.read_text(encoding="utf-8"))
    ui_nodes = {str(node.get("id")): node for node in ui.get("nodes", [])}

    for node_id, input_names in WIDGET_INPUTS.items():
        if node_id not in ui_nodes or node_id not in api:
            raise RuntimeError(f"Missing synchronized LAKIS node: {node_id}")
        ui_node = ui_nodes[node_id]
        api_node = api[node_id]
        if ui_node.get("type") != api_node.get("class_type"):
            raise RuntimeError(f"Node class mismatch for {node_id}")
        values = ui_node.get("widgets_values", [])
        if len(values) < len(input_names):
            raise RuntimeError(f"Not enough widget values for {node_id}")
        api_node["inputs"].update(dict(zip(input_names, values)))

    temporary = API_WORKFLOW.with_suffix(".tmp")
    temporary.write_text(json.dumps(api, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(API_WORKFLOW)
    print(f"Synchronized nodes: {', '.join(WIDGET_INPUTS)}")


if __name__ == "__main__":
    main()
