"""Narrow LAKIS external-UI bridge for the validated FAST/DETAIL workflow.

The saved Standard workflow and custom-node sources are never modified.  Every
request starts from the validated v7.1 runtime prompt and applies only an
in-memory application-state mapping before submitting Final Saver 775.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import threading
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

import aiohttp


COMFY_SERVER = "http://127.0.0.1:8189"
FINAL_NODE = "775"
DEV_ROOT = Path(__file__).resolve().parent.parent
COMFY_ROOT = DEV_ROOT.parent
OUTPUT_ROOT = COMFY_ROOT / "output"
STOP_FILE = DEV_ROOT / "STOP_AUTOMATION"
ALLOW_FILE = DEV_ROOT / "ALLOW_ONE_GENERATION"
TEMPLATE = COMFY_ROOT / "LAKIS" / "workflows" / "LAKIS_runtime_api_v7.1.json"
SAVED_WORKFLOW = COMFY_ROOT / "user" / "default" / "workflows" / "LAKIS_custom_v7.1.json"
AUDIT_PATH = DEV_ROOT / "external_ui_bridge_audit.jsonl"
UI_STATE_PATH = DEV_ROOT / "external_ui_user_state.json"
CAMERA_SOURCE = COMFY_ROOT / "custom_nodes" / "ComfyUI-KR-Camera-Control" / "camera_control.py"
MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
COMFYUI_SEED_MAX = 1125899906842624
PROMPT_STATE_KEYS = {
    "general", "quality", "artist", "trigger", "fixed", "negative",
    "negative_quality", "negative_artist", "negative_fixed",
}
MODEL_STATE_KEYS = {"checkpoint", "vae", "clip", "sampler", "scheduler", "steps", "cfg"}
OUTPUT_STATE_KEYS = {"width", "height", "seed", "seed_mode"}
DEFAULT_CHECKPOINT = "anima_baseV10.safetensors"
FIRST_RUN_PROMPT = {
    "general": (
        "natsume iroha, iroha (swimsuit) (blue archive), 1girl, solo, halo, long dark red hair, blue eyes, "
        "red frilled bikini, bracelet, sandals, lying on side, reclining on beach, head resting on one arm, "
        "one hand touching hair, one knee raised, other leg extended, looking at viewer, relaxed expression, "
        "full body, diagonal composition, close perspective, tropical beach, ocean waves, wet sand, "
        "golden sunset sky, palm leaves framing the scene, warm backlight, soft shadows, summer atmosphere"
    ),
    "quality": (
        "masterpiece, best quality, very aesthetic, absurdres, detailed eyes, detailed hair, "
        "anime illustration, cinematic lighting, warm color palette"
    ),
    "artist": "artist:doremi (doremi4704), year 2021, artist:masha, year 2024",
    "trigger": "",
    "fixed": "",
    "negative": (
        "lowres, blurry, bad anatomy, bad hands, extra fingers, missing fingers, fused fingers, extra limbs, "
        "missing limbs, malformed legs, duplicate, multiple girls, cropped feet, out of frame, text, watermark, signature"
    ),
    "negative_quality": "worst quality, low quality, normal quality, jpeg artifacts",
    "negative_artist": "",
    "negative_fixed": "",
}


def load_external_prompt_state() -> dict[str, str]:
    if not UI_STATE_PATH.is_file():
        return {}
    try:
        payload = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    prompt = payload.get("prompt", {}) if isinstance(payload, dict) else {}
    if not isinstance(prompt, dict):
        return {}
    return {
        key: str(prompt.get(key, ""))
        for key in PROMPT_STATE_KEYS
        if key in prompt
    }


def save_external_prompt_state(prompt: Any) -> dict[str, str]:
    if not isinstance(prompt, dict):
        raise ValueError("prompt state must be an object")
    clean = {key: str(prompt.get(key, ""))[:100_000] for key in PROMPT_STATE_KEYS}
    payload = _load_external_ui_payload()
    payload.update({"version": 2, "prompt": clean, "updated_at": time.time()})
    _write_external_ui_payload(payload)
    return clean


def _load_external_ui_payload() -> dict[str, Any]:
    if not UI_STATE_PATH.is_file():
        return {}
    try:
        payload = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_external_ui_payload(payload: dict[str, Any]) -> None:
    temporary = UI_STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, UI_STATE_PATH)


def load_external_generation_state() -> dict[str, Any]:
    payload = _load_external_ui_payload()
    model = payload.get("model", {})
    output = payload.get("output", {})
    return {
        "model": {key: model[key] for key in MODEL_STATE_KEYS if isinstance(model, dict) and key in model},
        "output": {key: output[key] for key in OUTPUT_STATE_KEYS if isinstance(output, dict) and key in output},
    }


def save_external_generation_state(model: Any, output: Any) -> dict[str, Any]:
    if not isinstance(model, dict) or not isinstance(output, dict):
        raise ValueError("model and output state must be objects")
    clean_model = {key: model[key] for key in MODEL_STATE_KEYS if key in model}
    clean_output = {key: output[key] for key in OUTPUT_STATE_KEYS if key in output}
    payload = _load_external_ui_payload()
    payload.update({
        "version": 2,
        "model": clean_model,
        "output": clean_output,
        "updated_at": time.time(),
    })
    _write_external_ui_payload(payload)
    return {"model": clean_model, "output": clean_output}


def _model_files(folder: str) -> list[str]:
    root = COMFY_ROOT / "models" / folder
    return sorted(
        str(path.relative_to(root)).replace("/", "\\")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS
    )


def workflow_configuration() -> dict[str, Any]:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    prompt_defaults = dict(FIRST_RUN_PROMPT)
    prompt_defaults.update(load_external_prompt_state())
    checkpoint_options = _model_files("diffusion_models")
    saved = load_external_generation_state()
    saved_model = saved["model"]
    saved_output = saved["output"]
    checkpoint_default = DEFAULT_CHECKPOINT if DEFAULT_CHECKPOINT in checkpoint_options else template["890:1365"]["inputs"]["model_name"]
    checkpoint = saved_model.get("checkpoint", checkpoint_default)
    if checkpoint not in checkpoint_options:
        checkpoint = checkpoint_default
    vae_options = _model_files("vae")
    vae_default = template["890:159"]["inputs"]["vae_name"]
    vae = saved_model.get("vae", vae_default)
    if vae not in vae_options:
        vae = vae_default
    clip_options = _model_files("text_encoders")
    clip_default = template["890:164"]["inputs"]["clip_name"]
    clip = saved_model.get("clip", clip_default)
    if clip not in clip_options:
        clip = clip_default
    return {
        "checkpoint": {
            "current": checkpoint,
            "options": checkpoint_options,
            "loader_class": template["890:1365"]["class_type"],
        },
        "vae": {
            "current": vae,
            "options": vae_options,
            "loader_class": template["890:159"]["class_type"],
        },
        "clip": {
            "current": clip,
            "options": clip_options,
            "loader_class": template["890:164"]["class_type"],
        },
        "lora": _saved_lora_configuration(),
        "prompt": prompt_defaults,
        "generation_state": {
            "model": {
                "sampler": str(saved_model.get("sampler", "euler_ancestral")),
                "scheduler": str(saved_model.get("scheduler", "normal")),
                "steps": int(saved_model.get("steps", 30)),
                "cfg": float(saved_model.get("cfg", 5.0)),
            },
            "output": {
                "width": int(saved_output.get("width", 1536)),
                "height": int(saved_output.get("height", 1024)),
                "seed": int(saved_output.get("seed", 579441119814924)),
                "seed_mode": str(saved_output.get("seed_mode", "random")),
            },
        },
    }


def _saved_lora_configuration() -> dict[str, Any]:
    workflow = json.loads(SAVED_WORKFLOW.read_text(encoding="utf-8"))
    preset = next(node for node in workflow.get("nodes", []) if str(node.get("id")) == "1925")
    widgets = preset["widgets_values"]
    profile_index = int(widgets[1])
    available = _model_files("loras")
    available_by_key = {name.replace("/", "\\").casefold(): name for name in available}
    configured: list[dict[str, Any]] = []
    try:
        profiles = json.loads(widgets[5]) if len(widgets) > 5 else {}
        profile = profiles.get(str(profile_index), {}) if isinstance(profiles, dict) else {}
        rows = profile.get("loras", []) if isinstance(profile, dict) else []
        snapshot = profile.get("saved_snapshot") if isinstance(profile, dict) else None
        if snapshot:
            decoded = json.loads(snapshot)
            if isinstance(decoded, dict) and isinstance(decoded.get("loras"), list):
                rows = decoded["loras"]
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            installed_name = available_by_key.get(str(row.get("name") or "").replace("/", "\\").casefold())
            if not installed_name:
                continue
            configured.append({
                "name": installed_name,
                "enabled": bool(row.get("on", row.get("enabled", True))),
                "strength": float(row.get("strength", 1)),
            })
    except (TypeError, ValueError, json.JSONDecodeError):
        configured = []
    return {
        # Restore the selected workflow profile, but only for LoRAs that are
        # actually installed. A clean first launch therefore remains empty.
        "current": configured,
        "options": available,
        "enabled": True,
        "profile_index": profile_index,
        "node_class": preset.get("type"),
    }


def _saved_prompt_defaults() -> dict[str, str]:
    workflow = json.loads(SAVED_WORKFLOW.read_text(encoding="utf-8"))
    studio = next(node for node in workflow.get("nodes", []) if str(node.get("id")) == "2133")
    fields = json.loads(studio["widgets_values"][8])
    buckets: dict[str, list[str]] = {
        "general": [], "quality": [], "artist": [], "trigger": [], "fixed": [],
        "negative": [], "negative_quality": [], "negative_artist": [], "negative_fixed": [],
    }
    for item in fields:
        if not item.get("enabled", True) or item.get("id") == "positive_general_kr_camera_bridge":
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        pane = item.get("pane", "positive")
        field_type = item.get("type", "general")
        key = field_type if pane == "positive" else (
            "negative" if field_type == "general" else f"negative_{field_type}"
        )
        if key in buckets:
            buckets[key].append(text)
    return {key: "\n\n".join(values) for key, values in buckets.items()}


def _audit(event: str, **details: Any) -> None:
    record = {"timestamp": time.time(), "event": event, **details}
    with AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def _dependencies(prompt: dict[str, Any], node_id: str) -> set[str]:
    found: set[str] = set()
    for value in prompt[node_id].get("inputs", {}).values():
        if isinstance(value, list) and len(value) == 2 and str(value[0]) in prompt:
            found.add(str(value[0]))
    return found


def _final_only(prompt: dict[str, Any]) -> dict[str, Any]:
    # Disabled cleanup has lazy inputs which must not keep its debug subsystem
    # alive in the API graph.
    router = prompt.get("2165", {}).get("inputs", {})
    if router.get("cleanup_enabled") is False:
        for key in ("cleanup_image", "old_shadow_mask", "semantic_shadow_preview"):
            router.pop(key, None)
    keep: set[str] = set()
    pending = [FINAL_NODE]
    while pending:
        node_id = pending.pop()
        if node_id in keep:
            continue
        if node_id not in prompt:
            raise RuntimeError(f"Missing dependency {node_id}")
        keep.add(node_id)
        pending.extend(_dependencies(prompt, node_id) - keep)
    return {node_id: prompt[node_id] for node_id in prompt if node_id in keep}


def _inject_prompts(prompt: dict[str, Any], prompt_state: dict[str, Any]) -> None:
    studio = prompt["2133"]["inputs"]
    fields = json.loads(studio["advanced_fields"])
    external_ids = {
        "positive_general_lakis_external", "positive_general_lakis_external_base",
        "positive_general_lakis_external_fixed", "positive_quality_lakis_external",
        "positive_artist_lakis_external", "positive_trigger_lakis_external",
        "negative_general_lakis_external", "negative_general_lakis_external_fixed",
        "negative_quality_lakis_external", "negative_artist_lakis_external",
    }
    fields = [
        item for item in fields
        if item.get("id") == "positive_general_kr_camera_bridge" or item.get("type") == "naia"
    ]
    specs = (
        ("positive_trigger_lakis_external", "positive", "trigger", "LAKIS Trigger Words", "trigger", True, 72),
        ("positive_artist_lakis_external", "positive", "artist", "LAKIS Artist Tags", "artist", False, 72),
        ("positive_quality_lakis_external", "positive", "quality", "LAKIS Quality Tags", "quality", False, 72),
        ("positive_general_lakis_external_fixed", "positive", "fixed", "LAKIS Fixed Prompt", "fixed", False, 72),
        ("positive_general_lakis_external", "positive", "general", "LAKIS General Tags", "general", False, 88),
        ("negative_artist_lakis_external", "negative", "artist", "LAKIS Negative Artist Tags", "negative_artist", False, 72),
        ("negative_quality_lakis_external", "negative", "quality", "LAKIS Negative Quality Tags", "negative_quality", False, 72),
        ("negative_general_lakis_external_fixed", "negative", "fixed", "LAKIS Fixed Negative", "negative_fixed", False, 72),
        ("negative_general_lakis_external", "negative", "general", "LAKIS Negative Prompt", "negative", False, 80),
    )
    for field_id, pane, field_type, label, state_key, pin, height in specs:
        value = str(prompt_state.get(state_key, "")).strip()
        fields.append({
            "id": field_id, "pane": pane, "type": field_type, "label": label,
            "text": value, "height": height, "heightMode": "manual",
            "enabled": bool(value), "pin": pin,
        })
    studio["advanced_fields"] = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


def _inject_loras(prompt: dict[str, Any], requested: Any, globally_enabled: bool = True) -> dict[str, Any]:
    if not isinstance(requested, list):
        raise ValueError("loras must be a list")
    if len(requested) > 64:
        raise ValueError("At most 64 LoRAs may be configured")

    available = _model_files("loras")
    canonical = {name.replace("/", "\\").lower(): name for name in available}
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(requested):
        if not isinstance(item, dict):
            raise ValueError(f"LoRA row {index + 1} must be an object")
        raw_name = str(item.get("name", "")).strip().replace("/", "\\")
        # An empty UI slot is only a chooser placeholder and is not part of the
        # runtime LoRA stack until the user explicitly selects a file.
        if not raw_name:
            continue
        name = canonical.get(raw_name.lower())
        if name is None:
            raise ValueError(f"Unknown LoRA: {raw_name}")
        strength = float(item.get("strength", 1.0))
        if not math.isfinite(strength) or not -20.0 <= strength <= 20.0:
            raise ValueError(f"LoRA strength must be between -20 and 20: {name}")
        rows.append({
            "name": name,
            "on": globally_enabled and bool(item.get("enabled", True)),
            "strength": strength,
            "strengthTwo": None,
        })

    inputs = prompt["1925"]["inputs"]
    profile_index = str(int(inputs.get("profile_index", 1)))
    profile_data = json.loads(inputs["profile_data"])
    profile = profile_data.setdefault(profile_index, {})
    profile["loras"] = deepcopy(rows)
    inputs["loras"] = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    inputs["profile_data"] = json.dumps(profile_data, ensure_ascii=False, separators=(",", ":"))
    return {
        "lora_count": len(rows),
        "enabled_lora_count": sum(1 for row in rows if row["on"]),
        "loras_globally_enabled": globally_enabled,
        "lora_profile_index": int(profile_index),
    }


def _camera_prompt(camera_inputs: dict[str, Any]) -> str:
    spec = importlib.util.spec_from_file_location("lakis_kr_camera_runtime", CAMERA_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load KR Camera Control: {CAMERA_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.KRCameraControl().generate(
        camera_inputs["pos_x"], camera_inputs["pos_y"], camera_inputs["pos_z"],
        camera_inputs["roll"], camera_inputs["config"], camera_inputs["frame_y"],
    )[0]


def _replace_camera_field(prompt: dict[str, Any], text: str) -> None:
    studio = prompt["2133"]["inputs"]
    fields = json.loads(studio["advanced_fields"])
    matched = False
    for item in fields:
        if item.get("id") == "positive_general_kr_camera_bridge":
            item.update({"text": text, "enabled": bool(text)})
            matched = True
            break
    if not matched:
        raise RuntimeError("Prompt Studio camera bridge field is missing")
    studio["advanced_fields"] = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


def build_prompt(application_state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not TEMPLATE.is_file():
        raise RuntimeError(f"Validated API prompt template is missing: {TEMPLATE}")
    prompt = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    required = {FINAL_NODE, "1925", "890:1281", "2133", "2135", "2138", "2139", "2140",
                "1736:1987",
                "1634:1721", "1634:1622", "1633:1616", "1633:1790", "1633:1612",
                "1633:1619", "2165"}
    missing = sorted(required - set(prompt))
    if missing:
        raise RuntimeError(f"Validated prompt contract changed; missing {missing}")

    generation = application_state.get("generation", {})
    output = application_state.get("output", {})
    camera = application_state.get("camera", {})
    prompt_state = application_state.get("prompt", {})
    lora_state = application_state.get("loras", workflow_configuration()["lora"]["current"])
    model = application_state.get("model", {})
    mode = generation.get("mode", "fast")
    if mode not in {"fast", "detail"}:
        raise ValueError("generation.mode must be fast or detail")

    detail = mode == "detail"
    for node_id in ("2138", "2139", "2140"):
        prompt[node_id]["inputs"]["value"] = detail

    seed = int(output.get("seed", 0))
    if not 0 <= seed <= COMFYUI_SEED_MAX:
        raise ValueError(f"Seed must be between 0 and {COMFYUI_SEED_MAX}")
    width = max(256, min(4096, int(output.get("width", 1024))))
    height = max(256, min(4096, int(output.get("height", 1536))))
    prompt["890:1864"]["inputs"]["seed"] = seed
    checkpoint = str(model.get("checkpoint", prompt["890:1365"]["inputs"]["model_name"]))
    vae = str(model.get("vae", prompt["890:159"]["inputs"]["vae_name"]))
    clip = str(model.get("clip", prompt["890:164"]["inputs"]["clip_name"]))
    available = workflow_configuration()
    if checkpoint not in available["checkpoint"]["options"]:
        raise ValueError(f"Unknown diffusion model: {checkpoint}")
    if "anima" not in checkpoint.lower():
        raise ValueError("FAST workflow requires an Anima-compatible diffusion model")
    if vae not in available["vae"]["options"]:
        raise ValueError(f"Unknown VAE: {vae}")
    if clip not in available["clip"]["options"]:
        raise ValueError(f"Unknown CLIP: {clip}")
    prompt["890:1365"]["inputs"]["model_name"] = checkpoint
    prompt["890:159"]["inputs"]["vae_name"] = vae
    prompt["890:164"]["inputs"]["clip_name"] = clip
    sampler_config = prompt["890:905"]["inputs"]
    sampler_config.update({
        "steps_total": int(model.get("steps", sampler_config["steps_total"])),
        "cfg": float(model.get("cfg", sampler_config["cfg"])),
        "sampler_name": str(model.get("sampler", sampler_config["sampler_name"])),
        "scheduler": str(model.get("scheduler", sampler_config["scheduler"])),
    })
    studio = prompt["2133"]["inputs"]
    # The external UI always supplies an explicit width/height pair.  Leaving
    # this on a named bucket makes Prompt Studio reject non-preset pairs and
    # silently fall back to the first (very tall) entry in that bucket.
    studio["resolution_bucket"] = "Custom"
    studio["resolution_size"] = f"{width} * {height} (custom)"
    studio["resolution_custom_width"] = width
    studio["resolution_custom_height"] = height

    # Also pin the actual txt2img latent dimensions.  This keeps the output
    # contract correct even if a future Prompt Studio release changes its
    # output ordering or custom-resolution parsing.
    initial_latent = prompt["1736:1987"]["inputs"]
    initial_latent["width"] = width
    initial_latent["height"] = height

    camera_inputs = prompt["2135"]["inputs"]
    for source, target in (("x", "pos_x"), ("y", "pos_y"), ("z", "pos_z"),
                           ("roll", "roll"), ("frame_y", "frame_y")):
        camera_inputs[target] = float(camera.get(source, camera_inputs.get(target, 0)))

    composition_enabled = bool(application_state.get("composition_enabled", True))
    camera_prompt = _camera_prompt(camera_inputs) if composition_enabled else ""
    _replace_camera_field(prompt, camera_prompt)

    _inject_prompts(prompt, prompt_state)
    lora_assertions = _inject_loras(
        prompt, lora_state, bool(application_state.get("lora_enabled", True))
    )

    # Accepted S1R2 Initial Spectrum: one patch, Initial only.
    spectrum = prompt["1634:1721"]["inputs"]
    spectrum.update({"enabled": True, "one_sampler_only": True, "verbose": False})
    prompt["1633:1723"]["inputs"].update(
        {"enabled": False, "one_sampler_only": False, "verbose": False}
    )
    prompt["1633:1612"]["inputs"]["model"] = ["1633:1619", 0]

    # The public prototype does not expose the unfinished Light Control yet.
    # Route the Initial latent directly into HighRez so none of the LAKIS
    # light/geometry stages are scheduled by Final-only dependency closure.
    prompt["1633:1616"]["inputs"]["on_false"] = ["1634:1622", 0]
    prompt["1633:1790"]["inputs"]["samples"] = ["1634:1622", 0]

    # Validated S7 Turbo HighRez is shared by FAST and DETAIL.  The user-facing
    # mode controls only Face/Eye/USDU, not the lighting engine or sampler base.
    turbo_id = "lakis_external_turbo_highrez"
    prompt[turbo_id] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {"model": ["1633:1619", 0],
                   "lora_name": "anima-turbo-lora-v0.2.safetensors",
                   "strength_model": 1.0},
        "_meta": {"title": "LAKIS External UI - Turbo HighRez"},
    }
    prompt["1633:1612"]["inputs"].update({
        "model": [turbo_id, 0], "steps": 3, "cfg": 1.0,
        "sampler_name": "gradient_estimation", "scheduler": "simple", "denoise": 0.2,
    })

    prompt = _final_only(prompt)
    light_nodes = {"2158", "2142", "2148", "2143", "2151", "2150"}
    assertions = {
        "final_only": FINAL_NODE in prompt,
        "cleanup_absent": "2154" not in prompt,
        "semantic_shadow_absent": "2161" not in prompt,
        "initial_spectrum": prompt["1634:1721"]["inputs"]["enabled"] is True,
        "highrez_spectrum_absent": "1633:1723" not in prompt,
        "prototype_light_disabled": not (light_nodes & set(prompt)),
        "detail_enabled": detail,
        "node_count": len(prompt),
        "camera_prompt": camera_prompt,
        "composition_enabled": composition_enabled,
        "lora_stack_node": prompt["890:1281"]["inputs"].get("lora_stack") == ["1925", 1],
        **lora_assertions,
    }
    ignored_assertions = {"detail_enabled", "node_count", "lora_count", "enabled_lora_count",
                          "loras_globally_enabled", "lora_profile_index", "composition_enabled",
                          "camera_prompt"}
    if not all(value for key, value in assertions.items() if key not in ignored_assertions):
        raise RuntimeError(f"External UI prompt preflight failed: {assertions}")
    return prompt, assertions


NODE_WEIGHTS = {
    "1634:1622": 25.0, "1635": 1.0, "2158": 2.0, "2142": 1.0,
    "2148": 2.0, "2143": 1.0, "2151": 1.0, "2150": 18.0,
    "1633:1790": 1.0, "1633:1794": 1.0, "1633:1612": 8.0,
    "1633:1611": 1.0, "1530:1826": 15.0, "1836:2069": 12.0,
    "1541:1538": 24.0, FINAL_NODE: 1.0,
}
NODE_LABELS = {
    "1634:1622": "Initial", "1635": "Decode", "2158": "SAM3",
    "2142": "Depth", "2148": "DSINE", "2143": "Relight",
    "2151": "Cast Shadow", "2150": "VAE Encode",
    "1633:1790": "HighRez Decode", "1633:1794": "HighRez Encode",
    "1633:1612": "HighRez", "1633:1611": "HighRez Decode",
    "1530:1826": "Face Detail", "1836:2069": "Eye Detail",
    "1541:1538": "Upscale", FINAL_NODE: "Final Save",
}


@dataclass
class GenerationState:
    state: str = "idle"
    percent: float = 0.0
    stage: str = ""
    prompt_id: str | None = None
    output_url: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    mode: str | None = None
    seed: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancel_requested: bool = False
    prompt_requests: int = 0
    preview_revision: int = 0
    preview_frames: int = 0
    preview_mime: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {key: value for key, value in self.__dict__.items() if key != "lock"}

    def update(self, **values: Any) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)


class WorkflowBridge:
    def __init__(self) -> None:
        self.status = GenerationState()
        self._worker: threading.Thread | None = None
        self._consumed_allowance: Path | None = None
        self._preview_lock = threading.Lock()
        self._preview_bytes: bytes | None = None
        self._preview_mime = "image/jpeg"

    def preview_snapshot(self) -> tuple[bytes | None, str, int]:
        with self._preview_lock:
            return self._preview_bytes, self._preview_mime, self.status.preview_revision

    def _clear_preview(self) -> None:
        with self._preview_lock:
            self._preview_bytes = None
            self.status.preview_revision += 1

    def _set_preview(self, payload: bytes, mime: str) -> None:
        if not payload or len(payload) > 32 * 1024 * 1024:
            return
        with self._preview_lock:
            self._preview_bytes = payload
            self._preview_mime = mime
            self.status.preview_revision += 1
            self.status.preview_frames += 1
            self.status.preview_mime = mime

    def start(self, application_state: dict[str, Any]) -> dict[str, Any]:
        with self.status.lock:
            if self.status.state in {"preparing", "running", "cancelling"}:
                raise RuntimeError("A LAKIS generation is already active")
        if not STOP_FILE.is_file():
            raise RuntimeError("STOP_AUTOMATION safety lock is missing")
        prompt, preflight = build_prompt(application_state)
        self._clear_preview()
        token = {"request_id": uuid.uuid4().hex, "created_at": time.time(), "source": "external_ui_click"}
        with ALLOW_FILE.open("x", encoding="utf-8") as stream:
            json.dump(token, stream)
        self.status.update(state="preparing", percent=0.0, stage="생성 중", prompt_id=None,
                           preview_frames=0, preview_mime=None,
                           output_url=None, error=None, error_code=None, error_detail=None,
                           mode=application_state["generation"]["mode"],
                           seed=int(application_state["output"]["seed"]),
                           started_at=time.time(), finished_at=None, cancel_requested=False,
                           prompt_requests=0)
        self._worker = threading.Thread(
            target=self._thread_main, args=(prompt, preflight, token),
            name="lakis-external-ui-generation", daemon=True,
        )
        self._worker.start()
        return {"ok": True, "request_id": token["request_id"], "preflight": preflight}

    def _thread_main(self, prompt: dict[str, Any], preflight: dict[str, Any], token: dict[str, Any]) -> None:
        try:
            asyncio.run(self._run(prompt, preflight, token))
        except Exception as error:
            error_code, public_message = self._public_error(error)
            self.status.update(state="error", error=public_message, error_code=error_code,
                               error_detail=str(error)[:4000], stage="오류", finished_at=time.time())
            _audit("external_ui_generation_failed", error=repr(error), prompt_requests=self.status.prompt_requests)
        finally:
            if self.status.prompt_requests:
                self._request_runtime_reset()
            if ALLOW_FILE.exists():
                ALLOW_FILE.unlink()
            if self._consumed_allowance and self._consumed_allowance.exists():
                self._consumed_allowance.unlink()

    @staticmethod
    def _public_error(error: Exception) -> tuple[str, str]:
        detail = str(error)
        lowered = detail.lower()
        if "fault failed: 2" in lowered or "vram allocation failed" in lowered:
            return (
                "MODEL_MEMORY_STATE_FAILED",
                "GPU 모델 메모리 상태가 불안정해 생성이 중단됐어요. "
                "ComfyUI가 종료됐다면 LAKIS를 다시 실행한 뒤 재시도해 주세요.",
            )
        if "connection refused" in lowered or "cannot connect" in lowered or "connect call failed" in lowered:
            return "COMFYUI_NOT_AVAILABLE", "ComfyUI 연결이 끊어졌어요. LAKIS를 다시 실행해 주세요."
        if "queue is not empty" in lowered:
            return "COMFYUI_QUEUE_BUSY", "ComfyUI에서 다른 작업이 실행 중이에요. 완료 후 다시 시도해 주세요."
        if "value_bigger_than_max" in lowered or "seed must be between" in lowered:
            return "INVALID_SEED", f"시드는 0부터 {COMFYUI_SEED_MAX} 사이여야 해요."
        if "unknown lora" in lowered:
            return "UNKNOWN_LORA", "선택한 LoRA 파일을 찾을 수 없어요. LoRA 목록을 새로 확인해 주세요."
        return "GENERATION_FAILED", "생성 중 오류가 발생했어요. 자세한 내용은 LAKIS 로그에 저장했어요."

    def _request_runtime_reset(self) -> None:
        """Reset ComfyUI execution/model caches between isolated LAKIS jobs."""
        try:
            request = Request(
                COMFY_SERVER + "/free",
                data=json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
            _audit("external_ui_runtime_reset_requested", reason="isolate_next_spectrum_run")
        except Exception as reset_error:
            _audit("external_ui_runtime_reset_unavailable", error=repr(reset_error))

    async def _run(self, prompt: dict[str, Any], preflight: dict[str, Any], token: dict[str, Any]) -> None:
        client_id = f"lakis-ui-{uuid.uuid4().hex}"
        async with aiohttp.ClientSession() as session:
            async with session.get(COMFY_SERVER + "/queue", timeout=3) as response:
                queue = await response.json()
            if queue.get("queue_running") or queue.get("queue_pending"):
                raise RuntimeError("ComfyUI queue is not empty")
            if self.status.cancel_requested:
                self.status.update(state="cancelled", stage="중지됨", finished_at=time.time())
                return

            consumed = DEV_ROOT / f".ALLOW_ONE_GENERATION.consumed.{token['request_id']}"
            os.replace(ALLOW_FILE, consumed)
            self._consumed_allowance = consumed
            websocket_url = f"ws://127.0.0.1:8189/ws?clientId={client_id}"
            async with session.ws_connect(websocket_url, max_msg_size=16 * 1024 * 1024) as ws:
                payload = {
                    "prompt": prompt,
                    "client_id": client_id,
                    "partial_execution_targets": [FINAL_NODE],
                    # The installed ComfyUI default is preview_method=none.
                    # Scope latent previews to this LAKIS request so the center
                    # image can show sampler progress without changing the
                    # backend launch policy or the stored workflow.
                    "extra_data": {"preview_method": "auto"},
                }
                async with session.post(COMFY_SERVER + "/prompt", json=payload, timeout=60) as response:
                    self.status.update(prompt_requests=1)
                    body = await response.json()
                    if response.status >= 400:
                        raise RuntimeError(f"ComfyUI /prompt rejected: {body}")
                prompt_id = body.get("prompt_id")
                if not prompt_id:
                    raise RuntimeError(f"ComfyUI returned no prompt_id: {body}")
                self.status.update(state="running", prompt_id=prompt_id, stage="생성 중")
                _audit("external_ui_prompt_queued", prompt_id=prompt_id, preflight=preflight,
                       prompt_requests=1, retries=0)
                completed = await self._observe(ws, prompt_id, prompt)

            if not completed:
                _audit("external_ui_generation_cancelled", prompt_id=prompt_id)
                return

            output_url = await self._find_output(session, prompt_id)
            self.status.update(state="complete", percent=100.0, stage="완료",
                               output_url=output_url, finished_at=time.time())
            _audit("external_ui_generation_complete", prompt_id=prompt_id, output_url=output_url)

    async def _observe(self, ws: aiohttp.ClientWebSocketResponse, prompt_id: str,
                       prompt: dict[str, Any]) -> bool:
        weights = {node_id: NODE_WEIGHTS.get(node_id, 0.08) for node_id in prompt}
        total = sum(weights.values()) or 1.0
        completed: set[str] = set()
        current: str | None = None
        current_fraction = 0.0
        while True:
            message = await ws.receive(timeout=1800)
            if message.type == aiohttp.WSMsgType.BINARY:
                self._capture_preview_frame(bytes(message.data))
                continue
            if message.type != aiohttp.WSMsgType.TEXT:
                continue
            envelope = json.loads(message.data)
            event = envelope.get("type")
            data = envelope.get("data", {})
            event_prompt = data.get("prompt_id")
            if event_prompt and event_prompt != prompt_id:
                continue
            if event == "executing":
                next_node = data.get("node")
                if current and current in prompt:
                    completed.add(current)
                current = str(next_node) if next_node is not None else None
                current_fraction = 0.0
                if next_node is None:
                    return True
                self._set_weighted_progress(weights, completed, total, current, 0.0)
            elif event == "progress" and current:
                maximum = float(data.get("max") or 1)
                current_fraction = min(1.0, float(data.get("value") or 0) / maximum)
                self._set_weighted_progress(weights, completed, total, current, current_fraction)
            elif event in {"execution_error", "execution_interrupted"}:
                if event == "execution_interrupted" and self.status.cancel_requested:
                    self.status.update(state="cancelled", stage="중지됨", finished_at=time.time())
                    return False
                raise RuntimeError(json.dumps(data, ensure_ascii=False)[:2000])
            elif event == "execution_success":
                return True

    def _capture_preview_frame(self, frame: bytes) -> None:
        if len(frame) < 8:
            return
        event_type = struct.unpack(">I", frame[:4])[0]
        if event_type == 1:
            image_type = struct.unpack(">I", frame[4:8])[0]
            self._set_preview(frame[8:], "image/png" if image_type == 2 else "image/jpeg")
        elif event_type == 4:
            metadata_length = struct.unpack(">I", frame[4:8])[0]
            image_start = 8 + metadata_length
            if image_start > len(frame):
                return
            mime = "image/jpeg"
            try:
                metadata = json.loads(frame[8:image_start].decode("utf-8"))
                mime = str(metadata.get("image_type") or mime)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            self._set_preview(frame[image_start:], mime)

    def _set_weighted_progress(self, weights: dict[str, float], completed: set[str],
                               total: float, current: str, fraction: float) -> None:
        value = sum(weights[node] for node in completed if node in weights)
        value += weights.get(current, 0.0) * fraction
        # Keep 100% for confirmed Final Saver/history completion.
        percent = min(99.0, max(self.status.percent, value / total * 100.0))
        title = NODE_LABELS.get(current, "처리")
        self.status.update(percent=percent, stage=f"생성 중 · {title}")

    async def _find_output(self, session: aiohttp.ClientSession, prompt_id: str) -> str:
        async with session.get(f"{COMFY_SERVER}/history/{prompt_id}", timeout=15) as response:
            history = await response.json()
        outputs = history.get(prompt_id, {}).get("outputs", {}).get(FINAL_NODE, {})
        images = outputs.get("images", [])
        if images:
            image = images[-1]
            query = urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                               "type": image.get("type", "output")})
            return f"{COMFY_SERVER}/view?{query}"

        # The installed Image Saver reports no `images` entry in history. Since
        # this bridge requires an empty queue before its one owned prompt, a file
        # created after this request began is attributable to the current prompt.
        threshold = float(self.status.started_at or time.time()) - 2.0
        candidates = [
            path for path in OUTPUT_ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            and path.stat().st_mtime >= threshold
        ]
        if not candidates:
            raise RuntimeError("Final Saver 775 completed but no current-request output file was found")
        path = max(candidates, key=lambda item: item.stat().st_mtime)
        relative = path.relative_to(OUTPUT_ROOT)
        query = urlencode({"filename": relative.name,
                           "subfolder": relative.parent.as_posix() if relative.parent != Path(".") else "",
                           "type": "output"})
        return f"{COMFY_SERVER}/view?{query}"

    def cancel(self) -> dict[str, Any]:
        with self.status.lock:
            if self.status.state not in {"preparing", "running"}:
                return {"ok": False, "reason": "no_active_generation"}
            was_preparing = self.status.state == "preparing"
            self.status.state = "cancelling"
            self.status.stage = "중지 중"
            self.status.cancel_requested = True
        if was_preparing:
            _audit("external_ui_prequeue_cancel_requested")
            return {"ok": True}
        request = Request(COMFY_SERVER + "/interrupt", data=b"{}", method="POST",
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            response.read()
        _audit("external_ui_user_cancel_requested", prompt_id=self.status.prompt_id)
        return {"ok": True}
