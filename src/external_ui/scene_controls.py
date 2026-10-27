"""LAKIS 8.0 3D pose boundary; saved workflows and upstream nodes stay intact.

Selectively ported from DEKIS scene controls. Suspended bounding boxes, external
control images and experimental inpaint model selection are not public features.
The installer/updater obtains weights from the publisher; this UI module does
not perform downloads.
"""

import hashlib
import json
import math
import mimetypes
import os
import threading
from urllib.parse import unquote, urlsplit


MODELS = {
    "anima_3dpose_6200.safetensors": {
        "sha256": "97542346a658d23ca65368b568aa9aaf2486ccda8942612983aaffdc986cd495",
        "source": "https://huggingface.co/toyxyz/Anima_ControlNet-LLLite",
        "revision": "37f3a4b6574f1dce3dfe3b5440285a39b11b3d8d",
    },
    "anima_regional_4335.safetensors": {
        "sha256": "e907ea9259b324a11c94e5767420a6a46c6a9d86597df5ccf9b1ad5eeb817618",
        "source": "https://huggingface.co/toyxyz/Anima_ControlNet-LLLite",
        "revision": "37f3a4b6574f1dce3dfe3b5440285a39b11b3d8d",
    },
}
STATE_FILENAME = "scene-controls-v8.json"
STATE_LOCK = threading.Lock()
REQUIRED_NODES = (
    "ToyxyzPose3DEditor", "ComfyCoupleBasePrompt", "ComfyCoupleRegionPainter",
    "ComfyCoupleMask", "AnimaLLLiteApply_sdscripts",
)


def model_status(name, comfy_root):
    if name not in MODELS:
        raise ValueError("지원하지 않는 3D 포즈 제어 모델입니다.")
    spec = MODELS[name]
    target = comfy_root / "models" / "controlnet" / name
    digest = None
    if target.is_file():
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "ok": True, "model": name, "installed": digest is not None,
        "valid": digest == spec["sha256"], "hash_verified": digest is not None,
        "expected_sha256": spec["sha256"], "actual_sha256": digest,
        "official_source": spec["source"], "revision": spec["revision"],
        "model_card": f"{spec['source']}/blob/{spec['revision']}/README.md",
        "license_name": "upstream-anima-and-source-data-terms",
        "manual_install_only": False,
        "installation_method": "installer_updater_official_download",
        "notice": (
            "설치기·업데이터가 공식 배포처에서 제어 모델을 다운로드하고 SHA-256을 검증합니다. "
            "모델이 없으면 최신 설치기의 Repair로 추가해 주세요. "
            "Anima의 비상업·비프로덕션 제한과 원본 데이터 이용 조건이 적용됩니다. "
            "파일 확인은 별도의 이용 허가를 뜻하지 않습니다."
        ),
        "absolute_path": str(target) if digest is not None else None,
    }


def normalize_state(value):
    if not isinstance(value, dict):
        raise ValueError("장면 설정은 객체여야 합니다.")
    if value.get("multicharacter") is True:
        raise ValueError("바운딩 박스 기능은 개발이 일시 중단되어 사용할 수 없습니다.")
    result = dict(value)
    for key in ("enabled", "toyxyz_enabled"):
        result[key] = value.get(key, False) is True
    result["multicharacter"] = False
    result["pose_enabled"] = result["toyxyz_enabled"]
    result["region_enabled"] = result["toyxyz_enabled"]
    for key in ("pose_strength", "region_strength"):
        try:
            number = float(value.get(key, 1.0))
        except (ValueError, TypeError) as error:
            raise ValueError("제어 강도는 0~2 범위여야 합니다.") from error
        if not math.isfinite(number) or not 0 <= number <= 2:
            raise ValueError("제어 강도는 0~2 범위여야 합니다.")
        result[key] = number
    for key in ("pose_data", "toyxyz_render_data", "toyxyz_paint_data"):
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > 8_000_000:
            raise ValueError("저장할 장면 데이터가 너무 큽니다.")
        result[key] = text
    return result


def load_state(root):
    path = root / STATE_FILENAME
    if not path.is_file():
        return normalize_state({})
    return normalize_state(json.loads(path.read_text(encoding="utf-8")))


def handle_get(handler, root, comfy_root):
    path = urlsplit(handler.path).path
    if path == "/api/scene-controls":
        try:
            with STATE_LOCK:
                state = load_state(root)
            handler._send_json(200, {
                "ok": True, "version": "8.0.0", "state": state,
                "models": {name: model_status(name, comfy_root) for name in MODELS},
            })
        except (ValueError, TypeError, OSError) as error:
            handler._send_json(503, {"ok": False, "error": str(error)})
        return True
    if not path.startswith("/vendor/toyxyz/"):
        return False
    web = (comfy_root / "custom_nodes" / "ComfyUI_toyxyz_test_nodes" / "web").resolve()
    target = (web / unquote(path.removeprefix("/vendor/toyxyz/"))).resolve()
    if not target.is_relative_to(web) or not target.is_file():
        handler.send_error(404)
        return True
    if target.suffix not in {".js", ".json", ".gz", ".bin", ".css", ".png", ".svg", ".txt"}:
        handler.send_error(404)
        return True
    payload = target.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)
    return True


def handle_post(handler, root):
    if urlsplit(handler.path).path != "/api/scene-controls":
        return False
    try:
        state = normalize_state(handler._read_json(40_000_000))
        with STATE_LOCK:
            root.mkdir(parents=True, exist_ok=True)
            target = root / STATE_FILENAME
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, target)
        handler._send_json(200, {"ok": True, "state": state})
    except (ValueError, TypeError, OSError) as error:
        handler._send_json(400, {"ok": False, "error": str(error)})
    return True


def _widget_defaults(schema):
    result = {}
    for name, spec in schema["input"]["required"].items():
        options = spec[1] if len(spec) > 1 else {}
        if "default" in options:
            result[name] = options["default"]
        elif isinstance(spec[0], list):
            result[name] = spec[0][0]
    return result


def apply_scene_controls(prompt, application, info, comfy_root, width, height):
    config = normalize_state(application.get("scene_controls", {}))
    if not (config["enabled"] and config["toyxyz_enabled"]):
        return {"scene_controls_enabled": False, "toyxyz_enabled": False}
    if application.get("inpaint", {}).get("enabled") or application.get("i2i", {}).get("enabled"):
        raise ValueError("3D 포즈를 사용하려면 i2i와 인페인트를 꺼 주세요.")
    if application.get("composition_enabled"):
        raise ValueError("3D 포즈를 사용하려면 구도 설정을 꺼 주세요.")
    try:
        capture = json.loads(config["toyxyz_render_data"])
        painting = json.loads(config["toyxyz_paint_data"])
        pose = json.loads(config["pose_data"])
    except (ValueError, TypeError) as error:
        raise ValueError("3D 인물·영역 편집기에서 설정을 먼저 적용해 주세요.") from error
    if not all(isinstance(data, dict) and type(data.get("version")) is int
               and data["version"] == 1 for data in (capture, painting, pose)):
        raise ValueError("3D 편집 데이터 형식이 올바르지 않습니다.")
    source = capture.get("region_painter", {})
    if not isinstance(source, dict):
        raise ValueError("3D 인물 마스크 데이터 형식이 올바르지 않습니다.")
    if (source.get("width"), source.get("height")) != (width, height) or (
            painting.get("width"), painting.get("height")) != (width, height):
        raise ValueError("이미지 크기가 바뀌었습니다. 3D 인물·영역 편집기를 다시 적용해 주세요.")
    missing = [name for name in REQUIRED_NODES if name not in info]
    if missing:
        raise ValueError("3D 포즈 노드가 누락되었습니다. Repair로 복구해 주세요: " + ", ".join(missing))
    inventory = info["AnimaLLLiteApply_sdscripts"]["input"]["required"]["lllite_name"][0]
    for name in MODELS:
        if name not in inventory or not model_status(name, comfy_root)["valid"]:
            raise ValueError(f"설치기·업데이터로 제어 모델을 설치하거나 Repair로 확인해 주세요: {name}")

    prompt["lakis:toyxyz_pose"] = {
        "class_type": "ToyxyzPose3DEditor", "inputs": {
            "width": width, "height": height, "pose_data": config["pose_data"],
            "render_data": config["toyxyz_render_data"],
        },
    }
    prompt["lakis:toyxyz_base"] = {
        "class_type": "ComfyCoupleBasePrompt",
        "inputs": {"base_prompt_text": ["890:2012", 0]},
    }
    prompt["lakis:toyxyz_painter"] = {
        "class_type": "ComfyCoupleRegionPainter", "inputs": {
            "clip": ["890:1281", 1], "width": width, "height": height,
            "paint_data": config["toyxyz_paint_data"],
            "region_painter": ["lakis:toyxyz_pose", 5],
            "region": ["lakis:toyxyz_base", 0],
        },
    }
    for key, name, end in (
        ("pose", "anima_3dpose_6200.safetensors", 1.0),
        ("region", "anima_regional_4335.safetensors", 0.3),
    ):
        image_input = ["lakis:toyxyz_pose" if key == "pose" else "lakis:toyxyz_painter", 0]
        for stage, owner in (("initial", "1634:1721"), ("highrez", "1633:1612")):
            identifier = f"lakis:{key}_{stage}"
            prompt[identifier] = {
                "class_type": "AnimaLLLiteApply_sdscripts", "inputs": {
                    "model": prompt[owner]["inputs"]["model"],
                    "lllite_name": name, "image": image_input,
                    "strength": config[key + "_strength"],
                    "start_percent": 0.0, "end_percent": end, "preserve_wrapper": True,
                },
            }
            prompt[owner]["inputs"]["model"] = [identifier, 0]
    for stage, model_owner, sampler in (
        ("initial", "1634:1721", "1634:1622"), ("highrez", "1633:1612", "1633:1612"),
    ):
        identifier = f"lakis:toyxyz_{stage}"
        inputs = _widget_defaults(info["ComfyCoupleMask"])
        inputs.update({
            "model": prompt[model_owner]["inputs"]["model"],
            "region": ["lakis:toyxyz_painter", 1],
            "negative": prompt[sampler]["inputs"]["negative"],
            "model_type": "anima",
        })
        prompt[identifier] = {"class_type": "ComfyCoupleMask", "inputs": inputs}
        prompt[model_owner]["inputs"]["model"] = [identifier, 0]
        prompt[sampler]["inputs"]["positive"] = [identifier, 1]
        prompt[sampler]["inputs"]["negative"] = [identifier, 2]
    return {
        "scene_controls_enabled": True, "toyxyz_enabled": True,
        "pose_enabled": True, "region_enabled": True,
        "scene_prompt_contract": {
            f"{stage}_{branch}": prompt[sampler]["inputs"][branch] == [f"lakis:toyxyz_{stage}", output]
            for stage, sampler in (("initial", "1634:1622"), ("highrez", "1633:1612"))
            for branch, output in (("positive", 1), ("negative", 2))
        },
    }
