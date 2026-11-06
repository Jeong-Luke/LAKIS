"""MOSS graph for the shared LAKIS submission and Final Saver contract."""

from copy import deepcopy
import json
import math
from pathlib import Path
import uuid
import re

import moss_features
import moss_sampling
import moss_workflows
from moss_errors import MossValidationError


MODEL = {
    "checkpoint": "moss_image_sft_int8_convrot.safetensors",
    "clip": "qwen3.5_9b_int8_convrot.safetensors",
    "vae": "flux2-vae.safetensors",
    "sampler": "euler", "scheduler": "sgm_uniform", "steps": 50, "cfg": 3.0,
}
OUTPUT = {"width": 1024, "height": 1024}
LIMITS = {"min_dimension": 256, "max_dimension": 1536, "max_pixels": 1024 * 1536,
          "max_steps": 100, "min_cfg": 1.0, "max_cfg": 10.0}
LOADERS = (
    ("checkpoint", "UNet loader with Name (Image Saver)", "unet_name"),
    ("clip", "CLIPLoader", "clip_name"),
    ("vae", "VAELoader", "vae_name"),
)
REQUIRED_NODES = (
    "UNet loader with Name (Image Saver)", "CLIPLoader", "VAELoader", "CLIPTextEncode",
    "EmptyFlux2LatentImage", "KSampler", "VAEDecode", "Image Saver",
    "ModelSamplingAuraFlow", "SkipLayerGuidanceDiTSimple",
    "PrimitiveStringMultiline", "PrimitiveInt", "PrimitiveFloat",
    "Sampler Selector (Image Saver)", "Scheduler Selector (Image Saver)",
)


def engine(value=None):
    if value is None:
        return "anima"
    if value not in ("anima", "moss"):
        raise ValueError("generation.engine must be anima or moss")
    return value


def _options(info, node, field):
    inputs = info.get(node, {}).get("input", {})
    for section in ("required", "optional"):
        spec = inputs.get(section, {}).get(field)
        if isinstance(spec, list) and spec:
            if isinstance(spec[0], list):
                return spec[0]
            if len(spec) > 1 and isinstance(spec[1], dict):
                return spec[1].get("options", [])
    return []


def is_moss_path(name):
    return isinstance(name, str) and name.replace("\\", "/").casefold().startswith("moss/")


def lora_names(info):
    return [name for name in _options(info, "LoraLoaderModelOnly", "lora_name")
            if is_moss_path(name)]


def configuration(info, *, composition_available=False):
    info = info if isinstance(info, dict) else {}
    missing = [f"ComfyUI 노드: {name}" for name in REQUIRED_NODES if name not in info]
    error_code = "LKS-MOSS-1001" if missing else None
    inventory = {}
    for key, node, field in LOADERS:
        inventory[key] = [
            name for name in _options(info, node, field)
            if name == MODEL[key] or (key == "checkpoint" and is_moss_path(name))
        ]
        if not inventory[key]:
            missing.append(f"모델: {MODEL[key]}")
            error_code = error_code or "LKS-MOSS-1002"
    if "moss_image" not in _options(info, "CLIPLoader", "type"):
        missing.append("CLIPLoader의 moss_image 지원")
        error_code = "LKS-MOSS-1001"
    inventory.update(moss_sampling.sampling_choices(info))
    for field in ("sampler_name", "scheduler"):
        key = "sampler" if field == "sampler_name" else "scheduler"
        if MODEL[key] not in _options(info, "KSampler", field):
            missing.append(f"KSampler {field}: {MODEL[key]}")
            error_code = error_code or ("LKS-MOSS-1004" if key == "sampler" else "LKS-MOSS-1005")
    return {
        "ready": not missing, "missing": missing, "inventory": inventory, "error_code": error_code,
        "defaults": {"model": dict(MODEL), "output": dict(OUTPUT)},
        "limits": dict(LIMITS),
        "capabilities": {
            "checkpoint": True, "lora": "LoraLoaderModelOnly" in info,
            "sampler": bool(inventory["sampler"]), "scheduler": bool(inventory["scheduler"]),
            "composition": composition_available, "regions": True,
            "advanced_features": True, "translation": True, "wildcards": True,
            "i2i": False, "scene_controls": False, "detail": False, "scope": False,
        },
    }


def require_ready(info):
    status = configuration(info)
    if not status["ready"]:
        raise MossValidationError(status["error_code"], "MOSS 생성 준비가 되지 않았습니다. " + "; ".join(status["missing"]))


def validate_models(prompt, info):
    require_ready(info)
    inventory = configuration(info)["inventory"]
    for node_id, key, field in (("1", "checkpoint", "unet_name"),
                                ("4", "clip", "clip_name"), ("10", "vae", "vae_name")):
        if moss_workflows.get_input(prompt, node_id, field) not in inventory[key]:
            raise MossValidationError("LKS-MOSS-1002", f"Invalid MOSS model selection: {key}")
    available_loras = lora_names(info)
    for node in prompt.values():
        if node.get("class_type") == "LoraLoaderModelOnly" and node["inputs"]["lora_name"] not in available_loras:
            raise MossValidationError("LKS-MOSS-1003", "선택한 MOSS LoRA가 현재 설치에 없습니다.")


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise MossValidationError("LKS-MOSS-1009", f"MOSS {name}: {low}..{high} 범위의 정수가 필요합니다.")
    return value


def composition_inputs(state):
    camera = state.get("camera", {})
    if not isinstance(camera, dict):
        raise MossValidationError("LKS-MOSS-1009", "MOSS 구도 설정은 객체여야 합니다.")
    values = {}
    for key, default in (("x", 0), ("y", .35), ("z", -.45), ("roll", 0), ("frame_y", 0)):
        value = camera.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -1 <= value <= 1:
            raise MossValidationError("LKS-MOSS-1009", f"MOSS 구도 {key}는 -1..1 범위의 숫자여야 합니다.")
        values[f"pos_{key}" if key in {"x", "y", "z"} else key] = value
    values["config"] = '{"no_weight":true}'
    return values


def build_prompt(state, info, output_root, seed_max, *, camera_prompt_builder=None):
    require_ready(info)
    generation = state.get("generation", {})
    if generation.get("mode") != "moss" or generation.get("lakis_mode"):
        raise MossValidationError("LKS-MOSS-1008", "MOSS 프로토타입은 기본 생성만 지원합니다. FAST/DETAIL은 ANIMA에서 사용해 주세요.")
    unsupported = (
        state.get("i2i", {}).get("enabled"),
        state.get("inpaint", {}).get("enabled"),
        state.get("scene_controls", {}).get("enabled"),
        state.get("scene_controls", {}).get("toyxyz_enabled"),
        state.get("node_overrides"),
    )
    if any(unsupported):
        raise MossValidationError("LKS-MOSS-1008", "MOSS에서는 포즈·i2i·인페인트·ANIMA 고급 노드 설정을 사용할 수 없습니다.")
    model = state.get("model", {})
    inventory = configuration(info)["inventory"]
    for key in ("checkpoint", "clip", "vae"):
        if model.get(key) not in inventory[key]:
            raise MossValidationError("LKS-MOSS-1002", f"MOSS {key} 설정을 확인해 주세요: {MODEL[key]}")
    output = state.get("output", {})
    width = _integer(output.get("width"), "width", 256, 1536)
    height = _integer(output.get("height"), "height", 256, 1536)
    if width % 16 or height % 16 or width * height > LIMITS["max_pixels"]:
        raise MossValidationError("LKS-MOSS-1009", "MOSS 해상도는 16의 배수이며 총 1,572,864 픽셀 이하여야 합니다.")
    seed = _integer(output.get("seed"), "seed", 0, seed_max)
    steps = _integer(model.get("steps"), "steps", 1, 100)
    cfg = model.get("cfg")
    if isinstance(cfg, bool) or not isinstance(cfg, (int, float)) or not math.isfinite(cfg) or not 1 <= cfg <= 10:
        raise MossValidationError("LKS-MOSS-1009", "MOSS CFG는 1..10 범위의 유한한 숫자여야 합니다.")
    prompts = state.get("prompt", {})
    if not isinstance(prompts, dict) or any(not isinstance(value, str) for value in prompts.values()):
        raise MossValidationError("LKS-MOSS-1009", "MOSS 프롬프트 항목은 문자열이어야 합니다.")
    positive = ", ".join(str(prompts.get(key, "")).strip()
                         for key in ("trigger", "artist", "quality", "fixed", "general")
                         if str(prompts.get(key, "")).strip())
    negative = ", ".join(str(prompts.get(key, "")).strip()
                         for key in ("negative_artist", "negative_quality", "negative_fixed", "negative")
                         if str(prompts.get(key, "")).strip())
    camera_prompt = ""
    composition_enabled = state.get("composition_enabled", False)
    if not isinstance(composition_enabled, bool):
        raise MossValidationError("LKS-MOSS-1009", "MOSS 구도 사용 여부는 boolean이어야 합니다.")
    if composition_enabled:
        if camera_prompt_builder is None:
            raise MossValidationError("LKS-MOSS-1001", "MOSS 구도 프롬프트 서비스를 사용할 수 없습니다.")
        camera_prompt = camera_prompt_builder(composition_inputs(state)).strip().rstrip(",")
        if camera_prompt:
            positive = f"{positive}, {camera_prompt}" if positive else camera_prompt
    if len(positive) > 16000 or len(negative) > 16000:
        raise MossValidationError("LKS-MOSS-1009", "MOSS 긍정·부정 프롬프트는 각각 16,000자 이하여야 합니다.")
    if re.search(r"__[^\r\n]+?__", positive + "\n" + negative):
        raise MossValidationError("LKS-MOSS-1009", "생성 전에 와일드카드를 치환해 주세요.")
    prompt = base_graph(model, width, height, seed, steps, cfg, positive, negative)
    sampling = moss_sampling.normalize({
        "sampler": model.get("sampler"), "scheduler": model.get("scheduler"),
        "node_overrides": state.get("moss_node_overrides", {}),
    }, info, prompt)
    moss_sampling.apply(prompt, sampling)
    selected_loras = state.get("loras", [])
    if not isinstance(selected_loras, list):
        raise MossValidationError("LKS-MOSS-1003", "MOSS LoRA 선택은 배열이어야 합니다.")
    loras = []
    for item in selected_loras:
        if not isinstance(item, dict) or not isinstance(item.get("name", ""), str):
            raise MossValidationError("LKS-MOSS-1003", "MOSS LoRA 항목 형식이 올바르지 않습니다.")
        if not item.get("name", "").strip():
            continue
        loras.append({**item, "enabled": item.get("enabled", False) if state.get("lora_enabled", True) else False})
    options = moss_features.validate_options({
        "checkpoint": model["checkpoint"], "loras": loras,
        "i2i": state.get("i2i", {"enabled": False}),
        "regions": state.get("moss_regions", {"enabled": False, "regions": []}),
        "detail": state.get("moss_detail", {"enabled": False}),
    }, checkpoints=inventory["checkpoint"], loras=lora_names(info),
        width=width, height=height, available_nodes=info)
    regions = options["regions"]
    region_prompt = regions["enabled"] and any(
        region["caption"].strip()
        or (region["label"] == "text" and region.get("text", "").strip())
        for region in regions["regions"]
    )
    if not positive and not region_prompt:
        raise MossValidationError("LKS-MOSS-1009", "MOSS 메인 프롬프트 또는 활성 영역 프롬프트에 내용을 입력해 주세요.")
    prompt = moss_features.augment_workflow(prompt, {
        "prompt": positive, "negative_prompt": negative, "width": width, "height": height,
    }, options)
    saver = prompt["775"]
    if saver.get("class_type") != "Image Saver":
        raise MossValidationError("LKS-MOSS-1010", "MOSS requires the existing LAKIS Final Saver 775 contract")
    saver["inputs"].update(
        filename=f"LAKIS_MOSS_{seed}_{uuid.uuid4().hex}",
        path=str(Path(output_root) / "LAKIS"), images=["9", 0],
        custom=json.dumps({
            "generation_engine": "moss", "clip": MODEL["clip"], "vae": MODEL["vae"],
            "moss_options": options, "moss_sampling": sampling,
            "wildcard": state.get("wildcard", {}),
        }, ensure_ascii=False),
    )
    saver.setdefault("_meta", {})["generation_engine"] = "moss"
    return prompt, {
        "engine": "moss", "final_only": True, "node_count": len(prompt),
        "resolution": f"{width}x{height}", "camera_prompt": camera_prompt,
        "detail_enabled": False, "composition_enabled": composition_enabled,
        "inpaint_enabled": False, "i2i_enabled": False, "scene_controls_enabled": False,
        "enabled_lora_count": sum(row["enabled"] for row in options["loras"]),
        "moss_options": options, "moss_sampling": sampling,
    }


def base_graph(model=None, width=1024, height=1024, seed=0, steps=50, cfg=3.0,
               positive="", negative=""):
    model = MODEL if model is None else model
    try:
        prompt = moss_workflows.load_api()
        if prompt["775"]["class_type"] != "Image Saver":
            raise ValueError("MOSS Final Saver 775 must be Image Saver")
        for node_id, name, value in (
            ("1", "unet_name", model["checkpoint"]),
            ("4", "clip_name", model["clip"]), ("10", "vae_name", model["vae"]),
            ("5", "text", positive), ("6", "text", negative),
            ("7", "width", width), ("7", "height", height),
            ("8", "seed", seed), ("8", "steps", steps), ("8", "cfg", cfg),
            ("8", "sampler_name", model["sampler"]), ("8", "scheduler", model["scheduler"]),
        ):
            moss_workflows.set_input(prompt, node_id, name, value)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise MossValidationError("LKS-MOSS-1010", f"Invalid MOSS API workflow: {error}") from error
    return prompt
