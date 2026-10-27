"""Native prepare/handoff/apply/recover against a real runtime, in isolation.

The old core and Python are sentinels, not a real 7.5.4 installation. Preparation
uses the authenticated candidate's Python. The test entry point calls the same
embedded native helper methods as the UI, without dialogs or desktop shortcuts.
Local HTTP delivery is included; Internet download time and GUI are not.
"""
import argparse
from contextlib import closing
import ctypes
from email.parser import BytesFeedParser
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_updater_bridge as bridge
import runtime_manifest as contract
from benchmark_runtime_patch import digest

PREVIEW_MANIFEST = "A660CC8D2317A94E2EA7E84E92FF014F27F7B0E10865792D6A02E9B230648163"
NATIVE_NAMES = ("LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe")


def invoke(executable, *arguments, environment=None):
    started = time.monotonic()
    last = None
    with subprocess.Popen([str(executable), *map(str, arguments)], env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace") as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            if line.strip():
                last = line
        code = process.wait()
    if code:
        raise RuntimeError(f"native command failed ({code}): {arguments[0]}")
    return last, time.monotonic() - started


def package(source, manifest, binaries, work, *, application_files=None):
    """Merge pinned application files and derive the BOM from verified metadata."""
    version = manifest["version"]
    overrides = {name: (binaries / name).read_bytes() for name in NATIVE_NAMES}
    overrides["VERSION"] = version.encode("utf-8")
    for relative, pin in (application_files or {}).items():
        relative = contract.normalized_path(relative)
        allowed = (
            relative in {"LICENSE.md", "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md",
                         "LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe",
                         "ComfyUI/custom_nodes/ComfyUI_toyxyz_test_nodes/__init__.py"}
            or relative.startswith("ComfyUI/LAKIS/external_ui/")
            or relative.startswith("third_party_licenses/")
        )
        if not allowed or contract.protected_path(relative) or contract.generated_path(relative):
            raise ValueError("application overlay is outside its release scope: " + relative)
        data = Path(pin["source"]).read_bytes()
        if len(data) != pin["size"] or hashlib.sha256(data).hexdigest().upper() != pin["sha256"].upper():
            raise ValueError("application source changed: " + relative)
        overrides[relative] = data
    revised = json.loads(json.dumps(manifest))
    replaced = set()
    for row in revised["files"]:
        if row["path"] in overrides:
            data = overrides[row["path"]]
            row.update(size=len(data), sha256=hashlib.sha256(data).hexdigest().upper())
            replaced.add(row["path"])
    if not set(NATIVE_NAMES).issubset(replaced):
        raise RuntimeError("native entry points are missing from the frozen runtime")
    for relative in sorted(overrides.keys() - replaced):
        data = overrides[relative]
        revised["files"].append({
            "path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest().upper(),
        })
    revised["files"].sort(key=lambda row: row["path"])
    missing = set(contract.REQUIRED_FILES) - {row["path"] for row in revised["files"]}
    if missing:
        raise ValueError(f"incomplete runtime: {sorted(missing)}")
    archive = work / f"LAKIS_Runtime_{version}.zip"
    print("LOCAL_PACKAGE_STARTED", flush=True)
    packages = {}
    distribution_names = set()
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as output:
        for row in revised["files"]:
            relative = row["path"]
            if relative in overrides:
                output.writestr(relative, overrides[relative])
                continue
            observed, count = hashlib.sha256(), 0
            metadata = BytesFeedParser() if (
                re.fullmatch(
                    r"python_embeded/Lib/site-packages/[^/]+\.dist-info/METADATA",
                    relative,
                )
            ) else None
            with (source / relative).open("rb") as incoming, output.open(relative, "w", force_zip64=True) as entry:
                for block in iter(lambda: incoming.read(1024 * 1024), b""):
                    observed.update(block)
                    count += len(block)
                    entry.write(block)
                    if metadata is not None:
                        metadata.feed(block)
            if count != row["size"] or observed.hexdigest().upper() != row["sha256"]:
                raise RuntimeError("runtime input changed: " + relative)
            if metadata is not None:
                headers = metadata.close()
                name, version = headers.get("Name"), headers.get("Version")
                if not name or not version:
                    raise RuntimeError("incomplete package metadata: " + relative)
                canonical = re.sub(r"[-_.]+", "-", name).lower()
                if canonical in distribution_names:
                    raise RuntimeError("duplicate installed distribution: " + canonical)
                distribution_names.add(canonical)
                packages[name] = version
        if not packages:
            raise RuntimeError("runtime has no installed-distribution metadata")
        revised["runtime"]["packages"] = dict(sorted(packages.items()))
        raw = (json.dumps(revised, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        output.writestr(contract.MANIFEST_NAME, raw)
    assets = work / "assets"
    assets.mkdir()
    parts, combined = [], hashlib.sha256()
    with archive.open("rb") as incoming:
        index = 0
        while incoming.tell() < archive.stat().st_size:
            index += 1
            name = archive.name + f".part{index:03d}"
            part_hash, count = hashlib.sha256(), 0
            with (assets / name).open("xb") as outgoing:
                while count < 1024 ** 3:
                    block = incoming.read(min(1024 * 1024, 1024 ** 3 - count))
                    if not block:
                        break
                    outgoing.write(block)
                    count += len(block)
                    part_hash.update(block)
                    combined.update(block)
            parts.append({
                "name": name, "bytes": count, "sha256": part_hash.hexdigest().upper(),
                "url": f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{version}/" + name,
            })
    bundle = {
        "schema": 2, "product": "LAKIS", "version": version,
        "comfyui_version": contract.COMFY_VERSION, "name": archive.name,
        "bytes": archive.stat().st_size, "files": len(revised["files"]),
        "sha256": combined.hexdigest().upper(),
        "manifest_sha256": hashlib.sha256(raw).hexdigest().upper(), "parts": parts,
    }
    print(json.dumps({"local_bundle": bundle, "native_hashes": {
        name: hashlib.sha256(data).hexdigest().upper() for name, data in overrides.items()
    }}), flush=True)
    return assets, bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--expected-manifest", default=PREVIEW_MANIFEST)
    parser.add_argument("--bridge", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="ln-"))
    print("NATIVE_BENCHMARK_WORKSPACE=" + str(work), flush=True)
    embedded_path, _ = invoke(args.probe, "helpers")
    embedded = Path(embedded_path.strip())
    pins = {name: digest(embedded / name) for name in bridge.RUNTIME_HELPERS}
    pins.update({name: digest(args.bridge / name) for name in NATIVE_NAMES})
    pins["probe"] = digest(args.probe)
    print(json.dumps({"source_and_binary_hashes": pins}), flush=True)
    start = time.monotonic()
    manifest = contract.verify_runtime(args.candidate, args.expected_manifest, "8.0.0")
    input_verification = time.monotonic() - start
    required = 7 * sum(row["size"] for row in manifest["files"])
    if shutil.disk_usage(work).free < required:
        raise RuntimeError("insufficient space for retained isolated runtime test artifacts")
    assets, bundle = package(args.candidate, manifest, args.bridge, work)
    document = {
        "schema": 2, "kind": "runtime-update", "version": "8.0.0",
        "minimum_version": "7.5.4", "minimum_updater_version": "8.0.0",
        "files": [], "delete": [], "runtime_bundle": bundle,
    }
    descriptor = work / "update.json"
    descriptor.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    target = work / "t"
    target.mkdir()
    for name in NATIVE_NAMES:
        shutil.copyfile(args.bridge / name, target / name)
    # A correctly named parent exercises real PID/start-time handoff validation.
    parent = target / "LAKIS_Updater.exe"
    shutil.copyfile(args.probe, parent)
    old_files = {
        "VERSION": b"7.5.4", "python_embeded/python.exe": b"old-python-fixture",
        "ComfyUI/main.py": b"old-core-fixture",
        "ComfyUI/LAKIS/STOP_AUTOMATION": b"stop",
    }
    user_files = {
        "ComfyUI/models/checkpoints/model.bin": b"model-must-not-be-opened",
        "ComfyUI/models/loras/lora.bin": b"lora-preserved",
        "ComfyUI/input/input.png": b"input-preserved",
        "ComfyUI/output/output.png": b"output-preserved",
        "ComfyUI/user/default/workflows/saved.json": b'{"retained":42}',
        "ComfyUI/user/runtime-health-profile/lora-manager/recipes.db": b"existing-profile-must-not-be-opened",
    }
    for relative, data in {**old_files, **user_files}.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    identities = {relative: (target / relative).stat().st_ino for relative in user_files}
    before = {relative: digest(target / relative) for relative in (*old_files, *NATIVE_NAMES)}
    database = target / "ComfyUI/user/comfyui.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("create table preservation_fixture(value integer)")
        db.execute("insert into preservation_fixture values (42)")
    database_before = digest(database)
    requests = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            super().do_GET()

        def log_message(self, *_):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(assets)))
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    environment = dict(os.environ, LAKIS_RC_RELEASE_BASE_URL=f"http://127.0.0.1:{http.server_port}")
    cache = work / "cache"
    cache.mkdir()
    try:
        last, prepare_seconds = invoke(parent, "runtime-prepare",
            args.candidate / "python_embeded/python.exe", descriptor, target, cache, environment=environment)
    finally:
        http.shutdown()
        http.server_close()
        worker.join()
    handoff = json.loads(last)
    locked = contract._open(str(target / "ComfyUI/models/checkpoints/model.bin"), 0x80000000, 0, None, 3, 0x80, None)
    if locked == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        last, apply_seconds = invoke(args.probe, "runtime-apply", handoff["path"], handoff["sha256"])
    finally:
        contract._close(locked)
    result = json.loads(last)
    if result["status"] != "complete":
        raise RuntimeError("native runtime update did not complete")
    for name in NATIVE_NAMES:
        if digest(target / name) != pins[name]:
            raise RuntimeError("installed native entry point mismatch: " + name)
    with closing(sqlite3.connect(database)) as db:
        if db.execute("pragma integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("database integrity failure")
        if db.execute("select value from preservation_fixture").fetchall() != [(42,)]:
            raise RuntimeError("database preservation failure")
    invoke(args.probe, "guard", target)
    for relative, data in user_files.items():
        path = target / relative
        if path.read_bytes() != data or path.stat().st_ino != identities[relative]:
            raise RuntimeError("user data changed: " + relative)
    new_output = target / "ComfyUI/output/new-after-update.png"
    new_output.write_bytes(b"new-image")
    last, rollback_seconds = invoke(args.probe, "runtime-recover", handoff["path"], handoff["sha256"])
    if json.loads(last)["status"] != "rolled-back" or digest(database) != database_before:
        raise RuntimeError("native rollback or database restoration failed")
    for relative, expected in before.items():
        if digest(target / relative) != expected:
            raise RuntimeError("program rollback mismatch: " + relative)
    for relative, data in user_files.items():
        path = target / relative
        if path.read_bytes() != data or path.stat().st_ino != identities[relative]:
            raise RuntimeError("rollback changed user data: " + relative)
    if new_output.read_bytes() != b"new-image":
        raise RuntimeError("new output was not preserved")
    invoke(args.probe, "guard", target)
    print(json.dumps({
        "status": "native-benchmark-complete", "workspace": str(work),
        "fixture_scope": "synthetic-old-core; real-new-runtime; native-helper-methods; no-GUI",
        "input_verification_seconds": input_verification,
        "native_prepare_seconds": prepare_seconds, "native_apply_seconds": apply_seconds,
        "component_timings": result["timings"], "rollback_seconds": rollback_seconds,
        "local_http_requests": requests, "internet_download_included": False,
        "user_data_preserved": True, "database_integrity": "ok", "new_output_preserved": True,
    }), flush=True)


if __name__ == "__main__":
    main()
