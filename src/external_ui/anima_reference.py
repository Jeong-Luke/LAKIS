"""Opt-in SnapRef references on request-local Initial and HighRez models."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re


ADAPTER = "snapref_v2a.safetensors"
ADAPTER_BYTES = 381_821_960
MAX_REFERENCES = 3
DEFAULTS = {
    "enabled": False, "mode": "cs", "fidelity": 1.0, "ref_megapixels": 1.0,
    "experimental_forecast": False,
    "references": [{"image_name": "", "strength": 0.0}],
}
IMAGE_NAME = re.compile(r"LAKIS_reference_[a-f0-9]{64}\.(png|jpg|webp)")


def experimental():
    return os.environ.get("LAKIS_SNAPREF_EXPERIMENT") == "1"


def is_adapter(name):
    return str(name).replace("\\", "/").rsplit("/", 1)[-1] == ADAPTER


def normalize(value):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("ANIMA reference state must be an object")
    source = deepcopy(value)
    image_name = source.pop("image_name", "")
    strength = source.pop("strength", 0.0)
    legacy_weight = source.pop("weight", None)
    if "references" not in source:
        if "strength" not in value and "weight" in value:
            if (type(legacy_weight) not in (int, float) or not math.isfinite(legacy_weight)
                    or not 0 <= legacy_weight <= 2):
                raise ValueError("ANIMA reference legacy weight must be between 0 and 2")
            strength = max(-3.0, math.log(legacy_weight)) if legacy_weight > 0 else 0.0
            if legacy_weight == 0:
                source["enabled"] = False
        source["references"] = [{"image_name": image_name, "strength": strength}]
    result = {**deepcopy(DEFAULTS), **source}
    for key in ("enabled", "experimental_forecast"):
        if type(result[key]) is not bool:
            raise ValueError(f"ANIMA reference {key} must be boolean")
    if result["mode"] not in ("cs", "char"):
        raise ValueError("ANIMA reference mode must be cs or char")
    for key, minimum, maximum in (("fidelity", 0., 1.), ("ref_megapixels", .25, 2.)):
        number = result[key]
        if (type(number) not in (int, float) or not math.isfinite(number)
                or not minimum <= number <= maximum):
            raise ValueError(f"ANIMA reference {key} must be between {minimum} and {maximum}")
    references = result["references"]
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_REFERENCES:
        raise ValueError("레퍼런스는 1개부터 최대 3개까지 설정할 수 있어요.")
    cleaned = []
    for item in references:
        if not isinstance(item, dict):
            raise ValueError("ANIMA reference entry must be an object")
        entry = {"image_name": "", "strength": 0.0, **deepcopy(item)}
        if not isinstance(entry["image_name"], str):
            raise ValueError("ANIMA reference image_name must be text")
        target = entry.get("target_type", "global")
        target_id = entry.get("target_id", "")
        if target not in ("global", "pose", "box"):
            raise ValueError("ANIMA reference target_type must be global, pose or box")
        if not isinstance(target_id, str) or len(target_id) > 256 or (target != "global" and not target_id):
            raise ValueError("레퍼런스를 연결할 3D 인물 또는 박스를 다시 선택해 주세요.")
        if entry["image_name"] and not IMAGE_NAME.fullmatch(entry["image_name"]):
            raise ValueError("ANIMA 레퍼런스 이미지를 다시 선택해 주세요.")
        strength = entry["strength"]
        if (type(strength) not in (int, float) or not math.isfinite(strength)
                or not -3. <= strength <= 3.):
            raise ValueError("ANIMA reference strength must be between -3 and 3")
        cleaned.append(entry)
    result["references"] = cleaned
    return result


def image_path(input_root, name):
    if not isinstance(name, str) or not IMAGE_NAME.fullmatch(name):
        raise ValueError("ANIMA 레퍼런스 이미지를 다시 선택해 주세요.")
    root = Path(input_root).resolve()
    target = (root / name).resolve()
    if target.parent != root or not target.is_file():
        raise ValueError("ANIMA 레퍼런스 이미지를 다시 선택해 주세요.")
    return target


def configuration(comfy_root, object_info):
    root = Path(comfy_root)
    missing = [name for name in ("SnapRef", "LoadImage") if name not in object_info]
    adapter = root / "models/loras" / ADAPTER
    if not adapter.is_file() or adapter.stat().st_size != ADAPTER_BYTES:
        missing.append(ADAPTER)
    return {
        "experimental": experimental(),
        "ready": experimental() and not missing, "missing": missing,
        "defaults": deepcopy(DEFAULTS), "max_references": MAX_REFERENCES,
        "regional_ready": all(name in object_info for name in (
            "LAKISRegionalReference", "LAKISRegionalSnapRef", "LAKISPoseReferenceMask")),
    }


def _regional_plan(prompt, application, references, info, width, height):
    """Validate every target before the caller changes its request-local graph."""
    import anima_regions

    if (type(width) is not int or type(height) is not int
            or not 64 <= width <= 4096 or not 64 <= height <= 4096):
        raise ValueError("영역 레퍼런스 해상도는 가로·세로 64~4096 정수여야 합니다.")
    required = {"LAKISRegionalReference", "LAKISRegionalSnapRef"}
    targets = {item.get("target_type", "global") for item in references}
    if "pose" in targets:
        required.add("LAKISPoseReferenceMask")
    if "global" in targets or "box" in targets:
        required.add("SolidMask")
    if "box" in targets:
        required.add("MaskComposite")
    missing = sorted(required - info.keys())
    if missing:
        raise ValueError("영역 레퍼런스 커스텀 노드를 설치해 주세요: " + ", ".join(missing))
    nodes, links, cache = {}, [], {}

    def add(name, kind, inputs):
        identifier = "lakis:anima_reference:" + name
        nodes[identifier] = {"class_type": kind, "inputs": inputs}
        return [identifier, 0]

    if "box" in targets:
        boxes = anima_regions.normalize(application.get("anima_regions"))
        if not boxes["enabled"]:
            raise ValueError("박스 레퍼런스를 사용하려면 바운딩 박스를 켜 주세요.")
        by_id = {region["id"]: region for region in boxes["regions"]}
        empty = add("mask:empty", "SolidMask", {"value": 0.0, "width": width, "height": height})
    if "pose" in targets:
        scene = application.get("scene_controls", {})
        if not (scene.get("enabled") and scene.get("toyxyz_enabled")):
            raise ValueError("인물 레퍼런스를 사용하려면 3D 포즈를 켜 주세요.")
        try:
            source = json.loads(scene["toyxyz_render_data"])["region_painter"]
            bodies = source["bodies"]
            body_ids = [body["id"] for body in bodies]
            if (source["width"], source["height"]) != (width, height) or len(set(body_ids)) != len(body_ids):
                raise ValueError("stale pose capture")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("3D 인물 마스크가 오래되었거나 잘못되었습니다. 편집기를 다시 적용해 주세요.") from error
        owners = [identifier for identifier, node in prompt.items()
                  if node.get("class_type") == "ToyxyzPose3DEditor"
                  and node.get("inputs", {}).get("render_data") == scene["toyxyz_render_data"]]
        if len(owners) != 1:
            raise ValueError("3D 인물의 생성 연결을 확인할 수 없습니다. 편집기를 다시 적용해 주세요.")
        pose_owner = owners[0]
    for item in references:
        kind, target_id = item.get("target_type", "global"), item.get("target_id", "")
        key = (kind, target_id if kind != "global" else "")
        if key not in cache:
            name = "mask:" + str(len(cache))
            if kind == "global":
                link = add(name, "SolidMask", {"value": 1.0, "width": width, "height": height})
            elif kind == "pose":
                if target_id not in body_ids:
                    raise ValueError("연결된 3D 인물이 없어졌습니다. 레퍼런스의 적용 대상을 다시 선택해 주세요.")
                link = add(name, "LAKISPoseReferenceMask", {
                    "region_painter": [pose_owner, 5], "body_id": target_id, "body_number": 1})
            else:
                if target_id not in by_id:
                    raise ValueError("연결된 박스가 없어졌습니다. 레퍼런스의 적용 대상을 다시 선택해 주세요.")
                x0, y0, x1, y1 = anima_regions._pixels(by_id[target_id]["bbox"], width, height)
                solid = add(name + ":solid", "SolidMask", {"value": 1.0, "width": x1 - x0, "height": y1 - y0})
                link = add(name, "MaskComposite", {
                    "destination": empty, "source": solid, "x": x0, "y": y0, "operation": "add"})
            cache[key] = link
        links.append(cache[key])
    return nodes, links


def apply(prompt, application_state, object_info, comfy_root, *, width=None, height=None):
    settings = normalize(application_state.get("anima_reference"))
    if not settings["enabled"] or not experimental():
        return {"anima_reference_enabled": False}
    if application_state.get("generation", {}).get("engine", "anima") != "anima":
        raise ValueError("ANIMA 레퍼런스는 ANIMA 모드에서만 사용할 수 있어요.")
    if any(application_state.get(key, {}).get("enabled") for key in ("i2i", "inpaint")):
        raise ValueError("ANIMA 레퍼런스와 i2i·인페인트는 함께 사용할 수 없어요.")
    status = configuration(comfy_root, object_info)
    if not status["ready"]:
        raise ValueError("ANIMA 레퍼런스 준비 필요: " + ", ".join(status["missing"]))
    references = [item for item in settings["references"] if item["image_name"]]
    if not references:
        raise ValueError("ANIMA 레퍼런스 이미지를 한 장 이상 선택해 주세요.")
    if len(references) > 1:
        optional = object_info.get("SnapRef", {}).get("input", {}).get("optional", {})
        required = {"use_batch", "multi_layout", "weight_1"}
        for index in range(2, len(references) + 1):
            required.update((f"image_{index}", f"weight_{index}"))
        if not required.issubset(optional):
            raise ValueError("설치된 SnapRef 노드가 다중 레퍼런스 입력을 지원하지 않아요.")
    # Validate all images and boundaries before mutating the request-local graph.
    for item in references:
        image_path(Path(comfy_root) / "input", item["image_name"])
    ports = (("initial", "1634:1721"), ("highrez", "1633:1612"))
    for _, owner in ports:
        if not isinstance(prompt.get(owner, {}).get("inputs", {}).get("model"), list):
            raise ValueError("ANIMA reference model boundary is missing: " + owner)
    for loader in ("890:164", "890:159"):
        if loader not in prompt:
            raise ValueError("ANIMA reference loader is missing: " + loader)
    regional = any(item.get("target_type", "global") != "global" for item in references)
    forecast = regional and settings["experimental_forecast"]
    if forecast:
        optional = object_info.get("LAKISRegionalSnapRef", {}).get("input", {}).get("optional", {})
        if "experimental_forecast" not in optional or "SpectrumKSampler" not in object_info:
            raise ValueError("영역 생성 가속 노드가 준비되지 않았어요. 시험 백엔드를 다시 시작해 주세요.")
    mask_links = []
    if regional:
        output = application_state.get("output", {})
        mask_nodes, mask_links = _regional_plan(
            prompt, application_state, references, object_info,
            output.get("width") if width is None else width,
            output.get("height") if height is None else height)
        prompt.update(mask_nodes)
    image_ids = []
    for index, item in enumerate(references, 1):
        image_id = "lakis:anima_reference:image" + (f":{index}" if index > 1 else "")
        prompt[image_id] = {"class_type": "LoadImage", "inputs": {"image": item["image_name"]}}
        image_ids.append(image_id)
    bundle = None
    if regional:
        for index, (item, image_id, mask) in enumerate(zip(references, image_ids, mask_links), 1):
            identifier = f"lakis:anima_reference:reference:{index}"
            inputs = {"image": [image_id, 0], "mask": mask, "strength": item["strength"]}
            if bundle is not None:
                inputs["previous"] = bundle
            prompt[identifier] = {"class_type": "LAKISRegionalReference", "inputs": inputs}
            bundle = [identifier, 0]
    # SnapRef uses bias + log(weight_i); this preserves every signed UI strength
    # while keeping the official per-image weights inside their 0..2 bounds.
    bias = max(item["strength"] for item in references)
    for stage, owner in ports:
        node_id = "lakis:anima_reference:" + stage
        inputs = prompt[owner]["inputs"]
        if regional:
            prompt[node_id] = {"class_type": "LAKISRegionalSnapRef", "inputs": {
                "model": deepcopy(inputs["model"]), "clip": ["890:164", 0],
                "vae": ["890:159", 0], "references": bundle,
                "adapter": ADAPTER, "mode": settings["mode"],
                "ref_megapixels": settings["ref_megapixels"], "fidelity": settings["fidelity"],
            }}
            if forecast:
                prompt[node_id]["inputs"]["experimental_forecast"] = True
            inputs["model"] = [node_id, 0]
            continue
        reference_inputs = {
            "model": deepcopy(inputs["model"]), "clip": ["890:164", 0],
            "vae": ["890:159", 0], "image": [image_ids[0], 0],
            "adapter": ADAPTER, "mode": settings["mode"],
            "ref_in_uncond": False, "ref_megapixels": settings["ref_megapixels"],
            "strength": bias, "fidelity": settings["fidelity"],
            "ref_caption": "", "ref_guidance_on": False,
        }
        if len(references) > 1:
            reference_inputs.update(use_batch=False, multi_layout="separate")
            for index, item in enumerate(references, 1):
                reference_inputs[f"weight_{index}"] = math.exp(item["strength"] - bias)
                if index > 1:
                    reference_inputs[f"image_{index}"] = [image_ids[index - 1], 0]
        prompt[node_id] = {"class_type": "SnapRef", "inputs": reference_inputs}
        inputs["model"] = [node_id, 0]
    return {
        "anima_reference_enabled": True, "anima_reference_mode": settings["mode"],
        "anima_reference_count": len(references),
        "anima_reference_stages": ["initial", "highrez"],
        "anima_reference_guidance": False,
        "anima_reference_regional": regional,
        "anima_reference_experimental_forecast": forecast,
    }
