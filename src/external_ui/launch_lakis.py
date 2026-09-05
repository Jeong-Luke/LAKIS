"""Launch the LAKIS desktop web UI while keeping ComfyUI backend-only."""

from __future__ import annotations

import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen


UI_ROOT = Path(__file__).resolve().parent
COMFY_ROOT = UI_ROOT.parents[1]
PORTABLE_ROOT = COMFY_ROOT.parent
PYTHON = PORTABLE_ROOT / "python_embeded" / "python.exe"
COMFY_MAIN = COMFY_ROOT / "main.py"
UI_SERVER = UI_ROOT / "serve_ui.py"
DESKTOP_HOST = Path(os.environ.get("LAKIS_DESKTOP_HOST", PORTABLE_ROOT / "LAKIS_Desktop.exe"))
DEV_ROOT = UI_ROOT.parent
STATE_PATH = DEV_ROOT / "lakis_launcher_state.json"
LOG_ROOT = DEV_ROOT / "launcher_logs"
COMFY_PORT = 8189
UI_PORT = 8766
COMFY_URL = f"http://127.0.0.1:{COMFY_PORT}/system_stats"
UI_URL = f"http://127.0.0.1:{UI_PORT}/"


def responds(url: str, timeout: float = 1.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, URLError):
        return False


def wait_ready(url: str, process: subprocess.Popen | None, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if responds(url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def launch_hidden(command: list[str], log_name: str) -> tuple[subprocess.Popen, dict]:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_ROOT / f"{log_name}_{timestamp}.log"
    log_stream = log_path.open("ab", buffering=0)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    child_env = os.environ.copy()
    # ComfyUI and custom nodes may log Unicode symbols.  A hidden Windows
    # process otherwise inherits the legacy CP949 console encoding and can
    # terminate during startup when a node prints an emoji or another symbol
    # outside that code page.
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    # Keep LoRA Manager state local to this LAKIS runtime.  Its default
    # per-Windows-user directory is shared by every ComfyUI installation and
    # can otherwise reintroduce stale paths from an older portable install.
    child_env["LORA_MANAGER_SETTINGS_DIR"] = str(
        COMFY_ROOT / "user" / "default" / "lora-manager"
    )
    process = subprocess.Popen(
        command,
        cwd=str(PORTABLE_ROOT),
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=False,
    )
    record = {
        "pid": process.pid,
        "executable_path": str(Path(command[0]).resolve()),
        "command_line": command,
        "parent_pid": os.getpid(),
        "launch_timestamp": datetime.now().isoformat(timespec="seconds"),
        "log_path": str(log_path),
        "python_utf8": True,
    }
    return process, record


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "LAKIS 실행 오류", 0x10)
    except Exception:
        pass


def main() -> int:
    state = {
        "launcher_started_at": datetime.now().isoformat(timespec="seconds"),
        "launcher_pid": os.getpid(),
        "comfyui_source": "existing" if responds(COMFY_URL) else "launched_by_lakis",
        "comfyui_started_by_lakis": False,
        "comfyui_owned_pid": None,
        "ui_bridge_source": "existing" if responds(UI_URL) else "launched_by_lakis",
        "ui_bridge_started_by_lakis": False,
        "ui_bridge_owned_pid": None,
        "desktop_target": UI_URL,
    }
    comfy_process = None
    ui_process = None
    try:
        if state["comfyui_source"] == "launched_by_lakis":
            command = [str(PYTHON), "-s", str(COMFY_MAIN), "--windows-standalone-build",
                       "--port", str(COMFY_PORT), "--disable-auto-launch",
                       "--preview-method", "auto"]
            comfy_process, ownership = launch_hidden(command, "comfyui")
            state.update({
                "comfyui_started_by_lakis": True,
                "comfyui_owned_pid": comfy_process.pid,
                "comfyui_ownership": ownership,
            })
            save_state(state)
            if not wait_ready(COMFY_URL, comfy_process, 180):
                state["classification"] = "COMFYUI_START_FAILED"
                save_state(state)
                show_error("ComfyUI 백엔드를 시작하지 못했어. LAKIS launcher 로그를 확인해줘.")
                return 1

        if state["ui_bridge_source"] == "launched_by_lakis":
            command = [str(PYTHON), "-s", str(UI_SERVER)]
            ui_process, ownership = launch_hidden(command, "external_ui")
            state.update({
                "ui_bridge_started_by_lakis": True,
                "ui_bridge_owned_pid": ui_process.pid,
                "ui_bridge_ownership": ownership,
            })
            save_state(state)
            if not wait_ready(UI_URL, ui_process, 20):
                state["classification"] = "LAKIS_UI_START_FAILED"
                save_state(state)
                show_error("LAKIS UI 브리지를 시작하지 못했어. launcher 로그를 확인해줘.")
                return 1

        state["classification"] = "LAKIS_READY"
        state["ready_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        if not DESKTOP_HOST.is_file():
            raise FileNotFoundError(f"LAKIS desktop host is missing: {DESKTOP_HOST}")
        desktop_process = subprocess.Popen([str(DESKTOP_HOST), UI_URL], cwd=str(PORTABLE_ROOT))
        state["desktop_pid"] = desktop_process.pid
        save_state(state)
        return desktop_process.wait()
    except Exception as error:
        state["classification"] = "LAKIS_LAUNCH_FAILED"
        state["error"] = repr(error)
        save_state(state)
        show_error(f"LAKIS 실행 중 오류가 발생했어.\n\n{error}")
        return 1
    finally:
        for process in (ui_process, comfy_process):
            if process is None or process.poll() is not None:
                continue
            try:
                process.terminate()
                process.wait(timeout=10)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
