"""Narrow LAKIS external-UI bridge for the validated FAST/DETAIL workflow.

The saved Standard workflow and custom-node sources are never modified.  Every
request starts from the validated v7.1 runtime prompt and applies only an
in-memory application-state mapping before submitting Final Saver 775.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import struct
import threading
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

import aiohttp


COMFY_PORT = 8190 if os.environ.get("LAKIS_DEVELOPMENT") == "1" else 8189
COMFY_SERVER = f"http://127.0.0.1:{COMFY_PORT}"
FINAL_NODE = "775"
DEV_ROOT = Path(__file__).resolve().parent.parent
COMFY_ROOT = DEV_ROOT.parent
OUTPUT_ROOT = COMFY_ROOT / "output"
STOP_FILE = DEV_ROOT / "STOP_AUTOMATION"
ALLOW_FILE = DEV_ROOT / "ALLOW_ONE_GENERATION"
TEMPLATE = COMFY_ROOT / "LAKIS" / "workflows" / "LAKIS_runtime_api_v7.1.json"
SAVED_WORKFLOW = COMFY_ROOT / "user" / "default" / "workflows" / "LAKIS_custom_v7.1.json"
# Repair/updater installations made before v7.1 kept the validated workflow
# contents under their v7.0.24 filenames. Continue to accept those files so a
# UI-only update cannot leave the launcher without an executable workflow.
if not TEMPLATE.is_file():
    TEMPLATE = next(iter(sorted((COMFY_ROOT / "LAKIS" / "workflows").glob(
        "LAKIS_runtime_api_v*.json"
    ), reverse=True)), TEMPLATE)
if not SAVED_WORKFLOW.is_file():
    SAVED_WORKFLOW = next(iter(sorted((COMFY_ROOT / "user" / "default" / "workflows").glob(
        "LAKIS_custom_v*.json"
    ), reverse=True)), SAVED_WORKFLOW)
AUDIT_PATH = DEV_ROOT / "external_ui_bridge_audit.jsonl"
LEGACY_UI_STATE_PATH = DEV_ROOT / "external_ui_user_state.json"
USER_STATE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(DEV_ROOT))) / (
    "LAKIS Studio DEV" if os.environ.get("LAKIS_DEVELOPMENT") == "1" else "LAKIS Studio"
)
UNSCOPED_UI_STATE_PATH = USER_STATE_ROOT / "external_ui_user_state.json"
GENERATION_JOURNAL_PATH = USER_STATE_ROOT / "generation-runtime-journal.json"
GENERATION_STALL_SECONDS = 300


def _ui_state_path_for_install(install_root: Path, user_state_root: Path = USER_STATE_ROOT) -> Path:
    """Return a stable per-install state path without exposing the install path."""
    try:
        resolved = install_root.resolve()
    except OSError:
        resolved = install_root.absolute()
    normalized = os.path.normcase(os.path.normpath(str(resolved))).rstrip("\\/")
    scope = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return user_state_root / "installations" / scope / "external_ui_user_state.json"


UI_STATE_PATH = _ui_state_path_for_install(COMFY_ROOT.parent)
UPSCALER_CHOICE_PATH = USER_STATE_ROOT / "upscaler-license-choice.json"
LEGACY_UPSCALER_CHOICE_PATH = COMFY_ROOT.parent / ".lakis" / "upscaler-license-choice.json"
REALESRGAN_MODEL = "RealESRGAN_x4plus_anime_6B.pth"
ANIMESHARP_MODEL = "2x-AnimeSharpV4_Fast_RCAN_PU.safetensors"
UPSCALER_MODELS = {
    "realesrgan": REALESRGAN_MODEL,
    "animesharp": ANIMESHARP_MODEL,
}
UPSCALER_NODE_ID = "1541:1536"
UPSCALER_FIELD_NAME = "model_name"
CAMERA_SOURCE = COMFY_ROOT / "custom_nodes" / "ComfyUI-KR-Camera-Control" / "camera_control.py"
MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
COMFYUI_SEED_MAX = 1125899906842624
PROMPT_STATE_KEYS = {
    "general", "quality", "artist", "trigger", "fixed", "negative",
    "negative_quality", "negative_artist", "negative_fixed",
}
MODEL_STATE_KEYS = {"checkpoint", "vae", "clip", "sampler", "scheduler", "steps", "cfg"}
OUTPUT_STATE_KEYS = {"width", "height", "seed", "seed_mode", "aspect_locked"}
DEFAULT_CHECKPOINT = "anima_baseV10.safetensors"
SAMPLER_OPTIONS = (
    "euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun", "heunpp2",
    "exp_heun_2_x0", "exp_heun_2_x0_sde", "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast",
    "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_2s_ancestral_cfg_pp", "dpmpp_sde",
    "dpmpp_sde_gpu", "dpmpp_2m", "dpmpp_2m_cfg_pp", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu",
    "dpmpp_2m_sde_heun", "dpmpp_2m_sde_heun_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu",
    "ddpm", "lcm", "ipndm", "ipndm_v", "deis", "res_multistep", "res_multistep_cfg_pp",
    "res_multistep_ancestral", "res_multistep_ancestral_cfg_pp", "gradient_estimation",
    "gradient_estimation_cfg_pp", "er_sde", "seeds_2", "seeds_3", "sa_solver", "sa_solver_pece",
    "ddim", "uni_pc", "uni_pc_bh2", "er_sde_cns",
)
SCHEDULER_OPTIONS = (
    "simple", "sgm_uniform", "karras", "exponential", "ddim_uniform", "beta", "normal",
    "linear_quadratic", "kl_optimal",
)
_OBJECT_INFO_CACHE: dict[str, Any] = {}
_OBJECT_INFO_CACHE_AT = 0.0
ADVANCED_FLOAT_FIELD_NAMES = {
    "cfg", "pos_x", "pos_y", "pos_z", "roll", "frame_y",
    "alpha_l", "alpha_h", "smc_lambda", "smc_k", "rdc_tau",
    "rdc_alpha_ll", "rdc_alpha_hh", "crop_factor", "denoise",
    "seam_fix_denoise",
}

ADVANCED_NODE_GROUPS = {
    "model": ("890:1365", "890:159", "890:164", "890:905"),
    "lora": ("1925",),
    "composition": ("2135",),
    "i2i": ("1744", "1736:1737", "1634:1760"),
    "prompt": ("2133",),
    "generation": (
        "2138", "2139", "2140", "1541:1536",
        "1530:2051", "1530:1824", "1530:1827", "1530:1832", "1530:1835", "1530:1834", "1530:2060", "1530:1826",
        "1836:2076", "1836:2067", "1836:2077", "1836:2074", "1836:2078", "1836:2079", "1836:2080", "1836:2069",
        "1541:1535", "1541:1534", "1541:1533", "1541:1532", "1541:1540", "1541:1542", "1541:1837", "1541:1838", "1541:1538",
    ),
}

ADVANCED_NODE_TITLES = {
    "2138": "얼굴 디테일러 스위치", "2139": "눈 디테일러 스위치", "2140": "USDU 스위치",
    "1530:2051": "얼굴 감지 대상", "1530:1824": "얼굴 SAM3 감지", "1530:1827": "얼굴 마스크→SEGS",
    "1530:1832": "얼굴 DCW 스위치", "1530:1835": "얼굴 DCW", "1530:1834": "얼굴 Spectrum",
    "1530:2060": "얼굴 정렬 Hook", "1530:1826": "얼굴 디테일러",
    "1836:2076": "눈 감지 대상", "1836:2067": "눈 SAM3 감지", "1836:2077": "눈 마스크→SEGS",
    "1836:2074": "눈 DCW 스위치", "1836:2078": "눈 DCW", "1836:2079": "눈 Spectrum",
    "1836:2080": "눈 정렬 Hook", "1836:2069": "눈 디테일러",
    "1541:1535": "USDU 배율", "1541:1534": "USDU 타일 분할", "1541:1533": "USDU 가로 타일 계산",
    "1541:1532": "USDU 세로 타일 계산", "1541:1536": "USDU 업스케일 모델", "1541:1540": "USDU DCW",
    "1541:1542": "USDU DCW 스위치", "1541:1837": "USDU Spectrum", "1541:1838": "USDU 스텝",
    "1541:1538": "Ultimate SD Upscale",
}


def _is_node_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)) and isinstance(value[1], int)


def upscaler_choice_status() -> dict[str, Any]:
    """Return only a usable and licence-valid persisted upscaler choice.

    The per-user record is authoritative once it exists.  An invalid/stale
    per-user record must not silently fall back to an older installation
    record because doing so can reactivate a choice the user already changed.
    """
    model_root = COMFY_ROOT / "models" / "upscale_models"
    installed = {
        "realesrgan_installed": (model_root / REALESRGAN_MODEL).is_file(),
        "animesharp_installed": (model_root / ANIMESHARP_MODEL).is_file(),
    }
    choice_path = next(
        (path for path in (UPSCALER_CHOICE_PATH, LEGACY_UPSCALER_CHOICE_PATH) if path.is_file()),
        None,
    )
    if choice_path is None:
        return {"ok": True, "required": True, "reason": "missing_record", **installed}
    try:
        saved = json.loads(choice_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"ok": True, "required": True, "reason": "invalid_record", **installed}
    if not isinstance(saved, dict):
        return {"ok": True, "required": True, "reason": "invalid_record", **installed}

    choice = saved.get("choice")
    selected = UPSCALER_MODELS.get(choice)
    if selected is None or saved.get("model") != selected:
        return {"ok": True, "required": True, "reason": "invalid_record", **installed}
    if choice == "animesharp" and saved.get("noncommercial_acknowledged") is not True:
        return {"ok": True, "required": True, "reason": "licence_acknowledgement_required", **installed}
    if not (model_root / selected).is_file():
        return {"ok": True, "required": True, "reason": "selected_model_missing", **installed}
    return {
        "ok": True,
        "required": False,
        "choice": choice,
        "model": selected,
        **installed,
    }


def _preferred_upscaler() -> str | None:
    status = upscaler_choice_status()
    return status.get("model") if status.get("required") is False else None


def _comfy_object_info() -> dict[str, Any]:
    """Return live ComfyUI input schemas, retaining the last successful snapshot."""
    global _OBJECT_INFO_CACHE, _OBJECT_INFO_CACHE_AT
    if _OBJECT_INFO_CACHE and time.time() - _OBJECT_INFO_CACHE_AT < 300:
        return _OBJECT_INFO_CACHE
    try:
        with urlopen(COMFY_SERVER + "/object_info", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload:
            _OBJECT_INFO_CACHE = payload
            _OBJECT_INFO_CACHE_AT = time.time()
    except Exception:
        pass
    return _OBJECT_INFO_CACHE


def _enum_options(class_type: str, name: str, fallback: tuple[Any, ...] = (),
                  object_info: dict[str, Any] | None = None) -> list[Any]:
    info = object_info if object_info is not None else _comfy_object_info()
    node = info.get(class_type, {}) if isinstance(info, dict) else {}
    inputs = node.get("input", {}) if isinstance(node, dict) else {}
    for section in ("required", "optional"):
        fields = inputs.get(section, {}) if isinstance(inputs, dict) else {}
        spec = fields.get(name) if isinstance(fields, dict) else None
        if isinstance(spec, list) and spec:
            metadata = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            raw_values = spec[0] if isinstance(spec[0], list) else metadata.get("options")
            values = [value for value in raw_values or () if isinstance(value, (str, int, float)) and not isinstance(value, bool)]
            if values:
                values.extend(value for value in fallback if value not in values)
                return values
    return list(fallback)


def _input_schema_type(class_type: str, name: str,
                       object_info: dict[str, Any] | None = None) -> str | None:
    info = object_info if object_info is not None else _comfy_object_info()
    node = info.get(class_type, {}) if isinstance(info, dict) else {}
    inputs = node.get("input", {}) if isinstance(node, dict) else {}
    for section in ("required", "optional"):
        fields = inputs.get(section, {}) if isinstance(inputs, dict) else {}
        spec = fields.get(name) if isinstance(fields, dict) else None
        if isinstance(spec, list) and spec and isinstance(spec[0], str):
            return spec[0]
    return None


def _installed_upscaler_options() -> tuple[str, ...]:
    folder = COMFY_ROOT / "models" / "upscale_models"
    if not folder.is_dir():
        return ()
    return tuple(sorted(
        path.name for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS
    ))


def _input_constraints(class_type: str, name: str,
                       object_info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return safe numeric UI/validation constraints from a live node schema."""
    info = object_info if object_info is not None else _comfy_object_info()
    node = info.get(class_type, {}) if isinstance(info, dict) else {}
    inputs = node.get("input", {}) if isinstance(node, dict) else {}
    for section in ("required", "optional"):
        fields = inputs.get(section, {}) if isinstance(inputs, dict) else {}
        spec = fields.get(name) if isinstance(fields, dict) else None
        metadata = spec[1] if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict) else {}
        constraints = {}
        for key in ("min", "max", "step"):
            value = metadata.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                constraints[key] = value
        return constraints
    return {}


def advanced_node_configuration(template: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return editable primitive/JSON inputs for the five LAKIS control groups."""
    graph = template or json.loads(TEMPLATE.read_text(encoding="utf-8"))
    object_info = _comfy_object_info()
    groups: dict[str, list[dict[str, Any]]] = {}
    for group, node_ids in ADVANCED_NODE_GROUPS.items():
        nodes: list[dict[str, Any]] = []
        for node_id in node_ids:
            node = graph.get(node_id)
            if not isinstance(node, dict):
                continue
            fields = []
            for name, value in node.get("inputs", {}).items():
                if _is_node_link(value):
                    continue
                if node_id == "1541:1536" and name == "model_name":
                    value = _preferred_upscaler() or value
                class_type = str(node.get("class_type") or "")
                schema_type = _input_schema_type(class_type, name, object_info)
                numeric_string = isinstance(value, str) and re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value.strip()) is not None
                boolean_string = isinstance(value, str) and value.strip().lower() in {"true", "false"}
                boolean_value = value if isinstance(value, bool) else str(value).strip().lower() == "true"
                field_type = "boolean" if schema_type == "BOOLEAN" or boolean_string else "json" if isinstance(value, (dict, list)) else (
                    "boolean" if isinstance(value, bool) else
                    "number" if isinstance(value, (int, float)) or numeric_string else
                    "json" if isinstance(value, str) and value.startswith(("[", "{")) else "text"
                )
                if field_type == "boolean":
                    value = boolean_value
                fallback = SAMPLER_OPTIONS if name == "sampler_name" else SCHEDULER_OPTIONS if name == "scheduler" else (
                    _installed_upscaler_options() if node_id == "1541:1536" and name == "model_name" else ()
                )
                options = _enum_options(class_type, name, fallback, object_info)
                boolean_values = None
                if len(options) == 2:
                    normalized = {str(option).strip().lower(): option for option in options}
                    for positive, negative in (("on", "off"), ("enabled", "disabled"), ("yes", "no"), ("true", "false")):
                        if set(normalized) == {positive, negative}:
                            boolean_values = {"true": normalized[positive], "false": normalized[negative]}
                            field_type = "boolean"
                            value = str(value).strip().lower() == positive
                            break
                field = {
                    "name": name, "type": field_type, "value": value,
                    "encoded_json": field_type == "json" and isinstance(value, str),
                    "encoded_number": numeric_string,
                    "options": options or None,
                    "boolean_values": boolean_values,
                }
                if field_type == "number" and not options:
                    field.update(_input_constraints(class_type, name, object_info))
                fields.append(field)
            nodes.append({
                "id": node_id,
                "title": ADVANCED_NODE_TITLES.get(node_id, str(node.get("_meta", {}).get("title") or node.get("class_type") or node_id)),
                "class_type": str(node.get("class_type") or ""),
                "fields": fields,
            })
        groups[group] = nodes
    return groups


def _apply_advanced_node_overrides(prompt: dict[str, Any], requested: Any) -> None:
    if requested in (None, {}):
        return
    if not isinstance(requested, dict):
        raise ValueError("advanced node settings must be an object")
    allowed = {node_id for node_ids in ADVANCED_NODE_GROUPS.values() for node_id in node_ids}
    object_info = _comfy_object_info()
    for node_id, fields in requested.items():
        if node_id not in allowed or node_id not in prompt or not isinstance(fields, dict):
            continue
        inputs = prompt[node_id].get("inputs", {})
        for name, value in fields.items():
            if name not in inputs or _is_node_link(inputs[name]):
                continue
            # The licence choice is the sole authority for the bundled
            # upscaler.  A stale advanced-settings value must never switch a
            # RealESRGAN user back to AnimeSharp without acknowledgement (or
            # override the user's acknowledged AnimeSharp choice).
            if node_id == UPSCALER_NODE_ID and name == UPSCALER_FIELD_NAME:
                continue
            original = inputs[name]
            class_type = str(prompt[node_id].get("class_type") or "")
            schema_type = _input_schema_type(class_type, name, object_info)
            fallback = SAMPLER_OPTIONS if name == "sampler_name" else SCHEDULER_OPTIONS if name == "scheduler" else (
                _installed_upscaler_options() if node_id == "1541:1536" and name == "model_name" else ()
            )
            options = _enum_options(class_type, name, fallback, object_info)
            constraints = _input_constraints(class_type, name, object_info)
            declaration = {key: constraints[key] for key in ("min", "max", "step") if key in constraints}
            if options:
                declaration["options"] = list(options[:100])
                if len(options) > 100:
                    declaration["options_truncated"] = len(options) - 100

            def fail(reason: str) -> None:
                raise SettingsValidationError(
                    reason, node_id=node_id, node_type=class_type,
                    setting_name=name, received_value=value,
                    node_declaration=declaration,
                )

            if options and value not in options:
                fail(f"{node_id}.{name} is not a supported option")
            boolean_string = isinstance(original, str) and original.strip().lower() in {"true", "false"}
            if schema_type == "BOOLEAN" or boolean_string:
                if not isinstance(value, bool):
                    fail(f"{node_id}.{name} must be true or false")
            elif isinstance(original, bool):
                if not isinstance(value, bool):
                    fail(f"{node_id}.{name} must be true or false")
            elif isinstance(original, (int, float)) and not isinstance(original, bool):
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    fail(f"{node_id}.{name} must be a finite number")
                if isinstance(original, float) or name in ADVANCED_FLOAT_FIELD_NAMES:
                    value = float(value)
                else:
                    if not float(value).is_integer():
                        fail(f"{node_id}.{name} must be an integer")
                    value = int(value)
                if "min" in constraints and value < constraints["min"]:
                    fail(f"{node_id}.{name} is below the supported minimum")
                if "max" in constraints and value > constraints["max"]:
                    fail(f"{node_id}.{name} exceeds the supported maximum")
            elif isinstance(original, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                # Some ComfyUI enum-like inputs are numeric strings in the
                # template (for example Prompt Studio resolution_bucket), but
                # friendly UI preparation may temporarily replace them with a
                # label such as "Custom" before this final override pass.
                if not math.isfinite(float(value)):
                    fail(f"{node_id}.{name} must be a finite number")
                value = str(value)
            elif isinstance(original, (dict, list)):
                if not isinstance(value, type(original)):
                    fail(f"{node_id}.{name} has an invalid JSON type")
            elif not isinstance(value, str):
                fail(f"{node_id}.{name} must be text")
            inputs[name] = value


def _clean_advanced_node_overrides(requested: Any) -> dict[str, dict[str, Any]]:
    """Validate and retain only editable node fields for restart persistence."""
    if requested in (None, {}):
        return {}
    if not isinstance(requested, dict):
        raise ValueError("advanced node settings must be an object")
    if len(requested) > sum(len(ids) for ids in ADVANCED_NODE_GROUPS.values()):
        raise ValueError("too many advanced node settings")
    encoded = json.dumps(requested, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 2_000_000:
        raise ValueError("advanced node settings are too large")
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    validated = deepcopy(template)
    _apply_advanced_node_overrides(validated, requested)
    allowed = {node_id for node_ids in ADVANCED_NODE_GROUPS.values() for node_id in node_ids}
    clean: dict[str, dict[str, Any]] = {}
    for node_id, fields in requested.items():
        if node_id not in allowed or node_id not in template or not isinstance(fields, dict):
            continue
        editable = {
            name for name, original in template[node_id].get("inputs", {}).items()
            if not _is_node_link(original)
        }
        selected = {
            name: deepcopy(validated[node_id]["inputs"][name])
            for name in fields
            if name in editable
            and not (node_id == UPSCALER_NODE_ID and name == UPSCALER_FIELD_NAME)
        }
        if selected:
            clean[node_id] = selected
    return clean
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
    payload = _load_external_ui_payload()
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
    if UI_STATE_PATH.is_file():
        source = UI_STATE_PATH
    elif LEGACY_UI_STATE_PATH.is_file():
        # The installation-local legacy state belongs to this exact LAKIS
        # copy, so it must win over an unscoped LocalAppData file that may
        # have been written by a clean/test installation.
        source = LEGACY_UI_STATE_PATH
    elif UNSCOPED_UI_STATE_PATH.is_file():
        # Preserve settings for installations that already migrated to the
        # former global path but never had an installation-local legacy file.
        source = UNSCOPED_UI_STATE_PATH
    else:
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if source != UI_STATE_PATH and not UI_STATE_PATH.is_file():
        # First scoped launch: copy the chosen source without modifying or
        # deleting it.  Failure is non-fatal; this session still uses the
        # source payload and can retry migration on a later save/launch.
        try:
            _write_external_ui_payload(payload)
        except OSError:
            pass
    return payload


def _write_external_ui_payload(payload: dict[str, Any]) -> None:
    UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = UI_STATE_PATH.with_name(f".{UI_STATE_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, UI_STATE_PATH)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def remove_persisted_upscaler_override() -> bool:
    """Remove the legacy advanced override now governed by licence choice."""
    payload = _load_external_ui_payload()
    overrides = payload.get("node_overrides") if isinstance(payload, dict) else None
    node = overrides.get(UPSCALER_NODE_ID) if isinstance(overrides, dict) else None
    if not isinstance(node, dict) or UPSCALER_FIELD_NAME not in node:
        return False
    del node[UPSCALER_FIELD_NAME]
    if not node:
        del overrides[UPSCALER_NODE_ID]
    payload["updated_at"] = time.time()
    _write_external_ui_payload(payload)
    return True


def load_external_generation_state() -> dict[str, Any]:
    payload = _load_external_ui_payload()
    model = payload.get("model", {})
    output = payload.get("output", {})
    try:
        node_overrides = _clean_advanced_node_overrides(payload.get("node_overrides", {}))
    except (TypeError, ValueError, OSError, json.JSONDecodeError):
        node_overrides = {}
    return {
        "model": {key: model[key] for key in MODEL_STATE_KEYS if isinstance(model, dict) and key in model},
        "output": {key: output[key] for key in OUTPUT_STATE_KEYS if isinstance(output, dict) and key in output},
        "node_overrides": node_overrides,
    }


def save_external_generation_state(
    model: Any, output: Any, loras: Any = None, lora_enabled: Any = True,
    node_overrides: Any = None,
) -> dict[str, Any]:
    if not isinstance(model, dict) or not isinstance(output, dict):
        raise ValueError("model and output state must be objects")
    clean_model = {key: model[key] for key in MODEL_STATE_KEYS if key in model}
    if str(clean_model.get("sampler", "euler_ancestral")) not in _enum_options("KSampler", "sampler_name", SAMPLER_OPTIONS):
        raise ValueError("Unsupported sampler")
    if str(clean_model.get("scheduler", "normal")) not in _enum_options("KSampler", "scheduler", SCHEDULER_OPTIONS):
        raise ValueError("Unsupported scheduler")
    clean_output = {key: output[key] for key in OUTPUT_STATE_KEYS if key in output}
    if not isinstance(loras, list):
        loras = []
    if len(loras) > 64:
        raise ValueError("At most 64 LoRAs may be saved")
    clean_loras = []
    for item in loras:
        if not isinstance(item, dict):
            continue
        clean_loras.append({
            "name": str(item.get("name", ""))[:1000],
            "enabled": bool(item.get("enabled", False)),
            "strength": max(-20.0, min(20.0, float(item.get("strength", 1.0)))),
        })
    clean_overrides = _clean_advanced_node_overrides(node_overrides or {})
    payload = _load_external_ui_payload()
    payload.update({
        "version": 2,
        "model": clean_model,
        "output": clean_output,
        "lora": {"current": clean_loras, "enabled": bool(lora_enabled)},
        "node_overrides": clean_overrides,
        "updated_at": time.time(),
    })
    _write_external_ui_payload(payload)
    return {
        "model": clean_model, "output": clean_output, "lora": payload["lora"],
        "node_overrides": clean_overrides,
    }


def _model_files(folder: str) -> list[str]:
    root = COMFY_ROOT / "models" / folder
    return sorted(
        str(path.relative_to(root)).replace("/", "\\")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS
    )


def lora_inventory() -> dict[str, Any]:
    """Return the live LoRA inventory without touching persisted UI state."""
    options = _model_files("loras")
    signature = hashlib.sha256("\n".join(options).encode("utf-8")).hexdigest()
    return {"options": options, "signature": signature, "count": len(options)}


def workflow_configuration() -> dict[str, Any]:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    object_info = _comfy_object_info()
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
    sampler_options = _enum_options("KSampler", "sampler_name", SAMPLER_OPTIONS, object_info)
    scheduler_options = _enum_options("KSampler", "scheduler", SCHEDULER_OPTIONS, object_info)
    sampler = str(saved_model.get("sampler", "euler_ancestral"))
    if sampler not in sampler_options:
        sampler = "euler_ancestral"
    scheduler = str(saved_model.get("scheduler", "normal"))
    if scheduler not in scheduler_options:
        scheduler = "normal"
    return {
        "comfy_port": COMFY_PORT,
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
        "sampler": {"current": sampler, "options": sampler_options, "loader_class": "KSampler"},
        "scheduler": {"current": scheduler, "options": scheduler_options, "loader_class": "KSampler"},
        "lora": _saved_lora_configuration(),
        "prompt": prompt_defaults,
        "advanced_nodes": advanced_node_configuration(template),
        "generation_state": {
            "model": {
                "sampler": sampler,
                "scheduler": scheduler,
                "steps": int(saved_model.get("steps", 30)),
                "cfg": float(saved_model.get("cfg", 5.0)),
            },
            "output": {
                "width": int(saved_output.get("width", 1536)),
                "height": int(saved_output.get("height", 1024)),
                "seed": int(saved_output.get("seed", 579441119814924)),
                "seed_mode": str(saved_output.get("seed_mode", "random")),
                "aspect_locked": bool(saved_output.get("aspect_locked", False)),
            },
            "node_overrides": saved.get("node_overrides", {}),
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
    saved_lora = _load_external_ui_payload().get("lora", {})
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
    if isinstance(saved_lora, dict) and isinstance(saved_lora.get("current"), list):
        configured = []
        for row in saved_lora["current"]:
            if not isinstance(row, dict):
                continue
            raw_name = str(row.get("name") or "").replace("/", "\\")
            installed_name = available_by_key.get(raw_name.casefold()) if raw_name else ""
            configured.append({
                "name": installed_name or "",
                "enabled": bool(row.get("enabled", False)) and bool(installed_name),
                "strength": max(-20.0, min(20.0, float(row.get("strength", 1)))),
            })
    return {
        # Restore the selected workflow profile, but only for LoRAs that are
        # actually installed. A clean first launch therefore remains empty.
        "current": configured,
        "options": available,
        "enabled": bool(saved_lora.get("enabled", True)) if isinstance(saved_lora, dict) else True,
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
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Diagnostics must never turn a successful generation into a failure
        # on a protected or read-only installation.
        pass


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
    # Apply the persisted user choice in memory. This remains effective even
    # when LAKIS is installed in a location where packaged workflows are
    # read-only for the desktop process.
    selected_upscaler = _preferred_upscaler()
    if selected_upscaler:
        for node in prompt.values():
            if node.get("class_type") == "UpscaleModelLoader":
                inputs = node.get("inputs", {})
                if inputs.get("model_name") in {REALESRGAN_MODEL, ANIMESHARP_MODEL}:
                    inputs["model_name"] = selected_upscaler
    required = {FINAL_NODE, "1925", "890:1281", "2133", "2135", "2138", "2139", "2140",
                "1744", "1736:1737", "1634:1760",
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
    i2i = application_state.get("i2i", {})
    mode = generation.get("mode", "fast")
    if mode not in {"fast", "detail"}:
        raise ValueError("generation.mode must be fast or detail")

    detail = mode == "detail"
    for node_id in ("2138", "2139", "2140"):
        prompt[node_id]["inputs"]["value"] = detail

    seed = int(output.get("seed", 0))
    if not 0 <= seed <= COMFYUI_SEED_MAX:
        raise ValueError(f"Seed must be between 0 and {COMFYUI_SEED_MAX}")
    # VAE encoding and the Anima/Spectrum latent path must agree on exact
    # latent cells. Spectrum requires even latent dimensions, so output pixels
    # must be multiples of 16. A width such as 728 yields 91 latent cells and
    # is padded to 92 in one path, causing a 91-vs-92 KSampler mismatch.
    width = round(max(256, min(4096, int(output.get("width", 1024)))) / 16) * 16
    height = round(max(256, min(4096, int(output.get("height", 1536)))) / 16) * 16
    prompt["890:1864"]["inputs"]["seed"] = seed
    i2i_enabled = bool(i2i.get("enabled", False))
    i2i_denoise = max(0.0, min(1.0, float(i2i.get("denoise", 0.5))))
    if i2i_enabled:
        image_name = Path(str(i2i.get("image_name", ""))).name
        image_path = (COMFY_ROOT / "input" / image_name).resolve()
        if not image_name.startswith("LAKIS_i2i_input.") or image_path.parent != (COMFY_ROOT / "input").resolve() or not image_path.is_file():
            raise ValueError("i2i 입력 이미지를 다시 선택해 주세요.")
        prompt["1744"]["inputs"]["image"] = image_name
        # ImageScaleToTotalPixels preserves the source aspect ratio and can
        # produce latent dimensions that differ by one cell from Anima's
        # resolution conditioning. That mismatch fails inside KSampler (for
        # example 107 vs 108). Resize/crop the i2i source to the exact selected
        # output canvas before VAE encoding so both tensor contracts agree.
        prompt["1736:1741"] = {
            "inputs": {
                "image": ["1744", 0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "center",
            },
            "class_type": "ImageScale",
            "_meta": {"title": "i2i 입력을 출력 해상도에 맞춤"},
        }
    prompt["1736:1737"]["inputs"]["value"] = i2i_enabled
    prompt["1634:1760"]["inputs"]["value"] = i2i_denoise
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
    # The v6.1 reference workflow uses a calmer native-model i2i pass
    # (20 steps, CFG 8, Euler/Simple).  It preserves source structure better
    # than the normal T2I sampler defaults without increasing total work.
    if i2i_enabled:
        sampler_config.update({
            "steps_total": 20,
            "refiner_step": min(12, int(sampler_config.get("refiner_step", 12))),
            "cfg": 8.0,
            "sampler_name": "euler",
            "scheduler": "simple",
        })
    # Apply the requested dimensions to every resolution-producing node, not
    # just the node id used by one exported workflow revision. Runtime graph
    # updates can replace or duplicate those ids; leaving even one latent
    # source connected to an old portrait preset makes the visible values and
    # the generated image disagree.
    resolution_nodes: list[str] = []
    latent_nodes: list[str] = []
    for node_id, node in prompt.items():
        inputs = node.get("inputs", {})
        class_type = str(node.get("class_type", ""))
        if "resolution_custom_width" in inputs and "resolution_custom_height" in inputs:
            inputs["resolution_bucket"] = "Custom"
            inputs["resolution_size"] = f"{width} * {height} (custom)"
            inputs["resolution_custom_width"] = width
            inputs["resolution_custom_height"] = height
            resolution_nodes.append(node_id)
        if "latent" in class_type.casefold() and "width" in inputs and "height" in inputs:
            inputs["width"] = width
            inputs["height"] = height
            latent_nodes.append(node_id)
    if not resolution_nodes or not latent_nodes:
        raise RuntimeError(
            "Workflow resolution contract is incomplete: "
            f"prompt_studios={resolution_nodes}, latent_sources={latent_nodes}"
        )

    camera_inputs = prompt["2135"]["inputs"]
    for source, target in (("x", "pos_x"), ("y", "pos_y"), ("z", "pos_z"),
                           ("roll", "roll"), ("frame_y", "frame_y")):
        camera_inputs[target] = float(camera.get(source, camera_inputs.get(target, 0)))

    # Camera-control node values must be applied after the friendly controls
    # but before its generated text is embedded in Prompt Studio. Applying
    # these only with the final advanced pass changes a node that dependency
    # closure later removes and therefore has no effect on the generated image.
    requested_overrides = application_state.get("node_overrides")
    if isinstance(requested_overrides, dict) and "2135" in requested_overrides:
        _apply_advanced_node_overrides(prompt, {"2135": requested_overrides["2135"]})

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
    if not i2i_enabled:
        prompt[turbo_id] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["1633:1619", 0],
                       "lora_name": "anima-turbo-lora-v0.2.safetensors",
                       "strength_model": 1.0},
            "_meta": {"title": "LAKIS External UI - Turbo HighRez"},
        }
    # v6.1 runs a 20-step native HighRez pass.  LAKIS keeps its 1.25x,
    # bicubic, multiple-of-32, max-2560 scaling contract, but uses a shorter
    # 12/16-step native pass: materially more reconstruction than the former
    # 5/6-step Turbo path at roughly the same total sampling budget.
    highrez_steps = (16 if detail else 12) if i2i_enabled else 3
    highrez_cfg = (6.0 if detail else 5.0) if i2i_enabled else 1.0
    highrez_sampler = "euler" if i2i_enabled else "gradient_estimation"
    highrez_denoise = (0.31 if detail else 0.28) if i2i_enabled else 0.2
    highrez_model = ["1633:1619", 0] if i2i_enabled else [turbo_id, 0]
    prompt["1633:1612"]["inputs"].update({
        "model": highrez_model, "steps": highrez_steps, "cfg": highrez_cfg,
        "sampler_name": highrez_sampler, "scheduler": "simple", "denoise": highrez_denoise,
    })

    # Advanced-panel values intentionally run after the friendly controls so
    # an explicit node-level edit is the final authority for this generation.
    _apply_advanced_node_overrides(prompt, requested_overrides)

    prompt = _final_only(prompt)
    # i2i and t2i must share the exact same positive/negative conditioning
    # chain. Guard this contract before queueing so a workflow edit can never
    # silently produce an image while ignoring either prompt branch.
    prompt_contract = {
        "positive_text": prompt.get("890:903", {}).get("inputs", {}).get("text") == ["890:2012", 0],
        "negative_text": prompt.get("890:904", {}).get("inputs", {}).get("text") == ["890:2013", 0],
        "initial_positive": prompt.get("1634:1622", {}).get("inputs", {}).get("positive") == ["1634:1624", 4],
        "initial_negative": prompt.get("1634:1622", {}).get("inputs", {}).get("negative") == ["1634:1624", 5],
        "highrez_positive": prompt.get("1633:1612", {}).get("inputs", {}).get("positive") == ["1633:1618", 4],
        "highrez_negative": prompt.get("1633:1612", {}).get("inputs", {}).get("negative") == ["1633:1618", 5],
    }
    if not all(prompt_contract.values()):
        raise RuntimeError(f"Prompt conditioning contract is disconnected: {prompt_contract}")
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
        "resolution": f"{width}x{height}",
        "i2i_enabled": i2i_enabled,
        "i2i_denoise": i2i_denoise,
        "highrez_steps": highrez_steps,
        "highrez_cfg": highrez_cfg,
        "highrez_sampler": highrez_sampler,
        "highrez_denoise": highrez_denoise,
        "prompt_contract": prompt_contract,
        "resolution_nodes": resolution_nodes,
        "latent_nodes": latent_nodes,
        **lora_assertions,
    }
    ignored_assertions = {"detail_enabled", "node_count", "lora_count", "enabled_lora_count",
                          "loras_globally_enabled", "lora_profile_index", "composition_enabled",
                          "camera_prompt", "resolution", "resolution_nodes", "latent_nodes",
                          "i2i_enabled", "i2i_denoise", "highrez_steps", "highrez_cfg",
                          "highrez_sampler", "highrez_denoise"}
    ignored_assertions.add("prompt_contract")
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
    "2142": "Depth", "2143": "Relight",
    "2151": "Cast Shadow", "2150": "VAE Encode",
    "1633:1790": "HighRez Decode", "1633:1794": "HighRez Encode",
    "1633:1612": "HighRez", "1633:1611": "HighRez Decode",
    "1530:1826": "Face Detail", "1836:2069": "Eye Detail",
    "1541:1538": "Upscale", FINAL_NODE: "Final Save",
}

NODE_ERROR_CODES = {
    "890:1365": ("LKS-MOD-1001", "체크포인트를 불러오지 못했어요."),
    "890:159": ("LKS-MOD-1002", "VAE를 불러오지 못했어요."),
    "890:164": ("LKS-MOD-1003", "CLIP 텍스트 인코더를 불러오지 못했어요."),
    "2133": ("LKS-GEN-1201", "프롬프트를 인코딩하지 못했어요."),
    "1744": ("LKS-I2I-1001", "i2i 입력 이미지를 불러오지 못했어요."),
    "1736:1741": ("LKS-I2I-1002", "i2i 입력 이미지 크기를 변환하지 못했어요."),
    "1634:1622": ("LKS-GEN-1301", "Initial 샘플링 단계에서 오류가 발생했어요."),
    "1635": ("LKS-GEN-1302", "Initial 이미지 디코딩 단계에서 오류가 발생했어요."),
    "1633:1794": ("LKS-GEN-1401", "HighRez 이미지 인코딩 단계에서 오류가 발생했어요."),
    "1633:1612": ("LKS-GEN-1402", "HighRez 샘플링 단계에서 오류가 발생했어요."),
    "1633:1790": ("LKS-GEN-1403", "HighRez 이미지 디코딩 단계에서 오류가 발생했어요."),
    "1633:1611": ("LKS-GEN-1403", "HighRez 이미지 디코딩 단계에서 오류가 발생했어요."),
    "1530:1826": ("LKS-GEN-1501", "얼굴 디테일 처리 중 오류가 발생했어요."),
    "1836:2069": ("LKS-GEN-1502", "눈 디테일 처리 중 오류가 발생했어요."),
    "1541:1538": ("LKS-GEN-1601", "업스케일 단계에서 오류가 발생했어요."),
    "775": ("LKS-GEN-1701", "완성된 이미지를 저장하지 못했어요."),
}


class SettingsValidationError(ValueError):
    def __init__(self, message: str, *, node_id: str, node_type: str,
                 setting_name: str, received_value: Any,
                 node_declaration: dict[str, Any]) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.node_type = node_type
        self.setting_name = setting_name
        self.received_value = received_value
        self.node_declaration = node_declaration
        self.internal_reason = message

    def diagnostic(self) -> dict[str, Any]:
        return {
            "setting_node_id": self.node_id,
            "setting_node_type": self.node_type,
            "setting_name": self.setting_name,
            "received_value": self.received_value,
            "node_declaration": self.node_declaration,
            "internal_reason": self.internal_reason,
        }


class GenerationExecutionError(RuntimeError):
    """Structured ComfyUI failure preserved for support diagnostics."""

    def __init__(self, payload: dict[str, Any], *, node_id: str | None,
                 node_type: str | None, failure_stage: str) -> None:
        self.payload = payload if isinstance(payload, dict) else {}
        self.node_id = node_id
        self.node_type = node_type
        self.failure_stage = failure_stage
        self.exception_type = str(self.payload.get("exception_type") or "ComfyUIExecutionError")
        message = str(self.payload.get("exception_message") or "ComfyUI execution failed")
        super().__init__(message + " | " + json.dumps(self.payload, ensure_ascii=False)[:3500])


class GenerationStallError(TimeoutError):
    def __init__(self, *, node_id: str | None, node_type: str | None,
                 failure_stage: str, inactive_seconds: float) -> None:
        self.node_id = node_id
        self.node_type = node_type
        self.failure_stage = failure_stage
        self.exception_type = type(self).__name__
        self.inactive_seconds = round(inactive_seconds, 1)
        super().__init__(f"ComfyUI activity stopped for {self.inactive_seconds}s at node "
                         f"{node_id or 'unknown'} ({node_type or 'unknown'})")


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
    error_stage: str | None = None
    error_node_id: str | None = None
    error_node_type: str | None = None
    error_exception_type: str | None = None
    request_id: str | None = None
    diagnostic_context: dict[str, Any] = field(default_factory=dict)
    mode: str | None = None
    i2i_enabled: bool = False
    prompt_used: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancel_requested: bool = False
    prompt_requests: int = 0
    preview_revision: int = 0
    preview_frames: int = 0
    preview_mime: str | None = None
    last_node_id: str | None = None
    last_node_type: str | None = None
    last_activity_at: float | None = None
    last_node_started_at: float | None = None
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
        self._recover_interrupted_generation()
        # No worker exists during bridge construction. A remaining one-shot
        # authorization therefore belongs to an interrupted previous process.
        if ALLOW_FILE.is_file():
            try:
                ALLOW_FILE.unlink()
                _audit("external_ui_stale_allowance_cleared")
            except OSError as error:
                _audit("external_ui_stale_allowance_clear_failed", error=repr(error))

    def _write_generation_journal(self) -> None:
        snapshot = self.status.snapshot()
        if snapshot.get("state") not in {"preparing", "running", "cancelling"}:
            self._clear_generation_journal()
            return
        GENERATION_JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = GENERATION_JOURNAL_PATH.with_suffix(".tmp")
        safe = {key: snapshot.get(key) for key in (
            "state", "request_id", "prompt_id", "stage", "mode", "i2i_enabled",
            "started_at", "last_activity_at", "last_node_started_at",
            "last_node_id", "last_node_type", "diagnostic_context",
        )}
        temporary.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, GENERATION_JOURNAL_PATH)

    @staticmethod
    def _clear_generation_journal() -> None:
        try:
            GENERATION_JOURNAL_PATH.unlink(missing_ok=True)
        except OSError as error:
            _audit("external_ui_generation_journal_clear_failed", error=repr(error))

    def _recover_interrupted_generation(self) -> None:
        if not GENERATION_JOURNAL_PATH.is_file():
            return
        try:
            saved = json.loads(GENERATION_JOURNAL_PATH.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("generation journal is not an object")
            node_id = str(saved.get("last_node_id") or "") or None
            node_type = str(saved.get("last_node_type") or "") or None
            self.status.update(
                state="error", error="이전 생성 중 ComfyUI 또는 LAKIS가 비정상 종료됐어요.",
                error_code="LKS-GEN-1008", error_detail="Recovered an unfinished generation journal",
                error_stage=saved.get("stage") or "비정상 종료 복구",
                error_node_id=node_id, error_node_type=node_type,
                error_exception_type="RecoveredInterruptedGeneration",
                request_id=saved.get("request_id"), prompt_id=saved.get("prompt_id"),
                diagnostic_context=saved.get("diagnostic_context") or {},
                mode=saved.get("mode"), i2i_enabled=bool(saved.get("i2i_enabled")),
                started_at=saved.get("started_at"), finished_at=time.time(),
                last_activity_at=saved.get("last_activity_at"),
                last_node_started_at=saved.get("last_node_started_at"),
                last_node_id=node_id, last_node_type=node_type, stage="오류",
            )
            _audit("external_ui_interrupted_generation_recovered", request_id=saved.get("request_id"),
                   prompt_id=saved.get("prompt_id"), node_id=node_id, node_type=node_type)
        except Exception as error:
            _audit("external_ui_generation_journal_recovery_failed", error=repr(error))
        finally:
            self._clear_generation_journal()

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
        prompt_used = deepcopy(application_state.get("prompt", {}))
        prompt_used["composition"] = str(preflight.get("camera_prompt") or "")
        self._clear_preview()
        token = {"request_id": uuid.uuid4().hex, "created_at": time.time(), "source": "external_ui_click"}
        with ALLOW_FILE.open("x", encoding="utf-8") as stream:
            json.dump(token, stream)
        diagnostic_context = self._diagnostic_context(application_state)
        self.status.update(state="preparing", percent=0.0, stage="생성 중", prompt_id=None,
                           preview_frames=0, preview_mime=None,
                           output_url=None, error=None, error_code=None, error_detail=None,
                           error_stage=None, error_node_id=None, error_node_type=None,
                           error_exception_type=None, request_id=token["request_id"],
                           diagnostic_context=diagnostic_context,
                           mode=application_state["generation"]["mode"],
                           i2i_enabled=bool(application_state.get("i2i", {}).get("enabled", False)),
                           prompt_used=prompt_used,
                           seed=int(application_state["output"]["seed"]),
                           started_at=time.time(), finished_at=None, cancel_requested=False,
                           prompt_requests=0, last_node_id=None, last_node_type=None,
                           last_activity_at=time.time(), last_node_started_at=None)
        self._write_generation_journal()
        self._worker = threading.Thread(
            target=self._thread_main, args=(prompt, preflight, token),
            name="lakis-external-ui-generation", daemon=True,
        )
        self._worker.start()
        return {"ok": True, "request_id": token["request_id"], "preflight": preflight}

    @staticmethod
    def _diagnostic_context(application_state: dict[str, Any]) -> dict[str, Any]:
        """Copy only reproducibility settings; never prompt text, images, or paths."""
        model = application_state.get("model", {})
        output = application_state.get("output", {})
        generation = application_state.get("generation", {})
        camera = application_state.get("camera", {})
        i2i = application_state.get("i2i", {})
        loras = application_state.get("loras", [])
        return {
            "generation": {key: generation.get(key) for key in ("mode",)},
            "model": {key: model.get(key) for key in (
                "checkpoint", "vae", "clip", "sampler", "scheduler", "steps", "cfg"
            )},
            "output": {key: output.get(key) for key in ("width", "height", "aspect_locked")},
            "loras_enabled": bool(application_state.get("lora_enabled", True)),
            "loras": [
                {key: item.get(key) for key in ("name", "strength", "enabled")}
                for item in loras[:64] if isinstance(item, dict)
            ],
            "camera": {key: camera.get(key) for key in (
                "enabled", "pos_x", "pos_y", "pos_z", "roll", "frame_y"
            )},
            "i2i": {
                "enabled": bool(i2i.get("enabled", False)),
                "denoise": i2i.get("denoise"),
                "source_size_enabled": bool(i2i.get("source_size_enabled", False)),
            },
            "advanced_node_settings": deepcopy(application_state.get("node_overrides", {})),
        }

    def _thread_main(self, prompt: dict[str, Any], preflight: dict[str, Any], token: dict[str, Any]) -> None:
        try:
            asyncio.run(self._run(prompt, preflight, token))
        except Exception as error:
            error_code, public_message = self._public_error(error)
            node_id = getattr(error, "node_id", None)
            node_type = getattr(error, "node_type", None)
            exception_type = getattr(error, "exception_type", type(error).__name__)
            failure_stage = getattr(error, "failure_stage", None) or self.status.stage or "생성 준비"
            self.status.update(state="error", error=public_message, error_code=error_code,
                               error_detail=str(error)[:4000], error_stage=failure_stage,
                               error_node_id=node_id, error_node_type=node_type,
                               error_exception_type=exception_type,
                               stage="오류", finished_at=time.time())
            _audit(
                "external_ui_generation_failed", error_code=error_code,
                request_id=token["request_id"], prompt_id=self.status.prompt_id,
                failure_stage=failure_stage, node_id=node_id, node_type=node_type,
                exception_type=exception_type, error=repr(error),
                prompt_requests=self.status.prompt_requests,
            )
        finally:
            if self.status.prompt_requests:
                self._request_runtime_reset()
            if ALLOW_FILE.exists():
                ALLOW_FILE.unlink()
            if self._consumed_allowance and self._consumed_allowance.exists():
                self._consumed_allowance.unlink()
            self._clear_generation_journal()

    @staticmethod
    def _public_error(error: Exception) -> tuple[str, str]:
        detail = str(error)
        lowered = detail.lower()
        node_id = getattr(error, "node_id", None)
        if isinstance(error, SettingsValidationError):
            return "LKS-CFG-1103", "세부 설정값이 해당 ComfyUI 노드의 입력 규격과 맞지 않아요."
        if "fault failed: 2" in lowered or "vram allocation failed" in lowered:
            return (
                "LKS-GEN-1004",
                "GPU 모델 메모리 상태가 불안정해 생성이 중단됐어요. "
                "ComfyUI가 종료됐다면 LAKIS를 다시 실행한 뒤 재시도해 주세요.",
            )
        if "out of memory" in lowered or "cuda error: memory" in lowered:
            return "LKS-GEN-1005", "GPU 메모리가 부족해 생성이 중단됐어요. 해상도나 LoRA 수를 줄여 주세요."
        if "nan" in lowered or "inf values" in lowered:
            return "LKS-GEN-1006", "계산값이 불안정해 생성이 중단됐어요. CFG나 태그 가중치를 낮춰 주세요."
        if isinstance(error, GenerationStallError):
            return "LKS-GEN-1009", "ComfyUI 작업이 진행되지 않아 생성을 중단했어요. 오류 정보를 복사해 전달해 주세요."
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or "timed out" in lowered:
            return "LKS-GEN-1007", "생성 단계가 제한 시간 안에 응답하지 않았어요."
        if "connection refused" in lowered or "cannot connect" in lowered or "connect call failed" in lowered:
            return "LKS-GEN-1002", "ComfyUI 연결이 끊어졌어요. LAKIS를 다시 실행해 주세요."
        if "queue is not empty" in lowered:
            return "LKS-GEN-1003", "ComfyUI에서 다른 작업이 실행 중이에요. 완료 후 다시 시도해 주세요."
        if "value_bigger_than_max" in lowered or "seed must be between" in lowered:
            return "LKS-GEN-1101", f"시드는 0부터 {COMFYUI_SEED_MAX} 사이여야 해요."
        if "unknown lora" in lowered:
            return "LKS-MOD-1201", "선택한 LoRA 파일을 찾을 수 없어요. LoRA 목록을 새로 확인해 주세요."
        if "unknown diffusion model" in lowered:
            return "LKS-MOD-1101", "선택한 체크포인트 파일을 찾을 수 없어요."
        if "requires an anima-compatible" in lowered:
            return "LKS-MOD-1102", "선택한 체크포인트는 현재 LAKIS 생성 경로와 호환되지 않아요."
        if "unknown vae" in lowered:
            return "LKS-MOD-1103", "선택한 VAE 파일을 찾을 수 없어요."
        if "unknown clip" in lowered:
            return "LKS-MOD-1104", "선택한 CLIP 파일을 찾을 수 없어요."
        if "i2i 입력 이미지를 다시 선택" in detail:
            return "LKS-I2I-1101", "i2i 입력 이미지를 다시 선택해 주세요."
        if "unsupported sampler" in lowered:
            return "LKS-CFG-1101", "지원하지 않는 샘플러가 선택됐어요."
        if "unsupported scheduler" in lowered:
            return "LKS-CFG-1102", "지원하지 않는 스케줄러가 선택됐어요."
        if "advanced node settings" in lowered or "node settings" in lowered:
            return "LKS-CFG-1103", "세부 설정값이 올바르지 않아요."
        if node_id in NODE_ERROR_CODES:
            return NODE_ERROR_CODES[node_id]
        return "LKS-GEN-1001", "생성 중 오류가 발생했어요. 자세한 내용은 LAKIS 로그에 저장했어요."

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
            websocket_url = f"ws://127.0.0.1:{COMFY_PORT}/ws?clientId={client_id}"
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
                self._write_generation_journal()
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
            try:
                message = await ws.receive(timeout=GENERATION_STALL_SECONDS)
            except asyncio.TimeoutError as error:
                snapshot = self.status.snapshot()
                inactive = time.time() - float(snapshot.get("last_activity_at") or time.time())
                raise GenerationStallError(
                    node_id=snapshot.get("last_node_id"), node_type=snapshot.get("last_node_type"),
                    failure_stage=snapshot.get("stage") or "ComfyUI 실행", inactive_seconds=inactive,
                ) from error
            self.status.update(last_activity_at=time.time())
            if message.type == aiohttp.WSMsgType.BINARY:
                self._capture_preview_frame(bytes(message.data))
                self._write_generation_journal()
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
                node_type = str(prompt.get(current, {}).get("class_type") or "") or None
                self.status.update(last_node_id=current, last_node_type=node_type,
                                   last_node_started_at=time.time())
                self._write_generation_journal()
                self._set_weighted_progress(weights, completed, total, current, 0.0)
            elif event == "progress" and current:
                maximum = float(data.get("max") or 1)
                current_fraction = min(1.0, float(data.get("value") or 0) / maximum)
                self._set_weighted_progress(weights, completed, total, current, current_fraction)
                self._write_generation_journal()
            elif event in {"execution_error", "execution_interrupted"}:
                if event == "execution_interrupted" and self.status.cancel_requested:
                    self.status.update(state="cancelled", stage="중지됨", finished_at=time.time())
                    return False
                failed_node_id = str(data.get("node_id") or current or "") or None
                failed_node_type = str(data.get("node_type") or "") or (
                    str(prompt.get(failed_node_id, {}).get("class_type") or "") if failed_node_id else ""
                ) or None
                raise GenerationExecutionError(
                    data, node_id=failed_node_id, node_type=failed_node_type,
                    failure_stage=NODE_LABELS.get(failed_node_id, self.status.stage or "ComfyUI 실행"),
                )
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
