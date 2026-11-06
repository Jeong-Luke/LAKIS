"""Run the bundled LoRA Manager with installation- and engine-local profiles."""

from __future__ import annotations

import argparse
import atexit
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen
import uuid

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import moss_mode


ENGINES = ("anima", "moss")
_POOLS = {}
_POOL_LOCK = threading.Lock()


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_matches_engine(path, engine, roots):
    """Keep legacy ANIMA files in place while excluding the MOSS namespace."""
    moss_mode.engine(engine)
    path = Path(path).resolve()
    for root in roots:
        try:
            relative = path.relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            continue
        return moss_mode.is_moss_path(relative) == (engine == "moss")
    return False


def scope_scanner(scanner_class, engine, roots):
    original = scanner_class._process_model_file

    async def process(self, file_path, root_path, **kwargs):
        if not file_matches_engine(file_path, engine, roots):
            return None
        return await original(self, file_path, root_path, **kwargs)

    scanner_class._process_model_file = process


def manager_environment(settings_dir):
    env = os.environ.copy()
    for name in (
        "LORA_MANAGER_CACHE_DB", "LORA_MANAGER_RECIPE_CACHE_DB",
        "LORA_MANAGER_TAG_FTS_DB", "LORA_MANAGER_RECIPE_FTS_DB",
        "LORA_MANAGER_MODEL_UPDATE_DB",
    ):
        env.pop(name, None)
    env.update(
        LORA_MANAGER_SETTINGS_DIR=str(settings_dir),
        LORA_MANAGER_STANDALONE="1",
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
    )
    return env


class ManagerPool:
    def __init__(self, comfy_root, lora_roots):
        self.comfy_root = Path(comfy_root).resolve()
        self.roots = list(dict.fromkeys(Path(root).resolve() for root in lora_roots))
        self.local_root = self.comfy_root / "models" / "loras"
        self.state_root = self.comfy_root / "user" / "default" / "lora-manager"
        self.source = self.comfy_root / "custom_nodes" / "ComfyUI-Lora-Manager" / "standalone.py"
        self.instances = {}
        self.lock = threading.Lock()

    def prepare_profile(self, engine):
        if engine not in ENGINES:
            raise ValueError("LoRA 모드는 anima 또는 moss여야 합니다.")
        model_roots = [(self.local_root / name).resolve() for name in ENGINES]
        if any(a.is_relative_to(b) for a, b in (model_roots, model_roots[::-1])):
            raise RuntimeError("ANIMA와 MOSS LoRA 저장 경로가 겹칩니다.")
        model_root = (self.local_root / engine).resolve()
        settings_dir = self.state_root / engine
        settings_file = settings_dir / "settings.json"
        primary = [str(model_root)]
        extra = [
            str(root if engine == "anima" else root / "moss")
            for root in self.roots
            if (root if engine == "anima" else root / "moss").resolve() != model_root
        ]
        if settings_file.exists():
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
            for library in [settings, *settings.get("libraries", {}).values()]:
                for value in library.get("folder_paths", {}).get("loras", []):
                    if Path(value).resolve() != model_root:
                        raise RuntimeError(f"{engine.upper()} LoRA Manager의 저장 경로가 전용 폴더와 다릅니다.")
                for value in library.get("extra_folder_paths", {}).get("loras", []):
                    if Path(value).resolve() not in {Path(root).resolve() for root in extra}:
                        raise RuntimeError(f"{engine.upper()} LoRA Manager의 추가 경로가 현재 설치와 다릅니다.")
                default = library.get("default_lora_root")
                if default and Path(default).resolve() != model_root:
                    raise RuntimeError(f"{engine.upper()} LoRA 다운로드 경로가 전용 폴더와 다릅니다.")
            return settings_dir

        # Preserve the original ANIMA profile, including unknown preferences.
        # The original file and databases are never rewritten or moved.
        legacy_file = self.state_root / "settings.json"
        settings = json.loads(legacy_file.read_text(encoding="utf-8")) if engine == "anima" and legacy_file.is_file() else {}
        settings = deepcopy(settings)
        library = {
            "folder_paths": {"loras": primary, "checkpoints": [], "unet": [], "embeddings": []},
            "extra_folder_paths": {"loras": extra},
            "default_lora_root": str(model_root),
        }
        for path in (model_root, settings_dir / "recipes", settings_dir / "example_images", settings_dir / "temp"):
            path.mkdir(parents=True, exist_ok=True)
        settings.update(
            **library,
            active_library=engine.upper(),
            libraries={engine.upper(): deepcopy(library)},
            recipes_path=str(settings_dir / "recipes"),
            example_images_path=str(settings_dir / "example_images"),
            auto_download_example_images=False,
        )
        _write_json(settings_file, settings)
        return settings_dir

    def manager_url(self, engine):
        with self.lock:
            settings_dir = self.prepare_profile(engine)
            instance = self.instances.get(engine)
            if instance is None or instance["process"].poll() is not None:
                if not self.source.is_file():
                    raise RuntimeError(f"설치된 LoRA Manager를 찾을 수 없습니다: {self.source}")
                token = uuid.uuid4().hex
                ready = settings_dir / f"ready-{token}.json"
                stop = settings_dir / f"stop-{token}"
                command = [
                    sys.executable, "-s", str(Path(__file__).resolve()),
                    "--source", str(self.source), "--settings", str(settings_dir),
                    "--engine", engine, "--roots", json.dumps([str(root) for root in self.roots]),
                    "--token", token, "--parent-pid", str(os.getpid()),
                    "--parent-created", str(psutil.Process().create_time()),
                ]
                log_path = settings_dir / f"launch-{token}.log"
                with log_path.open("ab", buffering=0) as log:
                    process = subprocess.Popen(
                        command, cwd=str(settings_dir), env=manager_environment(settings_dir),
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                instance = {"process": process, "token": token, "ready": ready, "stop": stop}
                self.instances[engine] = instance
                try:
                    deadline = time.monotonic() + 45
                    while not ready.is_file():
                        if process.poll() is not None:
                            raise RuntimeError(f"{engine.upper()} LoRA Manager 시작 실패: {log_path}")
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f"{engine.upper()} LoRA Manager 준비 시간 초과: {log_path}")
                        time.sleep(0.1)
                except Exception:
                    self._stop(instance)
                    raise
            identity = json.loads(instance["ready"].read_text(encoding="utf-8"))
            expected = {
                "engine": engine, "settings": str(settings_dir.resolve()),
                "pid": instance["process"].pid, "token": instance["token"],
            }
            if any(identity.get(key) != value for key, value in expected.items()):
                raise RuntimeError("LoRA Manager 실행 소유 정보를 확인하지 못했습니다.")
            base = f'http://127.0.0.1:{int(identity["port"])}'
            with urlopen(base + "/api/lakis-manager-identity", timeout=3) as response:
                observed = json.load(response)
            if observed != expected:
                raise RuntimeError("다른 LoRA Manager에는 연결하지 않습니다.")
            return base + "/loras"

    @staticmethod
    def _stop(instance):
        process = instance["process"]
        if process.poll() is None:
            instance["stop"].touch()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        instance["ready"].unlink(missing_ok=True)
        instance["stop"].unlink(missing_ok=True)

    def close(self):
        with self.lock:
            for instance in self.instances.values():
                self._stop(instance)
            self.instances.clear()


def manager_url(comfy_root, engine, lora_roots):
    root = Path(comfy_root).resolve()
    with _POOL_LOCK:
        if root not in _POOLS:
            _POOLS[root] = ManagerPool(root, lora_roots)
        pool = _POOLS[root]
    return pool.manager_url(engine)


def stop_managers():
    with _POOL_LOCK:
        for pool in _POOLS.values():
            pool.close()
        _POOLS.clear()


async def _run_worker(args):
    settings = Path(args.settings).resolve()
    parent = psutil.Process(args.parent_pid)
    if parent.create_time() != args.parent_created:
        raise RuntimeError("LoRA Manager의 부모 프로세스가 일치하지 않습니다.")
    upstream = runpy.run_path(args.source)
    sys.modules["folder_paths"].get_temp_directory = lambda: str(settings / "temp")
    from aiohttp import web
    from py.services.lora_scanner import LoraScanner

    scope_scanner(LoraScanner, args.engine, json.loads(args.roots))
    if not upstream["validate_settings"]():
        raise RuntimeError("LoRA Manager 설정을 확인하지 못했습니다.")
    server = upstream["StandaloneServer"]()
    upstream["StandaloneLoraManager"].add_routes(server)
    identity = {"engine": args.engine, "settings": str(settings), "pid": os.getpid(), "token": args.token}

    async def identify(request):
        return web.json_response(identity)

    server.app.router.add_get("/api/lakis-manager-identity", identify)
    await server.setup()
    runner = web.AppRunner(server.app, shutdown_timeout=5)
    try:
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        _write_json(settings / f"ready-{args.token}.json", {**identity, "port": port})
        while parent.is_running() and not (settings / f"stop-{args.token}").exists():
            await asyncio.sleep(0.25)
    finally:
        await runner.cleanup()


atexit.register(stop_managers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--engine", choices=ENGINES, required=True)
    parser.add_argument("--roots", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--parent-created", type=float, required=True)
    asyncio.run(_run_worker(parser.parse_args()))
