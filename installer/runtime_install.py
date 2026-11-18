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
    ensure_visual_cpp_runtime, ensure_webview2_runtime, promote_verified_partial,
    reject_reparse_path, safe_leaf, sha256, zip_extraction_plan,
)
from runtime_manifest import COMFY_VERSION, _pinned_path, normalized_path, verify_runtime
import runtime_manifest as runtime_contract
from runtime_transition import _assert_original, _target_path, activate
from application_release import compose, installer_identity, read_release_metadata

RUNTIME_HELPERS = (
    "runtime_install.py", "runtime_transition.py", "runtime_manifest.py", "runtime_health.py",
    "application_release.py",
)
SNAPREF_FRESH_VERSION = "8.1.3.2"
SNAPREF_HELPER = "ComfyUI/LAKIS/install_snapref.py"


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


def _extended_path(path: Path) -> Path:
    """Use Win32 extended paths without depending on LongPathsEnabled."""
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def extract_runtime_zip(archive: Path, destination: Path, *, expected_entries: int) -> None:
    """Extract only into a new root; pin the archive and each active ancestry."""
    archive = _extended_path(archive)
    root = _extended_path(destination)
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


def prepare_required_models(cache: Path, target: Path, version: str) -> dict:
    """Validate all destinations before downloading, retaining exact local files."""
    cache = reject_reparse_path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    files = {}
    pending = []
    cache_bytes = 0
    stage_bytes = 0
    for relative, spec in runtime_contract.required_model_specs(version).items():
        destination = reject_reparse_path(target / relative)
        if destination.exists():
            if (not destination.is_file() or destination.stat().st_size != spec["size"]
                    or sha256(destination) != spec["sha256"]):
                raise ValueError(f"기존 모델을 보존했습니다. 이름 충돌을 확인해 주세요: {destination}")
            files[relative] = destination
        else:
            cached = cache_path(cache, spec["name"], spec["sha256"])
            partial = cached.with_suffix(cached.suffix + ".part")
            allocated = 0
            for path in (cached, partial):
                reject_reparse_path(path)
                if path.exists():
                    if not path.is_file():
                        raise ValueError(f"model cache entry is not a file: {path}")
                    allocated += path.stat().st_size
            cache_bytes += max(0, spec["size"] - allocated)
            stage_bytes += spec["size"]
            pending.append((relative, spec, cached))
    # Cache and model staging can share a volume. Checking each separately
    # would overcommit that disk when the 15.5 GB MOSS set is not cached.
    same_volume = cache.stat().st_dev == target.parent.stat().st_dev
    cache_required = cache_bytes + (stage_bytes if same_volume else 0)
    if shutil.disk_usage(cache).free < cache_required:
        raise RuntimeError(f"모델 다운로드·준비 공간이 부족합니다. 캐시 볼륨에 {cache_required:,} bytes가 필요합니다.")
    if not same_volume and shutil.disk_usage(target.parent).free < stage_bytes:
        raise RuntimeError(f"모델 설치 준비 공간이 부족합니다. 설치 볼륨에 {stage_bytes:,} bytes가 필요합니다.")
    for index, (relative, spec, cached) in enumerate(pending, 1):
        print(f"[모델 준비 {index}/{len(pending)}] {spec['name']} · {spec['size']:,} bytes", flush=True)
        files[relative] = download(
            spec["url"], cached, spec["sha256"], spec["size"], display_name=spec["name"],
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
    if tuple(map(int, manifest["version"].split("."))) >= (8, 1, 0):
        copy_file(
            candidate / "ComfyUI/LAKIS/external_ui/workflows/LAKIS_MOSS_custom_v8.1_editable.json",
            seed / "ComfyUI/user/default/workflows/LAKIS_MOSS_custom_v8.1.json",
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


def prepare_fresh_snapref(candidate: Path, seed: Path, cache: Path, manifest_hash: str) -> None:
    # Use the helper already shipped in the authenticated application release.
    # Execute exactly the bytes verified here, without consulting import paths
    # or changing the legacy updater's separately pinned copy of this helper.
    manifest = reject_reparse_path(candidate / runtime_contract.MANIFEST_NAME).read_bytes()
    if hashlib.sha256(manifest).hexdigest().upper() != manifest_hash.upper():
        raise ValueError("runtime manifest hash mismatch")
    inventory = runtime_contract.validate_runtime_manifest(json.loads(manifest), SNAPREF_FRESH_VERSION)
    entry = inventory.get(SNAPREF_HELPER.casefold())
    if entry is None:
        raise ValueError("SnapRef helper is missing from the pinned application manifest")
    helper = reject_reparse_path(candidate / entry["path"])
    source = helper.read_bytes()
    if len(source) != entry["size"] or hashlib.sha256(source).hexdigest().upper() != entry["sha256"].upper():
        raise ValueError("SnapRef helper integrity mismatch")
    pins = {"__name__": "_lakis_fresh_snapref", "__file__": str(helper)}
    exec(compile(source, str(helper), "exec"), pins)

    print("[SnapRef] v2a · CircleStone Labs Non-Commercial License v1.2 (비상업·비프로덕션). "
          "레퍼런스 첫 사용 시 별도 동의가 필요합니다.", flush=True)
    print(f"{pins['WEIGHT_LICENSE_URL']}\n{pins['WEIGHT_NOTICE_URL']}", flush=True)
    print("[SnapRef] 공식 추론 노드와 라이선스·고지문 확인", flush=True)
    files = pins["inference_files"]()
    name, size, expected = pins["WEIGHT_NAME"], pins["WEIGHT_SIZE"], pins["WEIGHT_SHA256"].upper()
    cached = cache_path(cache, name, expected)
    staged = seed / "ComfyUI/models/loras" / name
    with cache_entry_lock(cached, name):
        reject_reparse_path(cached)
        if cached.is_file() and cached.stat().st_size == size and sha256(cached) == expected:
            print(f"[SnapRef] 검증된 가중치 재사용 · {name}", flush=True)
        else:
            print(f"[SnapRef] 공식 가중치 다운로드 · {size:,} bytes", flush=True)
            with tempfile.TemporaryDirectory(prefix=".lakis-snapref-", dir=cached.parent) as work:
                partial = Path(work) / name
                pins["download_weight"](partial)
                promote_verified_partial(partial, cached, name)
        copy_file(cached, staged)
    if staged.stat().st_size != size or sha256(staged) != expected:
        raise ValueError("SnapRef weight changed during staging")
    node = seed / runtime_contract.SNAPREF_NODE
    node.mkdir(parents=True)
    for name, data in files.items():
        path = node / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
    print("[SnapRef] 가중치와 추론 노드 검증 완료", flush=True)


def prepare_candidate(manifest: dict, cache: Path, *, target: Path | None = None,
                      mode: str | None = None, metadata=None) -> Path:
    bundle, release, _, _ = installer_identity(manifest)
    if release and metadata is None:
        metadata = read_release_metadata(bundle, release, cache)
    if target is not None:
        target = _target_path(target, prepare_only=True)
        if mode not in {"fresh", "update", "repair"}:
            raise ValueError("invalid runtime preparation mode")
        if mode != "fresh" and metadata is not None:
            contract = metadata["editable_templates"]
            runtime_contract.check_editable_template_compatibility(
                runtime_contract.editable_template_snapshot(target, contract), contract)
    baseline = prepare_bundle(bundle, bundle["version"], cache)
    return compose(baseline, bundle, release, cache, metadata=metadata) if release else baseline


def install(manifest: dict, target: Path, cache: Path, mode: str, method: str,
            *, prepared_root: Path | None = None, include_animesharp: bool = False) -> dict:
    if mode not in {"fresh", "update", "repair"} or method not in {"cmd", "gui", "updater"}:
        raise ValueError("invalid runtime installation mode or caller")
    if type(include_animesharp) is not bool or (include_animesharp and (mode != "fresh" or method != "gui")):
        raise ValueError("optional model requires explicit fresh GUI installation consent")
    target = _target_path(target)
    bundle, release, version, manifest_hash = installer_identity(manifest)
    metadata = read_release_metadata(bundle, release, cache) if release else None
    if mode != "fresh" and metadata is not None:
        contract = metadata["editable_templates"]
        runtime_contract.check_editable_template_compatibility(
            runtime_contract.editable_template_snapshot(target, contract), contract)
    # Reject an unrelated target before installing a system prerequisite.
    # Activation repeats the identity check under its transaction lock.
    _assert_original(target, version, mode)
    ensure_visual_cpp_runtime(manifest, cache)
    if prepared_root is None:
        candidate = prepare_candidate(manifest, cache, metadata=metadata)
    else:
        candidate = reject_reparse_path(prepared_root)
        verified = verify_runtime(candidate, manifest_hash, version)
        if release and verified["source_revision"].lower() != release["source_revision"].lower():
            raise ValueError("application source revision mismatch")
    initial_data = None
    model_files = None
    if mode == "fresh":
        initial_data = prepare_default_data(candidate, manifest, cache, method, include_animesharp)
        if version == SNAPREF_FRESH_VERSION and method in {"cmd", "gui"}:
            prepare_fresh_snapref(candidate, initial_data, cache, manifest_hash)
        ensure_webview2_runtime(manifest, cache)
    else:
        model_files = prepare_required_models(cache, target, version)
    return activate(candidate, target, manifest_hash, version, mode,
                    initial_data, model_files=model_files,
                    editable_contract=metadata["editable_templates"] if metadata else None)


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
            candidate = prepare_candidate(manifest, args.cache, target=args.target, mode=args.mode)
            result = {"status": "prepared", "candidate": str(candidate)}
        else:
            result = install(manifest, args.target, args.cache, args.mode, args.method,
                             prepared_root=args.prepared_root,
                             include_animesharp=args.include_noncommercial_upscaler)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(f"LAKIS runtime install failed: {error}", file=sys.stderr)
        raise SystemExit(1)
