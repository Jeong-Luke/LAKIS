"""Compile the shared box editor into ANIMA's existing regional attention nodes."""
from __future__ import annotations

import base64
import io
import json
import math

import moss_features
from moss_errors import MossValidationError
from scene_controls import _widget_defaults


def normalize(value):
    try:
        return moss_features.normalize_regions(
            {"enabled": False, "regions": []} if value is None else value)
    except MossValidationError as error:
        raise ValueError(f"ANIMA 영역 설정: {error}") from error


def _pixels(bbox, width, height):
    x0, y0, x1, y1 = bbox
    return (math.floor(x0 * width / 1000), math.floor(y0 * height / 1000),
            math.ceil(x1 * width / 1000), math.ceil(y1 * height / 1000))


def _caption(region):
    parts = [region["caption"].strip()]
    if region["label"] == "text":
        parts.append("text: " + json.dumps(region["text"], ensure_ascii=False))
    return ", ".join(part for part in parts if part)


def _paint_data(regions, width, height):
    from PIL import Image, ImageDraw

    if width * height * len(regions) > 64 * 1024 * 1024:
        raise ValueError("ANIMA 영역 마스크는 합계 64백만 픽셀 이하여야 합니다. 영역 수나 해상도를 줄여 주세요.")
    layers = []
    for index, region in enumerate(regions):
        x0, y0, x1, y1 = _pixels(region["bbox"], width, height)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(112, 214, 154, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        layers.append({
            "id": f"lakis-box-{index}", "color": "#70d69a", "visible": True,
            "strength": 1.0, "prompt": _caption(region),
            "mask": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        })
    return json.dumps({"version": 1, "width": width, "height": height, "layers": layers},
                      ensure_ascii=False, separators=(",", ":"))


def apply(prompt, application, info, width, height):
    config = normalize(application.get("anima_regions"))
    if not config["enabled"]:
        return {"anima_regions_enabled": False, "anima_region_count": 0}
    positive_regions = [region for region in config["regions"] if _caption(region)]
    negative_regions = [region for region in config["regions"]
                        if region.get("negative_prompt", "").strip()]
    if not positive_regions and not negative_regions:
        return {"anima_regions_enabled": False, "anima_region_count": 0}
    scene = application.get("scene_controls", {})
    if application.get("i2i", {}).get("enabled") or application.get("inpaint", {}).get("enabled"):
        raise ValueError("ANIMA 바운딩 박스는 i2i·인페인트와 별도로 사용해 주세요.")
    if (type(width) is not int or type(height) is not int
            or not 64 <= width <= 4096 or not 64 <= height <= 4096):
        raise ValueError("ANIMA 영역 마스크 해상도는 가로·세로 64~4096 정수여야 합니다.")
    required = set()
    if positive_regions:
        required.update(("ComfyCoupleBasePrompt", "ComfyCoupleRegionPainter", "ComfyCoupleMask"))
    if negative_regions:
        required.update(("SolidMask", "MaskComposite", "CLIPTextEncode",
                         "ConditioningSetMask", "ConditioningCombine"))
    missing = sorted(required - info.keys())
    if missing:
        raise ValueError("ANIMA 영역 제어 노드가 누락되었습니다: " + ", ".join(missing))

    def add(name, kind, inputs):
        node_id = "lakis:anima_regions:" + name
        prompt[node_id] = {"class_type": kind, "inputs": inputs}
        return [node_id, 0]

    clip = ["890:1281", 1]
    if positive_regions:
        base = add("base", "ComfyCoupleBasePrompt", {"base_prompt_text": ["890:2012", 0]})
        painter = add("painter", "ComfyCoupleRegionPainter", {
            "clip": clip, "width": width, "height": height,
            "paint_data": _paint_data(positive_regions, width, height), "region": base,
        })
        region_ref = [painter[0], 1]
    negatives = []
    if negative_regions:
        empty = add("empty", "SolidMask", {"value": 0.0, "width": width, "height": height})
        for index, region in enumerate(negative_regions):
            x0, y0, x1, y1 = _pixels(region["bbox"], width, height)
            solid = add(f"negative:{index}:solid", "SolidMask", {
                "value": 1.0, "width": x1 - x0, "height": y1 - y0,
            })
            mask = add(f"negative:{index}:mask", "MaskComposite", {
                "destination": empty, "source": solid, "x": x0, "y": y0, "operation": "add",
            })
            encoded = add(f"negative:{index}:text", "CLIPTextEncode", {
                "clip": clip, "text": region["negative_prompt"],
            })
            negatives.append(add(f"negative:{index}:condition", "ConditioningSetMask", {
                "conditioning": encoded, "mask": mask, "strength": 1.0, "set_cond_area": "default",
            }))
    for stage, owner, sampler in (("initial", "1634:1721", "1634:1622"),
                                   ("highrez", "1633:1612", "1633:1612")):
        negative = prompt[sampler]["inputs"]["negative"]
        for index, condition in enumerate(negatives):
            negative = add(f"{stage}:negative:{index}", "ConditioningCombine", {
                "conditioning_1": negative, "conditioning_2": condition,
            })
        if positive_regions:
            inputs = _widget_defaults(info["ComfyCoupleMask"])
            inputs.update(model=prompt[owner]["inputs"]["model"], region=region_ref,
                          negative=negative, model_type="anima", skip_positive_conditioning=True)
            result = add(stage, "ComfyCoupleMask", inputs)
            prompt[owner]["inputs"]["model"] = result
            prompt[sampler]["inputs"]["positive"] = [result[0], 1]
            negative = [result[0], 2]
        prompt[sampler]["inputs"]["negative"] = negative
    return {
        "anima_regions_enabled": True, "anima_region_count": len(config["regions"]),
        "anima_region_stages": ["initial", "highrez"],
        "anima_regions_with_pose": bool(scene.get("enabled") and scene.get("toyxyz_enabled")),
    }
