"""Launch the LAKIS desktop web UI while keeping ComfyUI backend-only."""

from __future__ import annotations

import ctypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
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
COMFY_URL = f"http://127.0.0.1:{COMFY_PORT}/system_stats"
INSTALLATION_ID = hashlib.sha256(
    os.path.normcase(str(PORTABLE_ROOT.resolve())).encode("utf-8")
).hexdigest()


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


def fetch_json(url: str, timeout: float = 1.0) -> dict | None:
    try:
        with urlopen(url, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                return None
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (OSError, URLError, UnicodeError, json.JSONDecodeError):
        return None


def bridge_identity_matches(
    payload: dict | None,
    session_token: str,
    expected_pid: int | None = None,
) -> bool:
    """Accept only the bridge created for this launch and installation."""
    if not isinstance(payload, dict):
        return False
    try:
        pid = int(payload.get("pid", 0))
        protocol = int(payload.get("protocol", 0))
    except (TypeError, ValueError):
        return False
    return (
        payload.get("product") == "LAKIS"
        and protocol == 1
        and payload.get("installation_id") == INSTALLATION_ID
        and payload.get("session_token") == session_token
        and (expected_pid is None or pid == expected_pid)
    )


def wait_ui_bridge_ready(
    ready_path: Path,
    process: subprocess.Popen,
    session_token: str,
    timeout: float,
) -> str | None:
    """Wait for and verify the exact per-launch UI bridge endpoint."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return None
        try:
            payload = json.loads(ready_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            time.sleep(0.1)
            continue
        if not bridge_identity_matches(payload, session_token, process.pid):
            time.sleep(0.1)
            continue
        try:
            port = int(payload.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            time.sleep(0.1)
            continue
        ui_url = f"http://127.0.0.1:{port}/"
        identity = fetch_json(ui_url + "api/launcher-identity", timeout=1.0)
        if bridge_identity_matches(identity, session_token, process.pid):
            return ui_url
        time.sleep(0.1)
    return None


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
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "LAKIS 실행 오류", 0x10)
    except Exception:
        pass


def main() -> int:
    session_token = secrets.token_hex(32)
    ready_path = DEV_ROOT / f"ui_bridge_ready_{os.getpid()}_{session_token[:12]}.json"
    comfy_port_in_use = responds(COMFY_URL)
    state = {
        "launcher_started_at": datetime.now().isoformat(timespec="seconds"),
        "launcher_pid": os.getpid(),
        "installation_id": INSTALLATION_ID,
        # Never attach to an arbitrary ComfyUI merely because the shared
        # backend port responds. A stale process from another installation
        # would otherwise load the wrong models, workflows, and user state.
        "comfyui_source": "port_in_use" if comfy_port_in_use else "launched_by_lakis",
        "comfyui_started_by_lakis": False,
        "comfyui_owned_pid": None,
        # Never attach to a process merely because a shared port responds.
        # Every launch gets an OS-assigned port plus an unguessable handshake.
        "ui_bridge_source": "launched_by_lakis",
        "ui_bridge_started_by_lakis": False,
        "ui_bridge_owned_pid": None,
        "desktop_target": None,
    }
    comfy_process = None
    ui_process = None
    try:
        save_state(state)
        if comfy_port_in_use:
            state["classification"] = "LAKIS_COMFYUI_PORT_IN_USE_FAILED"
            save_state(state)
            show_error(
                "다른 ComfyUI 또는 이전 LAKIS 백엔드가 8189 포트를 사용 중이야.\n\n"
                "실행 중인 LAKIS와 ComfyUI를 종료한 뒤 다시 실행해줘."
            )
            return 1
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

        command = [
            str(PYTHON), "-s", str(UI_SERVER),
            "--port", "0",
            "--session-token", session_token,
            "--ready-file", str(ready_path),
        ]
        ui_process, ownership = launch_hidden(command, "external_ui")
        state.update({
            "ui_bridge_started_by_lakis": True,
            "ui_bridge_owned_pid": ui_process.pid,
            "ui_bridge_ownership": ownership,
        })
        save_state(state)
        ui_url = wait_ui_bridge_ready(ready_path, ui_process, session_token, 20)
        if ui_url is None:
            state["classification"] = "LAKIS_UI_IDENTITY_FAILED"
            save_state(state)
            show_error("이 설치본의 LAKIS UI 브리지를 확인하지 못했어. launcher 로그를 확인해줘.")
            return 1

        state["classification"] = "LAKIS_READY"
        state["ready_at"] = datetime.now().isoformat(timespec="seconds")
        state["desktop_target"] = ui_url
        save_state(state)
        if not DESKTOP_HOST.is_file():
            raise FileNotFoundError(f"LAKIS desktop host is missing: {DESKTOP_HOST}")
        desktop_process = subprocess.Popen([str(DESKTOP_HOST), ui_url], cwd=str(PORTABLE_ROOT))
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
        try:
            ready_path.unlink(missing_ok=True)
        except OSError:
            pass
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
