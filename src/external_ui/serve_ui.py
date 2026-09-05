"""Serve the LAKIS prototype and expose a narrowly scoped Explorer bridge."""

from __future__ import annotations

import html
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

UI_ROOT = Path(__file__).resolve().parent
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from workflow_bridge import (
    WorkflowBridge,
    save_external_generation_state,
    save_external_prompt_state,
    workflow_configuration,
)

try:
    import psutil
except ImportError:  # optional in prototype runtime
    psutil = None


COMFY_ROOT = UI_ROOT.parents[1].resolve()
LAKIS_VERSION_PATH = COMFY_ROOT.parent / "VERSION"
OUTPUT_ROOT = (COMFY_ROOT / "output").resolve()
AUDIT_PATH = COMFY_ROOT / "LAKIS_DEV" / "process_audit.jsonl"
HOST = "127.0.0.1"
PORT = 8766
COMFY_SERVER = "http://127.0.0.1:8189"
WORKFLOW_ROOT = COMFY_ROOT / "user" / "default" / "workflows"
LAKIS_WORKFLOW = WORKFLOW_ROOT / "LAKIS_custom_v7.1.json"
AUTOPATCH_MARKER = COMFY_ROOT / "custom_nodes" / "ComfyUI-LAKIS-AutoPatch" / "startup_workflow.json"
GENERATION_BRIDGE = WorkflowBridge()
KOREAN_PATTERN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
TRANSLATION_SPLIT_PATTERN = re.compile(r"([,\n]+)")

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
    if GOOGLE_TRANSLATOR is None:
        raise RuntimeError("Google 번역 기능을 불러오지 못했어요.")
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
        translated_body = GOOGLE_TRANSLATOR.translate(part.strip(), "auto", "en")
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
    with AUDIT_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


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


def workflow_version() -> str:
    versions = []
    for path in WORKFLOW_ROOT.glob("LAKIS_custom_v*.json"):
        raw = path.stem.rsplit("_v", 1)[-1]
        try:
            versions.append((tuple(int(part) for part in raw.split(".")), raw))
        except ValueError:
            continue
    return max(versions)[1] if versions else "unknown"


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

    def _prepare_lakis_workflow(self) -> dict:
        if not LAKIS_WORKFLOW.is_file() or LAKIS_WORKFLOW.parent.resolve() != WORKFLOW_ROOT:
            raise FileNotFoundError(f"LAKIS workflow is missing: {LAKIS_WORKFLOW}")
        workflow = json.loads(LAKIS_WORKFLOW.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
            raise ValueError("LAKIS workflow is not a valid ComfyUI workflow")
        AUTOPATCH_MARKER.parent.mkdir(parents=True, exist_ok=True)
        temporary = AUTOPATCH_MARKER.with_suffix(".tmp")
        temporary.write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, AUTOPATCH_MARKER)
        audit({
            "event": "external_ui_workflow_open_prepared",
            "workflow": str(LAKIS_WORKFLOW),
            "marker": str(AUTOPATCH_MARKER),
            "node_count": len(workflow["nodes"]),
        })
        return {"ok": True, "comfy_url": COMFY_SERVER + "/", "node_count": len(workflow["nodes"])}

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
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

    def _read_json(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 1_000_000:
            raise ValueError("Invalid request size")
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/open-workflow":
            try:
                self._send_json(200, self._prepare_lakis_workflow())
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
                saved = save_external_generation_state(incoming.get("model"), incoming.get("output"))
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


if __name__ == "__main__":
    mutex = None
    if os.name == "nt":
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LAKIS_UI_BRIDGE_8766")
        if not mutex or ctypes.windll.kernel32.GetLastError() == 183:
            print("LAKIS UI bridge is already running.")
            sys.exit(0)
    print(f"LAKIS UI: http://{HOST}:{PORT}")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    finally:
        if mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)
