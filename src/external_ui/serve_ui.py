"""Serve the LAKIS prototype and expose a narrowly scoped Explorer bridge."""

from __future__ import annotations

import argparse
import html
import ipaddress
import base64
import binascii
import csv
from functools import lru_cache
import hashlib
import json
import os
import re
import secrets
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, quote, urlencode, urlparse

try:
    from PIL import Image
except ImportError:
    Image = None

UI_ROOT = Path(__file__).resolve().parent
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from workflow_bridge import (
    LOCAL_INPAINT_V2,
    WorkflowBridge,
    lora_inventory,
    model_inventory,
    remove_persisted_upscaler_override,
    save_external_generation_state,
    save_external_prompt_state,
    load_external_prompt_bundle,
    upscaler_choice_status,
    workflow_configuration,
)

try:
    import psutil
except ImportError:  # optional in prototype runtime
    psutil = None


COMFY_ROOT = UI_ROOT.parents[1].resolve()
INSTALL_ROOT = COMFY_ROOT.parent.resolve()
DEVELOPMENT = os.environ.get("LAKIS_DEVELOPMENT") == "1"
USER_STATE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(INSTALL_ROOT))) / (
    "LAKIS Studio DEV" if DEVELOPMENT else "LAKIS Studio"
)
UPSCALER_CHOICE_PATH = USER_STATE_ROOT / "upscaler-license-choice.json"
INPAINT_MODEL_NOTICE_PATH = USER_STATE_ROOT / "inpaint-model-notice.json"
LEGACY_UPSCALER_CHOICE_PATH = INSTALL_ROOT / ".lakis" / "upscaler-license-choice.json"
REALESRGAN_MODEL = "RealESRGAN_x4plus_anime_6B.pth"
REALESRGAN_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
REALESRGAN_SHA256 = "F872D837D3C90ED2E05227BED711AF5671A6FD1C9F7D7E91C911A61F155E99DA"
REALESRGAN_BYTES = 17_938_799
ANIMESHARP_MODEL = "2x-AnimeSharpV4_Fast_RCAN_PU.safetensors"
LLLITE_INPAINT_MODEL = "anima-lllite-inpainting-v2.safetensors"
LLLITE_INPAINT_SHA256 = "5242e677d2be34ee70ca7c97c3b14ff5ee49838c03fc1e60ac4852a180db6ef5"
LLLITE_INPAINT_SOURCE = "https://huggingface.co/kohya-ss/Anima-LLLite"
LLLITE_INPAINT_LICENSE = "CircleStone Labs Non-Commercial License"
LLLITE_INPAINT_LICENSE_PATH = INSTALL_ROOT / "third_party_licenses" / "Anima-LLLite-CircleStone-Non-Commercial-License.txt"
LAKIS_VERSION_PATH = (
    UI_ROOT.parent / "DEV_VERSION" if DEVELOPMENT else COMFY_ROOT.parent / "VERSION"
)
OUTPUT_ROOT = (COMFY_ROOT / "output").resolve()
OUTPUT_LOCATION_PATH = UI_ROOT.parent / "output-location.json"
INPUT_ROOT = (COMFY_ROOT / "input").resolve()
AUDIT_PATH = UI_ROOT.parent / "process_audit.jsonl"
HOST = "127.0.0.1"
PORT = 8766
COMFY_PORT = int(os.environ.get("LAKIS_COMFY_PORT") or (8190 if DEVELOPMENT else 8189))
COMFY_SERVER = f"http://127.0.0.1:{COMFY_PORT}"
WORKFLOW_ROOT = COMFY_ROOT / "user" / "default" / "workflows"
PACKAGED_WORKFLOW_ROOT = (UI_ROOT.parent / "workflows") if DEVELOPMENT else (COMFY_ROOT / "LAKIS" / "workflows")
PREFERRED_LAKIS_WORKFLOW = PACKAGED_WORKFLOW_ROOT / "LAKIS_runtime_api_v7.4.json"
RUNTIME_LAKIS_WORKFLOW = PACKAGED_WORKFLOW_ROOT / "LAKIS_runtime_api_v7.4.json"
RUNTIME_LAKIS_SOURCE_NAME = RUNTIME_LAKIS_WORKFLOW.name
EDITABLE_LAKIS_WORKFLOW = PACKAGED_WORKFLOW_ROOT / "LAKIS_custom_v7.4_editable.json"
AUTOPATCH_MARKER = COMFY_ROOT / "custom_nodes" / "ComfyUI-LAKIS-AutoPatch" / "startup_workflow.json"
GENERATION_BRIDGE = WorkflowBridge()
KOREAN_PATTERN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
TRANSLATION_SPLIT_PATTERN = re.compile(r"([,\n]+)")
I2I_DATA_PATTERN = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)$")
AUTOCOMPLETE_CSV = UI_ROOT / "data" / "autocomplete.csv"
BUILTIN_WILDCARD_ROOT = (UI_ROOT / "data" / "built_in_wildcards").resolve()
USER_WILDCARD_ROOT = (USER_STATE_ROOT / "wildcards").resolve()
WILDCARD_TOKEN_PATTERN = re.compile(r"__([A-Za-z0-9_][A-Za-z0-9_\-/]{0,199})__")
ANY_WILDCARD_TOKEN_PATTERN = re.compile(r"__([^\r\n]{1,240}?)__")
BUILTIN_WILDCARD_LABELS = {
    "background": "배경",
    "composition": "구도",
    "expression": "표정",
    "hair_style_female": "여성 헤어스타일",
    "outfit": "의상",
    "pose": "포즈",
    "prop": "소품",
}
INSTALLATION_ID = hashlib.sha256(
    os.path.normcase(str(INSTALL_ROOT.resolve())).encode("utf-8")
).hexdigest()
SERVER_SESSION_TOKEN = ""
SERVER_PORT = PORT


def lllite_inpaint_weight_status() -> dict:
    request = Request(
        COMFY_SERVER + "/object_info/AnimaLLLiteApply_sdscripts",
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
    )
    with urlopen(request, timeout=5.0) as response:
        object_info = json.loads(response.read().decode("utf-8"))
    required = object_info.get("AnimaLLLiteApply_sdscripts", {}).get("input", {}).get("required", {})
    combo = required.get("lllite_name", [])
    inventory = combo[0] if combo and isinstance(combo[0], list) else []
    inventory_match = next(
        (
            name for name in inventory
            if str(name).replace("\\", "/").rsplit("/", 1)[-1].casefold()
            == LLLITE_INPAINT_MODEL.casefold()
        ),
        None,
    )
    controlnet_root = (COMFY_ROOT / "models" / "controlnet").resolve()
    model_path = None
    if inventory_match is not None:
        relative_name = Path(*str(inventory_match).replace("\\", "/").split("/"))
        default_candidate = (controlnet_root / relative_name).resolve()
        if default_candidate.is_relative_to(controlnet_root) and default_candidate.is_file():
            model_path = default_candidate

    # folder_paths normally refreshes the combo inventory, but some ComfyUI
    # builds can briefly return a stale combo after a patch/restart. Check only
    # this installation's canonical controlnet root as a fallback. Requiring the
    # pinned hash prevents an unrelated same-named file from passing the gate.
    if model_path is None and controlnet_root.is_dir():
        for candidate in controlnet_root.rglob(LLLITE_INPAINT_MODEL):
            resolved_candidate = candidate.resolve()
            if resolved_candidate.is_relative_to(controlnet_root) and resolved_candidate.is_file():
                candidate_digest = hashlib.sha256(resolved_candidate.read_bytes()).hexdigest()
                if candidate_digest.casefold() == LLLITE_INPAINT_SHA256.casefold():
                    model_path = resolved_candidate
                    break

    digest = hashlib.sha256(model_path.read_bytes()).hexdigest() if model_path and model_path.is_file() else None
    hash_verified = digest is not None
    installed = inventory_match is not None or model_path is not None
    valid = installed and (not hash_verified or digest.casefold() == LLLITE_INPAINT_SHA256.casefold())
    return {
        "ok": True, "installed": installed, "valid": valid,
        "model": LLLITE_INPAINT_MODEL, "official_source": LLLITE_INPAINT_SOURCE,
        "license_name": LLLITE_INPAINT_LICENSE,
        "expected_sha256": LLLITE_INPAINT_SHA256, "actual_sha256": digest,
        "hash_verified": hash_verified, "absolute_path": str(model_path) if model_path else None,
        "runtime_discoverable": inventory_match is not None,
        "runtime_inventory_match": str(inventory_match) if inventory_match is not None else None,
        "detection_source": "runtime_inventory" if inventory_match is not None else (
            "same_install_controlnet" if model_path is not None else "missing"
        ),
        "runtime_inventory": inventory,
    }


def inpaint_model_notice_status() -> dict:
    acknowledged = False
    try:
        saved = json.loads(INPAINT_MODEL_NOTICE_PATH.read_text(encoding="utf-8"))
        acknowledged = saved.get("inpaint_model_notice_ack") is True
    except (OSError, ValueError, TypeError):
        pass
    return {"ok": True, "inpaint_model_notice_ack": acknowledged}


def acknowledge_inpaint_model_notice(payload: dict) -> dict:
    if payload.get("inpaint_model_notice_ack") is not True:
        raise ValueError("확인 상태가 올바르지 않습니다.")
    INPAINT_MODEL_NOTICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = INPAINT_MODEL_NOTICE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"inpaint_model_notice_ack": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(INPAINT_MODEL_NOTICE_PATH)
    return inpaint_model_notice_status()


def lllite_model_folder() -> Path:
    try:
        installed = lllite_inpaint_weight_status().get("absolute_path")
        if installed:
            return Path(str(installed)).resolve().parent
    except Exception:
        pass
    candidate = (COMFY_ROOT / "models" / "controlnet").resolve()
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("실제 모델 폴더를 찾을 수 없습니다.")


def _explorer_windows() -> list[int]:
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    windows: list[int] = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd: int, _lparam: int) -> bool:
        class_name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if class_name.value in {"CabinetWClass", "ExploreWClass"} and user32.IsWindowVisible(hwnd):
            windows.append(int(hwnd))
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return windows


def _open_folder_foreground(folder: Path) -> None:
    before = set(_explorer_windows())
    os.startfile(str(folder))
    if os.name != "nt":
        return
    time.sleep(0.35)
    windows = _explorer_windows()
    target = next((hwnd for hwnd in windows if hwnd not in before), windows[0] if windows else 0)
    if not target:
        return
    import ctypes

    user32 = ctypes.windll.user32
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    if foreground_thread and foreground_thread != current_thread:
        user32.AttachThreadInput(current_thread, foreground_thread, True)
    try:
        user32.ShowWindow(target, 9)
        user32.BringWindowToTop(target)
        user32.SetForegroundWindow(target)
    finally:
        if foreground_thread and foreground_thread != current_thread:
            user32.AttachThreadInput(current_thread, foreground_thread, False)


def _wildcard_file(root: Path, relative_name: str) -> Path:
    if not isinstance(relative_name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_\-/]{0,199}", relative_name):
        raise ValueError("잘못된 와일드카드 이름입니다.")
    if ".." in relative_name.split("/"):
        raise ValueError("잘못된 와일드카드 경로입니다.")
    candidate = (root / (relative_name + ".txt")).resolve()
    if candidate.parent != root and root not in candidate.parents:
        raise ValueError("와일드카드 폴더 밖의 파일은 사용할 수 없습니다.")
    if candidate.is_symlink():
        raise ValueError("심볼릭 링크 와일드카드는 사용할 수 없습니다.")
    return candidate


def _read_wildcard(path: Path) -> tuple[list[str], str]:
    payload = path.read_bytes()
    if len(payload) > 1024 * 1024:
        raise ValueError("와일드카드 파일은 1MB 이하여야 합니다.")
    text = payload.decode("utf-8-sig")
    entries = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not entries:
        raise ValueError(f"와일드카드 '{path.stem}'에 선택할 항목이 없습니다.")
    return entries, hashlib.sha256(payload).hexdigest().upper()


def wildcard_inventory() -> dict:
    USER_WILDCARD_ROOT.mkdir(parents=True, exist_ok=True)
    items = []
    for source, root in (("BUILT_IN", BUILTIN_WILDCARD_ROOT), ("USER", USER_WILDCARD_ROOT)):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.txt"), key=lambda item: item.as_posix().lower()):
            try:
                relative = path.relative_to(root).with_suffix("").as_posix()
                safe_path = _wildcard_file(root, relative)
                if safe_path != path.resolve():
                    continue
                entries, digest = _read_wildcard(safe_path)
            except (OSError, UnicodeError, ValueError):
                continue
            english_name = relative.replace("_", " ")
            korean_name = BUILTIN_WILDCARD_LABELS.get(relative) if source == "BUILT_IN" else None
            items.append({
                "name": relative, "display_name": f"{korean_name} | {english_name}" if korean_name else english_name,
                "source": source, "relative_path": relative + ".txt",
                "entry_count": len(entries), "entries": entries, "sha256": digest,
            })
    return {"ok": True, "items": items, "user_root": str(USER_WILDCARD_ROOT)}


def resolve_wildcard_payload(incoming: dict) -> dict:
    prompt = incoming.get("prompt")
    if not isinstance(prompt, dict):
        raise ValueError("프롬프트 형식이 올바르지 않습니다.")
    inpaint = incoming.get("inpaint") if isinstance(incoming.get("inpaint"), dict) else {}
    texts = {str(key): str(value or "") for key, value in prompt.items()}
    if str(inpaint.get("operation", "regenerate")) != "remove":
        texts["__inpaint_positive"] = str(inpaint.get("prompt") or "")
        texts["__inpaint_negative"] = str(inpaint.get("negative_prompt") or "")
    names = []
    for value in texts.values():
        for match in ANY_WILDCARD_TOKEN_PATTERN.finditer(value):
            name = match.group(1)
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_\-/]{0,199}", name) or ".." in name.split("/"):
                raise ValueError(f"잘못된 와일드카드 경로입니다: '{name}'")
            if name not in names:
                names.append(name)
    if names and not bool(incoming.get("enabled")):
        raise ValueError("프롬프트에 와일드카드가 있지만 랜덤 선택 기능이 꺼져 있습니다.")
    inventory = wildcard_inventory()["items"]
    lookup = {}
    for item in inventory:
        if item["source"] == "BUILT_IN":
            lookup.setdefault(item["name"], item)
    for item in inventory:
        if item["source"] == "USER":
            lookup[item["name"]] = item
    seed = int(incoming.get("seed", 0))
    excluded = incoming.get("excluded") if isinstance(incoming.get("excluded"), dict) else {}
    selections = []
    selected = {}
    for name in names:
        item = lookup.get(name)
        if not item:
            raise ValueError(f"와일드카드 '{name}'을 찾을 수 없습니다.")
        blocked = {str(value) for value in excluded.get(name, []) if isinstance(value, str)} if isinstance(excluded.get(name, []), list) else set()
        entries = [value for value in item["entries"] if value not in blocked]
        if not entries:
            raise ValueError(f"와일드카드 '{name}'에 사용할 후보가 없습니다.")
        digest = hashlib.sha256(f"{seed}\0{name}\0{item['sha256']}".encode("utf-8")).digest()
        value = entries[int.from_bytes(digest[:8], "big") % len(entries)]
        if WILDCARD_TOKEN_PATTERN.search(value):
            raise ValueError(f"와일드카드 '{name}'에 지원하지 않는 중첩 토큰이 있습니다.")
        selected[name] = value
        selections.append({
            "name": name, "value": value, "source": item["source"],
            "relative_file": item["relative_path"], "file_sha256": item["sha256"],
        })
    resolved = {key: WILDCARD_TOKEN_PATTERN.sub(lambda match: selected[match.group(1)], value) for key, value in texts.items()}
    resolved_inpaint = dict(inpaint)
    if "__inpaint_positive" in resolved:
        resolved_inpaint["prompt"] = resolved.pop("__inpaint_positive")
        resolved_inpaint["negative_prompt"] = resolved.pop("__inpaint_negative")
    return {"ok": True, "prompt": resolved, "inpaint": resolved_inpaint, "selections": selections}

LINK_SERVER = None
LINK_THREAD = None
LINK_HOST = ""
LINK_PORT = 0
LINK_PIN = ""
LINK_SESSION = ""
LINK_AUTH_FAILURES: dict[str, list[float]] = {}
LINK_LOCK = threading.Lock()
LINK_DEFAULT_PORT = int(os.environ.get("LAKIS_LINK_PORT", "8767"))


def _tailscale_address() -> str:
    override = os.environ.get("LAKIS_LINK_HOST", "").strip()
    if override:
        return override
    candidates = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.add(item[4][0])
    except OSError:
        pass
    if psutil is not None:
        try:
            for interface, addresses in psutil.net_if_addrs().items():
                if "tailscale" not in interface.lower():
                    continue
                for address in addresses:
                    if address.family == socket.AF_INET:
                        candidates.add(address.address)
        except (AttributeError, OSError):
            pass
    for value in sorted(candidates):
        try:
            if ipaddress.ip_address(value) in ipaddress.ip_network("100.64.0.0/10"):
                return value
        except ValueError:
            continue
    raise RuntimeError("Tailscale 주소를 찾지 못했습니다. PC와 휴대폰의 Tailscale 연결을 확인해 주세요.")


def link_connection_info() -> dict:
    return {
        "ok": True,
        "enabled": LINK_SERVER is not None,
        "url": f"http://{LINK_HOST}:{LINK_PORT}/" if LINK_SERVER is not None else None,
        "pin": LINK_PIN if LINK_SERVER is not None else None,
    }


def start_link_server() -> dict:
    global LINK_SERVER, LINK_THREAD, LINK_HOST, LINK_PORT, LINK_PIN, LINK_SESSION
    with LINK_LOCK:
        if LINK_SERVER is not None:
            return link_connection_info()
        host = _tailscale_address()
        pin = f"{secrets.randbelow(1_000_000):06d}"
        server = ThreadingHTTPServer((host, LINK_DEFAULT_PORT), LinkHandler)
        LINK_HOST, LINK_PORT, LINK_PIN = host, int(server.server_address[1]), pin
        LINK_SESSION = secrets.token_urlsafe(32)
        LINK_SERVER = server
        LINK_THREAD = threading.Thread(target=server.serve_forever, name="lakis-link", daemon=True)
        LINK_THREAD.start()
        audit({"event": "lakis_link_started", "port": LINK_PORT})
        return link_connection_info()


def stop_link_server() -> dict:
    global LINK_SERVER, LINK_THREAD, LINK_HOST, LINK_PORT, LINK_PIN, LINK_SESSION
    with LINK_LOCK:
        server, thread = LINK_SERVER, LINK_THREAD
        LINK_SERVER = None; LINK_THREAD = None; LINK_HOST = ""; LINK_PORT = 0; LINK_PIN = ""; LINK_SESSION = ""
    if server is not None:
        server.shutdown(); server.server_close()
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=3)
    LINK_AUTH_FAILURES.clear()
    audit({"event": "lakis_link_stopped"})
    return link_connection_info()



def configured_output_root() -> Path:
    try:
        payload = json.loads(OUTPUT_LOCATION_PATH.read_text(encoding="utf-8"))
        candidate = Path(str(payload.get("path") or "")).expanduser().resolve()
        if candidate.is_dir():
            return candidate
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return OUTPUT_ROOT


def _prompt_graph_metadata(graph: object) -> dict:
    result = {"checkpoint": "확인할 수 없음", "loras": [], "seed": None, "prompt": "", "negative_prompt": ""}
    if not isinstance(graph, dict):
        return result
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        kind = str(node.get("class_type") or "")

        # LAKIS generates from the canonical diffusion-model loader. Auxiliary
        # CheckpointLoaderSimple nodes load SAM segmentation weights and must
        # never be presented as the image-generation checkpoint.
        if kind == "DiffusionModelLoaderKJ" and inputs.get("model_name"):
            result["checkpoint"] = str(inputs["model_name"])

        # Node 1925 is the submission-time snapshot of the user LoRA stack.
        # Fixed internal accelerator/adaptor nodes are implementation details,
        # while rows whose `on` value is false were not applied to this image.
        if kind == "EasyUseAnimaLoraPreset" and isinstance(inputs.get("loras"), str):
            rows = json.loads(inputs["loras"])
            if isinstance(rows, list):
                result["loras"] = [
                    {"name": str(row["name"]), "strength": row.get("strength", 1)}
                    for row in rows
                    if isinstance(row, dict)
                    and row.get("on") is True
                    and row.get("name") not in {None, "", "None"}
                ]

        if result["seed"] is None:
            for key in ("seed", "noise_seed"):
                if isinstance(inputs.get(key), int):
                    result["seed"] = inputs[key]
                    break
        if "promptstudio" in kind.lower() and isinstance(inputs.get("advanced_fields"), str):
            fields = json.loads(inputs["advanced_fields"])
            positive, negative = [], []
            for field in fields if isinstance(fields, list) else []:
                if isinstance(field, dict) and field.get("enabled", True) is not False and field.get("text"):
                    (negative if field.get("pane") == "negative" else positive).append(str(field["text"]))
            result["prompt"] = ", ".join(positive)
            result["negative_prompt"] = ", ".join(negative)
    return result


def _image_prompt_metadata(path: Path) -> dict:
    result = {"checkpoint": "확인할 수 없음", "loras": [], "seed": None, "prompt": "", "negative_prompt": ""}
    if Image is None:
        return result
    try:
        with Image.open(path) as image:
            raw = str(image.getexif().get(272, ""))
        marker = raw.find("prompt:")
        if marker < 0:
            return result
        graph, _ = json.JSONDecoder().raw_decode(raw[marker + 7:])
        result = _prompt_graph_metadata(graph)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return result


def _history_roots() -> list[tuple[str, Path]]:
    configured = configured_output_root().resolve()
    roots = [("configured", configured)]
    default = OUTPUT_ROOT.resolve()
    if default != configured and default.is_dir():
        roots.append(("default", default))
    return roots


def _history_target(item_id: str) -> tuple[Path, Path]:
    value = str(item_id or "")
    if ":" not in value:
        root_key, relative = "configured", value
    else:
        root_key, relative = value.split(":", 1)
    roots = dict(_history_roots())
    root = roots.get(root_key)
    if root is None:
        raise ValueError("invalid history root")
    target = (root / relative).resolve()
    if (target.parent != root and root not in target.parents) or target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("invalid history image")
    return root, target


def image_history() -> dict:
    roots = _history_roots()
    paths = sorted(
        (
            (root_key, root, path)
            for root_key, root in roots
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ),
        key=lambda item: item[2].stat().st_mtime,
        reverse=True,
    )[:300]
    items = []
    for root_key, root, path in paths:
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        item_id = f"{root_key}:{relative}"
        items.append({"id": item_id, "name": path.name, "date": time.strftime("%Y/%m/%d", time.localtime(stat.st_mtime)), "modified": stat.st_mtime, "url": "/api/history-image?id=" + quote(item_id), **_image_prompt_metadata(path)})
    configured = roots[0][1]
    return {
        "ok": True, "root": str(configured), "default_root": str(OUTPUT_ROOT),
        "custom": configured != OUTPUT_ROOT.resolve(), "includes_default_root": len(roots) > 1,
        "items": items,
    }


def delete_history_image(relative: str) -> dict:
    _, target = _history_target(relative)
    if not target.is_file():
        raise FileNotFoundError(target)
    escaped = str(target).replace("'", "''")
    command = "Add-Type -AssemblyName Microsoft.VisualBasic;" + f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('{escaped}',[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)"
    completed = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", command], capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0 or target.exists():
        raise OSError(completed.stderr.strip() or "failed to move image to recycle bin")
    return {"ok": True, "id": str(relative), "recycled": True}


def delete_history_images_batch(values) -> dict:
    if not isinstance(values, list):
        raise ValueError("items must be a list")
    requested = list(dict.fromkeys(str(value or "") for value in values if str(value or "")))
    if not requested:
        raise ValueError("select at least one image")
    current_ids = {str(item["id"]) for item in image_history()["items"]}
    deleted, failed = [], []
    for item_id in requested:
        if item_id not in current_ids:
            failed.append({"id": item_id, "reason": "not a current Library item"})
            continue
        try:
            delete_history_image(item_id)
            deleted.append(item_id)
        except (OSError, ValueError) as error:
            failed.append({"id": item_id, "reason": str(error)[:500]})
    return {"ok": not failed, "requested": len(requested), "deleted": len(deleted),
            "failed": len(failed), "deleted_items": deleted, "failed_items": failed}


def choose_output_root() -> dict:
    command = """
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.ShowInTaskbar = $false; $owner.TopMost = $true; $owner.StartPosition = 'CenterScreen'; $owner.Size = New-Object System.Drawing.Size(1,1); $owner.Opacity = 0
$owner.Show(); $owner.Activate()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'LAKIS 이미지 저장 폴더 선택'
try { if ($dialog.ShowDialog($owner) -eq 'OK') { $dialog.SelectedPath } } finally { $dialog.Dispose(); $owner.Close(); $owner.Dispose() }
"""
    completed = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", command], capture_output=True, text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    selected = completed.stdout.strip()
    if not selected:
        return {"ok": False, "cancelled": True}
    target = Path(selected).resolve()
    target.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_LOCATION_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"path": str(target)}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, OUTPUT_LOCATION_PATH)
    return {"ok": True, "path": str(target), "restart_required": True}


def launcher_identity() -> dict:
    try:
        version = LAKIS_VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"
    return {
        "ok": True,
        "product": "LAKIS",
        "protocol": 1,
        "installation_id": INSTALLATION_ID,
        "install_root": str(INSTALL_ROOT),
        "ui_root": str(UI_ROOT),
        "pid": os.getpid(),
        "port": SERVER_PORT,
        "session_token": SERVER_SESSION_TOKEN,
        "version": version,
    }


def write_ready_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(launcher_identity(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


@lru_cache(maxsize=1)
def load_csv_autocomplete() -> tuple[tuple[str, str, int, str, str], ...]:
    """Load the bundled, popularity-sorted LAKIS tag dictionary once."""
    entries: list[tuple[str, str, int, str]] = []
    if not AUTOCOMPLETE_CSV.is_file():
        return tuple()
    with AUTOCOMPLETE_CSV.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.reader(stream):
            if len(row) < 4 or not row[0].strip():
                continue
            tag, tag_type, count_text, description = row[:4]
            # The 2026-09-07 dictionary uses a prose description followed by
            # `키워드: <분류>, 실제 검색어, ...`. Parse this before the legacy
            # `한글 표시명:` form so the keyword marker itself cannot be
            # mistaken for a display label.
            keyword_match = re.search(r"키워드:\s*(?:<[^>]+>\s*,?\s*)?([^,]+)", description)
            if keyword_match:
                korean_label = keyword_match.group(1).strip()
            else:
                label_match = re.match(r"^\[[^\]]+\]\s*([^:/]{1,48}?)\s*:", description)
                korean_label = label_match.group(1).strip() if label_match else ""
            try:
                count = int(count_text)
            except ValueError:
                count = 0
            section = {"0": "general", "1": "artist", "3": "copyright", "4": "character", "5": "meta"}.get(
                tag_type.strip(), "general"
            )
            entries.append((tag.strip(), korean_label, count, description.strip(), section))
    return tuple(entries)


@lru_cache(maxsize=512)
def csv_tag_suggestions(query: str, limit: int = 12) -> tuple[dict, ...]:
    normalized_text = query.strip().casefold()
    normalized_tag_query = normalized_text.replace(" ", "_")
    if len(normalized_text) < 2:
        return tuple()
    matches = []
    korean_query = bool(KOREAN_PATTERN.search(query))
    for tag, korean_label, count, description, _section in load_csv_autocomplete():
        normalized_tag = normalized_tag_identity(tag)
        matched = normalized_tag.startswith(normalized_tag_identity(normalized_tag_query))
        if korean_query:
            matched = normalized_text in korean_label.casefold() or normalized_text in description.casefold()
        if matched:
            matches.append({
                "tag": tag,
                "ko": korean_label,
                "count": count,
                "description": description,
                "source": "lakis_csv",
            })
            if len(matches) >= limit:
                break
    return tuple(matches)


def normalized_tag_identity(value: object) -> str:
    """Treat spaces, underscores, repeated whitespace and case as one tag."""
    unescaped = re.sub(r"\\([()\[\]{}])", r"\1", str(value or ""))
    return "_".join(unescaped.strip().casefold().replace("_", " ").split())


@lru_cache(maxsize=1)
def csv_tag_lookup() -> dict[str, tuple[str, str, int, str, str]]:
    return {normalized_tag_identity(row[0]): row for row in load_csv_autocomplete()}

try:
    EASYUSE_ANIMA_ROOT = COMFY_ROOT / "custom_nodes" / "comfyui-easyuse-anima"
    if str(EASYUSE_ANIMA_ROOT) not in sys.path:
        sys.path.insert(0, str(EASYUSE_ANIMA_ROOT))
    from easyuse_anima.translation.providers.google import GoogleTranslationProvider
    GOOGLE_TRANSLATOR = GoogleTranslationProvider(timeout_seconds=10.0)
except Exception:
    GOOGLE_TRANSLATOR = None


def translate_korean_text(value: str) -> str:
    """Translate only comma/newline fields containing Hangul, preserving tags."""
    text = str(value or "")
    if not KOREAN_PATTERN.search(text):
        return text
    translated = []
    for part in TRANSLATION_SPLIT_PATTERN.split(text):
        if not part or TRANSLATION_SPLIT_PATTERN.fullmatch(part):
            translated.append(part)
            continue
        if not KOREAN_PATTERN.search(part):
            translated.append(part)
            continue
        leading = part[: len(part) - len(part.lstrip())]
        trailing = part[len(part.rstrip()) :]
        source_text = part.strip()
        translated_body = ""
        provider_error: Exception | None = None
        if GOOGLE_TRANSLATOR is not None:
            try:
                translated_body = GOOGLE_TRANSLATOR.translate(source_text, "auto", "en")
            except Exception as error:
                provider_error = error
        if not translated_body:
            try:
                endpoint = (
                    "https://translate.googleapis.com/translate_a/single"
                    f"?client=gtx&sl=auto&tl=en&dt=t&q={quote(source_text)}"
                )
                request = Request(endpoint, headers={"User-Agent": "LAKIS/7.3.6"})
                with urlopen(request, timeout=10.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                translated_body = "".join(
                    str(segment[0]) for segment in (payload[0] or [])
                    if isinstance(segment, list) and segment
                )
            except Exception as fallback_error:
                raise RuntimeError("Google prompt translation providers failed") from (provider_error or fallback_error)
        if not translated_body:
            raise RuntimeError("Google prompt translation returned an empty result")
        translated.append(leading + html.unescape(translated_body) + trailing)
    return "".join(translated)


def translate_prompt_payload(prompt: object) -> dict:
    if not isinstance(prompt, dict):
        raise ValueError("Invalid prompt payload")
    if sum(len(str(value or "")) for value in prompt.values()) > 20_000:
        raise ValueError("번역할 프롬프트가 너무 깁니다.")
    return {str(key): translate_korean_text(value) for key, value in prompt.items()}


def audit(event: dict) -> None:
    event = {"timestamp": time.time(), **event}
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        # Diagnostics must never turn an otherwise successful UI request into
        # a failure on read-only or protected installations.
        pass


def _replace_upscaler(value: object, selected: str) -> object:
    if isinstance(value, dict):
        return {key: _replace_upscaler(item, selected) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_upscaler(item, selected) for item in value]
    if isinstance(value, str) and value in {REALESRGAN_MODEL, ANIMESHARP_MODEL}:
        return selected
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _ensure_realesrgan_model() -> Path:
    """Install the pinned BSD model outside the legacy updater's protected tree."""
    model_path = COMFY_ROOT / "models" / "upscale_models" / REALESRGAN_MODEL
    if model_path.is_file() and model_path.stat().st_size == REALESRGAN_BYTES:
        if _sha256(model_path) == REALESRGAN_SHA256:
            return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = model_path.with_name(model_path.name + ".lakis-download")
    try:
        if temporary.exists():
            temporary.unlink()
        request = Request(
            REALESRGAN_URL + "?lakis_model=" + str(time.time_ns()),
            headers={
                "User-Agent": "LAKIS/7.3.6",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )
        digest = hashlib.sha256()
        received = 0
        with urlopen(request, timeout=60.0) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > REALESRGAN_BYTES:
                    raise RuntimeError("RealESRGAN 다운로드 크기가 예상보다 큽니다.")
                digest.update(chunk)
                output.write(chunk)
        if received != REALESRGAN_BYTES or digest.hexdigest().upper() != REALESRGAN_SHA256:
            raise RuntimeError("RealESRGAN 파일 검증에 실패했습니다.")
        os.replace(temporary, model_path)
        audit({"event": "realesrgan_model_installed", "bytes": received})
        return model_path
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def save_upscaler_choice(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("올바르지 않은 선택입니다.")
    choice = str(payload.get("choice") or "")
    if choice not in {"realesrgan", "animesharp"}:
        raise ValueError("업스케일러를 선택해 주세요.")
    if choice == "animesharp" and payload.get("acknowledged") is not True:
        raise ValueError("AnimeSharp의 비상업 라이선스에 동의해야 합니다.")
    selected = REALESRGAN_MODEL if choice == "realesrgan" else ANIMESHARP_MODEL
    model_path = COMFY_ROOT / "models" / "upscale_models" / selected
    if choice == "realesrgan":
        model_path = _ensure_realesrgan_model()
    if not model_path.is_file():
        raise FileNotFoundError(f"선택한 업스케일러 파일이 없습니다: {selected}")

    record = {
        "choice": choice,
        "model": selected,
        "license": "BSD-3-Clause" if choice == "realesrgan" else "CC-BY-NC-SA-4.0",
        "noncommercial_acknowledged": choice == "animesharp",
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # This is user preference, not installation data. Persist it first in a
    # per-user writable directory so protected/custom installations do not
    # show the migration screen again after a successful choice.
    UPSCALER_CHOICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = UPSCALER_CHOICE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, UPSCALER_CHOICE_PATH)

    # Older builds allowed this field to be stored as a generic advanced
    # override.  Remove it when the user confirms a licence-aware choice so it
    # cannot conflict on this or a later launch.
    override_removed = False
    override_error = None
    try:
        override_removed = remove_persisted_upscaler_override()
    except OSError as error:
        # Runtime generation independently rejects this protected override, so
        # a temporarily locked state file must not undo an otherwise valid
        # licence choice or keep the migration dialog open.
        override_error = repr(error)

    changed = []
    write_errors = []
    for name in ("LAKIS_runtime_api_v7.4.json", "LAKIS_runtime_visual_v7.4.json"):
        path = PACKAGED_WORKFLOW_ROOT / name
        if not path.is_file():
            continue
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            updated = _replace_upscaler(workflow, selected)
            workflow_temporary = path.with_suffix(path.suffix + ".tmp")
            workflow_temporary.write_text(json.dumps(updated, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(workflow_temporary, path)
            changed.append(name)
        except OSError as error:
            write_errors.append({"workflow": name, "error": repr(error)})

    audit({"event": "upscaler_license_choice_saved", "choice": choice, "workflows": changed,
           "write_errors": write_errors, "advanced_override_removed": override_removed,
           "advanced_override_error": override_error})
    return {"ok": True, "choice": choice, "model": selected, "workflows": changed,
            "runtime_applied": True, "advanced_override_removed": override_removed}


def open_output_folder() -> int:
    output_root = configured_output_root()
    if not output_root.is_dir():
        raise RuntimeError(f"Output path does not exist: {output_root}")
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    if not explorer.is_file():
        raise FileNotFoundError(explorer)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(explorer), str(output_root)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        cwd=str(COMFY_ROOT),
    )
    audit({
        "event": "external_ui_open_output_folder",
        "pid": process.pid,
        "executable": str(explorer),
        "command_line": [str(explorer), str(output_root)],
        "parent_pid": os.getpid(),
        "target": str(output_root),
    })
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        audit({
            "event": "external_ui_explorer_still_running",
            "pid": process.pid,
            "action": "left_running_as_user_requested",
        })
    return process.pid


def open_legal_document(document: str) -> dict:
    allowed = {
        "license": INSTALL_ROOT / "LICENSE.md",
        "third-party": INSTALL_ROOT / "THIRD_PARTY_NOTICES.md",
        "lllite-inpaint": LLLITE_INPAINT_LICENSE_PATH,
    }
    path = allowed.get(document)
    allowed_roots = {INSTALL_ROOT, (INSTALL_ROOT / "third_party_licenses").resolve()}
    if path is None or not path.is_file() or path.parent.resolve() not in allowed_roots:
        raise FileNotFoundError("라이선스 문서를 찾을 수 없습니다.")
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "document": document}


def save_source_image(data_url: object, stem: str = "LAKIS_i2i_input") -> dict:
    match = I2I_DATA_PATTERN.fullmatch(str(data_url or ""))
    if not match:
        raise ValueError("PNG, JPEG 또는 WebP 이미지만 사용할 수 있어요.")
    try:
        payload = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("입력 이미지 데이터가 올바르지 않아요.") from error
    if not payload or len(payload) > 32 * 1024 * 1024:
        raise ValueError("입력 이미지는 32MB 이하여야 해요.")
    extension = "jpg" if match.group(1) == "jpeg" else match.group(1)
    signatures = {
        "png": payload.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": payload.startswith(b"\xff\xd8\xff"),
        "webp": payload.startswith(b"RIFF") and payload[8:12] == b"WEBP",
    }
    if not signatures[extension]:
        raise ValueError("파일 내용이 선택한 이미지 형식과 일치하지 않아요.")
    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    target = INPUT_ROOT / f"{stem}.{extension}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, target)
    return {"ok": True, "image_name": target.name, "bytes": len(payload)}


def save_i2i_image(data_url: object) -> dict:
    return save_source_image(data_url, "LAKIS_i2i_input")


def save_inpaint_image(data_url: object) -> dict:
    return save_source_image(data_url, "LAKIS_inpaint_input")


def save_inpaint_mask(data_url: object) -> dict:
    match = I2I_DATA_PATTERN.fullmatch(str(data_url or ""))
    if not match or match.group(1) != "png":
        raise ValueError("인페인트 마스크는 PNG 형식이어야 해요.")
    try:
        payload = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("인페인트 마스크 데이터가 올바르지 않아요.") from error
    if not payload or len(payload) > 32 * 1024 * 1024 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("인페인트 마스크 데이터가 올바르지 않아요.")
    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    target = INPUT_ROOT / "LAKIS_inpaint_mask.png"
    temporary = target.with_suffix(".png.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, target)
    mask_info = {"mask_ratio": None, "mask_bbox": None, "large_edit": False}
    if Image is not None:
        try:
            with Image.open(target) as loaded:
                mask = loaded.convert("L")
                bbox = mask.getbbox()
                if bbox is None:
                    raise ValueError("수정할 영역을 칠해 주세요.")
                histogram = mask.histogram()
                active_pixels = sum(histogram[1:])
                ratio = active_pixels / max(1, mask.width * mask.height)
                mask_info = {
                    "mask_ratio": round(ratio, 6),
                    "mask_bbox": {"x": bbox[0], "y": bbox[1], "width": bbox[2] - bbox[0], "height": bbox[3] - bbox[1]},
                    "large_edit": ratio >= 0.35,
                }
        except ValueError:
            target.unlink(missing_ok=True)
            raise
    return {"ok": True, "image_name": target.name, "bytes": len(payload), **mask_info}


def workflow_version() -> str:
    versions = []
    for path in WORKFLOW_ROOT.glob("LAKIS_custom_v*.json"):
        raw = path.stem.rsplit("_v", 1)[-1]
        try:
            versions.append((tuple(int(part) for part in raw.split(".")), raw))
        except ValueError:
            continue
    return max(versions)[1] if versions else "unknown"


def _workflow_sort_key(path: Path) -> tuple[int, ...]:
    raw = path.stem.rsplit("_v", 1)[-1]
    try:
        return tuple(int(part) for part in raw.split("."))
    except ValueError:
        return ()


def resolve_lakis_workflow(kind: str = "runtime") -> tuple[Path, dict]:
    """Return the packaged workflow selected by the sidebar."""
    if kind == "editable":
        candidates = [EDITABLE_LAKIS_WORKFLOW, WORKFLOW_ROOT / "LAKIS_custom_v7.1_fullsync_review.json"]
    elif kind == "runtime":
        # The monitor must never fall back to a user-editable workflow.
        candidates = [RUNTIME_LAKIS_WORKFLOW]
    else:
        raise ValueError("Unknown workflow kind")
    seen: set[Path] = set()
    errors = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            allowed_roots = {WORKFLOW_ROOT.resolve(), PACKAGED_WORKFLOW_ROOT.resolve()}
            if not candidate.is_file() or candidate.parent.resolve() not in allowed_roots:
                continue
            workflow = json.loads(candidate.read_text(encoding="utf-8-sig"))
            if kind == "runtime":
                valid = isinstance(workflow, dict) and bool(workflow) and all(
                    isinstance(node, dict) and isinstance(node.get("class_type"), str)
                    for node in workflow.values()
                )
            else:
                valid = isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list)
            if valid:
                return candidate, workflow
            errors.append(f"{candidate.name}: invalid workflow structure")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{candidate.name}: {error}")
    detail = "; ".join(errors) if errors else "no LAKIS_custom_v*.json files found"
    raise FileNotFoundError(f"No valid LAKIS workflow in {WORKFLOW_ROOT}: {detail}")


def lakis_version() -> str:
    try:
        value = LAKIS_VERSION_PATH.read_text(encoding="utf-8-sig").strip()
        if value and all(part.isdigit() for part in value.split(".")):
            return value
    except OSError:
        pass
    return workflow_version()


def system_status() -> dict:
    comfy_stats = None
    try:
        with urlopen(COMFY_SERVER + "/system_stats", timeout=1.5) as response:
            comfy_stats = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        pass
    system = (comfy_stats or {}).get("system", {})
    devices = (comfy_stats or {}).get("devices", [])
    device = devices[0] if devices else {}
    ram_total = int(system.get("ram_total") or 0)
    ram_free = int(system.get("ram_free") or 0)
    cpu_percent = None
    if psutil is not None:
        memory = psutil.virtual_memory()
        ram_total = int(memory.total)
        ram_free = int(memory.available)
        cpu_percent = float(psutil.cpu_percent(interval=None))
    return {
        "lakis_version": lakis_version(),
        "workflow_version": workflow_version(),
        "comfyui_running": comfy_stats is not None,
        "vram_total": int(device.get("vram_total") or 0),
        "vram_free": int(device.get("vram_free") or 0),
        "ram_total": ram_total,
        "ram_free": ram_free,
        "cpu_percent": cpu_percent,
        "generation": GENERATION_BRIDGE.status.snapshot(),
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_ROOT), **kwargs)

    def _prepare_lakis_workflow(self, kind: str = "runtime") -> dict:
        workflow_path, workflow = resolve_lakis_workflow(kind)
        display_name = RUNTIME_LAKIS_SOURCE_NAME if kind == "runtime" else workflow_path.name
        saved_choice = upscaler_choice_status().get("choice")
        selected = REALESRGAN_MODEL if saved_choice == "realesrgan" else ANIMESHARP_MODEL if saved_choice == "animesharp" else None
        if selected:
            workflow = _replace_upscaler(workflow, selected)
        AUTOPATCH_MARKER.parent.mkdir(parents=True, exist_ok=True)
        temporary = AUTOPATCH_MARKER.with_suffix(".tmp")
        marker = {
            "lakis_autopatch": {
                "display_name": display_name,
                "format": "api" if kind == "runtime" else "workflow",
            },
            "workflow": workflow,
        }
        temporary.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, AUTOPATCH_MARKER)
        node_count = len(workflow.get("nodes", workflow))
        audit({
            "event": "external_ui_workflow_open_prepared",
            "kind": kind,
            "workflow": str(workflow_path),
            "display_name": display_name,
            "marker": str(AUTOPATCH_MARKER),
            "node_count": node_count,
        })
        return {
            "ok": True,
            "comfy_url": COMFY_SERVER + "/",
            "workflow_kind": kind,
            "workflow_name": display_name,
            "node_count": node_count,
        }

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/api/inpaint-model-notice":
            self._send_json(200, inpaint_model_notice_status())
            return
        if urlparse(self.path).path == "/api/lllite-weight-status":
            try:
                self._send_json(200, lllite_inpaint_weight_status())
            except Exception as error:
                self._send_json(503, {"ok": False, "valid": False, "error": str(error)})
            return
        if urlparse(self.path).path == "/api/image-history":
            self._send_json(200, image_history())
            return
        if urlparse(self.path).path == "/api/history-image":
            relative = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            try:
                _, target = _history_target(relative)
                payload = target.read_bytes()
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(target.suffix.lower())
                if not mime:
                    raise ValueError("unsupported image")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (OSError, ValueError):
                self.send_error(404)
            return
        if urlparse(self.path).path == "/api/comfy-view":
            query = parse_qs(urlparse(self.path).query)
            filename = query.get("filename", [""])[0]
            subfolder = query.get("subfolder", [""])[0]
            image_type = query.get("type", ["output"])[0]
            try:
                if not filename or image_type not in {"output", "temp", "input"}:
                    raise ValueError("invalid ComfyUI image request")
                upstream_query = urlencode({
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": image_type,
                })
                request = Request(
                    COMFY_SERVER + "/view?" + upstream_query,
                    headers={"Accept": "image/png,image/jpeg,image/webp"},
                )
                with urlopen(request, timeout=15.0) as response:
                    payload = response.read(45_000_001)
                    mime = str(response.headers.get_content_type() or "")
                if not payload or len(payload) > 45_000_000 or mime not in {"image/png", "image/jpeg", "image/webp"}:
                    raise ValueError("invalid ComfyUI image response")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (OSError, URLError, ValueError):
                self.send_error(404)
            return
        if urlparse(self.path).path == "/api/dev-revision":
            frontend_patterns = ("*.html", "*.js", "*.css")
            revision = 0
            if DEVELOPMENT:
                revision = max(
                    (path.stat().st_mtime_ns for pattern in frontend_patterns for path in UI_ROOT.glob(pattern)),
                    default=0,
                )
            self._send_json(200, {
                "ok": True, "development": DEVELOPMENT, "revision": str(revision),
                "bridge_import_path": str(Path(__import__("workflow_bridge").__file__).resolve()),
                "local_inpaint_v2": LOCAL_INPAINT_V2,
            })
            return
        if urlparse(self.path).path == "/api/launcher-identity":
            self._send_json(200, launcher_identity())
            return
        if self.path == "/api/upscaler-license-choice":
            self._send_json(200, upscaler_choice_status())
            return
        if self.path.startswith("/api/tag-suggestions"):
            query = parse_qs(urlparse(self.path).query).get("q", [""])[0][:100]
            csv_results = list(csv_tag_suggestions(query, 12))
            try:
                with urlopen(
                    COMFY_SERVER + "/easyuse_anima/autocomplete?q=" + quote(query) + "&limit=12",
                    timeout=3.0,
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                remote_results = payload.get("results", payload.get("items", []))
                suggestions = []
                known = set()
                for item in csv_results + list(remote_results):
                    if not isinstance(item, dict) or not item.get("tag"):
                        continue
                    identity = normalized_tag_identity(item["tag"])
                    if not identity or identity in known:
                        continue
                    known.add(identity)
                    suggestions.append(item)
                self._send_json(200, {"ok": True, "suggestions": suggestions[:12], "source": "lakis_csv"})
            except Exception as error:
                audit({"event": "external_ui_autocomplete_failed", "error": repr(error)})
                self._send_json(200, {"ok": True, "suggestions": csv_results, "source": "lakis_csv"})
            return
        if self.path == "/api/workflow-config":
            self._send_json(200, workflow_configuration())
            return
        if self.path == "/api/prompt-state":
            self._send_json(200, {"ok": True, **load_external_prompt_bundle()})
            return
        if self.path == "/api/wildcards":
            self._send_json(200, wildcard_inventory())
            return
        if self.path == "/api/lora-options":
            self._send_json(200, lora_inventory())
            return
        if self.path == "/api/model-options":
            self._send_json(200, model_inventory())
            return
        if self.path == "/api/generation-status":
            self._send_json(200, GENERATION_BRIDGE.status.snapshot())
            return
        if self.path.startswith("/api/generation-preview"):
            payload, mime, revision = GENERATION_BRIDGE.preview_snapshot()
            if payload is None:
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-LAKIS-Preview-Revision", str(revision))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if urlparse(self.path).path == "/api/lakis-link-info":
            self._send_json(200, link_connection_info())
            return
        if self.path != "/api/status":
            super().do_GET()
            return
        self._send_json(200, system_status())

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, max_size: int = 1_000_000) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > max_size:
            raise ValueError("Invalid request size")
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/inpaint-model-notice":
            try:
                self._send_json(200, acknowledge_inpaint_model_notice(self._read_json()))
            except Exception as error:
                self._send_json(400, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/lakis-link-control":
            try:
                action = str(self._read_json().get("action") or "status")
                if action == "start":
                    result = start_link_server()
                elif action == "stop":
                    result = stop_link_server()
                elif action == "status":
                    result = link_connection_info()
                else:
                    raise ValueError("지원하지 않는 LAKIS Link 작업입니다.")
                self._send_json(200, result)
            except Exception as error:
                audit({"event": "lakis_link_control_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/delete-history-image":
            try:
                incoming = self._read_json()
                self._send_json(200, delete_history_image(str(incoming.get("id") or "")))
            except (OSError, ValueError) as error:
                audit({"event": "image_history_delete_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": "선택한 이미지를 휴지통으로 보내지 못했어요."})
            return
        if self.path == "/api/delete-history-images-batch":
            try:
                incoming = self._read_json()
                result = delete_history_images_batch(incoming.get("items"))
                self._send_json(200, result)
            except (OSError, ValueError) as error:
                audit({"event": "image_history_batch_delete_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": "선택한 이미지를 휴지통으로 보내지 못했어요."})
            return
        if self.path == "/api/choose-output-folder":
            try:
                self._read_json()
                self._send_json(200, choose_output_root())
            except Exception as error:
                audit({"event": "output_folder_choice_failed", "error": repr(error)})
                self._send_json(500, {"ok": False, "error": "저장 경로를 변경하지 못했어요."})
            return
        if self.path == "/api/warmup":
            try:
                self._read_json()
                self._send_json(200, GENERATION_BRIDGE.warmup())
            except Exception as error:
                audit({"event": "external_ui_warmup_request_failed", "error": repr(error)})
                # Warmup is an optimization. Its failure must never prevent LAKIS startup.
                self._send_json(200, {"ok": False, "status": "failed", "error": str(error)})
            return
        if self.path == "/api/open-legal-document":
            try:
                incoming = self._read_json()
                self._send_json(200, open_legal_document(str(incoming.get("document") or "")))
            except Exception as error:
                audit({"event": "external_ui_legal_document_open_failed", "error": repr(error)})
                self._send_json(404, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/upscaler-license-choice":
            try:
                self._send_json(200, save_upscaler_choice(self._read_json()))
            except Exception as error:
                audit({"event": "upscaler_license_choice_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/i2i-image":
            try:
                result = save_i2i_image(self._read_json(45_000_000).get("data_url"))
                self._send_json(200, result)
            except Exception as error:
                audit({"event": "external_ui_i2i_upload_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/inpaint-mask":
            try:
                result = save_inpaint_mask(self._read_json(45_000_000).get("data_url"))
                self._send_json(200, result)
            except Exception as error:
                audit({"event": "external_ui_inpaint_mask_upload_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/inpaint-image":
            try:
                result = save_inpaint_image(self._read_json(45_000_000).get("data_url"))
                self._send_json(200, result)
            except Exception as error:
                audit({"event": "external_ui_inpaint_image_upload_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/open-workflow":
            try:
                incoming = self._read_json()
                self._send_json(200, self._prepare_lakis_workflow(str(incoming.get("kind") or "runtime")))
            except Exception as error:
                audit({"event": "external_ui_workflow_open_failed", "error": repr(error)})
                self._send_json(500, {"ok": False, "error": "LAKIS 워크플로를 준비하지 못했어요."})
            return
        if self.path == "/api/classify-prompt":
            try:
                incoming = self._read_json()
                text = str(incoming.get("text") or "")
                request_body = json.dumps({"text": text, "limit": 500}).encode("utf-8")
                request = Request(
                    COMFY_SERVER + "/easyuse_anima/classify_prompt",
                    data=request_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5.0) as response:
                    result = json.loads(response.read().decode("utf-8"))
                tokens = result.get("tokens", []) if isinstance(result, dict) else []
                lookup = csv_tag_lookup()
                for token in tokens:
                    if not isinstance(token, dict) or token.get("section") not in {None, "", "unknown"}:
                        continue
                    identity = normalized_tag_identity(token.get("base") or token.get("token"))
                    match = lookup.get(identity)
                    if not match:
                        continue
                    tag, korean_label, count, description, section = match
                    token.update({
                        "base": re.sub(r"\\([()\[\]{}])", r"\1", tag),
                        "section": section,
                        "label": korean_label or section,
                        "learned": True,
                        "count": count,
                        "description": description,
                        "source": "lakis_csv",
                    })
                self._send_json(200, {
                    "ok": True,
                    "tokens": tokens,
                })
            except Exception as error:
                audit({"event": "external_ui_prompt_classify_failed", "error": repr(error)})
                self._send_json(503, {"ok": False, "tokens": [], "error": "태그 판별 서비스를 사용할 수 없어요."})
            return
        if self.path == "/api/translate-prompt":
            try:
                translated = translate_prompt_payload(self._read_json().get("prompt"))
                self._send_json(200, {"ok": True, "prompt": translated})
            except Exception as error:
                audit({"event": "external_ui_prompt_translation_failed", "error": repr(error)})
                self._send_json(503, {
                    "ok": False,
                    "error": "프롬프트를 영어로 번역하지 못했어요. 인터넷 연결을 확인해 주세요.",
                })
            return
        if self.path == "/api/resolve-wildcards":
            try:
                self._send_json(200, resolve_wildcard_payload(self._read_json()))
            except Exception as error:
                audit({"event": "external_ui_wildcard_resolve_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/open-wildcard-folder":
            try:
                USER_WILDCARD_ROOT.mkdir(parents=True, exist_ok=True)
                _open_folder_foreground(USER_WILDCARD_ROOT)
                self._send_json(200, {"ok": True})
            except Exception as error:
                self._send_json(500, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/open-lllite-model-folder":
            try:
                model_folder = lllite_model_folder()
                _open_folder_foreground(model_folder)
                self._send_json(200, {"ok": True})
            except Exception as error:
                self._send_json(500, {"ok": False, "error": str(error)})
            return
        if self.path == "/api/prompt-state":
            try:
                incoming = self._read_json()
                saved = save_external_prompt_state(
                    incoming.get("prompt"), incoming.get("prompt_enabled"),
                    incoming.get("inpaint_prompt"), incoming.get("translation_enabled"),
                    incoming.get("prompt_ui"),
                )
                self._send_json(200, {"ok": True, **saved})
            except Exception as error:
                audit({"event": "external_ui_prompt_state_save_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": "프롬프트 상태를 저장하지 못했어요."})
            return
        if self.path == "/api/generation-state":
            try:
                incoming = self._read_json()
                saved = save_external_generation_state(
                    incoming.get("model"), incoming.get("output"),
                    incoming.get("loras"), incoming.get("lora_enabled", True),
                    incoming.get("node_overrides"),
                    incoming.get("generation"),
                    incoming.get("camera"),
                    incoming.get("composition_enabled", True),
                    incoming.get("wildcard_enabled", False),
                )
                self._send_json(200, {"ok": True, **saved})
            except Exception as error:
                audit({"event": "external_ui_generation_state_save_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": "모델 설정을 저장하지 못했어요."})
            return
        if self.path == "/api/generate":
            incoming = self._read_json()
            try:
                inpaint = incoming.get("inpaint") if isinstance(incoming.get("inpaint"), dict) else {}
                if bool(inpaint.get("enabled")):
                    weight = lllite_inpaint_weight_status()
                    if not weight["valid"]:
                        self._send_json(409, {
                            **weight,
                            "ok": False,
                            "error_code": "LAKIS_LLLITE_WEIGHT_REQUIRED",
                            "error_stage": "요청 검증",
                            "error": "Anima LLLite Inpainting 모델을 공식 배포처에서 직접 설치해 주세요.",
                        })
                        return
                result = GENERATION_BRIDGE.start(incoming)
                self._send_json(202, result)
            except FileExistsError as error:
                audit({"event": "external_ui_generate_allowance_conflict", "error": repr(error)})
                self._send_json(409, {
                    "ok": False,
                    "error": "다른 생성 요청이 준비 중입니다. 잠시 후 다시 시도해 주세요.",
                    "error_code": "LKS-GEN-1010",
                    "error_stage": "생성 요청 준비",
                    "error_node_id": None,
                    "error_node_type": None,
                    "setting_diagnostic": None,
                    "diagnostic_context": GENERATION_BRIDGE._diagnostic_context(incoming),
                    "request_id": None,
                })
            except Exception as error:
                audit({"event": "external_ui_generate_rejected", "error": repr(error)})
                error_code, public_message = GENERATION_BRIDGE._public_error(error)
                self._send_json(409, {
                    "ok": False, "error": public_message, "error_code": error_code,
                    "error_detail": str(error)[:1000],
                    "error_stage": "요청 검증",
                    "error_node_id": getattr(error, "node_id", None),
                    "error_node_type": getattr(error, "node_type", None),
                    "setting_diagnostic": error.diagnostic() if hasattr(error, "diagnostic") else None,
                    "diagnostic_context": GENERATION_BRIDGE._diagnostic_context(incoming),
                    "request_id": None,
                })
            return
        if self.path == "/api/cancel":
            try:
                self._send_json(200, GENERATION_BRIDGE.cancel())
            except Exception as error:
                audit({"event": "external_ui_cancel_failed", "error": repr(error)})
                self._send_json(500, {"ok": False, "error": str(error)})
            return
        parsed_path = urlparse(self.path).path
        if parsed_path != "/api/open-output-folder":
            if parsed_path == "/api/lllite-weight-status":
                try:
                    self._send_json(200, lllite_inpaint_weight_status())
                except Exception as error:
                    self._send_json(500, {"ok": False, "error": str(error)})
                return
            self.send_error(404)
            return
        try:
            pid = open_output_folder()
            self._send_json(200, {"ok": True, "pid": pid})
        except Exception as error:  # fail closed and report only the local error
            audit({"event": "external_ui_open_output_folder_failed", "error": repr(error)})
            self._send_json(500, {"ok": False, "error": str(error)})


class LinkHandler(Handler):
    server_version = "LAKIS-Link"

    def _authorized(self) -> bool:
        if not LINK_SESSION:
            return False
        cookie = self.headers.get("Cookie", "")
        return any(part.strip() == f"lakis_link={LINK_SESSION}" for part in cookie.split(";"))

    def _login_page(self, failed: bool = False) -> None:
        message = "PIN이 올바르지 않습니다." if failed else "PC의 LAKIS Link PIN을 입력하세요."
        body = f"""<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"theme-color\" content=\"#0b0d14\"><title>LAKIS Link</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0d14;color:#fff;font-family:system-ui}}main{{width:min(360px,calc(100% - 40px));padding:28px;border:1px solid #4f437d;border-radius:18px;background:#151925}}h1{{margin:0 0 8px}}p,small{{color:#aeb4c3}}input,button{{box-sizing:border-box;width:100%;min-height:48px;margin-top:12px;border-radius:10px;border:1px solid #454b60;background:#0e111a;color:#fff;padding:10px}}button{{background:#44348f;font-weight:700}}</style></head><body><main><h1>LAKIS Link</h1><p>{html.escape(message)}</p><form method=\"post\" action=\"/link-login\"><input name=\"pin\" type=\"password\" inputmode=\"numeric\" pattern=\"[0-9]*\" maxlength=\"6\" autocomplete=\"one-time-code\" autofocus required><button>연결하기</button></form><small>같은 Tailscale 네트워크에 연결된 기기에서 사용해 주세요.</small></main></body></html>""".encode("utf-8")
        self.send_response(401 if failed else 200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/link-login": self._login_page(); return
        if not self._authorized(): self._login_page(); return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/link-login":
            size = min(int(self.headers.get("Content-Length", "0")), 1024)
            form = parse_qs(self.rfile.read(size).decode("utf-8", errors="replace"))
            client = self.client_address[0]; now = time.monotonic()
            recent = [stamp for stamp in LINK_AUTH_FAILURES.get(client, []) if now - stamp < 600]
            if len(recent) >= 5:
                body = "Too many login attempts. Try again later.".encode("utf-8")
                self.send_response(429); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.send_header("Retry-After", "600"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if str(form.get("pin", [""])[0]) != LINK_PIN:
                recent.append(now); LINK_AUTH_FAILURES[client] = recent; self._login_page(True); return
            LINK_AUTH_FAILURES.pop(client, None)
            self.send_response(303); self.send_header("Location", "/"); self.send_header("Cache-Control", "no-store"); self.send_header("Set-Cookie", f"lakis_link={LINK_SESSION}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400"); self.end_headers(); return
        if not self._authorized(): self.send_error(401); return
        super().do_POST()


def run_server(port: int, session_token: str, ready_file: Path | None = None) -> None:
    global SERVER_PORT, SERVER_SESSION_TOKEN
    SERVER_SESSION_TOKEN = session_token
    server = ThreadingHTTPServer((HOST, port), Handler)
    SERVER_PORT = int(server.server_address[1])
    if ready_file is not None:
        write_ready_file(ready_file)
    print(f"LAKIS UI: http://{HOST}:{SERVER_PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        if LINK_SERVER is not None:
            stop_link_server()
        server.server_close()
        if ready_file is not None:
            try:
                payload = json.loads(ready_file.read_text(encoding="utf-8"))
                if payload.get("session_token") == session_token:
                    ready_file.unlink(missing_ok=True)
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the LAKIS desktop UI")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--session-token", default="")
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    run_server(args.port, args.session_token, args.ready_file)


if __name__ == "__main__":
    main()
