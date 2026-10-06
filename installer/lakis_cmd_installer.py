"""Zero-PowerShell companion for LAKIS_CMD_Install.cmd.

The CMD bootstrap verifies and extracts the pinned ComfyUI portable archive.
This script then runs with that embedded Python, downloads only allowlisted
artifacts, verifies every byte, and promotes the completed staging tree.
"""

from __future__ import annotations

import argparse
import binascii
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import msvcrt
import os
import re
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
import zipfile
import zlib


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def transient_file_error(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EBUSY, errno.EPERM} or getattr(error, "winerror", None) in {5, 32, 33}


def cache_verification_error(path: Path, display_name: str, error: OSError) -> RuntimeError:
    winerror = getattr(error, "winerror", None)
    if winerror in {225, 226}:
        return RuntimeError(
            f"CACHE_SECURITY_BLOCKED: Windows 보안 또는 보안 프로그램이 다운로드 파일을 차단하거나 제거했습니다. "
            f"보안 프로그램의 보호 기록에서 파일과 탐지 내용을 확인해 주세요. "
            f"파일 검증을 완료하지 못해 설치를 중단했습니다. {display_name}: winerror={winerror}, path={path}"
        )
    return RuntimeError(
        f"CACHE_VERIFY_OPEN_FAILED: {display_name}: {type(error).__name__}: "
        f"errno={error.errno}, winerror={winerror}, path={path}"
    )


def sha256_with_retry(path: Path, display_name: str) -> str:
    last_error: OSError | None = None
    for attempt in range(1, 6):
        try:
            return sha256(path)
        except OSError as error:
            last_error = error
            if getattr(error, "winerror", None) in {225, 226} or not transient_file_error(error):
                raise cache_verification_error(path, display_name, error) from error
            if attempt < 5:
                time.sleep(attempt * 0.2)
    assert last_error is not None
    raise cache_verification_error(path, display_name, last_error) from last_error


def safe_relative(value: str) -> Path:
    relative = Path(value.replace("/", os.sep))
    if relative.is_absolute() or relative.drive or relative.root or ":" in value or ".." in relative.parts or not relative.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return relative


WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
    "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³",
}


def validate_windows_component(value: str) -> None:
    if (not value or value in {".", ".."} or any(ord(character) < 32 for character in value)
            or any(character in '<>:"/\\|?*' for character in value)
            or value.endswith((".", " "))
            or value.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES):
        raise ValueError(f"unsafe Windows path component: {value}")


def safe_leaf(value: str) -> str:
    relative = safe_relative(value)
    if len(relative.parts) != 1:
        raise ValueError(f"unsafe file name: {value}")
    validate_windows_component(relative.name)
    return relative.name


def cache_path(cache: Path, display_name: str, expected_hash: str) -> Path:
    """Return a short, manifest-independent Windows cache path."""
    digest = expected_hash.strip().upper()
    if len(digest) != 64 or any(character not in "0123456789ABCDEF" for character in digest):
        raise ValueError(f"invalid SHA-256 for cache entry: {display_name}")
    suffix = Path(display_name).suffix.casefold()
    if suffix not in {".zip", ".7z", ".exe", ".json", ".safetensors", ".pth", ".bin"}:
        suffix = ".bin"
    return cache / f"a-{digest}{suffix}"


@contextmanager
def cache_entry_lock(destination: Path, display_name: str, timeout_seconds: float = 14400.0):
    """Serialize one content-addressed cache entry across installer processes."""
    lock_path = destination.with_suffix(destination.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    acquired = False
    deadline = time.monotonic() + timeout_seconds
    last_notice = 0.0
    try:
        while handle is None:
            try:
                handle = lock_path.open("a+b")
            except OSError as error:
                if not transient_file_error(error) or time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"CACHE_LOCK_FAILED: {display_name}: {type(error).__name__}: "
                        f"errno={error.errno}, winerror={getattr(error, 'winerror', None)}, path={lock_path}"
                    ) from error
                now = time.monotonic()
                if now - last_notice >= 5.0:
                    print(f"  [대기] 다른 설치기가 캐시를 사용 중입니다: {display_name}", flush=True)
                    last_notice = now
                time.sleep(0.2)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        while not acquired:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError as error:
                if not transient_file_error(error) or time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"CACHE_LOCK_FAILED: {display_name}: {type(error).__name__}: "
                        f"errno={error.errno}, winerror={getattr(error, 'winerror', None)}, path={lock_path}"
                    ) from error
                now = time.monotonic()
                if now - last_notice >= 5.0:
                    print(f"  [대기] 다른 설치기가 캐시를 사용 중입니다: {display_name}", flush=True)
                    last_notice = now
                time.sleep(0.2)
        yield
    finally:
        if acquired:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        if handle is not None:
            handle.close()


def promote_verified_partial(partial: Path, destination: Path, display_name: str) -> None:
    """Atomically publish a verified download, tolerating short AV/indexer locks."""
    last_error: OSError | None = None
    for attempt in range(1, 6):
        try:
            os.replace(partial, destination)
            return
        except OSError as error:
            last_error = error
            if not transient_file_error(error):
                raise RuntimeError(
                    f"CACHE_PROMOTE_FAILED: {display_name}: {type(error).__name__}: "
                    f"errno={error.errno}, winerror={getattr(error, 'winerror', None)}, path={partial}"
                ) from error
            if attempt < 5:
                time.sleep(attempt * 0.2)
    assert last_error is not None
    raise RuntimeError(
        f"CACHE_PROMOTE_FAILED: {display_name}: {type(last_error).__name__}: "
        f"errno={last_error.errno}, winerror={getattr(last_error, 'winerror', None)}, "
        f"path={partial}"
    ) from last_error


def download(
    url: str,
    destination: Path,
    expected_hash: str,
    expected_bytes: int = 0,
    max_attempts: int = 6,
    display_name: str | None = None,
) -> Path:
    label = display_name or destination.name
    with cache_entry_lock(destination, label):
        return _download_locked(url, destination, expected_hash, expected_bytes, max_attempts, label)


class InvalidContentRangeError(ValueError):
    """The response cannot be safely appended to a partial download."""


class InvalidDownloadOriginError(ValueError):
    """An external download left the approved HTTPS origins."""


def validate_download_origin(requested: str, final: str) -> None:
    original, target = urllib.parse.urlsplit(requested), urllib.parse.urlsplit(final)
    if original.scheme == target.scheme == "file" and requested == final:
        return  # Explicit local fixtures are not network downloads.
    hosts = {"github.com", "api.github.com", "codeload.github.com", "raw.githubusercontent.com",
             "objects.githubusercontent.com", "release-assets.githubusercontent.com", "cdn.jsdelivr.net",
             "huggingface.co", "go.microsoft.com", "msedge.sf.dl.delivery.mp.microsoft.com"}
    for value in (original, target):
        local = value.scheme == "http" and value.hostname in {"127.0.0.1", "localhost", "::1"}
        approved = value.hostname in hosts or (value.hostname or "").endswith(".hf.co")
        if value.username or value.password or not (local or value.scheme == "https" and approved):
            raise InvalidDownloadOriginError("DOWNLOAD_ORIGIN_INVALID: unapproved download origin")


def validate_content_range(value: str, offset: int, expected: int, content_length: int) -> int:
    match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", value or "")
    if match:
        start, end, total = map(int, match.groups())
        if (start == offset and end >= start and end == total - 1
                and (not expected or total == expected)
                and (content_length < 0 or content_length == end - start + 1)):
            return total
    raise InvalidContentRangeError("DOWNLOAD_RANGE_INVALID: invalid Content-Range response")


def _download_locked(
    url: str,
    destination: Path,
    expected_hash: str,
    expected_bytes: int,
    max_attempts: int,
    label: str,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if (not expected_bytes or destination.stat().st_size == expected_bytes) and sha256_with_retry(destination, label) == expected_hash:
            print(f"  [확인] {label}", flush=True)
            return destination
        destination.unlink()
    partial = destination.with_suffix(destination.suffix + ".part")
    # A previous process can stop after the last byte but before promotion.
    # Avoid requesting a range past EOF (HTTP 416) on every subsequent run.
    if partial.is_file() and (not expected_bytes or partial.stat().st_size >= expected_bytes):
        if (not expected_bytes or partial.stat().st_size == expected_bytes) and sha256_with_retry(partial, label) == expected_hash:
            promote_verified_partial(partial, destination, label)
            print(f"  [확인] {label}", flush=True)
            return destination
        if expected_bytes:
            partial.unlink()
    print(f"  [다운로드] {label}", flush=True)
    last_error: Exception | None = None
    progress_visible = False
    for attempt in range(1, max_attempts + 1):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "LAKIS-CMD-Installer/1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            validate_download_origin(url, url)
            with urllib.request.urlopen(request, timeout=120) as response:
                validate_download_origin(url, response.geturl() if hasattr(response, "geturl") else url)
                response_size = int(response.headers.get("Content-Length") or -1)
                range_total = 0
                if getattr(response, "status", None) == 206:
                    range_total = validate_content_range(
                        response.headers.get("Content-Range"), offset, expected_bytes, response_size)
                resumed = offset > 0 and getattr(response, "status", None) == 206
                if offset and not resumed:
                    offset = 0
                mode = "ab" if resumed else "wb"
                total = expected_bytes or range_total or (offset + response_size if response_size > 0 else 0)
                received = offset
                last_percent = int(received * 100 / total) if total else -1
                progress_frame = 0
                progress_glyphs = "/-\\|"
                with partial.open(mode) as output:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        received += len(block)
                        percent = int(received * 100 / total) if total else -1
                        if percent >= 0 and percent // 2 != last_percent // 2:
                            glyph = progress_glyphs[progress_frame % len(progress_glyphs)]
                            progress_frame += 1
                            print(
                                f"\r        {label} {percent:3d}%  {glyph}",
                                end="",
                                flush=True,
                            )
                            progress_visible = True
                            last_percent = percent
            if progress_visible:
                print(flush=True)
                progress_visible = False
            break
        except Exception as error:
            if isinstance(error, InvalidDownloadOriginError):
                raise
            last_error = error
            if (isinstance(error, InvalidContentRangeError)
                    or isinstance(error, urllib.error.HTTPError) and error.code == 416):
                # A hash-verified complete partial was handled above. This
                # range is unusable; restart this bounded download attempt.
                partial.unlink(missing_ok=True)
            if progress_visible:
                print(flush=True)
                progress_visible = False
            if attempt == max_attempts:
                raise RuntimeError(
                    f"download failed after {max_attempts} attempts: {label}: "
                    f"{type(error).__name__}: {error}"
                ) from error
            saved = partial.stat().st_size if partial.exists() else 0
            print(
                f"        연결이 끊어졌습니다. 이어받기 재시도 {attempt}/{max_attempts - 1} "
                f"(저장됨: {saved:,} bytes)",
                flush=True,
            )
            time.sleep(min(attempt * 2, 10))
    else:  # pragma: no cover - the loop either breaks or raises
        raise RuntimeError(f"download failed: {label}: {last_error}")
    if expected_bytes and partial.stat().st_size != expected_bytes:
        raise RuntimeError(f"CACHE_SIZE_FAILED: {label}")
    print(f"  [검증] {label}", flush=True)
    actual_hash = sha256_with_retry(partial, label)
    if actual_hash != expected_hash:
        partial.unlink()
        raise RuntimeError(f"SHA-256 verification failed: {label}")
    promote_verified_partial(partial, destination, label)
    print(f"  [캐시 확정] {label}", flush=True)
    return destination


RVTOOLS_ZIP_SHA256 = "AC92C92CF6454E850E6A2B5053D13962BC2936539F669B910C4A49EDB875ECBD"
RVTOOLS_EXAMPLE = "ComfyUI-RvTools_v2-d3f7e8beb477dff6c0fac44b298ab74ac433d93e/workflow/Workflow.png"


def extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        # The verified upstream ZIP has two distinct example PNGs whose names
        # differ only by case. Preserve both on Windows, without accepting
        # ambiguous paths in any other archive or changing runtime files.
        remap_example = (RVTOOLS_EXAMPLE in bundle.namelist()
                         and sha256_with_retry(archive, "rvtools.zip") == RVTOOLS_ZIP_SHA256)
        for entry in bundle.infolist():
            normalized = entry.filename.replace("\\", "/")
            if remap_example and entry.filename == RVTOOLS_EXAMPLE:
                normalized = normalized.removesuffix("Workflow.png") + "Workflow-example.png"
            trimmed = normalized.rstrip("/")
            parts = trimmed.split("/") if trimmed else []
            if not parts or normalized.startswith("/"):
                raise RuntimeError(f"unsafe ZIP path: {entry.filename}")
            try:
                for part in parts:
                    validate_windows_component(part)
            except ValueError as error:
                raise RuntimeError(f"unsafe ZIP path: {entry.filename}") from error
            identity = "/".join(parts).casefold()
            if identity in seen:
                raise RuntimeError(f"duplicate Windows ZIP path: {entry.filename}")
            seen.add(identity)
            output = destination.joinpath(*parts).resolve()
            try:
                output.relative_to(root)
            except ValueError as error:
                raise RuntimeError(f"unsafe ZIP path: {entry.filename}") from error
            if entry.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)


def only_directory(root: Path) -> Path:
    entries = [entry for entry in root.iterdir() if entry.is_dir()]
    if len(entries) != 1:
        raise RuntimeError(f"archive must contain one root directory: {root}")
    return entries[0]


def install_archive(archive: Path, destination: Path, scratch: Path) -> None:
    if scratch.exists():
        shutil.rmtree(scratch)
    extract_zip(archive, scratch)
    source = only_directory(scratch)
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise RuntimeError(f"required source directory is missing: {source}")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def create_default_input_image(comfy_root: Path) -> Path:
    width, height = 1536, 1024
    background = (26, 29, 42)
    circle = (106, 90, 205)  # System.Drawing Brushes.SlateBlue
    center_x, center_y, radius = 768, 328, 228
    rows = []
    for y in range(height):
        row = bytearray()
        dy = y - center_y
        for x in range(width):
            color = circle if (x - center_x) ** 2 + dy ** 2 <= radius ** 2 else background
            row.extend(color)
        rows.append(b"\x00" + bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )
    destination = comfy_root / "input" / "LAKIS_1_2026-09-01-221228.webp"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(png)
    return destination


def install_release_source(source_root: Path, portable_root: Path) -> None:
    comfy = portable_root / "ComfyUI"
    custom = comfy / "custom_nodes"
    inventory = source_root / "resources" / "PRODUCTION_NODE_PACKAGES.txt"
    package_names = []
    for raw in inventory.read_text(encoding="utf-8-sig").splitlines():
        name = raw.strip()
        if not name or name.startswith("#"):
            continue
        if not name.replace("-", "").replace("_", "").isalnum() or name in package_names:
            raise RuntimeError(f"invalid managed node package: {name}")
        package_names.append(name)
    if not package_names:
        raise RuntimeError("managed node inventory is empty")
    for name in package_names:
        package = source_root / "src" / "custom_nodes" / name
        if not (package / "__init__.py").is_file():
            raise RuntimeError(f"required managed node package is missing: {name}")
        copy_tree(package, custom / name)

    runtime = comfy / "LAKIS"
    copy_tree(source_root / "src" / "external_ui", runtime / "external_ui")
    runtime.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "resources" / "STOP_AUTOMATION", runtime / "STOP_AUTOMATION")
    shutil.copy2(source_root / "src" / "runtime" / "sync_runtime_workflow.py", runtime / "sync_runtime_workflow.py")
    workflows = runtime / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    for name in (
        "LAKIS_runtime_api_v7.4.json",
        "LAKIS_runtime_visual_v7.4.json",
        "LAKIS_custom_v7.4_editable.json",
    ):
        shutil.copy2(source_root / "workflows" / name, workflows / name)
    user_workflows = comfy / "user" / "default" / "workflows"
    user_workflows.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        source_root / "workflows" / "LAKIS_custom_v7.4_editable.json",
        user_workflows / "LAKIS_custom_v7.4.json",
    )
    shutil.copy2(source_root / "LICENSE.md", portable_root / "LICENSE.md")
    shutil.copy2(source_root / "THIRD_PARTY_NOTICES.md", portable_root / "THIRD_PARTY_NOTICES.md")
    copy_tree(source_root / "third_party_licenses", portable_root / "third_party_licenses")
    spectrum = custom / "comfyui-spectrum-ksampler"
    spectrum.mkdir(parents=True, exist_ok=True)
    for name in ("nodes.py", "spectrum.py"):
        shutil.copy2(
            source_root / "patches" / "ComfyUI-Spectrum-KSampler" / "files" / name,
            spectrum / name,
        )


def validate_layout(root: Path, layout_path: Path) -> tuple[int, list[str]]:
    layout = json.loads(layout_path.read_text(encoding="utf-8-sig"))
    errors: list[str] = []
    files = layout.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("release-layout file list is invalid")
    for item in files:
        relative = safe_relative(str(item["path"]))
        actual = root / relative
        if not actual.is_file():
            errors.append(f"missing:{relative.as_posix()}")
            continue
        if "size" in item and actual.stat().st_size != int(item["size"]):
            errors.append(f"size:{relative.as_posix()}")
            continue
        if "sha256" in item and sha256(actual) != str(item["sha256"]).upper():
            errors.append(f"hash:{relative.as_posix()}")
    return len(files), errors


def safe_requirements(source: Path) -> Path:
    """Mirror the public Setup's pinned replacements without executing shell text."""
    replacements = {
        "git+https://github.com/facebookresearch/sam2": "https://codeload.github.com/facebookresearch/sam2/zip/2b90b9f5ceec907a1c18123530e92e794ad901a4",
        "git+https://github.com/ltdrdata/img2texture.git": "https://codeload.github.com/ltdrdata/img2texture/zip/d6159abea44a0b2cf77454d3d46962c8b21eb9d3",
        "git+https://github.com/ltdrdata/cstr": "https://codeload.github.com/ltdrdata/cstr/zip/0520c29a18a7a869a6e5983861d6f7a4c86f8e9b",
        "git+https://github.com/ltdrdata/ffmpy.git": "https://codeload.github.com/ltdrdata/ffmpy/zip/f000737698b387ffaeab7cd871b0e9185811230d",
    }
    text = source.read_text(encoding="utf-8-sig")
    for old, new in replacements.items():
        text = text.replace(old, new)
    output = source.with_suffix(source.suffix + ".lakis.txt")
    output.write_text(text, encoding="utf-8")
    return output


def desktop_directory() -> Path:
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, "Desktop")
        return Path(os.path.expandvars(value)).resolve()
    except (ImportError, OSError):
        return (Path.home() / "Desktop").resolve()


def has_webview2_runtime() -> bool:
    import winreg
    # Microsoft-documented Evergreen runtime product registration. Check both
    # installation scopes and registry views from embedded 64-bit Python.
    client = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, client, 0, winreg.KEY_READ | view) as key:
                    version, _kind = winreg.QueryValueEx(key, 'pv')
                if isinstance(version, str):
                    parts = version.strip().split('.')
                    if len(parts) == 4 and all(p.isdigit() for p in parts) and any(int(p) > 0 for p in parts):
                        return True
            except OSError:
                continue
    return False


def ensure_webview2_runtime(manifest: dict, cache: Path) -> None:
    if has_webview2_runtime():
        print('  [확인] Microsoft WebView2 Runtime', flush=True)
        return
    record = manifest['webview2']
    display_name = record.get('name', 'MicrosoftEdgeWebview2Setup.exe')
    installer = download(
        record['url'], cache_path(cache, display_name, record['sha256']),
        record['sha256'], int(record['bytes']), display_name=display_name,
    )
    print('  [설치] Microsoft WebView2 Runtime', flush=True)
    subprocess.run([str(installer), '/silent', '/install'], check=True, cwd=cache)
    if not has_webview2_runtime():
        raise RuntimeError('Microsoft WebView2 Runtime 설치를 확인할 수 없습니다. 재부팅 후 설치기를 다시 실행해 주세요.')


def create_desktop_shortcut(
    target: Path,
    desktop: Path | None = None,
    runner=subprocess.run,
) -> Path:
    desktop = desktop or desktop_directory()
    desktop.mkdir(parents=True, exist_ok=True)
    shortcut = desktop / "LAKIS.lnk"
    launcher = target / "LAKIS.exe"
    script_text = "\r\n".join((
        'Set shell = CreateObject("WScript.Shell")',
        "Set link = shell.CreateShortcut(WScript.Arguments(0))",
        "link.TargetPath = WScript.Arguments(1)",
        "link.WorkingDirectory = WScript.Arguments(2)",
        "link.IconLocation = WScript.Arguments(3)",
        "link.Save",
    ))
    script_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".vbs", encoding="ascii", delete=False
        ) as script:
            script.write(script_text)
            script_path = Path(script.name)
        runner(
            [
                "cscript.exe",
                "//nologo",
                str(script_path),
                str(shortcut),
                str(launcher),
                str(target),
                f"{launcher},0",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not shortcut.is_file():
            raise RuntimeError("desktop shortcut was not created")
        return shortcut
    finally:
        if script_path is not None:
            script_path.unlink(missing_ok=True)


def install(manifest_path: Path, portable_root: Path, target: Path, cache: Path, dry_run: bool) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise RuntimeError("unsupported CMD installer manifest")
    portable_root = portable_root.resolve()
    target = target.resolve()
    if not (portable_root / "python_embeded" / "python.exe").is_file():
        raise RuntimeError("verified embedded Python is missing")
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("target directory is not empty")
    if portable_root == target or portable_root in target.parents or target in portable_root.parents:
        raise RuntimeError("staging and target paths overlap")
    if dry_run:
        print(json.dumps({"ok": True, "version": manifest["version"], "nodes": len(manifest["nodes"]) + 1,
                          "models": len(manifest["models"]), "target": str(target)}, ensure_ascii=False))
        return

    custom = portable_root / "ComfyUI" / "custom_nodes"
    models_root = portable_root / "ComfyUI" / "models"
    # Keep extraction paths short. The verified cache filename intentionally
    # includes the full SHA-256, but reusing that long name below a staging
    # directory can hit the legacy Windows MAX_PATH limit (260 characters).
    # The install is sequential and install_archive resets this slot each time.
    scratch = portable_root.parent / ".u"
    scratch.mkdir(parents=True, exist_ok=True)
    node_stage = scratch / "n"
    custom.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    for name, url, digest, relative in manifest["nodes"]:
        archive = download(url, cache_path(cache, name, digest), digest, display_name=name)
        install_archive(archive, custom / safe_relative(relative), node_stage)
    name, url, digest, relative = manifest["nested_node"]
    archive = download(url, cache_path(cache, name, digest), digest, display_name=name)
    install_archive(archive, custom / safe_relative(relative), node_stage)

    for name, url, digest, relative, size in manifest["models"]:
        cached = download(url, cache_path(cache, name, digest), digest, int(size), display_name=name)
        destination = models_root / safe_relative(relative) / safe_leaf(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, destination)

    source_item = manifest["source"]
    source_archive = download(
        source_item["url"],
        cache_path(cache, source_item["name"], source_item["sha256"]),
        source_item["sha256"],
        int(source_item["bytes"]),
        display_name=source_item["name"],
    )
    source_stage = scratch / "release-source"
    if source_stage.exists():
        shutil.rmtree(source_stage)
    print(f"  [압축 해제] {source_item['name']}", flush=True)
    extract_zip(source_archive, source_stage)
    install_release_source(only_directory(source_stage), portable_root)

    release_base = str(manifest["release_base"]).rstrip("/")
    repair = manifest["repair_pack"]
    layout = manifest["release_layout"]
    repair_path = download(f"{release_base}/{repair['name']}", cache_path(cache, repair["name"], repair["sha256"]), repair["sha256"], int(repair.get("bytes", 0)), display_name=repair["name"])
    layout_path = download(f"{release_base}/{layout['name']}", cache_path(cache, layout["name"], layout["sha256"]), layout["sha256"], int(layout.get("bytes", 0)), display_name=layout["name"])
    extract_zip(repair_path, portable_root)
    create_default_input_image(portable_root / "ComfyUI")

    python = portable_root / "python_embeded" / "python.exe"
    dependency_log = portable_root / ".lakis-cmd-dependencies.log"
    dependency_files = sorted(custom.glob("*/requirements.txt"))
    for index, requirements in enumerate(dependency_files, 1):
        print(f"  [설치 {index:02d}/{len(dependency_files):02d}] {requirements.parent.name}", flush=True)
        pinned_requirements = safe_requirements(requirements)
        with dependency_log.open("a", encoding="utf-8", errors="replace") as log:
            subprocess.run([str(python), "-s", "-m", "pip", "install", "--disable-pip-version-check", "-r", str(pinned_requirements)],
                           cwd=portable_root, stdout=log, stderr=subprocess.STDOUT, check=True)

    managed_count, errors = validate_layout(portable_root, layout_path)
    if errors:
        raise RuntimeError("managed layout mismatch: " + ", ".join(errors[:10]))
    ensure_webview2_runtime(manifest, cache)
    state_root = portable_root / ".lakis"
    state_root.mkdir(exist_ok=True)
    (state_root / "optional-models.txt").write_text(
        "No optional non-commercial model selected.\r\n", encoding="utf-8"
    )
    (state_root / "upscaler-license-choice.json").write_text(
        json.dumps({
            "choice": "realesrgan",
            "model": "RealESRGAN_x4plus_anime_6B.pth",
            "license": "BSD-3-Clause",
            "noncommercial_acknowledged": False,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (portable_root / "VERSION").write_text(str(manifest["version"]), encoding="utf-8")
    (portable_root / "install.complete").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )
    (state_root / "install-method.txt").write_text("cmd\n", encoding="ascii")

    if target.exists():
        target.rmdir()
    os.replace(portable_root, target)
    shutil.rmtree(scratch, ignore_errors=True)
    # The caller owns the staging parent; it may contain unrelated files.
    # Keep it (including extraction logs) rather than deleting it recursively.
    try:
        shortcut = create_desktop_shortcut(target)
        print(f"  [확인] 바탕화면 바로가기 생성: {shortcut.name}", flush=True)
    except Exception as error:
        print(f"  [안내] 바탕화면 바로가기를 만들지 못했습니다: {error}", flush=True)
    print(f"  [확인] 관리 파일 {managed_count}/{managed_count}개 검증 완료", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--portable-root", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        install(args.manifest, args.portable_root, args.target, args.cache, args.dry_run)
        return 0
    except Exception as error:
        print(f"LAKIS 설치 중 오류가 발생했습니다: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
