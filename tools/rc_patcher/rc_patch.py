from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

FORMAT = "lakis-team-patch-v1"
STATE_DIR = ".lakis_rc_patcher"
PROTECTED = {
    "models", "loras", "user", "input", "output", "library", "logs", "cache",
    ".audit", "external_ui_user_state", "installation-scoped-user-state",
}
MODEL_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}


class PatchError(RuntimeError):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def normalize(value: object) -> str:
    text = str(value or "").replace("\\", "/")
    p = PurePosixPath(text)
    if not text or text.startswith(("/", "//", "\\")) or p.is_absolute():
        raise PatchError(f"unsafe absolute path: {text}")
    if len(text) >= 2 and text[1] == ":":
        raise PatchError(f"unsafe drive path: {text}")
    if any(part in {"", ".", ".."} for part in p.parts):
        raise PatchError(f"unsafe relative path: {text}")
    return "/".join(p.parts)


def protected(rel: str) -> bool:
    parts = {part.casefold() for part in PurePosixPath(rel).parts}
    if parts & PROTECTED:
        return True
    return PurePosixPath(rel).suffix.casefold() in MODEL_SUFFIXES


def safe_target(root: Path, rel: str) -> Path:
    target = (root / Path(*PurePosixPath(rel).parts)).resolve(strict=False)
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise PatchError(f"path escapes install root: {rel}")
    cursor = root_resolved
    for part in PurePosixPath(rel).parts[:-1]:
        cursor = cursor / part
        if cursor.exists() and (cursor.is_symlink() or cursor.is_mount()):
            raise PatchError(f"reparse/symlink path blocked: {rel}")
    return target


def read_version(root: Path) -> str:
    for candidate in (root / "VERSION", root / "ComfyUI" / "LAKIS" / "VERSION"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8-sig").strip().lstrip("v")
    raise PatchError("LAKIS VERSION file not found")


def validate_install(root: Path) -> None:
    if not root.is_dir() or not (root / "ComfyUI").is_dir() or not (root / "LAKIS.exe").is_file():
        raise PatchError("selected folder is not a LAKIS installation")
    read_version(root)


def read_package(zip_path: Path) -> tuple[dict, dict[str, zipfile.ZipInfo]]:
    if not zip_path.is_file():
        raise PatchError("patch ZIP not found")
    with zipfile.ZipFile(zip_path) as archive:
        infos = {}
        for info in archive.infolist():
            name = normalize(info.filename.rstrip("/")) if info.filename.rstrip("/") else ""
            if not name:
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise PatchError(f"symlink entry blocked: {name}")
            if name in infos:
                raise PatchError(f"duplicate ZIP entry: {name}")
            infos[name] = info
        if "patch_manifest.json" not in infos:
            raise PatchError("patch_manifest.json missing")
        try:
            manifest = json.loads(archive.read(infos["patch_manifest.json"]).decode("utf-8"))
        except Exception as exc:
            raise PatchError("malformed patch manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise PatchError("unsupported patch format")
    if not all(isinstance(manifest.get(k), str) and manifest[k].strip() for k in ("display_version", "internal_version", "base_version")):
        raise PatchError("manifest version fields are invalid")
    files = manifest.get("files")
    deletes = manifest.get("delete", [])
    hashes = manifest.get("base_hashes", [])
    if not isinstance(files, list) or not isinstance(deletes, list) or not isinstance(hashes, list):
        raise PatchError("manifest lists are invalid")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise PatchError("invalid file entry")
        rel = normalize(entry.get("path"))
        if rel in seen or protected(rel):
            raise PatchError(f"protected or duplicate payload path: {rel}")
        seen.add(rel)
        if f"payload/{rel}" not in infos:
            raise PatchError(f"payload missing: {rel}")
        if not isinstance(entry.get("size"), int) or entry["size"] < 0 or not isinstance(entry.get("sha256"), str):
            raise PatchError(f"invalid payload metadata: {rel}")
    for raw in deletes:
        rel = normalize(raw)
        if protected(rel):
            raise PatchError(f"protected delete path: {rel}")
    for entry in hashes:
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
            raise PatchError("invalid base hash entry")
        rel = normalize(entry.get("path"))
        if protected(rel):
            raise PatchError(f"protected base hash path: {rel}")
    return manifest, infos


def ensure_not_running(root: Path) -> None:
    state_files = list(root.glob("ComfyUI/LAKIS*/lakis*_launcher_state.json"))
    for state_file in state_files:
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in ("launcher_pid", "desktop_pid", "comfyui_owned_pid", "ui_bridge_owned_pid"):
            pid = state.get(key)
            if isinstance(pid, int) and pid > 0:
                try:
                    os.kill(pid, 0)
                except OSError:
                    continue
                raise PatchError("LAKIS와 ComfyUI를 종료한 뒤 다시 시도해 주세요.")


def validate_base(root: Path, manifest: dict) -> None:
    current = read_version(root)
    expected = manifest["base_version"].strip().lstrip("v")
    if current != expected:
        raise PatchError(f"wrong base version: expected {expected}, current {current}")
    for entry in manifest.get("base_hashes", []):
        rel = normalize(entry["path"])
        target = safe_target(root, rel)
        if not target.is_file() or digest(target) != entry["sha256"].upper():
            raise PatchError(f"base hash mismatch: {rel}")


def extract_verified(zip_path: Path, manifest: dict, staging: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for entry in manifest["files"]:
            rel = normalize(entry["path"])
            info = archive.getinfo(f"payload/{rel}")
            destination = safe_target(staging, rel)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            if destination.stat().st_size != entry["size"] or digest(destination) != entry["sha256"].upper():
                raise PatchError(f"payload hash mismatch: {rel}")


def state_root(root: Path) -> Path:
    return root / STATE_DIR


def log(root: Path, payload: dict) -> None:
    folder = state_root(root) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rollback_record(root: Path, record_dir: Path, remove_record: bool = False) -> None:
    data = json.loads((record_dir / "backup_manifest.json").read_text(encoding="utf-8"))
    for item in reversed(data["entries"]):
        rel = normalize(item["path"])
        target = safe_target(root, rel)
        backup = record_dir / "files" / Path(*PurePosixPath(rel).parts)
        if item["original_existed"]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.exists():
            if not target.is_file() and not target.is_symlink():
                raise PatchError(f"rollback refuses directory removal: {rel}")
            target.unlink()
    if remove_record:
        shutil.rmtree(record_dir)


def apply(zip_path: Path, root: Path) -> dict:
    validate_install(root)
    ensure_not_running(root)
    manifest, _ = read_package(zip_path)
    validate_base(root, manifest)
    lock = state_root(root) / "patch.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(handle)
    except FileExistsError as exc:
        raise PatchError("another patch or update operation is active") from exc
    record_dir = state_root(root) / "backups" / manifest["internal_version"]
    try:
        if record_dir.exists():
            raise PatchError("this RC patch is already recorded")
        with tempfile.TemporaryDirectory(prefix="lakis-rc-stage-") as temp:
            stage = Path(temp)
            extract_verified(zip_path, manifest, stage)
            targets = [normalize(e["path"]) for e in manifest["files"]]
            targets += [normalize(e) for e in manifest.get("delete", []) if normalize(e) not in targets]
            record_dir.mkdir(parents=True)
            entries = []
            for rel in targets:
                target = safe_target(root, rel)
                existed = target.is_file()
                entries.append({"path": rel, "original_existed": existed, "original_sha256": digest(target) if existed else None})
                if existed:
                    backup = record_dir / "files" / Path(*PurePosixPath(rel).parts)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                elif target.exists():
                    raise PatchError(f"target is not a regular file: {rel}")
            record = {"format": FORMAT, "patch_version": manifest["display_version"], "internal_version": manifest["internal_version"], "base_version": manifest["base_version"], "timestamp": time.time(), "entries": entries, "package_sha256": digest(zip_path)}
            (record_dir / "backup_manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                for entry in manifest["files"]:
                    rel = normalize(entry["path"])
                    source = safe_target(stage, rel)
                    target = safe_target(root, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + ".rcpatch.tmp")
                    shutil.copy2(source, temporary)
                    os.replace(temporary, target)
                for raw in manifest.get("delete", []):
                    target = safe_target(root, normalize(raw))
                    if target.exists():
                        if not target.is_file() and not target.is_symlink():
                            raise PatchError(f"directory delete blocked: {raw}")
                        target.unlink()
                for entry in manifest["files"]:
                    target = safe_target(root, normalize(entry["path"]))
                    if digest(target) != entry["sha256"].upper():
                        raise PatchError(f"post-apply hash mismatch: {entry['path']}")
            except Exception:
                rollback_record(root, record_dir, remove_record=True)
                raise
        result = {"ok": True, "status": "PATCH APPLIED", "package": manifest["display_version"], "internal_version": manifest["internal_version"], "files": len(manifest["files"]), "deleted": len(manifest.get("delete", []))}
        log(root, result)
        return result
    except Exception as exc:
        result = {"ok": False, "status": "PATCH FAILED", "error": str(exc)}
        try:
            log(root, result)
        except Exception:
            pass
        raise
    finally:
        lock.unlink(missing_ok=True)


def rollback(root: Path) -> dict:
    validate_install(root)
    ensure_not_running(root)
    backups = state_root(root) / "backups"
    records = sorted((p for p in backups.glob("*") if (p / "backup_manifest.json").is_file()), key=lambda p: p.stat().st_mtime, reverse=True) if backups.exists() else []
    if not records:
        raise PatchError("restore point not found")
    rollback_record(root, records[0], remove_record=True)
    result = {"ok": True, "status": "ROLLBACK COMPLETE", "restored": records[0].name}
    log(root, result)
    return result


def inspect(zip_path: Path) -> dict:
    manifest, _ = read_package(zip_path)
    return {"ok": True, "format": manifest["format"], "display_version": manifest["display_version"], "internal_version": manifest["internal_version"], "base_version": manifest["base_version"], "files": len(manifest["files"]), "delete": len(manifest.get("delete", [])), "zip_sha256": digest(zip_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect"); p.add_argument("zip")
    p = sub.add_parser("apply"); p.add_argument("zip"); p.add_argument("root")
    p = sub.add_parser("rollback"); p.add_argument("root")
    args = parser.parse_args()
    try:
        if args.command == "inspect": result = inspect(Path(args.zip).resolve())
        elif args.command == "apply": result = apply(Path(args.zip).resolve(), Path(args.root).resolve())
        else: result = rollback(Path(args.root).resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
