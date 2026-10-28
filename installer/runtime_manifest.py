"""File contract shared by fresh, update and repair runtime candidates.

The manifest hash must come from the verified release descriptor, not from
the candidate being checked. User data is never part of the release payload.
"""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, ExitStack
import ctypes
from ctypes import wintypes
import json
import msvcrt
import os
from pathlib import Path
import re
import shutil

from lakis_cmd_installer import (
    reject_reparse_path, sha256, validate_windows_component,
)

MANIFEST_NAME = "RUNTIME_SHA256SUMS.json"
COMFY_VERSION = "0.42.0"
COMFY_COMMIT = "355cd6b14c92c19ac3188fe528e47a3f21ef5178"
# Publisher downloads, not entries in the release-owned program manifest.
POSE_MODELS = {
    "ComfyUI/models/controlnet/anima_3dpose_6200.safetensors": {
        "name": "anima_3dpose_6200.safetensors",
        "url": "https://huggingface.co/toyxyz/Anima_ControlNet-LLLite/resolve/37f3a4b6574f1dce3dfe3b5440285a39b11b3d8d/anima_3dpose_6200.safetensors",
        "sha256": "97542346A658D23CA65368B568AA9AAF2486CCDA8942612983AAFFDC986CD495",
        "size": 51133576,
    },
    "ComfyUI/models/controlnet/anima_regional_4335.safetensors": {
        "name": "anima_regional_4335.safetensors",
        "url": "https://huggingface.co/toyxyz/Anima_ControlNet-LLLite/resolve/37f3a4b6574f1dce3dfe3b5440285a39b11b3d8d/anima_regional_4335.safetensors",
        "sha256": "E907EA9259B324A11C94E5767420A6A46C6A9D86597DF5CCF9B1AD5EEB817618",
        "size": 51133584,
    },
}
PROTECTED_DIRECTORIES = (
    ".lakis", "ComfyUI/models", "ComfyUI/input", "ComfyUI/output",
    "ComfyUI/user", "ComfyUI/temp",
    "ComfyUI/custom_nodes/was-ns/workflows", "ComfyUI/custom_nodes/was-ns/cache",
    "ComfyUI/custom_nodes/comfyui-impact-pack/custom_wildcards",
)
PROTECTED_FILES = (
    "LAKIS_OUTPUT_DIRECTORY.txt", "ComfyUI/extra_model_paths.yaml",
    "ComfyUI/LAKIS/external_ui_user_state.json",
    "ComfyUI/custom_nodes/comfyui-custom-scripts/pysssss.json",
    "ComfyUI/custom_nodes/was-ns/was_suite_config.json",
    "ComfyUI/custom_nodes/was-ns/was_suite_settings.json",
    "ComfyUI/custom_nodes/was-ns/was_history.json",
    "ComfyUI/custom_nodes/was-ns/styles.json",
    "ComfyUI/custom_nodes/was-ns/nsp_pantry.json",
    "ComfyUI/custom_nodes/comfyui-impact-pack/impact-pack.ini",
    "ComfyUI/custom_nodes/comfyui-impact-pack/modules/impact/impact-pack.ini",
)
GENERATED_PATHS = (
    "ComfyUI/LAKIS/launcher_logs", "ComfyUI/LAKIS/lakis_launcher_state.json",
)
REQUIRED_FILES = (
    "VERSION", "LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Desktop.exe",
    "python_embeded/python.exe", "ComfyUI/main.py",
    "ComfyUI/LAKIS/STOP_AUTOMATION",
    "ComfyUI/LAKIS/external_ui/launch_lakis.py",
    "ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.4.json",
    "LAKIS_Patcher.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe", "LAKIS.ico",
    "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll",
    "LICENSE.md", "THIRD_PARTY_NOTICES.md",
    "third_party_licenses/Microsoft-WebView2-SDK-1.0.4191.47-LICENSE.txt",
    "third_party_licenses/NVIDIA-CUDA-13.0.0-EULA.md",
    "third_party_licenses/NVIDIA-cuDNN-9.24.0-EULA.md",
)


def pose_model_rows(model_files, target: Path) -> list[dict]:
    """Allow only missing, pinned defaults; never replace an existing model."""
    if model_files is None:
        return []
    if not isinstance(model_files, dict) or set(model_files) != set(POSE_MODELS):
        raise ValueError("unexpected pose model download set")
    rows = []
    for relative, spec in POSE_MODELS.items():
        source = reject_reparse_path(Path(model_files[relative]))
        if (not source.is_file() or source.stat().st_size != spec["size"]
                or sha256(source) != spec["sha256"]):
            raise ValueError(f"pose model download failed verification: {spec['name']}")
        destination = reject_reparse_path(target / relative)
        if destination.exists():
            if (not destination.is_file() or destination.stat().st_size != spec["size"]
                    or sha256(destination) != spec["sha256"]):
                raise ValueError(f"기존 모델을 보존했습니다. 이름 충돌을 확인해 주세요: {destination}")
            continue
        rows.append({"path": relative, "source": source, "size": spec["size"],
                     "sha256": spec["sha256"]})
    return rows


def normalized_path(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("runtime path must be a string")
    parts = value.replace("\\", "/").split("/")
    for part in parts:
        validate_windows_component(part)
    return "/".join(parts)


def protected_path(relative: str) -> bool:
    path = relative.casefold()
    return (
        path in {name.casefold() for name in PROTECTED_FILES}
        or any(path == name.casefold() or path.startswith(name.casefold() + "/")
               for name in PROTECTED_DIRECTORIES)
    )


def generated_path(relative: str) -> bool:
    path = relative.casefold()
    return (any(part.casefold() in {".git", "__pycache__"} for part in relative.split("/"))
            or any(path == name.casefold() or path.startswith(name.casefold() + "/")
                   for name in GENERATED_PATHS))


_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_open = _kernel.CreateFileW
_open.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_open.restype = wintypes.HANDLE
_close = _kernel.CloseHandle
_close.argtypes = [wintypes.HANDLE]
_close.restype = wintypes.BOOL
_attributes = _kernel.GetFileInformationByHandleEx
_attributes.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_attributes.restype = wintypes.BOOL


class _AttributeTag(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]


@contextmanager
def _pinned_path(path, *, directory=False, read_file=False):
    """Reject links on the opened object and hold its name/content stable.

    Parents remain pinned by the caller. FILE_SHARE_READ excludes concurrent
    writes, deletes, renames and reparse-point changes, rather than trusting a
    cached path check. BACKUP_SEMANTICS permits directories; OPEN_REPARSE_POINT
    opens a link itself so it can be rejected without following it.
    """
    # A metadata-only handle does not enforce data sharing restrictions.
    # Keep GENERIC_READ: the verifier must exclude writers, not just see names.
    handle = _open(str(path), 0x80000000, 1, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.WinError(ctypes.get_last_error())
        error.filename = str(path)
        raise error
    try:
        info = _AttributeTag()
        if not _attributes(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            error.filename = str(path)
            raise error
        if info.attributes & 0x400:
            raise RuntimeError(f"unsafe reparse path: {path}")
        is_directory = bool(info.attributes & 0x10)
        if directory and not is_directory:
            raise ValueError(f"runtime parent is not a directory: {path}")
        if read_file:
            if is_directory:
                raise ValueError(f"runtime file became a directory: {path}")
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None  # The CRT descriptor now owns the same pinned handle.
            with os.fdopen(descriptor, "rb") as stream:
                yield stream
        else:
            yield is_directory
    finally:
        if handle is not None:
            _close(handle)


def _runtime_file_batches(root: Path, *, allow_user_data: bool, scopes=None, batch_size=1):
    """Keep directory ancestors pinned until the consumer finishes each batch."""
    root = Path(os.path.abspath(root))
    active_directories = []
    retained = set()
    batch_pins = ExitStack()

    def included(relative):
        if relative == MANIFEST_NAME:
            return False
        if protected_path(relative):
            if not allow_user_data:
                raise ValueError(f"user data in runtime payload: {relative}")
            return False
        return not generated_path(relative)

    def visit(path, relative):
        if not included(relative):
            return
        with _pinned_path(path) as directory:
            if directory:
                active_directories.append(path)
                try:
                    yield from walk(path, relative)
                finally:
                    active_directories.pop()
            else:
                yield relative, path

    def walk(parent, relative):
        with os.scandir(parent) as entries:
            for entry in entries:
                child = normalized_path((relative + "/" if relative else "") + entry.name)
                if not included(child):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    yield from visit(parent / entry.name, child)
                else:
                    yield child, parent / entry.name

    def files():
        if scopes is None:
            yield from walk(root, "")
        else:
            for value in scopes:
                relative = normalized_path(value)
                if protected_path(relative) or generated_path(relative):
                    raise ValueError(f"non-release verification scope: {relative}")
                with ExitStack() as parents:
                    depth = len(active_directories)
                    try:
                        parent = root
                        for name in relative.split("/")[:-1]:
                            parent = parent / name
                            parents.enter_context(_pinned_path(parent, directory=True))
                            active_directories.append(parent)
                        yield from visit(root / relative, relative)
                    finally:
                        del active_directories[depth:]

    with ExitStack() as ancestors, batch_pins:
        for parent in reversed(root.parents):
            ancestors.enter_context(_pinned_path(parent, directory=True))
        ancestors.enter_context(_pinned_path(root, directory=True))
        batch = []
        with closing(files()) as source:
            for relative, path in source:
                # Traversal may leave a small directory before this batch is
                # full. Retain its complete ancestry first, while the original
                # traversal handles are still held. Only this bounded batch's
                # directories are retained, not the entire runtime tree.
                for directory in active_directories:
                    if directory not in retained:
                        batch_pins.enter_context(_pinned_path(directory, directory=True))
                        retained.add(directory)
                batch.append((relative, path))
                if len(batch) == batch_size:
                    yield batch
                    batch = []
                    batch_pins.close()
                    retained.clear()
            if batch:
                yield batch


def runtime_files(root: Path, *, allow_user_data: bool, scopes=None):
    """Yield immutable, regular files while their complete ancestry is pinned."""
    with closing(_runtime_file_batches(root, allow_user_data=allow_user_data, scopes=scopes)) as batches:
        for batch in batches:
            for relative, path in batch:
                with _pinned_path(path) as directory:
                    if directory:
                        raise ValueError(f"runtime file became a directory: {relative}")
                    yield relative, path


def _validate_identity(manifest: dict, expected_version: str) -> None:
    if (not isinstance(expected_version, str)
            or not re.fullmatch(r"\d+\.\d+\.\d+", expected_version)):
        raise ValueError("invalid LAKIS runtime version")
    if (manifest.get("schema") != 1 or manifest.get("product") != "LAKIS"
            or manifest.get("version") != expected_version):
        raise ValueError("runtime manifest identity mismatch")
    runtime = manifest.get("runtime", {})
    if (runtime.get("comfyui_version") != COMFY_VERSION
            or runtime.get("comfyui_commit") != COMFY_COMMIT):
        raise ValueError("unexpected ComfyUI runtime identity")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", str(manifest.get("source_revision", ""))):
        raise ValueError("invalid LAKIS source revision")


def create_manifest(root: Path, version: str, source_revision: str, runtime: dict) -> dict:
    """Inventory a prepared candidate without writing or changing its files."""
    result = {
        "schema": 1, "product": "LAKIS", "version": version,
        "source_revision": source_revision, "runtime": runtime, "files": [],
    }
    _validate_identity(result, version)
    seen = set()
    for relative, path in runtime_files(root, allow_user_data=True):
        key = relative.casefold()
        if key in seen:
            raise ValueError(f"duplicate runtime path: {relative}")
        seen.add(key)
        result["files"].append({
            "path": relative, "size": path.stat().st_size, "sha256": sha256(path),
        })
    result["files"].sort(key=lambda row: row["path"])
    missing = {name.casefold() for name in REQUIRED_FILES} - seen
    if missing:
        raise ValueError(f"incomplete runtime: {sorted(missing)}")
    if (root / "VERSION").read_text(encoding="utf-8-sig").strip() != version:
        raise ValueError("runtime VERSION mismatch")
    return result


def _stream_digest(stream, destination=None):
    """Hash the exact bytes read, optionally persisting them before returning."""
    if destination is None:
        return hashlib.file_digest(stream, "sha256").hexdigest()
    destination = reject_reparse_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_reparse_path(destination)
    digest = hashlib.sha256()
    with destination.open("xb") as outgoing:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            outgoing.write(block)
            digest.update(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    return digest.hexdigest()


def verify_runtime(root: Path, expected_hash: str, expected_version: str,
                   *, allow_user_data: bool = False, scopes=None, progress=False,
                   stage_root=None) -> dict:
    root = reject_reparse_path(root)
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_hash):
        raise ValueError("trusted runtime manifest hash is required")
    path = reject_reparse_path(root / MANIFEST_NAME)
    raw_manifest = path.read_bytes()
    if hashlib.sha256(raw_manifest).hexdigest().upper() != expected_hash.upper():
        raise ValueError("runtime manifest hash mismatch")
    manifest = json.loads(raw_manifest.decode("utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid runtime manifest")
    _validate_identity(manifest, expected_version)
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("empty runtime manifest")
    expected = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid runtime entry")
        relative = normalized_path(entry.get("path"))
        key = relative.casefold()
        if key in expected:
            raise ValueError(f"duplicate runtime path: {relative}")
        if relative == MANIFEST_NAME or protected_path(relative) or generated_path(relative):
            raise ValueError(f"non-release path in manifest: {relative}")
        if (type(entry.get("size")) is not int or entry["size"] < 0
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[a-fA-F0-9]{64}", entry["sha256"])):
            raise ValueError(f"invalid runtime file contract: {relative}")
        expected[key] = entry
    missing = {name.casefold() for name in REQUIRED_FILES} - expected.keys()
    if missing:
        raise ValueError(f"incomplete runtime: {sorted(missing)}")
    if stage_root is not None:
        stage_root = reject_reparse_path(stage_root)
        if (allow_user_data or scopes is not None or stage_root == root
                or root in stage_root.parents or stage_root in root.parents):
            raise ValueError("staging requires a separate complete release payload")
        required = sum(entry["size"] for entry in entries) + len(raw_manifest)
        if shutil.disk_usage(stage_root.parent).free < required:
            raise RuntimeError("not enough space for new program files")
        stage_root.mkdir()

    def verify_file(item):
        relative, actual = item
        entry = expected[relative.casefold()]
        destination = stage_root / relative if stage_root is not None else None
        with _pinned_path(actual, read_file=True) as stream:
            if (os.fstat(stream.fileno()).st_size != entry["size"]
                    or _stream_digest(stream, destination).upper() != entry["sha256"].upper()):
                raise ValueError(f"runtime file mismatch: {relative}")

    found, last_report = set(), 0
    # Sixteen readers and 64 queued files bound I/O and memory. Small directories
    # can share a batch, but every reader finishes before its ancestry is released.
    with closing(_runtime_file_batches(root, allow_user_data=allow_user_data, scopes=scopes,
                                       batch_size=64)) as batches:
        with ThreadPoolExecutor(max_workers=16) as readers:
            for batch in batches:
                for relative, _ in batch:
                    key = relative.casefold()
                    if key in found:
                        raise ValueError(f"duplicate runtime path: {relative}")
                    found.add(key)
                    if key not in expected:
                        raise ValueError(f"unlisted runtime file: {relative}")
                list(readers.map(verify_file, batch))
                if progress and (not last_report or len(found) - last_report >= 256 or len(found) == len(expected)):
                    print(f"[검증] 프로그램 파일 {len(found):,}/{len(expected):,}", flush=True)
                    last_report = len(found)
    if expected.keys() - found:
        raise ValueError(f"missing runtime files: {sorted(expected.keys() - found)}")
    if (root / "VERSION").read_text(encoding="utf-8-sig").strip() != expected_version:
        raise ValueError("runtime VERSION mismatch")
    if stage_root is not None and (stage_root / "VERSION").read_text(encoding="utf-8-sig").strip() != expected_version:
        raise ValueError("staged runtime VERSION mismatch")
    return manifest
