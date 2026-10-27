"""Isolated smoke check for a prepared LAKIS ComfyUI runtime candidate."""
from __future__ import annotations

import argparse
from collections.abc import Iterable
from contextlib import closing
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

from runtime_manifest import runtime_files


EXPECTED_COMFYUI_VERSION = "0.42.0"
WORKFLOW_RELATIVE = Path(
    "ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.4.json"
)
MAX_LOG_BYTES = 256 * 1024
POLL_INTERVAL_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 2.0
PROCESS_STOP_TIMEOUT_SECONDS = 5.0


class _BoundedLog:
    def __init__(self, limit: int = MAX_LOG_BYTES):
        self._limit = limit
        self._content = bytearray()
        self._lock = threading.Lock()

    def append(self, value: bytes | str) -> None:
        if isinstance(value, str):
            value = value.encode("utf-8", errors="replace")
        if not value:
            return
        with self._lock:
            if len(value) >= self._limit:
                self._content[:] = value[-self._limit :]
                return
            self._content.extend(value)
            excess = len(self._content) - self._limit
            if excess > 0:
                del self._content[:excess]

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self._content)


def _capture_output(stream, log: _BoundedLog) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            log.append(chunk)
    except (OSError, ValueError) as exc:
        log.append(f"\n[diagnostic capture stopped: {exc}]\n")


def _select_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _read_required_nodes(workflow_path: Path) -> set[str]:
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"cannot read required-node workflow {workflow_path}: {exc}"
        ) from exc
    if not isinstance(workflow, dict):
        raise RuntimeError(f"required-node workflow is not an object: {workflow_path}")

    launcher_path = workflow_path.parent.parent / "external_ui" / "launch_lakis.py"
    spec = importlib.util.spec_from_file_location("lakis_candidate_launcher", launcher_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate runtime capability contract: {launcher_path}")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    # Use the product's actual contract: editor metadata is not executable,
    # and bridge-injected public nodes must also be registered.
    required = launcher.required_runtime_node_types(workflow)
    if not required:
        raise RuntimeError(f"required-node workflow contains no class_type names: {workflow_path}")
    return required


def _append_command_output(log: _BoundedLog, label: str, output) -> None:
    if output:
        if isinstance(output, bytes):
            text = output.decode("utf-8", errors="replace")
        else:
            text = str(output)
        log.append(f"\n--- {label} ---\n{text}\n")


def _owns_listener(python: Path, pid: int, port: int, root: Path, timeout: float) -> bool:
    """Ask the candidate interpreter's psutil to inspect the owned process."""
    probe = (
        "import json, psutil, sys\n"
        "pid, port = int(sys.argv[1]), int(sys.argv[2])\n"
        "connections = psutil.Process(pid).net_connections(kind='inet')\n"
        "def address_parts(address):\n"
        "    if hasattr(address, 'ip'):\n"
        "        return address.ip, address.port\n"
        "    return address[0], address[1]\n"
        "owned = any(\n"
        "    connection.status == psutil.CONN_LISTEN\n"
        "    and connection.laddr\n"
        "    and address_parts(connection.laddr) == ('127.0.0.1', port)\n"
        "    for connection in connections\n"
        ")\n"
        "print(json.dumps(owned))\n"
    )
    command = [
        str(python), "-s", "-c", probe, str(pid), str(port),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("timed out verifying the ComfyUI listener process with psutil") from exc
    except OSError as exc:
        raise RuntimeError(f"could not run the embedded psutil listener check: {exc}") from exc

    output = completed.stdout or b""
    if completed.returncode != 0:
        details = (completed.stderr or output)
        if isinstance(details, bytes):
            details = details.decode("utf-8", errors="replace")
        details = str(details).strip()[-1000:]
        raise RuntimeError(
            "embedded psutil listener check failed"
            + (f": {details}" if details else "")
        )
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    try:
        result = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("embedded psutil listener check returned invalid output") from exc
    if not isinstance(result, bool):
        raise RuntimeError("embedded psutil listener check returned a non-boolean result")
    return result


def _fetch_json(url: str, timeout: float):
    with urlopen(url, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"endpoint returned HTTP {status}")
        return json.loads(response.read().decode("utf-8"))


def _comfyui_version(system_stats) -> str | None:
    system = system_stats.get("system")
    if not isinstance(system, dict):
        return None
    version = system.get("comfyui_version")
    return version if isinstance(version, str) and version else None


def _stop_child(child) -> None:
    if child.poll() is None:
        child.terminate()
    try:
        child.wait(timeout=PROCESS_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=PROCESS_STOP_TIMEOUT_SECONDS)


def _start_log_reader(child, log: _BoundedLog):
    stream = getattr(child, "stdout", None)
    if stream is None:
        return None
    reader = threading.Thread(
        target=_capture_output,
        args=(stream, log),
        name="lakis-runtime-health-log",
        daemon=True,
    )
    reader.start()
    return reader


def _finish_log_reader(child, reader, log: _BoundedLog) -> str | None:
    if reader is None:
        return None
    reader.join(timeout=PROCESS_STOP_TIMEOUT_SECONDS)
    if reader.is_alive():
        stream = getattr(child, "stdout", None)
        if stream is not None:
            try:
                stream.close()
            except OSError as exc:
                log.append(f"\n[could not close diagnostic pipe: {exc}]\n")
        reader.join(timeout=1.0)
    if reader.is_alive():
        return "diagnostic output reader did not stop"
    return None


def _isolated_entrypoint(comfy_root: Path, profile: Path) -> list[str]:
    """Run independent program copies, including nodes that write beside __file__."""
    # Reuse the payload boundary and reparse-safe traversal. Do not copy user
    # data, generated files, or use hardlinks: nodes may write beside their code.
    with closing(runtime_files(
        comfy_root.parent, allow_user_data=True, scopes=("ComfyUI",),
    )) as files:
        for relative, source in files:
            destination = profile / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
    isolated_comfy = profile / "ComfyUI"
    entrypoint = isolated_comfy / "main.py"
    paths = profile / "custom-node-paths.json"
    # JSON is also valid YAML. Both imports and custom-node discovery must use
    # the copies; CLI data paths alone do not isolate __file__-relative writes.
    paths.write_text(json.dumps({
        "runtime_health": {"custom_nodes": str(isolated_comfy / "custom_nodes")},
    }), encoding="utf-8")
    bootstrap = (
        "import runpy, sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "sys.argv = sys.argv[2:]; "
        "runpy.run_path(sys.argv[0], run_name='__main__')"
    )
    return [
        "-c", bootstrap, str(isolated_comfy), str(entrypoint),
        "--extra-model-paths-config", str(paths),
    ]


def check_runtime(root: Path, timeout: float = 180) -> dict:
    """Check an isolated runtime candidate without submitting a prompt."""
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number of seconds")

    deadline = time.monotonic() + float(timeout)
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"runtime candidate root is not a directory: {root}")

    comfy_root = root / "ComfyUI"
    python = root / "python_embeded" / "python.exe"
    main_script = comfy_root / "main.py"
    # A later check must not reopen or migrate an earlier check's profile.
    # Custom-node startup can scan models, rewrite sidecars and purge staged
    # deletions. Its entire data base must therefore be disposable.
    profile = Path(tempfile.mkdtemp(prefix="lakis-runtime-health-"))
    for name in ("user", "input", "output", "temp", "models", "custom_nodes"):
        (profile / name).mkdir()
    child_env = os.environ.copy()
    for name, directory in {
        "USERPROFILE": profile,
        "HOME": profile,
        "LOCALAPPDATA": profile / "AppData" / "Local",
        "APPDATA": profile / "AppData" / "Roaming",
        "XDG_CACHE_HOME": profile / "cache",
        "XDG_CONFIG_HOME": profile / "config",
        "HF_HOME": profile / "cache" / "huggingface",
        "TORCH_HOME": profile / "cache" / "torch",
        "LORA_MANAGER_SETTINGS_DIR": profile / "lora-manager",
        "WAS_CONFIG_DIR": profile / "was-node-suite",
    }.items():
        directory.mkdir(parents=True, exist_ok=True)
        child_env[name] = str(directory)
    child_env["LORA_MANAGER_CACHE_DB"] = str(profile / "lora-manager" / "models.db")
    child_env["LORA_MANAGER_RECIPE_CACHE_DB"] = str(profile / "lora-manager" / "recipes.db")
    child_env["WAS_BLOCK_AUTO_INSTALL"] = "1"
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    log_fd, log_name = tempfile.mkstemp(
        prefix="runtime-health-",
        suffix=".log",
        dir=str(profile),
    )
    os.close(log_fd)
    log_path = Path(log_name)
    log = _BoundedLog()

    child = None
    reader = None
    failure = None
    cleanup_error = None
    log_write_error = None
    result = None

    try:
        if not python.is_file():
            raise RuntimeError(f"embedded Python is missing: {python}")
        if not main_script.is_file():
            raise RuntimeError(f"ComfyUI entry point is missing: {main_script}")

        required_nodes = _read_required_nodes(root / WORKFLOW_RELATIVE)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("runtime health check timed out before pip check")
        try:
            pip_check = subprocess.run(
                [str(python), "-s", "-m", "pip", "check"],
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=remaining,
                check=False,
                env=child_env,
            )
        except subprocess.TimeoutExpired as exc:
            _append_command_output(log, "pip check", exc.stdout)
            raise RuntimeError("embedded Python pip check timed out") from exc
        except OSError as exc:
            raise RuntimeError(f"could not run embedded Python pip check: {exc}") from exc
        _append_command_output(log, "pip check", pip_check.stdout)
        if pip_check.returncode != 0:
            raise RuntimeError(
                f"embedded Python pip check failed with exit code {pip_check.returncode}"
            )
        if not pip_check.stdout:
            log.append("\n--- pip check ---\npassed\n")

        entrypoint_args = _isolated_entrypoint(comfy_root, profile)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("runtime health check timed out before ComfyUI startup")
        port = _select_port()
        # Assets remain disabled: ComfyUI checks only the installed DB lock,
        # not its schema, and does not migrate or open the user database.
        database_url = f"sqlite:///{(comfy_root / 'user/comfyui.db').resolve().as_posix()}"
        command = [
            str(python),
            "-s",
            *entrypoint_args,
            "--listen", "127.0.0.1",
            "--port", str(port),
            "--disable-auto-launch",
            "--base-directory", str(profile),
            "--models-directory", str(profile / "models"),
            "--user-directory", str(profile),
            "--input-directory", str(profile / "input"),
            "--output-directory", str(profile / "output"),
            "--temp-directory", str(profile / "temp"),
            "--database-url", database_url,
            "--disable-assets",
        ]
        child = subprocess.Popen(
            command,
            cwd=str(profile),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=child_env,
        )
        reader = _start_log_reader(child, log)

        base_url = f"http://127.0.0.1:{port}"
        system_url = f"{base_url}/system_stats"
        object_info_url = f"{base_url}/object_info"
        last_system_error = "no system_stats response received"
        last_object_info_error = "no object_info response received"

        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(
                    f"ComfyUI process exited prematurely with code {child.returncode}"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            request_timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)
            system_stats = None
            object_info = None
            try:
                system_stats = _fetch_json(system_url, request_timeout)
                if not isinstance(system_stats, dict):
                    raise RuntimeError("system_stats response is not an object")
                last_system_error = "system_stats did not report system.comfyui_version"
            except Exception as exc:
                last_system_error = f"{type(exc).__name__}: {exc}"[:500]

            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    object_info = _fetch_json(
                        object_info_url,
                        min(REQUEST_TIMEOUT_SECONDS, remaining),
                    )
                    if not isinstance(object_info, dict):
                        raise RuntimeError("object_info response is not an object")
                    last_object_info_error = "object_info has not reported required nodes"
                except Exception as exc:
                    last_object_info_error = f"{type(exc).__name__}: {exc}"[:500]

            if time.monotonic() >= deadline:
                break
            if child.poll() is not None:
                raise RuntimeError(
                    f"ComfyUI process exited prematurely with code {child.returncode}"
                )

            if system_stats is not None or object_info is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    owns_listener = _owns_listener(
                        python, child.pid, port, root, min(5.0, remaining)
                    )
                except RuntimeError as exc:
                    raise RuntimeError(f"could not verify endpoint identity: {exc}") from exc
                if not owns_listener:
                    raise RuntimeError(
                        "endpoint identity mismatch: the listener at "
                        f"127.0.0.1:{port} is not the ComfyUI subprocess started by this check"
                    )

            version = (
                _comfyui_version(system_stats)
                if system_stats is not None
                else None
            )
            if version is not None and version != EXPECTED_COMFYUI_VERSION:
                raise RuntimeError(
                    "ComfyUI version mismatch: expected "
                    f"{EXPECTED_COMFYUI_VERSION}, observed {version}"
                )
            if version == EXPECTED_COMFYUI_VERSION and object_info is not None:
                missing_nodes = required_nodes - object_info.keys()
                if missing_nodes:
                    raise RuntimeError(
                        "ComfyUI is missing required workflow nodes: "
                        + ", ".join(sorted(missing_nodes))
                    )
                if child.poll() is not None:
                    raise RuntimeError(
                        f"ComfyUI process exited prematurely with code {child.returncode}"
                    )
                result = {
                    "comfyui_version": version,
                    "required_node_count": len(required_nodes),
                    "log_path": str(log_path),
                }
                break

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(POLL_INTERVAL_SECONDS, remaining))

        if result is None:
            raise RuntimeError(
                f"timed out waiting for ComfyUI readiness at 127.0.0.1:{port}; "
                f"last system_stats: {last_system_error}; "
                f"last object_info: {last_object_info_error}"
            )
    except BaseException as exc:
        failure = exc
        log.append(f"\nRuntime health check failed: {type(exc).__name__}: {exc}\n")
    finally:
        if child is not None:
            try:
                _stop_child(child)
            except Exception as exc:
                cleanup_error = exc
                log.append(f"\nCould not stop owned ComfyUI subprocess: {exc}\n")
            reader_error = _finish_log_reader(child, reader, log)
            if reader_error:
                cleanup_error = cleanup_error or RuntimeError(reader_error)
                log.append(f"\n{reader_error}\n")
        try:
            log_path.write_bytes(log.snapshot())
        except OSError as exc:
            log_write_error = exc

    if log_write_error is not None:
        message = f"could not retain diagnostics at {log_path}: {log_write_error}"
        if failure is not None:
            raise RuntimeError(f"{failure}; {message}") from failure
        raise RuntimeError(message)
    if cleanup_error is not None:
        message = f"runtime health cleanup failed: {cleanup_error}"
        if failure is not None:
            raise RuntimeError(f"{failure}; {message}; diagnostics: {log_path}") from failure
        raise RuntimeError(f"{message}; diagnostics: {log_path}") from cleanup_error
    if failure is not None:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise failure
        raise RuntimeError(f"{failure}; diagnostics: {log_path}") from failure
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check an isolated LAKIS runtime candidate.")
    parser.add_argument("--root", required=True, type=Path, help="verified candidate root")
    args = parser.parse_args(argv)
    try:
        result = check_runtime(args.root)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"runtime health check failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
