"""Export the production LAKIS DETAIL API workflow from the runtime builder.

This keeps the inspectable workflow artifact on the exact same code path as
the external UI instead of maintaining a second, hand-edited prompt graph.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch


RELEASE_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_PATH = RELEASE_ROOT / "src" / "external_ui" / "workflow_bridge.py"
TEMPLATE_PATH = RELEASE_ROOT / "workflows" / "LAKIS_runtime_api_v7.1.json"
OUTPUT_PATH = RELEASE_ROOT / "workflows" / "LAKIS_DETAIL_runtime_api_v7.3.json"


def _load_bridge():
    spec = importlib.util.spec_from_file_location("lakis_workflow_export_bridge", BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load workflow bridge: {BRIDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configuration(template: dict) -> dict:
    return {
        "checkpoint": {
            "current": template["890:1365"]["inputs"]["model_name"],
            "options": [template["890:1365"]["inputs"]["model_name"]],
        },
        "vae": {
            "current": template["890:159"]["inputs"]["vae_name"],
            "options": [template["890:159"]["inputs"]["vae_name"]],
        },
        "clip": {
            "current": template["890:164"]["inputs"]["clip_name"],
            "options": [template["890:164"]["inputs"]["clip_name"]],
        },
        "sampler": {
            "current": template["890:905"]["inputs"]["sampler_name"],
            "options": [template["890:905"]["inputs"]["sampler_name"]],
        },
        "scheduler": {
            "current": template["890:905"]["inputs"]["scheduler"],
            "options": [template["890:905"]["inputs"]["scheduler"]],
        },
        "lora": {"current": [], "profile_index": 0},
    }


def main() -> None:
    bridge = _load_bridge()
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    config = _configuration(template)
    state = {
        "generation": {
            "mode": "detail",
            "lakis_mode": True,
            "upscale_engine": "lakis_scope",
        },
        "model": {
            "checkpoint": config["checkpoint"]["current"],
            "vae": config["vae"]["current"],
            "clip": config["clip"]["current"],
            "sampler": config["sampler"]["current"],
            "scheduler": config["scheduler"]["current"],
            "steps": int(template["890:905"]["inputs"]["steps_total"]),
            "cfg": float(template["890:905"]["inputs"]["cfg"]),
        },
        "output": {
            "width": 1056,
            "height": 1472,
            "seed": 0,
            "seed_mode": "fixed",
            "aspect_locked": False,
        },
        "prompt": {key: "" for key in bridge.PROMPT_STATE_KEYS},
        "loras": [],
        "lora_enabled": False,
        "composition_enabled": False,
        "camera": {},
        "i2i": {"enabled": False, "denoise": 0.5},
        "node_overrides": {},
    }
    with (
        patch.object(bridge, "TEMPLATE", TEMPLATE_PATH),
        patch.object(bridge, "workflow_configuration", return_value=config),
        patch.object(bridge, "_is_anima_checkpoint", return_value=True),
        patch.object(bridge, "_camera_prompt", return_value=""),
        patch.object(bridge, "DEVELOPMENT", False),
    ):
        graph, assertions = bridge.build_prompt(state)

    required = {"lakis:vram:base_to_face", "lakis:face_scope", "1541:1538", bridge.FINAL_NODE}
    missing = sorted(required - set(graph))
    if missing:
        raise RuntimeError(f"LAKIS DETAIL export is incomplete: {missing}")
    if graph["lakis:face_scope"]["class_type"] != "LAKIS_DETAIL":
        raise RuntimeError("LAKIS_DETAIL node contract was not exported")
    if graph["1541:1538"]["class_type"] != "LAKIS_SCOPE":
        raise RuntimeError("LAKIS_SCOPE node contract was not exported")

    OUTPUT_PATH.write_text(
        json.dumps(graph, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(OUTPUT_PATH),
        "node_count": len(graph),
        "resolution": assertions["resolution"],
        "detail": graph["lakis:face_scope"]["class_type"],
        "upscale": graph["1541:1538"]["class_type"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
