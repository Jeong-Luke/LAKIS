"""Transactional activation of a verified LAKIS runtime, outside the live tree.

Candidate inputs contain release files only. Existing data is copied into a
unique sibling workspace before any rename. A failed or interrupted activation
retains every tree; recovery never deletes a database or a generated image.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

if __name__ == "__main__":
    # Recovery also runs outside the installation with an embedded interpreter.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lakis_cmd_installer import (
    cache_entry_lock, copy_file, copy_tree, reject_reparse_path,
    reject_reparse_tree, sha256, validate_windows_component,
)
from runtime_health import check_runtime
from runtime_manifest import (
    MANIFEST_NAME, PROTECTED_DIRECTORIES, PROTECTED_FILES, normalized_path,
    pose_model_rows, verify_runtime,
)


def _target_path(target: Path, *, prepare_only: bool = False) -> Path:
    target = reject_reparse_path(target)
    if target == Path(target.anchor) or target == Path.home():
        raise ValueError("a dedicated LAKIS installation directory is required")
    validate_windows_component(target.name)
    if not target.parent.is_dir():
        raise ValueError("target parent directory must already exist")
    # The old installed interpreter may download/verify its replacement, but
    # must exit before activation. Helpers and their cwd stay outside in both phases.
    paths = [Path(__file__).absolute(), Path.cwd()]
    if not prepare_only:
        paths.append(Path(sys.executable).absolute())
    for path in paths:
        if path == target or target in path.parents:
            raise ValueError("transition helper must run outside the target installation")
    return target


def _journal_path(target: Path) -> Path:
    return reject_reparse_path(target.parent / f".{target.name}-runtime-transition.json")


@contextmanager
def _journal_access(target: Path):
    # Windows replacement can fail while even a read-only observer has the
    # destination open. This short lock is distinct from the whole-transaction
    # lock, so progress readers never compete for activation ownership.
    lock = target.parent / f".{target.name}-runtime-journal"
    with cache_entry_lock(lock, "LAKIS runtime journal", timeout_seconds=30):
        yield _journal_path(target)


def _write_journal(target: Path, state: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{target.name}-journal-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        with _journal_access(target) as path:
            os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_journal(target: Path) -> dict | None:
    with _journal_access(target) as path:
        if not path.exists():
            return None
        state = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(state, dict) and state.get("schema") == 2:
        from runtime_patch import validate_state
        return validate_state(target, state)
    if (not isinstance(state, dict) or state.get("schema") != 1
            or state.get("target") != str(target)
            or type(state.get("had_original")) is not bool
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(state.get("version", "")))
            or not re.fullmatch(r"[A-Fa-f0-9]{64}", str(state.get("manifest_sha256", "")))
            or state.get("phase") not in {
                "preparing", "staged", "backing-up", "promoting", "checking",
                "complete", "restoring", "rolled-back",
            }):
        raise ValueError("invalid runtime transition journal")
    name = state.get("workspace")
    if not isinstance(name, str):
        raise ValueError("invalid transition workspace")
    validate_windows_component(name)
    if not name.startswith(f".{target.name}-"):
        raise ValueError("invalid transition workspace")
    workspace = reject_reparse_path(target.parent / name)
    if not workspace.is_dir():
        raise ValueError("transition workspace is missing")
    for child in ("stage", "backup", "failed"):
        reject_reparse_path(workspace / child)
    return state


def _result(target: Path, state: dict) -> dict:
    workspace = target.parent / state["workspace"]
    return {
        "status": state["phase"], "target": str(target),
        "workspace": str(workspace), "backup": str(workspace / "backup"),
        "retained_candidate": str(workspace / "failed"),
        "journal": str(_journal_path(target)),
    }


def _version(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", value):
        raise ValueError("invalid LAKIS version")
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (4 - len(parts))


def _assert_original(target: Path, version: str, mode: str) -> bool:
    if mode == "fresh":
        # An explicitly selected empty directory is preserved as a backup,
        # not deleted before the candidate has passed its checks.
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError("fresh target is not empty")
        return target.exists()
    if (not (target / "VERSION").is_file()
            or not (target / "ComfyUI/LAKIS/STOP_AUTOMATION").is_file()):
        raise ValueError("target is not an identified public LAKIS installation")
    current = _version((target / "VERSION").read_text(encoding="utf-8-sig").strip())
    expected = _version(version)
    if (mode == "update" and current >= expected) or (mode == "repair" and current != expected):
        raise ValueError("update must increase the version; repair must keep the version")
    return True


def assert_idle(root: Path, probe_python: Path, *, file_paths=None) -> None:
    """Never kill an existing process. Do not confuse another install with ours."""
    if not root.exists():
        return
    probe = (
        "import json, os, psutil, sys\n"
        "root = os.path.normcase(os.path.abspath(sys.argv[1])) + os.sep\n"
        "busy = []\n"
        "for process in psutil.process_iter(['pid', 'exe']):\n"
        "    exe = process.info['exe']\n"
        "    if exe and os.path.normcase(os.path.abspath(exe)).startswith(root):\n"
        "        busy.append(process.info['pid'])\n"
        "print(json.dumps(busy))\n"
    )
    checked = subprocess.run(
        [str(probe_python), "-s", "-c", probe, str(root)],
        cwd=str(probe_python.parent), capture_output=True, check=True, timeout=30,
    )
    busy = json.loads(checked.stdout)
    if not isinstance(busy, list):
        raise RuntimeError("invalid process ownership probe")
    if busy:
        raise RuntimeError(f"close this LAKIS installation before continuing (PIDs: {busy})")
    # Also detect open databases and files held by tools whose executables
    # live outside the installation. No file is changed by this probe.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    paths = (Path(parent) / name for parent, _, files in os.walk(root) for name in files) \
        if file_paths is None else file_paths
    for entry in paths:
        path = reject_reparse_path(entry)
        handle = create(str(path), 0x80000000, 0, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise RuntimeError(f"installation file is in use or unreadable: {path}")
        close(handle)


def _data_snapshot(root: Path) -> dict:
    result = {}
    for relative in (*PROTECTED_DIRECTORIES, *PROTECTED_FILES):
        path = root / relative
        if not path.exists():
            continue
        reject_reparse_tree(path)
        if path.is_file():
            result[relative] = (path.stat().st_size, sha256(path))
        else:
            result[relative + "/"] = None
            for parent, directories, files in os.walk(path):
                for name in directories:
                    result[(Path(parent) / name).relative_to(root).as_posix() + "/"] = None
                for name in files:
                    file = Path(parent) / name
                    result[file.relative_to(root).as_posix()] = (file.stat().st_size, sha256(file))
    return result


def _copy_data(source: Path, stage: Path) -> None:
    for relative in (*PROTECTED_DIRECTORIES, *PROTECTED_FILES):
        path = source / relative
        if path.is_dir():
            copy_tree(path, stage / relative)
        elif path.is_file():
            copy_file(path, stage / relative)


def _is_promoted_target(target: Path, state: dict) -> bool:
    manifest = reject_reparse_path(target / MANIFEST_NAME)
    return manifest.is_file() and sha256(manifest) == state["manifest_sha256"].upper()


def _restore(target: Path, state: dict) -> dict:
    workspace = target.parent / state["workspace"]
    stage, backup, failed = (workspace / name for name in ("stage", "backup", "failed"))
    reject_reparse_tree(target)
    reject_reparse_tree(backup)
    # The manifest marker and absent stage identify a tree we promoted. A
    # conflicting directory created by another process must not be moved.
    if backup.exists() or not state["had_original"]:
        if target.exists():
            if stage.exists() or failed.exists() or not _is_promoted_target(target, state):
                raise RuntimeError("ambiguous recovery target; all trees have been retained")
            state["phase"] = "restoring"
            _write_journal(target, state)
            os.rename(target, failed)
        if backup.exists():
            state["phase"] = "restoring"
            _write_journal(target, state)
            os.rename(backup, target)
    elif not target.exists():
        raise RuntimeError("original runtime is missing; recovery requires the retained backup")
    elif state["phase"] not in {"preparing", "staged", "backing-up", "restoring"}:
        raise RuntimeError("original backup is missing; refusing an ambiguous recovery")
    state["phase"] = "rolled-back"
    _write_journal(target, state)
    return _result(target, state)


@contextmanager
def _transaction_lock(target: Path):
    # The existing Windows byte-range lock releases automatically on a crash.
    lock = target.parent / f".{target.name}-runtime-transition"
    with cache_entry_lock(lock, "LAKIS runtime transition", timeout_seconds=0):
        yield


def recover(target: Path, probe_python: Path) -> dict:
    target = _target_path(target)
    probe_python = reject_reparse_path(probe_python)
    if target in probe_python.parents:
        raise ValueError("recovery interpreter must be outside the target")
    with _transaction_lock(target):
        state = _load_journal(target)
        if state is None:
            raise ValueError("no runtime transition to recover")
        if state["phase"] == "rolled-back":
            return _result(target, state)
        if state["schema"] == 2:
            from runtime_patch import restore
            return restore(target, state, probe_python)
        assert_idle(target, probe_python)
        assert_idle(target.parent / state["workspace"] / "backup", probe_python)
        return _restore(target, state)


def activate(candidate: Path, target: Path, manifest_sha256: str, version: str,
             mode: str, initial_data: Path | None = None, *, model_files=None) -> dict:
    if mode not in {"fresh", "update", "repair"}:
        raise ValueError("unsupported runtime transition mode")
    _version(version)
    target = _target_path(target)
    candidate = reject_reparse_path(candidate)
    if candidate == target or candidate in target.parents or target in candidate.parents:
        raise ValueError("candidate and target overlap")
    reject_reparse_tree(candidate)
    if initial_data is not None:
        if mode != "fresh":
            raise ValueError("initial data is only allowed for a fresh installation")
        initial_data = reject_reparse_path(initial_data)
        reject_reparse_tree(initial_data)
        if (initial_data == target or initial_data in target.parents
                or target in initial_data.parents):
            raise ValueError("initial data and target overlap")
    with _transaction_lock(target):
        previous = _load_journal(target)
        if previous and previous["phase"] not in {"complete", "rolled-back"}:
            raise RuntimeError("interrupted runtime transition: run recovery before another activation")
        manifest = verify_runtime(candidate, manifest_sha256, version)
        reject_reparse_tree(target)
        had_original = _assert_original(target, version, mode)
        python = candidate / "python_embeded/python.exe"
        assert_idle(target, python)
        original_data = _data_snapshot(target) if had_original else {}
        model_rows = pose_model_rows(model_files, target)
        data_source = initial_data if mode == "fresh" else target
        expected_data = _data_snapshot(data_source) if data_source is not None else {}
        required = (sum(row["size"] for row in manifest["files"])
                    + (candidate / MANIFEST_NAME).stat().st_size
                    + sum(row[0] for row in expected_data.values() if row is not None))
        if shutil.disk_usage(target.parent).free < required:
            raise RuntimeError("not enough space for the candidate and a separate user-data copy")
        # Native CUDA DLL loaders can reject paths that Python can copy.
        # Keep the sibling transaction name short without changing its volume,
        # ownership boundary, or acceptance of retained older journals.
        workspace = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
        stage, backup = workspace / "stage", workspace / "backup"
        state = {
            "schema": 1, "target": str(target), "workspace": workspace.name,
            "manifest_sha256": manifest_sha256.upper(), "version": version,
            "had_original": had_original, "phase": "preparing",
        }
        _write_journal(target, state)
        try:
            # Do not copy ignored .git or bytecode trees from a builder's
            # candidate. Only externally authenticated files may be activated.
            for entry in manifest["files"]:
                relative = normalized_path(entry["path"])
                copy_file(candidate / relative, stage / relative)
            copy_file(candidate / MANIFEST_NAME, stage / MANIFEST_NAME)
            verify_runtime(stage, manifest_sha256, version)
            if data_source is not None:
                _copy_data(data_source, stage)
                if _data_snapshot(stage) != expected_data or _data_snapshot(data_source) != expected_data:
                    raise RuntimeError("user data changed during staging; original installation was retained")
            for row in model_rows:
                destination = reject_reparse_path(stage / row["path"])
                if destination.exists():
                    raise RuntimeError("pose model destination appeared during staging")
                copy_file(row["source"], destination)
                if destination.stat().st_size != row["size"] or sha256(destination) != row["sha256"]:
                    raise ValueError("pose model changed during staging")
            # This is the copy of the database. The old database is never
            # opened by the new ComfyUI until a successful promotion.
            check_runtime(stage)
            verify_runtime(stage, manifest_sha256, version, allow_user_data=True)
            state["phase"] = "staged"
            _write_journal(target, state)
            assert_idle(target, python)
            if had_original:
                if _data_snapshot(target) != original_data:
                    raise RuntimeError("user data changed before promotion")
                state["phase"] = "backing-up"
                _write_journal(target, state)
                os.rename(target, backup)
            state["phase"] = "promoting"
            _write_journal(target, state)
            os.rename(stage, target)
            state["phase"] = "checking"
            _write_journal(target, state)
            # Check the final installation path, not just the staging path.
            check_runtime(target)
            verify_runtime(target, manifest_sha256, version, allow_user_data=True)
            state["phase"] = "complete"
            _write_journal(target, state)
        except Exception:
            _restore(target, state)
            raise
        return _result(target, state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    apply = subparsers.add_parser("activate")
    apply.add_argument("--candidate", required=True, type=Path)
    apply.add_argument("--manifest-sha256", required=True)
    apply.add_argument("--version", required=True)
    apply.add_argument("--mode", required=True, choices=("fresh", "update", "repair"))
    apply.add_argument("--initial-data", type=Path)
    restore = subparsers.add_parser("recover")
    restore.add_argument("--probe-python", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "activate":
            result = activate(args.candidate, args.target, args.manifest_sha256, args.version,
                              args.mode, args.initial_data)
        else:
            result = recover(args.target, args.probe_python)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print(f"LAKIS runtime transition failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
