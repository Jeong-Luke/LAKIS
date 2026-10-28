"""Journaled runtime replacement; existing user models are never replaced.

Only release-owned components are staged and exchanged. Existing user data
stays at its original path. The ComfyUI database is the explicit exception:
runtime startup can migrate it, so retain its original bytes and archive a
failed/new database before restoration. No retained tree is deleted.
Missing, explicitly pinned pose defaults may be added from verified publisher
downloads. Once installed they are user data and remain on program rollback.
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
import stat
import sys
import tempfile
import time

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lakis_cmd_installer import (
    reject_reparse_path, sha256, transient_file_error, validate_windows_component,
)
from runtime_health import check_runtime
import runtime_manifest as runtime_contract
from runtime_manifest import (
    GENERATED_PATHS, MANIFEST_NAME, PROTECTED_DIRECTORIES, PROTECTED_FILES,
    _stream_digest, generated_path, normalized_path, protected_path, verify_runtime,
)
from runtime_transition import (
    _assert_original, _load_journal, _target_path, _transaction_lock,
    _version, _write_journal, assert_idle,
)

DATABASE_PATHS = tuple("ComfyUI/user/comfyui.db" + suffix for suffix in ("", "-wal", "-shm"))
BOUNDARIES = {
    "/".join(name.casefold().split("/")[:index])
    for name in (*PROTECTED_DIRECTORIES, *PROTECTED_FILES, *GENERATED_PATHS)
    for index in range(1, len(name.split("/")) + 1)
}
PHASES = {"preparing", "prepared", "applying", "checking", "complete", "restoring", "rolled-back"}


def _identity(path: Path):
    path = reject_reparse_path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    kind = stat.S_IFMT(info.st_mode)
    if kind not in (stat.S_IFREG, stat.S_IFDIR) or not info.st_ino:
        raise RuntimeError(f"unsupported filesystem identity: {path}")
    return {"device": info.st_dev, "file": info.st_ino, "kind": kind}


def _valid_identity(value):
    return (
        isinstance(value, dict) and set(value) == {"device", "file", "kind"}
        and all(type(value[key]) is int for key in value)
        and value["file"] > 0 and value["kind"] in (stat.S_IFREG, stat.S_IFDIR)
    )


def _stage_component(source: Path, destination: Path) -> None:
    """Move verified staging data without replacing anything or changing access."""
    identity = _identity(source)
    # Match the installer's existing five-attempt, two-second file-I/O budget.
    # Only preparation is retried; the installation has not been changed yet.
    for attempt in range(1, 6):
        if _identity(source) != identity or _identity(destination) is not None:
            raise RuntimeError(f"staging component changed before move: {source}")
        try:
            os.rename(source, destination)
            return
        except OSError as error:
            if (getattr(error, "winerror", None) in {225, 226}
                    or not transient_file_error(error) or attempt == 5):
                raise
            print(f"[대기] 프로그램 준비 파일의 일시적 접근 제한을 확인합니다. "
                  f"({attempt}/5, winerror={getattr(error, 'winerror', None)})", flush=True)
            time.sleep(attempt * 0.2)


def _managed_scope(value):
    path = normalized_path(value)
    if protected_path(path) or generated_path(path) or path.casefold() in BOUNDARIES:
        raise ValueError(f"component would replace user data: {path}")
    return path


def component_plan(manifest):
    """Partition authenticated file paths at the fixed user-data boundaries."""
    groups = {}
    parents = {}
    for row in manifest["files"]:
        relative = normalized_path(row["path"])
        parts = relative.split("/")
        parent = "/".join(parts[:-1])
        if parent not in parents:
            parents[parent] = next((
                "/".join(parts[:index]) for index in range(1, len(parts))
                if "/".join(parts[:index]).casefold() not in BOUNDARIES
            ), None)
        component = _managed_scope(parents[parent] or relative)
        key = component.casefold()
        group = groups.setdefault(key, {"path": component, "rows": []})
        group["rows"].append(row)
    # Commit the visible version and authenticated file list after program files.
    return sorted(groups.values(), key=lambda group: (group["path"] == "VERSION", group["path"].casefold()))


def validate_state(target, state):
    if (state.get("schema") != 2 or state.get("mode") != "component-update"
            or state.get("target") != str(target) or state.get("had_original") is not True
            or state.get("phase") not in PHASES
            or type(state.get("database_started")) is not bool
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(state.get("version", "")))
            or not re.fullmatch(r"[A-Fa-f0-9]{64}", str(state.get("manifest_sha256", "")))):
        raise ValueError("invalid component-update journal")
    name = state.get("workspace")
    if not isinstance(name, str):
        raise ValueError("invalid component workspace")
    validate_windows_component(name)
    if not name.startswith(f".{target.name}-"):
        raise ValueError("component workspace is outside this installation")
    workspace = reject_reparse_path(target.parent / name)
    if not workspace.is_dir():
        raise ValueError("component workspace is missing")
    for name in ("stage", "backup", "failed", "database"):
        reject_reparse_path(workspace / name)
    operations = state.get("operations")
    if not isinstance(operations, list) or (not operations and state["phase"] not in {"preparing", "rolled-back"}):
        raise ValueError("invalid component operation list")
    scopes = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("invalid component operation")
        if operation.get("model") is True:
            path = operation.get("path")
            if path not in runtime_contract.POSE_MODELS or operation.get("old") is not None:
                raise ValueError("invalid additive pose model operation")
            if operation.get("new", {}).get("kind") != stat.S_IFREG:
                raise ValueError("pose model operation must contain a file")
        else:
            path = _managed_scope(operation.get("path"))
        key = path.casefold()
        if any(key == existing or key.startswith(existing + "/") or existing.startswith(key + "/")
               for existing in scopes):
            raise ValueError("overlapping component operations")
        scopes.append(key)
        if not _valid_identity(operation.get("new")):
            raise ValueError("invalid prepared component identity")
        if operation.get("old") is not None and not _valid_identity(operation["old"]):
            raise ValueError("invalid original component identity")
    databases = state.get("databases")
    if not isinstance(databases, list):
        raise ValueError("invalid database snapshots")
    if databases:
        if [row.get("path") for row in databases] != list(DATABASE_PATHS):
            raise ValueError("unexpected database snapshot paths")
        for row in databases:
            if type(row.get("present")) is not bool:
                raise ValueError("invalid database presence marker")
            if row["present"] and (
                not _valid_identity(row.get("snapshot"))
                or row["snapshot"]["kind"] != stat.S_IFREG
                or not re.fullmatch(r"[A-Fa-f0-9]{64}", str(row.get("sha256", "")))
            ):
                raise ValueError("invalid database snapshot identity")
    elif state["phase"] not in {"preparing", "rolled-back"}:
        raise ValueError("database snapshot is missing")
    return state


def _copy_verified(source, destination, expected_hash, expected_size=None):
    source = reject_reparse_path(source)
    with source.open("rb") as incoming:
        if ((expected_size is not None and os.fstat(incoming.fileno()).st_size != expected_size)
                or _stream_digest(incoming, destination).upper() != expected_hash.upper()):
            raise RuntimeError(f"prepared file integrity mismatch: {source}")


@contextmanager
def _database_locks(target):
    """Block writes/deletes while taking the small database-group snapshot."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handles = []
    try:
        for relative in DATABASE_PATHS:
            path = reject_reparse_path(target / relative)
            if not path.exists():
                continue
            # Allow other readers (including our copy/hash), but no writers or
            # renames. Acquire every existing sidecar before reading any of them.
            handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise RuntimeError(f"database is open for writing: {path}")
            handles.append(handle)
        yield
    finally:
        for handle in handles:
            close(handle)


def _database_snapshot(target, workspace):
    rows = []
    for relative in DATABASE_PATHS:
        source = reject_reparse_path(target / relative)
        identity = _identity(source)
        row = {"path": relative, "present": identity is not None}
        if identity is not None:
            if identity["kind"] != stat.S_IFREG:
                raise ValueError(f"database is not a regular file: {source}")
            row["sha256"] = sha256(source)
            backup = workspace / "database" / "before" / source.name
            _copy_verified(source, backup, row["sha256"])
            row["snapshot"] = _identity(backup)
        rows.append(row)
    return rows


def _database_unchanged(target, rows):
    for row in rows:
        path = reject_reparse_path(target / row["path"])
        if path.exists() != row["present"] or (row["present"] and sha256(path) != row["sha256"]):
            raise RuntimeError("database changed during runtime preparation; installation retained")


def _locations(target, workspace, index, operation):
    name = f"{index:06d}"
    return {
        "target": target / operation["path"], "backup": workspace / "backup" / name,
        "stage": workspace / "stage" / name, "failed": workspace / "failed" / name,
    }


def _check_recovery_locations(target, workspace, operations):
    # Validate all components before touching the first one. Unknown entries
    # are never deleted, overwritten or interpreted as this transaction's files.
    for index, operation in enumerate(operations):
        if operation.get("model") is True:
            continue  # Installed models are user data, not rollback components.
        paths = _locations(target, workspace, index, operation)
        identities = {name: _identity(path) for name, path in paths.items()}
        old, new = operation["old"], operation["new"]
        if identities["target"] not in (None, old, new):
            raise RuntimeError(f"recovery target identity changed: {paths['target']}")
        if identities["backup"] is not None and (old is None or identities["backup"] != old):
            raise RuntimeError("original component backup identity changed")
        if old is not None and sum(identities[name] == old for name in ("target", "backup")) != 1:
            raise RuntimeError("original component is missing or duplicated")
        for name in ("stage", "failed"):
            if identities[name] is not None and identities[name] != new:
                raise RuntimeError("prepared/retained component identity changed")
        if sum(identity == new for identity in identities.values()) > 1:
            raise RuntimeError("new component has ambiguous locations")


def _restore_databases(target, workspace, rows):
    for row in rows:
        destination = reject_reparse_path(target / row["path"])
        original = workspace / "database" / "before" / destination.name
        archived = reject_reparse_path(workspace / "database" / "failed" / destination.name)
        if row["present"]:
            if _identity(original) != row["snapshot"] or sha256(original) != row["sha256"]:
                raise RuntimeError("database backup changed; all copies retained")
            if destination.is_file() and sha256(destination) == row["sha256"]:
                continue
        elif not destination.exists():
            continue
        if destination.exists():
            if archived.exists():
                raise RuntimeError("ambiguous database recovery; all copies retained")
            archived.parent.mkdir(parents=True, exist_ok=True)
            os.rename(destination, archived)
        if row["present"]:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # The old database backup remains available after restoration.
            _copy_verified(original, destination, row["sha256"])


def _result(target, state):
    workspace = target.parent / state["workspace"]
    return {
        "status": state["phase"], "target": str(target), "workspace": str(workspace),
        "backup": str(workspace / "backup"), "retained_candidate": str(workspace / "failed"),
        "database_archive": str(workspace / "database" / "failed"),
    }


def restore(target, state, probe_python):
    validate_state(target, state)
    workspace = target.parent / state["workspace"]
    if state["phase"] == "preparing":
        # Preparation never changes the installation. A rejected payload must
        # not execute its unverified Python merely to retain partial staging.
        if state["operations"] or state["database_started"]:
            raise ValueError("invalid preparing transaction")
        state["phase"] = "rolled-back"
        _write_journal(target, state)
        return _result(target, state)
    assert_idle(target, probe_python, file_paths=[
        target / path for path in DATABASE_PATHS if (target / path).exists()
    ])
    _check_recovery_locations(target, workspace, state["operations"])
    # Validate every required DB snapshot before restoring any program component.
    if state["database_started"]:
        for row in state["databases"]:
            if row["present"]:
                path = workspace / "database" / "before" / Path(row["path"]).name
                if _identity(path) != row["snapshot"] or sha256(path) != row["sha256"]:
                    raise RuntimeError("database backup is invalid; recovery stopped")
    state["phase"] = "restoring"
    _write_journal(target, state)
    for index in reversed(range(len(state["operations"]))):
        operation = state["operations"][index]
        if operation.get("model") is True:
            continue
        paths = _locations(target, workspace, index, operation)
        if _identity(paths["target"]) == operation["new"]:
            paths["failed"].parent.mkdir(parents=True, exist_ok=True)
            os.rename(paths["target"], paths["failed"])
        if _identity(paths["backup"]) is not None:
            paths["target"].parent.mkdir(parents=True, exist_ok=True)
            os.rename(paths["backup"], paths["target"])
    if state["database_started"]:
        _restore_databases(target, workspace, state["databases"])
    state["phase"] = "rolled-back"
    _write_journal(target, state)
    return _result(target, state)


def activate(candidate, target, manifest_sha256, version, *, model_files=None):
    target = _target_path(Path(target))
    candidate = reject_reparse_path(candidate)
    if candidate == target or target in candidate.parents or candidate in target.parents:
        raise ValueError("candidate and installation overlap")
    with _transaction_lock(target):
        previous = _load_journal(target)
        if previous and previous["phase"] not in {"complete", "rolled-back"}:
            raise RuntimeError("an interrupted runtime transition must be recovered first")
        _assert_original(target, version, "update")
        if _version((target / "VERSION").read_text(encoding="utf-8-sig").strip()) < (7, 5, 4):
            raise ValueError("install the 7.5.4 updater bridge before a runtime update")
        started = time.monotonic()
        timings = {}
        probe_python = candidate / "python_embeded/python.exe"
        workspace = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
        state = {
            "schema": 2, "mode": "component-update", "target": str(target),
            "workspace": workspace.name, "manifest_sha256": manifest_sha256.upper(),
            "version": version, "had_original": True, "phase": "preparing",
            "operations": [], "databases": [], "database_started": False,
        }
        _write_journal(target, state)
        try:
            payload = workspace / "payload"
            print("[검증·준비] 새 런타임 파일을 검증하며 준비합니다.", flush=True)
            manifest = verify_runtime(candidate, manifest_sha256, version, progress=True,
                                      stage_root=payload)
            _copy_verified(candidate / MANIFEST_NAME, payload / MANIFEST_NAME, manifest_sha256)
            timings["verify_and_stage_seconds"] = time.monotonic() - started
            # No candidate code executes until every payload file is verified.
            # Models and generated images are not opened by the idle probe.
            assert_idle(target, probe_python, file_paths=[
                target / path for path in DATABASE_PATHS if (target / path).exists()
            ])
            groups = component_plan(manifest)
            groups.append({"path": MANIFEST_NAME, "rows": [{
                "path": MANIFEST_NAME, "sha256": manifest_sha256,
                "size": (payload / MANIFEST_NAME).stat().st_size,
            }]})
            model_rows = runtime_contract.pose_model_rows(model_files, target)
            for row in model_rows:
                _copy_verified(row["source"], payload / row["path"], row["sha256"], row["size"])
                groups.append({"path": row["path"], "rows": [row], "model": True})
            required = sum((target / path).stat().st_size for path in DATABASE_PATHS if (target / path).exists())
            if shutil.disk_usage(target.parent).free < required:
                raise RuntimeError("not enough space for the database snapshot")
            operations = []
            total = sum(len(group["rows"]) for group in groups)
            preparation_started = time.monotonic()
            with _database_locks(target):
                state["databases"] = _database_snapshot(target, workspace)
                (workspace / "stage").mkdir()
                for index, group in enumerate(groups):
                    scope = group["path"]
                    prepared = workspace / "stage" / f"{index:06d}"
                    old = _identity(target / scope)
                    _stage_component(payload / scope, prepared)
                    operation = {"path": scope, "old": old, "new": _identity(prepared)}
                    if group.get("model") is True:
                        if old is not None:
                            raise RuntimeError("pose model destination appeared during preparation")
                        operation["model"] = True
                    operations.append(operation)
                state["operations"] = operations
                timings["prepare_components_seconds"] = time.monotonic() - preparation_started
                state["phase"] = "prepared"
                validate_state(target, state)
                _write_journal(target, state)
                assert_idle(target, probe_python, file_paths=[])
                _database_unchanged(target, state["databases"])
                for operation in operations:
                    if _identity(target / operation["path"]) != operation["old"]:
                        raise RuntimeError("program component changed during preparation")
                state["phase"] = "applying"
                _write_journal(target, state)
                application_started = time.monotonic()
                for index, operation in enumerate(operations):
                    paths = _locations(target, workspace, index, operation)
                    paths["backup"].parent.mkdir(parents=True, exist_ok=True)
                    if operation["old"] is not None:
                        os.rename(paths["target"], paths["backup"])
                    paths["target"].parent.mkdir(parents=True, exist_ok=True)
                    os.rename(paths["stage"], paths["target"])
                    print(f"[교체] 프로그램 영역 {index + 1}/{len(operations)}", flush=True)
            timings["apply_components_seconds"] = time.monotonic() - application_started
            state["phase"] = "checking"
            state["database_started"] = True
            _write_journal(target, state)
            print("[실행 확인] 새 런타임과 DB를 확인합니다.", flush=True)
            health_started = time.monotonic()
            check_runtime(target)
            timings["health_seconds"] = time.monotonic() - health_started
            print("[최종 검증] 교체한 프로그램 파일을 확인합니다.", flush=True)
            verification_started = time.monotonic()
            verify_runtime(target, manifest_sha256, version, allow_user_data=True,
                           scopes=[operation["path"] for operation in operations
                                   if operation.get("model") is not True], progress=True)
            for row in model_rows:
                destination = reject_reparse_path(target / row["path"])
                if destination.stat().st_size != row["size"] or sha256(destination) != row["sha256"]:
                    raise ValueError("installed pose model failed verification")
            timings["verify_installed_seconds"] = time.monotonic() - verification_started
            state["phase"] = "complete"
            _write_journal(target, state)
        except Exception as error:
            try:
                restore(target, state, probe_python)
            except Exception as recovery_error:
                raise RuntimeError(
                    f"update failed: {error}; recovery needs attention: {recovery_error}; retained: {workspace}"
                ) from error
            raise
        result = _result(target, state)
        result["elapsed_seconds"] = time.monotonic() - started
        result["timings"] = timings
        result["component_count"] = len(operations)
        result["program_file_count"] = total - len(model_rows)
        result["added_pose_models"] = [row["path"] for row in model_rows]
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(activate(args.candidate, args.target, args.manifest_sha256, args.version), ensure_ascii=False))
        return 0
    except Exception as error:
        print(f"LAKIS component update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
