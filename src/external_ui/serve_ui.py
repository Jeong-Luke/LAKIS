"""Serve the LAKIS prototype and expose a narrowly scoped Explorer bridge."""

from __future__ import annotations

import argparse
import html
import base64
import binascii
import csv
from functools import lru_cache
import hashlib
import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, quote, urlparse

UI_ROOT = Path(__file__).resolve().parent
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from workflow_bridge import (
    WorkflowBridge,
    remove_persisted_upscaler_override,
    save_external_generation_state,
    save_external_prompt_state,
    upscaler_choice_status,
    workflow_configuration,
)

try:
    import psutil
except ImportError:  # optional in prototype runtime
    psutil = None


COMFY_ROOT = UI_ROOT.parents[1].resolve()
INSTALL_ROOT = COMFY_ROOT.parent.resolve()
USER_STATE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(INSTALL_ROOT))) / "LAKIS Studio"
UPSCALER_CHOICE_PATH = USER_STATE_ROOT / "upscaler-license-choice.json"
LEGACY_UPSCALER_CHOICE_PATH = INSTALL_ROOT / ".lakis" / "upscaler-license-choice.json"
REALESRGAN_MODEL = "RealESRGAN_x4plus_anime_6B.pth"
REALESRGAN_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
REALESRGAN_SHA256 = "F872D837D3C90ED2E05227BED711AF5671A6FD1C9F7D7E91C911A61F155E99DA"
REALESRGAN_BYTES = 17_938_799
ANIMESHARP_MODEL = "2x-AnimeSharpV4_Fast_RCAN_PU.safetensors"
LAKIS_VERSION_PATH = COMFY_ROOT.parent / "VERSION"
OUTPUT_ROOT = (COMFY_ROOT / "output").resolve()
INPUT_ROOT = (COMFY_ROOT / "input").resolve()
AUDIT_PATH = COMFY_ROOT / "LAKIS_DEV" / "process_audit.jsonl"
HOST = "127.0.0.1"
PORT = 8766
COMFY_SERVER = "http://127.0.0.1:8189"
WORKFLOW_ROOT = COMFY_ROOT / "user" / "default" / "workflows"
PACKAGED_WORKFLOW_ROOT = COMFY_ROOT / "LAKIS" / "workflows"
PREFERRED_LAKIS_WORKFLOW = WORKFLOW_ROOT / "LAKIS_custom_v7.1.json"
RUNTIME_LAKIS_WORKFLOW = PACKAGED_WORKFLOW_ROOT / "LAKIS_runtime_visual_v7.1.json"
EDITABLE_LAKIS_WORKFLOW = PACKAGED_WORKFLOW_ROOT / "LAKIS_custom_v7.1_editable.json"
AUTOPATCH_MARKER = COMFY_ROOT / "custom_nodes" / "ComfyUI-LAKIS-AutoPatch" / "startup_workflow.json"
GENERATION_BRIDGE = WorkflowBridge()
KOREAN_PATTERN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
TRANSLATION_SPLIT_PATTERN = re.compile(r"([,\n]+)")
I2I_DATA_PATTERN = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)$")
AUTOCOMPLETE_CSV = UI_ROOT / "data" / "autocomplete.csv"
INSTALLATION_ID = hashlib.sha256(
    os.path.normcase(str(INSTALL_ROOT.resolve())).encode("utf-8")
).hexdigest()
SERVER_SESSION_TOKEN = ""
SERVER_PORT = PORT


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
def load_csv_autocomplete() -> tuple[tuple[str, str, int, str], ...]:
    """Load the bundled, popularity-sorted LAKIS tag dictionary once."""
    entries: list[tuple[str, str, int, str]] = []
    if not AUTOCOMPLETE_CSV.is_file():
        return tuple()
    with AUTOCOMPLETE_CSV.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.reader(stream):
            if len(row) < 4 or not row[0].strip():
                continue
            tag, _tag_type, count_text, description = row[:4]
            label_match = re.match(r"^\[[^\]]+\]\s*([^:/]{1,48}?)\s*:", description)
            korean_label = label_match.group(1).strip() if label_match else ""
            try:
                count = int(count_text)
            except ValueError:
                count = 0
            entries.append((tag.strip(), korean_label, count, description.strip()))
    return tuple(entries)


@lru_cache(maxsize=512)
def csv_tag_suggestions(query: str, limit: int = 12) -> tuple[dict, ...]:
    normalized = query.strip().casefold().replace(" ", "_")
    if len(normalized) < 2:
        return tuple()
    matches = []
    for tag, korean_label, count, description in load_csv_autocomplete():
        if tag.casefold().startswith(normalized):
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
                request = Request(endpoint, headers={"User-Agent": "LAKIS/7.2.4"})
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
                "User-Agent": "LAKIS/7.2.4",
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
    for name in ("LAKIS_runtime_api_v7.1.json", "LAKIS_runtime_visual_v7.1.json"):
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
    if not OUTPUT_ROOT.is_dir() or OUTPUT_ROOT.parent != COMFY_ROOT:
        raise RuntimeError(f"Refusing unexpected output path: {OUTPUT_ROOT}")
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    if not explorer.is_file():
        raise FileNotFoundError(explorer)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(explorer), str(OUTPUT_ROOT)],
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
        "command_line": [str(explorer), str(OUTPUT_ROOT)],
        "parent_pid": os.getpid(),
        "target": str(OUTPUT_ROOT),
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
    }
    path = allowed.get(document)
    if path is None or not path.is_file() or path.parent.resolve() != INSTALL_ROOT:
        raise FileNotFoundError("라이선스 문서를 찾을 수 없습니다.")
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "document": document}


def save_i2i_image(data_url: object) -> dict:
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
    target = INPUT_ROOT / f"LAKIS_i2i_input.{extension}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, target)
    return {"ok": True, "image_name": target.name, "bytes": len(payload)}


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
    """Return the preferred or newest valid editable workflow without overwriting user data."""
    if kind == "editable":
        candidates = [EDITABLE_LAKIS_WORKFLOW, WORKFLOW_ROOT / "LAKIS_custom_v7.1_fullsync_review.json"]
    elif kind == "runtime":
        candidates = [RUNTIME_LAKIS_WORKFLOW, PREFERRED_LAKIS_WORKFLOW]
        candidates.extend(
            path for path in sorted(WORKFLOW_ROOT.glob("LAKIS_custom_v*.json"), key=_workflow_sort_key, reverse=True)
            if "editable" not in path.stem and "fullsync_review" not in path.stem
        )
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
            if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list):
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
        saved_choice = upscaler_choice_status().get("choice")
        selected = REALESRGAN_MODEL if saved_choice == "realesrgan" else ANIMESHARP_MODEL if saved_choice == "animesharp" else None
        if selected:
            workflow = _replace_upscaler(workflow, selected)
        AUTOPATCH_MARKER.parent.mkdir(parents=True, exist_ok=True)
        temporary = AUTOPATCH_MARKER.with_suffix(".tmp")
        temporary.write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, AUTOPATCH_MARKER)
        audit({
            "event": "external_ui_workflow_open_prepared",
            "kind": kind,
            "workflow": str(workflow_path),
            "marker": str(AUTOPATCH_MARKER),
            "node_count": len(workflow["nodes"]),
        })
        return {
            "ok": True,
            "comfy_url": COMFY_SERVER + "/",
            "workflow_kind": kind,
            "workflow_name": workflow_path.name,
            "node_count": len(workflow["nodes"]),
        }

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
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
                known = {item["tag"] for item in csv_results}
                suggestions = csv_results + [
                    item for item in remote_results
                    if isinstance(item, dict) and item.get("tag") not in known
                ]
                self._send_json(200, {"ok": True, "suggestions": suggestions[:12], "source": "lakis_csv"})
            except Exception as error:
                audit({"event": "external_ui_autocomplete_failed", "error": repr(error)})
                self._send_json(200, {"ok": True, "suggestions": csv_results, "source": "lakis_csv"})
            return
        if self.path == "/api/workflow-config":
            self._send_json(200, workflow_configuration())
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
                self._send_json(200, {
                    "ok": True,
                    "tokens": result.get("tokens", []) if isinstance(result, dict) else [],
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
        if self.path == "/api/prompt-state":
            try:
                saved = save_external_prompt_state(self._read_json().get("prompt"))
                self._send_json(200, {"ok": True, "prompt": saved})
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
                )
                self._send_json(200, {"ok": True, **saved})
            except Exception as error:
                audit({"event": "external_ui_generation_state_save_failed", "error": repr(error)})
                self._send_json(400, {"ok": False, "error": "모델 설정을 저장하지 못했어요."})
            return
        if self.path == "/api/generate":
            try:
                result = GENERATION_BRIDGE.start(self._read_json())
                self._send_json(202, result)
            except FileExistsError:
                self._send_json(409, {"ok": False, "error": "One-shot authorization already exists"})
            except Exception as error:
                audit({"event": "external_ui_generate_rejected", "error": repr(error)})
                error_code, public_message = GENERATION_BRIDGE._public_error(error)
                self._send_json(409, {"ok": False, "error": public_message, "error_code": error_code})
            return
        if self.path == "/api/cancel":
            try:
                self._send_json(200, GENERATION_BRIDGE.cancel())
            except Exception as error:
                audit({"event": "external_ui_cancel_failed", "error": repr(error)})
                self._send_json(500, {"ok": False, "error": str(error)})
            return
        if self.path != "/api/open-output-folder":
            self.send_error(404)
            return
        try:
            pid = open_output_folder()
            self._send_json(200, {"ok": True, "pid": pid})
        except Exception as error:  # fail closed and report only the local error
            audit({"event": "external_ui_open_output_folder_failed", "error": repr(error)})
            self._send_json(500, {"ok": False, "error": str(error)})


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
