# SPDX-FileCopyrightText: 2026 灰暗x
# SPDX-FileCopyrightText: 2026 ComfyUI-KR-Camera-Control contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone Korean camera prompt control derived from ComfyUI_bsk_UI."""

import copy
import json
import math


VERSION = "1.1.1"


DEFAULT_CAMERA_PRESETS = [
    {"name": "정면", "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0, "roll": 0.0, "frame_y": 0.0, "user_prompt": ""},
    {"name": "왼쪽", "pos_x": 0.5, "pos_y": 0.0, "pos_z": 0.0, "roll": 0.0, "frame_y": 0.0, "user_prompt": ""},
    {"name": "오른쪽", "pos_x": -0.5, "pos_y": 0.0, "pos_z": 0.0, "roll": 0.0, "frame_y": 0.0, "user_prompt": ""},
    {"name": "후면", "pos_x": 1.0, "pos_y": 0.0, "pos_z": 0.0, "roll": 0.0, "frame_y": 0.0, "user_prompt": ""},
]


DEFAULT_CONFIG = {
    "weight_min": 0.1,
    "weight_max": 10.0,
    "no_weight": False,
    "no_weight_threshold": 0.5,
    "active_user_prompt": "",
    "camera_presets": DEFAULT_CAMERA_PRESETS,
    "azimuth": {
        "enabled": True,
        "weight": 5.0,
        "deadzone_ratio": 0.2,
        "directions": {
            "front": {"tag": "from front", "enabled": True},
            "back": {"tag": "from behind", "enabled": True},
            "left": {"tag": "from right", "enabled": True},
            "right": {"tag": "from left", "enabled": True},
        },
    },
    "elevation": {
        "enabled": True,
        "weight": 5.0,
        "categories": {
            "bird": {"tag": "directly above, from above, aerial view", "enabled": True},
            "high": {"tag": "high angle, from above", "enabled": True},
            "eye": {"tag": "eye-level", "enabled": True},
            "low": {"tag": "low angle, from below", "enabled": True},
            "worm": {"tag": "directly below", "enabled": True},
        },
    },
    "distance": {
        "enabled": True,
        "weight": 5.0,
        "categories": {
            "ecu": {"tag": "extreme close-up", "enabled": True},
            "cu": {"tag": "close-up", "enabled": True},
            "medium": {"tag": "medium shot", "enabled": True},
            "full": {"tag": "full body", "enabled": True},
            "wide": {"tag": "wide shot", "enabled": True},
        },
    },
    "vertical_framing": {
        "enabled": True,
        "weight": 5.0,
        "deadzone": 0.05,
        "up_tag": "subject positioned high in frame, ample visible foreground below subject",
        "down_tag": "subject positioned low in frame",
    },
    "tilt": {
        "enabled": True,
        "deadzone": 0.15,
        "extra": 0.0,
        "dutch_tag": "dutch angle",
    },
    "wheel_step": 0.0003,
    "extras": {
        "lens": {"enabled": False, "value": "85mm lens"},
        "dof": {"enabled": False, "value": "shallow depth of field", "weight": 1.3},
        "movement": {"enabled": False, "value": "handheld camera"},
        "composition": {"enabled": False, "value": "rule of thirds"},
        "style": {"enabled": False, "value": "cinematic"},
    },
}

DEFAULT_CONFIG_JSON = json.dumps(DEFAULT_CONFIG, ensure_ascii=False)
DISTANCE_RANGES = {
    "ecu": (0.7, 1.0),
    "cu": (0.2, 0.7),
    "medium": (-0.2, 0.2),
    "full": (-0.7, -0.2),
    "wide": (-1.0, -0.7),
}
FARTHER_IS_STRONGER = {"medium", "full", "wide"}
def _merge_defaults(config, defaults):
    for key, value in defaults.items():
        if key not in config:
            config[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(config[key], dict):
            _merge_defaults(config[key], value)
    return config


def _clamp_axis(value):
    try:
        return max(-1.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_presets(value):
    if not isinstance(value, list):
        return copy.deepcopy(DEFAULT_CAMERA_PRESETS)
    presets = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        presets.append({
            "name": str(item.get("name") or f"프리셋 {index}"),
            "pos_x": _clamp_axis(item.get("pos_x", 0.0)),
            "pos_y": _clamp_axis(item.get("pos_y", 0.0)),
            "pos_z": _clamp_axis(item.get("pos_z", 0.0)),
            "roll": _clamp_axis(item.get("roll", 0.0)),
            "frame_y": _clamp_axis(item.get("frame_y", 0.0)),
            "user_prompt": str(item.get("user_prompt", item.get("prompt", "")) or ""),
        })
    return presets


def load_config(raw):
    if not raw:
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        config = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(config, dict):
        return copy.deepcopy(DEFAULT_CONFIG)
    legacy_total_weight = config.get("total_weight")
    had_camera_presets = isinstance(config.get("camera_presets"), list)
    legacy_preset_prompts = config.get("preset_prompts", {})
    config = _merge_defaults(config, DEFAULT_CONFIG)
    if legacy_total_weight is not None:
        for name in ("azimuth", "elevation", "distance"):
            config[name]["weight"] = legacy_total_weight
    config.pop("total_weight", None)
    config.get("elevation", {}).pop("extra", None)
    config.get("distance", {}).pop("extra", None)
    config.pop("extra_master", None)
    config["camera_presets"] = _normalize_presets(config.get("camera_presets"))
    if not had_camera_presets and isinstance(legacy_preset_prompts, dict):
        for index, preset in enumerate(config["camera_presets"]):
            preset["user_prompt"] = str(legacy_preset_prompts.get(str(index), "") or "")
    config.pop("preset_prompts", None)
    config.pop("preset_library_version", None)
    config.pop("legacy_presets_imported", None)
    return config


def _split_tags(tag):
    return [part.strip() for part in str(tag).split(",") if part.strip()]


def _weighted(tag, weight):
    return [f"({part}:{float(weight):.2f})" for part in _split_tags(tag)]


def _plain(tag):
    return _split_tags(tag)


def _append_user_prompt(prompt, user_prompt):
    extra = _split_tags(user_prompt)
    if not extra:
        return prompt
    base = str(prompt).rstrip(",").strip()
    parts = ([base] if base else []) + extra
    return ", ".join(parts) + ","


def _elevation_key(value):
    if value > 0.7:
        return "bird"
    if value > 0.2:
        return "high"
    if value >= -0.2:
        return "eye"
    if value >= -0.7:
        return "low"
    return "worm"


def _distance_key(value):
    if value > 0.7:
        return "ecu"
    if value > 0.2:
        return "cu"
    if value >= -0.2:
        return "medium"
    if value >= -0.7:
        return "full"
    return "wide"


def _distance_parts(config, value):
    key = _distance_key(value)
    category = config["distance"].get("categories", {}).get(key)
    if not category or not category.get("enabled", True) or not category.get("tag"):
        return []
    start, end = DISTANCE_RANGES[key]
    if key in FARTHER_IS_STRONGER:
        fraction = (end - value) / (end - start)
    else:
        fraction = (value - start) / (end - start)
    fraction = max(0.0, min(1.0, fraction))
    weight_min = float(config.get("weight_min", 0.1))
    weight_max = float(config.get("weight_max", 10.0))
    distance_weight = max(weight_min, min(weight_max, float(config.get("distance", {}).get("weight", 5.0))))
    weight = 1.0 + fraction * max(0.0, distance_weight - 1.0)
    weight = max(weight_min, min(weight_max, weight))
    return _weighted(category["tag"], weight)


def _azimuth_ratios(pos_x):
    angle = pos_x * math.pi
    ratios = {
        "front": max(0.0, math.cos(angle)),
        "back": max(0.0, -math.cos(angle)),
        "right": max(0.0, math.sin(angle)),
        "left": max(0.0, -math.sin(angle)),
    }
    total = sum(ratios.values())
    if total:
        ratios = {key: value / total for key, value in ratios.items()}
    return ratios


def _framing_parts(config, frame_y, weighted):
    framing = config.get("vertical_framing", {})
    amount = _clamp_axis(frame_y)
    if not framing.get("enabled", True) or abs(amount) < float(framing.get("deadzone", 0.05)):
        return []
    tag = framing.get("up_tag" if amount > 0 else "down_tag", "")
    if not tag:
        return []
    if not weighted:
        return _plain(tag)
    weight_min = float(config.get("weight_min", 0.1))
    weight_max = float(config.get("weight_max", 10.0))
    framing_weight = max(
        weight_min,
        min(weight_max, float(framing.get("weight", 5.0))),
    )
    weight = 1.0 + abs(amount) * max(0.0, framing_weight - 1.0)
    return _weighted(tag, max(weight_min, min(weight_max, weight)))


def _compute_weighted(pos_x, pos_y, pos_z, roll, config, frame_y=0.0):
    parts = []
    weight_min = float(config.get("weight_min", 0.1))
    weight_max = float(config.get("weight_max", 10.0))
    deadzone = float(config.get("azimuth", {}).get("deadzone_ratio", 0.2))
    azimuth = config.get("azimuth", {})
    azimuth_weight = max(weight_min, min(weight_max, float(azimuth.get("weight", 5.0))))

    if azimuth.get("enabled", True):
        ratios = _azimuth_ratios(pos_x)
        pole_gate = max(0.0, min(1.0, (1.0 - abs(pos_y)) / 0.1))
        budget = azimuth_weight * pole_gate
        for name in ("front", "back", "left", "right"):
            direction = azimuth.get("directions", {}).get(name, {})
            ratio = ratios[name]
            weight = ratio * budget
            if not direction.get("enabled", True) or not direction.get("tag") or ratio <= 0 or weight < deadzone:
                continue
            parts.extend(_weighted(direction["tag"], max(weight_min, min(weight_max, weight))))

    elevation = config.get("elevation", {})
    if elevation.get("enabled", True):
        category = elevation.get("categories", {}).get(_elevation_key(pos_y), {})
        elevation_weight = max(weight_min, min(weight_max, float(elevation.get("weight", 5.0))))
        weight = abs(pos_y) * elevation_weight
        if category.get("enabled", True) and category.get("tag") and weight >= deadzone:
            parts.extend(_weighted(category["tag"], max(weight_min, min(weight_max, weight))))

    distance = config.get("distance", {})
    if distance.get("enabled", True):
        parts.extend(_distance_parts(config, pos_z))

    parts.extend(_framing_parts(config, frame_y, weighted=True))

    tilt = config.get("tilt", {})
    if tilt.get("enabled", True) and abs(roll) >= float(tilt.get("deadzone", 0.15)):
        weight = 1.0 + float(tilt.get("extra", 0.0))
        parts.extend(_weighted(tilt.get("dutch_tag", ""), max(0.1, min(weight_max, weight))))

    for name in ("lens", "dof", "movement", "composition", "style"):
        extra = config.get("extras", {}).get(name, {})
        value = str(extra.get("value", "")).strip()
        if not extra.get("enabled") or not value:
            continue
        parts.append(f"({value}:{float(extra.get('weight', 1.3)):.2f})" if name == "dof" else value)

    return ", ".join(parts) + ("," if parts else "")


def _compute_plain(pos_x, pos_y, pos_z, roll, config, frame_y=0.0):
    parts = []
    threshold = float(config.get("no_weight_threshold", 0.5))
    azimuth = config.get("azimuth", {})
    if azimuth.get("enabled", True) and abs(pos_y) < 1.0:
        ratios = _azimuth_ratios(pos_x)
        enabled = [
            (name, ratio)
            for name, ratio in ratios.items()
            if azimuth.get("directions", {}).get(name, {}).get("enabled", True)
        ]
        if enabled:
            dominant = max(enabled, key=lambda item: item[1])[0]
            parts.extend(_plain(azimuth["directions"][dominant].get("tag", "")))
            for name, ratio in enabled:
                if name != dominant and ratio >= threshold:
                    parts.extend(_plain(azimuth["directions"][name].get("tag", "")))

    elevation_key = _elevation_key(pos_y)
    if config.get("elevation", {}).get("enabled", True) and elevation_key != "eye":
        category = config["elevation"].get("categories", {}).get(elevation_key, {})
        if category.get("enabled", True):
            parts.extend(_plain(category.get("tag", "")))

    distance_key = _distance_key(pos_z)
    if config.get("distance", {}).get("enabled", True) and distance_key != "medium":
        category = config["distance"].get("categories", {}).get(distance_key, {})
        if category.get("enabled", True):
            parts.extend(_plain(category.get("tag", "")))

    parts.extend(_framing_parts(config, frame_y, weighted=False))

    tilt = config.get("tilt", {})
    if tilt.get("enabled", True) and abs(roll) >= float(tilt.get("deadzone", 0.15)):
        parts.extend(_plain(tilt.get("dutch_tag", "")))

    for name in ("lens", "dof", "movement", "composition", "style"):
        extra = config.get("extras", {}).get(name, {})
        value = str(extra.get("value", "")).strip()
        if extra.get("enabled") and value:
            parts.append(value)
    return ", ".join(parts) + ("," if parts else "")


class KRCameraControl:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pos_x": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01, "label": "좌우 (X)"}),
                "pos_y": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01, "label": "상하 (Y)"}),
                "pos_z": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01, "label": "거리 (Z)"}),
                "roll": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01, "label": "롤 (R)"}),
                "config": ("STRING", {"default": DEFAULT_CONFIG_JSON, "multiline": True}),
                "frame_y": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01, "label": "세로 프레이밍"}),
            },
            "optional": {
                "preset_index": ("INT", {
                    "default": 0,
                    "min": -2147483648,
                    "max": 2147483647,
                    "step": 1,
                    "forceInput": True,
                    "label": "프리셋 인덱스",
                    "tooltip": "현재 프리셋 목록의 번호를 선택합니다. 범위를 0~(프리셋 수-1)로 둔 Random Int를 연결하면 전체 목록에서 랜덤 선택합니다.",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("카메라 프롬프트",)
    FUNCTION = "generate"
    CATEGORY = "KR Tools/카메라"
    DESCRIPTION = "카메라 방위·높이·거리·롤을 시각적으로 조절하여 STRING 프롬프트를 출력합니다."

    def generate(self, pos_x, pos_y, pos_z, roll, config, frame_y=0.0, preset_index=None):
        parsed = load_config(config)
        selected_preset = None
        presets = parsed.get("camera_presets", [])
        if preset_index is not None and presets:
            selected_index = int(preset_index) % len(presets)
            selected_preset = presets[selected_index]
            pos_x = selected_preset["pos_x"]
            pos_y = selected_preset["pos_y"]
            pos_z = selected_preset["pos_z"]
            roll = selected_preset.get("roll", 0.0)
            frame_y = selected_preset.get("frame_y", 0.0)
        values = (
            float(pos_x),
            float(pos_y),
            float(pos_z),
            float(roll),
            parsed,
            _clamp_axis(frame_y),
        )
        prompt = _compute_plain(*values) if parsed.get("no_weight") else _compute_weighted(*values)
        user_prompt = selected_preset.get("user_prompt", "") if selected_preset else parsed.get("active_user_prompt", "")
        prompt = _append_user_prompt(prompt, user_prompt)
        return (prompt,)


NODE_CLASS_MAPPINGS = {"KR_CameraControl": KRCameraControl}
NODE_DISPLAY_NAME_MAPPINGS = {"KR_CameraControl": "KR 카메라 컨트롤"}
