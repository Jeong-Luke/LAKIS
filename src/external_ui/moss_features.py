"""Pure validation and workflow helpers for the LAKIS MOSS preview.

The caller supplies the current model/node inventories and an already-built
MOSS workflow. This module does not inspect runtime state or import the
standalone MOSS prototype.
"""

from collections.abc import Mapping
import copy
import json
import math
from moss_errors import MossValidationError


_LAYOUT_LABELS = {"object", "character", "text"}
_MAX_REGIONS = 16
_MAX_LORAS = 20


def _inventory(values, field):
    if isinstance(values, Mapping):
        values = values.keys()
    if isinstance(values, (str, bytes)):
        raise MossValidationError("LKS-MOSS-1009", f"{field} 목록은 이름들의 배열이어야 해.")
    try:
        result = set(values)
    except TypeError as exc:
        raise MossValidationError("LKS-MOSS-1009", f"{field} 목록은 이름들의 배열이어야 해.") from exc
    if any(not isinstance(name, str) for name in result):
        raise MossValidationError("LKS-MOSS-1009", f"{field} 목록에는 문자열 이름만 들어갈 수 있어.")
    return result


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _positive_dimension(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MossValidationError("LKS-MOSS-1009", f"{field}은 1 이상의 정수여야 해.")
    return value


def _validate_bbox(value, field):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise MossValidationError("LKS-MOSS-1007", f"{field}.bbox는 [x0, y0, x1, y1] 네 좌표여야 해.")
    if any(not _is_number(coord) for coord in value):
        raise MossValidationError("LKS-MOSS-1007", f"{field}.bbox 좌표는 유한한 숫자여야 해.")
    x0, y0, x1, y1 = value
    if any(coord < 0 or coord > 1000 for coord in value):
        raise MossValidationError("LKS-MOSS-1007", f"{field}.bbox 좌표는 0부터 1000 사이여야 해.")
    if x1 <= x0 or y1 <= y0:
        raise MossValidationError("LKS-MOSS-1007", f"{field}.bbox는 왼쪽 위에서 오른쪽 아래로 넓이가 있어야 해.")
    return [x0, y0, x1, y1]


def _validate_text(value, field, *, required=False):
    if not isinstance(value, str):
        raise MossValidationError("LKS-MOSS-1007", f"{field}은 문자열이어야 해.")
    if len(value) > 2000:
        raise MossValidationError("LKS-MOSS-1007", f"{field}은 2000자 이하여야 해.")
    if required and not value.strip():
        raise MossValidationError("LKS-MOSS-1007", f"{field}은 비어 있을 수 없어.")
    return value


def _validate_moss_lora_name(name, field, inventory):
    normalized_name = name.replace("\\", "/")
    if not normalized_name.startswith("moss/"):
        raise MossValidationError("LKS-MOSS-1003", f"활성 LoRA는 moss/ 계열이어야 해: {name}")
    components = normalized_name.split("/")
    if (
        normalized_name.startswith("/")
        or "\x00" in normalized_name
        or ":" in normalized_name
        or any(component in {"", ".", ".."} for component in components)
    ):
        raise MossValidationError("LKS-MOSS-1003", f"{field}.name은 안전한 MOSS 상대 경로여야 해.")
    if name not in inventory:
        raise MossValidationError("LKS-MOSS-1003", f"활성 LoRA가 현재 MOSS LoRA 목록에 없어: {name}")


def _validate_disabled_feature(raw, key, *, label, scope=False):
    value = raw.get(key, {})
    if not isinstance(value, Mapping):
        raise MossValidationError("LKS-MOSS-1008", f"{label} 설정은 객체여야 해.")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise MossValidationError("LKS-MOSS-1008", f"{label}.enabled는 boolean이어야 해.")
    if enabled:
        raise MossValidationError("LKS-MOSS-1008", f"이 MOSS FAST 미리보기에서는 {label}을 사용할 수 없어.")
    if scope:
        scope_enabled = value.get("scope_enabled", False)
        if not isinstance(scope_enabled, bool):
            raise MossValidationError("LKS-MOSS-1008", "detail.scope_enabled는 boolean이어야 해.")
        if scope_enabled:
            raise MossValidationError("LKS-MOSS-1008", "이 MOSS FAST 미리보기에서는 scope를 사용할 수 없어.")


def validate_options(raw, *, checkpoints, loras, width, height,
                     available_nodes):
    """Validate options against supplied inventories and return a safe copy.

    Disabled LoRA selections are retained (except blank rows) and are never
    applied. Enabled LoRAs must match an exact installed MOSS inventory name.
    """
    if not isinstance(raw, Mapping):
        raise MossValidationError("LKS-MOSS-1009", "기능 설정은 객체여야 해.")

    _positive_dimension(width, "width")
    _positive_dimension(height, "height")
    checkpoint_inventory = _inventory(checkpoints, "체크포인트")
    lora_inventory = _inventory(loras, "LoRA")
    node_inventory = _inventory(available_nodes, "ComfyUI 노드")

    _validate_disabled_feature(raw, "i2i", label="i2i")
    _validate_disabled_feature(raw, "detail", label="detail", scope=True)

    checkpoint = raw.get("checkpoint")
    if not isinstance(checkpoint, str) or checkpoint not in checkpoint_inventory:
        raise MossValidationError("LKS-MOSS-1002", "checkpoint는 제공된 체크포인트 목록에 있는 이름이어야 해.")

    raw_loras = raw.get("loras")
    if not isinstance(raw_loras, (list, tuple)):
        raise MossValidationError("LKS-MOSS-1003", "loras는 선택 항목들의 배열이어야 해.")
    if len(raw_loras) > _MAX_LORAS:
        raise MossValidationError("LKS-MOSS-1003", f"LoRA는 최대 {_MAX_LORAS}개까지 선택할 수 있어.")

    normalized_loras = []
    for index, item in enumerate(raw_loras):
        field = f"loras[{index}]"
        if not isinstance(item, Mapping):
            raise MossValidationError("LKS-MOSS-1003", f"{field}는 객체여야 해.")
        name = item.get("name")
        if not isinstance(name, str):
            raise MossValidationError("LKS-MOSS-1003", f"{field}.name은 문자열이어야 해.")
        enabled = item.get("enabled")
        if not isinstance(enabled, bool):
            raise MossValidationError("LKS-MOSS-1003", f"{field}.enabled는 boolean이어야 해.")
        if not name.strip():
            if enabled:
                raise MossValidationError("LKS-MOSS-1003", f"{field}.name은 비어 있지 않은 문자열이어야 해.")
            continue
        strength = item.get("strength")
        if not _is_number(strength) or not -2 <= strength <= 2:
            raise MossValidationError("LKS-MOSS-1003", f"{field}.strength는 -2부터 2 사이의 유한한 숫자여야 해.")
        if enabled:
            _validate_moss_lora_name(name, field, lora_inventory)
        normalized_loras.append({
            "name": name,
            "strength": float(strength),
            "enabled": enabled,
        })

    raw_regions = raw.get("regions")
    if not isinstance(raw_regions, Mapping):
        raise MossValidationError("LKS-MOSS-1007", "regions는 설정 객체여야 해.")
    regions_enabled = raw_regions.get("enabled")
    if not isinstance(regions_enabled, bool):
        raise MossValidationError("LKS-MOSS-1007", "regions.enabled는 boolean이어야 해.")
    raw_region_items = raw_regions.get("regions")
    if not isinstance(raw_region_items, (list, tuple)):
        raise MossValidationError("LKS-MOSS-1007", "regions.regions는 영역 배열이어야 해.")
    if len(raw_region_items) > _MAX_REGIONS:
        raise MossValidationError("LKS-MOSS-1007", f"영역 프롬프트는 최대 {_MAX_REGIONS}개까지 설정할 수 있어.")

    normalized_regions = []
    seen_ids = set()
    for index, item in enumerate(raw_region_items):
        field = f"regions[{index}]"
        if not isinstance(item, Mapping):
            raise MossValidationError("LKS-MOSS-1007", f"{field}는 객체여야 해.")
        editor_id = item.get("id")
        if not isinstance(editor_id, str) or not editor_id.strip():
            raise MossValidationError("LKS-MOSS-1007", f"{field}.id는 비어 있지 않은 문자열이어야 해.")
        if editor_id in seen_ids:
            raise MossValidationError("LKS-MOSS-1007", f"영역 editor ID가 중복됐어: {editor_id}")
        seen_ids.add(editor_id)

        label = item.get("label")
        if not isinstance(label, str) or label not in _LAYOUT_LABELS:
            raise MossValidationError("LKS-MOSS-1007", f"{field}.label은 object, character, text 중 하나여야 해.")
        if "type" in item:
            layout_type = item["type"]
            if not isinstance(layout_type, str) or layout_type not in _LAYOUT_LABELS:
                raise MossValidationError("LKS-MOSS-1007", f"{field}.type은 object, character, text 중 하나여야 해.")
            if layout_type != label:
                raise MossValidationError("LKS-MOSS-1007", f"{field}.type과 label은 같은 종류여야 해.")

        caption = _validate_text(item.get("caption"), f"{field}.caption")
        bbox = _validate_bbox(item.get("bbox"), field)
        normalized_region = {
            "id": editor_id,
            "label": label,
            "caption": caption,
            "bbox": bbox,
        }
        if "negative_prompt" in item:
            normalized_region["negative_prompt"] = _validate_text(
                item["negative_prompt"], f"{field}.negative_prompt")
        if "text" in item:
            normalized_region["text"] = _validate_text(
                item["text"], f"{field}.text", required=(label == "text"))
        elif label == "text":
            raise MossValidationError("LKS-MOSS-1007", f"{field}.text는 text 영역에 꼭 필요해.")
        normalized_regions.append(normalized_region)

    if any(item["enabled"] for item in normalized_loras):
        missing_nodes = {"LoraLoaderModelOnly"} - node_inventory
        if missing_nodes:
            raise MossValidationError("LKS-MOSS-1001",
                "요청한 기능에 필요한 ComfyUI 노드가 없어: "
                + ", ".join(sorted(missing_nodes)))

    return {
        "checkpoint": checkpoint,
        "i2i": {"enabled": False},
        "loras": normalized_loras,
        "regions": {
            "enabled": regions_enabled,
            "regions": normalized_regions,
        },
        "detail": {
            "enabled": False,
            "scope": "none",
            "scope_enabled": False,
        },
    }


def _native_bbox(bbox, width, height):
    x0, y0, x1, y1 = _validate_bbox(bbox, "region")
    # MOSSImageLayoutPrompt consumes [y0, x0, y1, x1], floors leading
    # edges, ceils trailing edges, then centers them on the canvas.
    return [
        math.floor(round(y0 * height / 1000, 9)) - height // 2,
        math.floor(round(x0 * width / 1000, 9)) - width // 2,
        math.ceil(round(y1 * height / 1000, 9)) - height // 2,
        math.ceil(round(x1 * width / 1000, 9)) - width // 2,
    ]


def compile_layout(prompt, regions, width, height):
    """Compile editor xyxy boxes into centered MOSS-Image yxyx JSON."""
    if not isinstance(prompt, str):
        raise ValueError("prompt는 문자열이어야 해.")
    width = _positive_dimension(width, "width")
    height = _positive_dimension(height, "height")

    if isinstance(regions, Mapping):
        if regions.get("enabled") is False:
            return prompt
        region_items = regions.get("regions", [])
    else:
        region_items = regions
    if not isinstance(region_items, (list, tuple)):
        raise ValueError("regions는 영역 배열 또는 설정 객체여야 해.")
    if not region_items:
        return prompt

    items = []
    for index, region in enumerate(region_items):
        field = f"regions[{index}]"
        if not isinstance(region, Mapping):
            raise ValueError(f"{field}는 객체여야 해.")
        label = region.get("label")
        if not isinstance(label, str) or label not in _LAYOUT_LABELS:
            raise ValueError(f"{field}.label은 object, character, text 중 하나여야 해.")
        if "type" in region:
            layout_type = region["type"]
            if not isinstance(layout_type, str) or layout_type not in _LAYOUT_LABELS:
                raise ValueError(f"{field}.type은 object, character, text 중 하나여야 해.")
            if layout_type != label:
                raise ValueError(f"{field}.type과 label은 같은 종류여야 해.")
        caption = _validate_text(region.get("caption"), f"{field}.caption")
        item = {
            "label": label,
            "caption": caption,
            "bbox": _native_bbox(region.get("bbox"), width, height),
        }
        if label == "text":
            item["text"] = _validate_text(
                region.get("text"), f"{field}.text", required=True)
        items.append(item)

    layout = {
        "summary": {"caption": prompt.strip()},
        "items": items,
        "bbox_coord_space": "abs_centralized",
        "bbox_format": "yxyx",
    }
    return json.dumps(layout, ensure_ascii=False, separators=(",", ":"))


def _add_node(graph, class_type, inputs, next_id):
    node_id = next_id
    while str(node_id) in graph or node_id in graph:
        node_id += 1
    graph[str(node_id)] = {"class_type": class_type, "inputs": inputs}
    return [str(node_id), 0], node_id + 1


def _layout_summary(prompt):
    """Avoid nesting a layout already compiled by the public helper."""
    try:
        parsed = json.loads(prompt)
    except (TypeError, ValueError):
        return prompt
    if not isinstance(parsed, Mapping):
        return prompt
    if (parsed.get("bbox_coord_space") != "abs_centralized"
            or parsed.get("bbox_format") != "yxyx"):
        return prompt
    summary = parsed.get("summary")
    if isinstance(summary, Mapping) and isinstance(summary.get("caption"), str):
        return summary["caption"]
    return prompt


def augment_workflow(graph, params, options):
    """Return a copied graph with checkpoint, MOSS LoRAs, and regional text."""
    from moss_workflows import set_input

    result = copy.deepcopy(graph)
    try:
        set_input(result, "1", "unet_name", options["checkpoint"])
        next_id = max(
            (int(key) for key in result if str(key).isdigit()),
            default=0,
        ) + 1
        model_ref = ["1", 0]

        for lora in options["loras"]:
            if not lora["enabled"]:
                continue
            model_ref, next_id = _add_node(
                result,
                "LoraLoaderModelOnly",
                {
                    "model": model_ref,
                    "lora_name": lora["name"],
                    "strength_model": lora["strength"],
                },
                next_id,
            )
        if model_ref != ["1", 0]:
            result["2"]["inputs"]["model"] = model_ref

        regions = options["regions"]
        if regions["enabled"]:
            width = params["width"]
            height = params["height"]
            positive_prompt = _layout_summary(params["prompt"])
            set_input(result, "5", "text", compile_layout(
                positive_prompt, regions, width, height))

            negative_regions = [
                {
                    "label": "character" if region["label"] == "character" else "object",
                    "caption": region.get("negative_prompt", ""),
                    "bbox": region["bbox"],
                }
                for region in regions["regions"]
                if region.get("negative_prompt", "").strip()
            ]
            if negative_regions:
                negative_prompt = _layout_summary(params["negative_prompt"])
                set_input(result, "6", "text", compile_layout(
                    negative_prompt, negative_regions, width, height))
        return result
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "workflow, params 또는 options가 MOSS 통합 계약과 맞지 않아.") from exc
