"""Shared frozen-bundle preparation for public GUI, CMD, update and Repair."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import urlsplit
import zipfile

if __name__ == "__main__":
    # Embedded Python's ._pth omits the script directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lakis_cmd_installer import (
    cache_entry_lock, cache_path, copy_file, create_default_input_image, download,
    ensure_webview2_runtime, promote_verified_partial,
    reject_reparse_path, safe_leaf, sha256, zip_extraction_plan,
)
from runtime_manifest import COMFY_VERSION, _pinned_path, normalized_path, verify_runtime
import runtime_manifest as runtime_contract
from runtime_transition import _target_path, activate

RUNTIME_HELPERS = (
    "runtime_install.py", "runtime_transition.py", "runtime_manifest.py", "runtime_health.py",
)


def validate_bundle(bundle: dict, version: str) -> dict:
    if (not isinstance(bundle, dict) or bundle.get("schema") != 2
            or bundle.get("product") != "LAKIS" or bundle.get("version") != version
            or bundle.get("comfyui_version") != COMFY_VERSION
            or not re.fullmatch(r"\d+\.\d+\.\d+", version)):
        raise ValueError("runtime bundle identity mismatch")
    name = safe_leaf(bundle.get("name", ""))
    if not name.lower().endswith(".zip"):
        raise ValueError("runtime bundle must be a ZIP")
    for field in ("sha256", "manifest_sha256"):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(bundle.get(field, ""))):
            raise ValueError(f"invalid runtime bundle {field}")
    if type(bundle.get("bytes")) is not int or bundle["bytes"] <= 0:
        raise ValueError("invalid runtime bundle size")
    if type(bundle.get("files")) is not int or bundle["files"] <= 0:
        raise ValueError("invalid runtime bundle file count")
    parts = bundle.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 999:
        raise ValueError("runtime bundle requires ordered release parts")
    total = 0
    for index, part in enumerate(parts, 1):
        expected_name = f"{name}.part{index:03d}"
        if (not isinstance(part, dict) or part.get("name") != expected_name
                or type(part.get("bytes")) is not int or not 0 < part["bytes"] <= 1024 ** 3
                or not re.fullmatch(r"[a-fA-F0-9]{64}", str(part.get("sha256", "")))
                or part.get("url") !=
                f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{version}/{expected_name}"):
            raise ValueError("invalid runtime release part identity, size, hash or URL")
        total += part["bytes"]
    if total != bundle["bytes"]:
        raise ValueError("runtime part sizes do not match the archive size")
    if "url" in bundle:
        raise ValueError("runtime archive is assembled locally; publish only its parts")
    return dict(bundle)


def asset_url(asset: dict) -> str:
    override = os.environ.get("LAKIS_RC_RELEASE_BASE_URL")
    if not override:
        return asset["url"]
    parsed = urlsplit(override)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("LAKIS_RC_RELEASE_BASE_URL must be an explicit loopback HTTP base")
    return override.rstrip("/") + "/" + asset["name"]


def download_bundle(bundle: dict, cache: Path) -> Path:
    started = time.monotonic()
    transfer_seconds = 0.0
    destination = reject_reparse_path(cache_path(cache, bundle["name"], bundle["sha256"]))
    with cache_entry_lock(destination, bundle["name"]):
        if (destination.is_file() and destination.stat().st_size == bundle["bytes"]
                and sha256(destination) == bundle["sha256"].upper()):
            print(json.dumps({
                "status": "RUNTIME_ARCHIVE_TIMINGS", "cache_hit": True,
                "part_transfer_and_verification_seconds": 0.0,
                "assembly_and_archive_verification_seconds": time.monotonic() - started,
            }), flush=True)
            return destination
        fd, name = tempfile.mkstemp(prefix="runtime-assembling-", suffix=".zip", dir=cache)
        temporary = Path(name)
        try:
            digest, total = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as output:
                for part in bundle["parts"]:
                    transfer_started = time.monotonic()
                    incoming = download(
                        asset_url(part), cache_path(cache, part["name"], part["sha256"]),
                        part["sha256"], part["bytes"], display_name=part["name"],
                    )
                    transfer_seconds += time.monotonic() - transfer_started
                    with incoming.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            output.write(block)
                            digest.update(block)
                            total += len(block)
                output.flush()
                os.fsync(output.fileno())
            if total != bundle["bytes"] or digest.hexdigest().upper() != bundle["sha256"].upper():
                raise ValueError("assembled runtime archive integrity mismatch")
            reject_reparse_path(destination)
            promote_verified_partial(temporary, destination, bundle["name"])
        finally:
            if temporary.exists():
                temporary.unlink()
    print(json.dumps({
        "status": "RUNTIME_ARCHIVE_TIMINGS", "cache_hit": False,
        "part_transfer_and_verification_seconds": transfer_seconds,
        "assembly_and_archive_verification_seconds": time.monotonic() - started - transfer_seconds,
    }), flush=True)
    return destination


def extract_runtime_zip(archive: Path, destination: Path, *, expected_entries: int) -> None:
    """Extract only into a new root; pin the archive and each active ancestry."""
    archive = Path(os.path.abspath(archive))
    root = Path(os.path.abspath(destination))
    with ExitStack() as ancestors:
        for path in (archive, root):
            for parent in reversed(path.parents):
                ancestors.enter_context(_pinned_path(parent, directory=True))
        stream = ancestors.enter_context(_pinned_path(archive, read_file=True))
        bundle = ancestors.enter_context(zipfile.ZipFile(stream))
        plan = zip_extraction_plan(bundle, archive, root, expected_entries=expected_entries,
                                   check_destination=False)
        # Exclusive creation is essential: never apply this path to an existing
        # installation or merge an uninspected tree. All ZIP checks precede it.
        root.mkdir()
        ancestors.enter_context(_pinned_path(root, directory=True))

        def extract_file(item):
            entry, output = item
            # Parents stay pinned until this worker closes both streams. "xb"
            # refuses an existing file or link instead of following/overwriting it.
            with bundle.open(entry) as incoming, output.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)

        with ThreadPoolExecutor(max_workers=16) as writers:
            for start in range(0, len(plan), 64):
                with ExitStack() as directories:
                    pinned = {root}

                    def pin_directory(path):
                        if path in pinned:
                            return
                        pin_directory(path.parent)
                        try:
                            path.mkdir()
                        except FileExistsError:
                            pass
                        directories.enter_context(_pinned_path(path, directory=True))
                        pinned.add(path)

                    files = []
                    for entry, output in plan[start:start + 64]:
                        pin_directory(output if entry.is_dir() else output.parent)
                        if not entry.is_dir():
                            files.append((entry, output))
                    futures = []
                    try:
                        for item in files:
                            futures.append(writers.submit(extract_file, item))
                        for future in futures:
                            future.result()
                    finally:
                        # A failed worker must not release another worker's
                        # parent locks while it is still creating/writing files.
                        wait(futures)


def prepare_bundle(bundle: dict, version: str, cache: Path) -> Path:
    started = time.monotonic()
    bundle = validate_bundle(bundle, version)
    cache = reject_reparse_path(cache)
    archive = download_bundle(bundle, cache)
    archive_done = time.monotonic()
    workspace = Path(tempfile.mkdtemp(prefix="runtime-", dir=cache))
    candidate = workspace / "candidate"
    print("[압축 해제] 새 실행 환경의 파일을 준비합니다.", flush=True)
    extract_runtime_zip(archive, candidate, expected_entries=bundle["files"] + 1)
    extraction_done = time.monotonic()
    print("[검증] 압축 해제한 프로그램 파일을 확인합니다.", flush=True)
    verify_runtime(candidate, bundle["manifest_sha256"], version, progress=True)
    verified = time.monotonic()
    print(json.dumps({
        "status": "RUNTIME_PREPARE_TIMINGS",
        "archive_seconds": archive_done - started,
        "extraction_seconds": extraction_done - archive_done,
        "verification_seconds": verified - extraction_done,
        "total_seconds": verified - started,
    }), flush=True)
    return candidate


def prepare_pose_models(cache: Path, target: Path) -> dict:
    """Use the shared verified/resumable downloader, or retain an exact local file."""
    files = {}
    for relative, spec in runtime_contract.POSE_MODELS.items():
        destination = reject_reparse_path(target / relative)
        if destination.exists():
            if (not destination.is_file() or destination.stat().st_size != spec["size"]
                    or sha256(destination) != spec["sha256"]):
                raise ValueError(f"기존 모델을 보존했습니다. 이름 충돌을 확인해 주세요: {destination}")
            files[relative] = destination
        else:
            files[relative] = download(
                spec["url"], cache_path(cache, spec["name"], spec["sha256"]),
                spec["sha256"], spec["size"], display_name=spec["name"],
            )
    return files


def prepare_default_data(candidate: Path, manifest: dict, cache: Path, method: str,
                         include_animesharp: bool = False) -> Path:
    """Only a fresh install receives defaults; update/Repair never reset them."""
    seed = candidate.parent / "defaults"
    seed.mkdir()
    models = list(manifest["models"])
    models.extend(
        (spec["name"], spec["url"], spec["sha256"], "controlnet", spec["size"])
        for spec in runtime_contract.POSE_MODELS.values()
    )
    if include_animesharp:
        models.append(manifest["optional_animesharp"])
    for name, url, digest, relative, size in models:
        relative = normalized_path(relative)
        name = safe_leaf(name)
        cached = download(url, cache_path(cache, name, digest), digest, size, display_name=name)
        output = seed / "ComfyUI/models" / relative / name
        copy_file(cached, output)
        if output.stat().st_size != size or sha256(output) != digest.upper():
            raise ValueError(f"default model changed while copying: {name}")
    create_default_input_image(seed / "ComfyUI")
    copy_file(
        candidate / "ComfyUI/LAKIS/workflows/LAKIS_custom_v7.4_editable.json",
        seed / "ComfyUI/user/default/workflows/LAKIS_custom_v7.4.json",
    )
    settings = seed / ".lakis"
    settings.mkdir()
    (settings / "optional-models.txt").write_text(
        ("AnimeSharp V4 Fast | CC BY-NC-SA 4.0 | non-commercial | user accepted\r\n"
         if include_animesharp else "No optional non-commercial model selected.\r\n"), encoding="utf-8")
    (settings / "upscaler-license-choice.json").write_text(json.dumps({
        "choice": "animesharp" if include_animesharp else "realesrgan",
        "model": manifest["optional_animesharp"][0] if include_animesharp else "RealESRGAN_x4plus_anime_6B.pth",
        "license": "CC-BY-NC-SA-4.0" if include_animesharp else "BSD-3-Clause",
        "noncommercial_acknowledged": include_animesharp,
    }, indent=2) + "\n", encoding="utf-8")
    (settings / "install-method.txt").write_text(method + "\n", encoding="ascii")
    return seed


def install(manifest: dict, target: Path, cache: Path, mode: str, method: str,
            *, prepared_root: Path | None = None, include_animesharp: bool = False) -> dict:
    if mode not in {"fresh", "update", "repair"} or method not in {"cmd", "gui", "updater"}:
        raise ValueError("invalid runtime installation mode or caller")
    if type(include_animesharp) is not bool or (include_animesharp and (mode != "fresh" or method != "gui")):
        raise ValueError("optional model requires explicit fresh GUI installation consent")
    target = _target_path(target)
    if manifest.get("schema") != 1:
        raise ValueError("unsupported installer manifest")
    version = manifest["version"]
    bundle = validate_bundle(manifest.get("runtime_bundle"), version)
    if prepared_root is None:
        candidate = prepare_bundle(bundle, version, cache)
    else:
        candidate = reject_reparse_path(prepared_root)
        verify_runtime(candidate, bundle["manifest_sha256"], version)
    initial_data = None
    model_files = None
    if mode == "fresh":
        initial_data = prepare_default_data(candidate, manifest, cache, method, include_animesharp)
        ensure_webview2_runtime(manifest, cache)
    else:
        model_files = prepare_pose_models(cache, target)
    return activate(candidate, target, bundle["manifest_sha256"], version, mode,
                    initial_data, model_files=model_files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("fresh", "update", "repair"))
    parser.add_argument("--method", required=True, choices=("cmd", "gui", "updater"))
    parser.add_argument("--include-noncommercial-upscaler", action="store_true")
    preparation = parser.add_mutually_exclusive_group()
    preparation.add_argument("--prepare-only", action="store_true")
    preparation.add_argument("--prepared-root", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        if args.prepare_only:
            _target_path(args.target, prepare_only=True)
            candidate = prepare_bundle(manifest.get("runtime_bundle"), manifest["version"], args.cache)
            result = {"status": "prepared", "candidate": str(candidate)}
        else:
            result = install(manifest, args.target, args.cache, args.mode, args.method,
                             prepared_root=args.prepared_root,
                             include_animesharp=args.include_noncommercial_upscaler)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(f"LAKIS runtime install failed: {error}", file=sys.stderr)
        raise SystemExit(1)
