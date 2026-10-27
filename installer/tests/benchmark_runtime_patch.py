"""Exercise the real frozen runtime against a disposable application fixture.

This is not a real user's 7.5.3 installation. The new runtime bytes, startup,
database migration, replacement and rollback are real; the old core/Python are
sentinels, and the old LAKIS application files come from the published RepairPack.
No public update channel, real installation, or user's model is changed.
"""
from contextlib import closing
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
HELPERS = (
    "lakis_cmd_installer.py", "runtime_manifest.py", "runtime_health.py",
    "runtime_transition.py", "runtime_patch.py",
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--bridge", required=True, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="lp-"))
    print("BENCHMARK_WORKSPACE=" + str(work), flush=True)
    helpers = work / "helpers"
    helpers.mkdir()
    pins = {}
    for name in HELPERS:
        shutil.copyfile(SOURCE / name, helpers / name)
        pins[name] = digest(helpers / name)
    print(json.dumps({"source_hashes": pins}), flush=True)
    sys.path.insert(0, str(helpers))
    import lakis_cmd_installer as installer
    import runtime_patch
    import runtime_transition

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    if bundle["sha256"] != "25FFA0CE877DFD8AAA51CA60194B430276BEE1B9AC934EC59E96AA77B599CC19":
        raise RuntimeError("benchmark requires the frozen Preview 3 bundle")
    archive = work / "runtime.zip"
    joined, total = hashlib.sha256(), 0
    start = time.monotonic()
    with archive.open("xb") as output:
        for part in bundle["parts"]:
            part_hash, count = hashlib.sha256(), 0
            with (args.assets / part["name"]).open("rb") as incoming:
                for block in iter(lambda: incoming.read(1024 * 1024), b""):
                    part_hash.update(block)
                    joined.update(block)
                    output.write(block)
                    count += len(block)
            if count != part["bytes"] or part_hash.hexdigest().upper() != part["sha256"]:
                raise RuntimeError("frozen runtime part mismatch: " + part["name"])
            total += count
    if total != bundle["bytes"] or joined.hexdigest().upper() != bundle["sha256"]:
        raise RuntimeError("assembled archive mismatch")
    assembly_seconds = time.monotonic() - start
    candidate = work / "c"
    start = time.monotonic()
    print("EXTRACTION_STARTED", flush=True)
    installer.extract_zip(archive, candidate, expected_entries=bundle["files"] + 1)
    extraction_seconds = time.monotonic() - start
    print(json.dumps({"assembly_seconds": assembly_seconds, "extraction_seconds": extraction_seconds}), flush=True)

    repair = args.baseline / "LAKIS_RepairPack.zip"
    if digest(repair) != "C7EFE57BB5D9BE43ACA45C374C4B80D721F9BD04A3E4F204413B867E9905DE64":
        raise RuntimeError("baseline RepairPack mismatch")
    target = work / "t"
    installer.extract_zip(repair, target)
    # A marked, disposable old-core fixture. This cannot be used to claim
    # complete real-installation upgrade compatibility.
    (target / "ComfyUI/main.py").write_bytes(b"old-core-fixture")
    (target / "python_embeded").mkdir()
    (target / "python_embeded/python.exe").write_bytes(b"old-python-fixture")
    for name in ("LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe"):
        shutil.copyfile(args.bridge / name, target / name)
    (target / "VERSION").write_bytes(b"7.5.4")
    user_files = {
        "ComfyUI/models/checkpoints/preservation-fixture.bin": b"model-data",
        "ComfyUI/models/loras/preservation-fixture.bin": b"lora-data",
        "ComfyUI/input/preservation-fixture.bin": b"input-data",
        "ComfyUI/output/preservation-fixture.bin": b"output-data",
        "ComfyUI/user/default/workflows/preservation-fixture.json": b'{"preserve":42}',
    }
    identities = {}
    for relative, data in user_files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        identities[relative] = path.stat().st_ino
    database = target / "ComfyUI/user/comfyui.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("create table preservation_fixture(value integer)")
        db.execute("insert into preservation_fixture values (42)")
    database_before = digest(database)
    before_program = {
        row: digest(target / row)
        for row in ("VERSION", "LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe", "python_embeded/python.exe")
    }

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    locked = create(str(target / "ComfyUI/models/checkpoints/preservation-fixture.bin"),
                    0x80000000, 0, None, 3, 0x80, None)
    if locked == ctypes.c_void_p(-1).value:
        raise RuntimeError("could not exclusively lock model fixture")
    try:
        result = runtime_patch.activate(candidate, target, bundle["manifest_sha256"], "8.0.0")
    finally:
        close(locked)
    if result["status"] != "complete":
        raise RuntimeError("update did not complete")
    with closing(sqlite3.connect(database)) as db:
        if db.execute("pragma integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("updated database integrity failed")
        if db.execute("select value from preservation_fixture").fetchall() != [(42,)]:
            raise RuntimeError("database fixture was not preserved")
    for relative, data in user_files.items():
        path = target / relative
        if path.read_bytes() != data or path.stat().st_ino != identities[relative]:
            raise RuntimeError("user fixture changed: " + relative)
    print(json.dumps({"update": result, "user_data_preserved": True, "database_integrity": "ok"}, ensure_ascii=False), flush=True)

    new_output = target / "ComfyUI/output/created-after-update.bin"
    new_output.write_bytes(b"retain-new-output")
    start = time.monotonic()
    rollback = runtime_transition.recover(target, candidate / "python_embeded/python.exe")
    rollback_seconds = time.monotonic() - start
    if rollback["status"] != "rolled-back" or digest(database) != database_before:
        raise RuntimeError("database rollback mismatch")
    for relative, expected in before_program.items():
        if digest(target / relative) != expected:
            raise RuntimeError("program rollback mismatch: " + relative)
    for relative, data in user_files.items():
        path = target / relative
        if path.read_bytes() != data or path.stat().st_ino != identities[relative]:
            raise RuntimeError("rollback changed user data: " + relative)
    if new_output.read_bytes() != b"retain-new-output":
        raise RuntimeError("rollback removed a new output")
    print(json.dumps({
        "status": "benchmark-complete", "workspace": str(work),
        "fixture_scope": "published-753-app-files-with-synthetic-old-core-and-database",
        "assembly_seconds": assembly_seconds, "extraction_seconds": extraction_seconds,
        "update_seconds": result["elapsed_seconds"], "stage_timings": result["timings"],
        "rollback_seconds": rollback_seconds, "new_output_preserved": True,
        "network_download_included": False,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
