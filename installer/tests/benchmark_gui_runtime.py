"""Isolated real-program clone, native preparation, and actual updater GUI.

The desktop driver must observe and dismiss the update completion dialog, close
that window, approve the recovery dialog, and close the recovered window. This
runner never sends desktop input. Local delivery is not Internet performance.
"""
import argparse
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import zipfile

from benchmark_native_runtime import invoke, NATIVE_NAMES
from benchmark_runtime_patch import digest
import runtime_manifest as contract
from runtime_patch import component_plan
from runtime_transition import _load_journal


def emit(status, **values):
    print(json.dumps({"status": status, **values}), flush=True)


def program_files(root, scopes=None):
    allowed = {scope.casefold() for scope in scopes} if scopes is not None else None
    ancestors = {
        "/".join(scope.split("/")[:index])
        for scope in (allowed or ()) for index in range(1, len(scope.split("/")))
    }

    def selected(relative, directory=False):
        if allowed is None:
            return True
        parts = relative.casefold().split("/")
        return (directory and relative.casefold() in ancestors) or any(
            "/".join(parts[:index]) in allowed for index in range(1, len(parts) + 1))

    for parent, directories, names in os.walk(root, followlinks=False):
        for name in list(directories):
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            if (not selected(relative, True) or contract.protected_path(relative)
                    or contract.generated_path(relative)):
                directories.remove(name)
            elif path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("program directory is a reparse point: " + relative)
        for name in names:
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            if (not selected(relative) or contract.protected_path(relative)
                    or contract.generated_path(relative)):
                continue
            if path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("program file is a reparse point: " + relative)
            yield relative, path


def copy_program(source, target, entries):
    before = {}
    for relative, original in entries:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        observed = hashlib.sha256()
        with original.open("rb") as incoming, destination.open("xb") as outgoing:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                observed.update(block)
                outgoing.write(block)
        expected = observed.hexdigest().upper()
        if digest(destination) != expected:
            raise RuntimeError("program clone mismatch: " + relative)
        before[relative] = expected
    if (source / "VERSION").read_text().strip() != "7.5.3":
        raise ValueError("source installation must remain at 7.5.3")
    return before


def check_preservation(target, fixtures, identities, database):
    for relative, content in fixtures.items():
        path = target / relative
        if path.read_bytes() != content or path.stat().st_ino != identities[relative]:
            raise RuntimeError("protected data changed: " + relative)
    with closing(sqlite3.connect(database)) as db:
        if db.execute("pragma integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("database integrity failure")
        if db.execute("select value from preservation_fixture").fetchall() != [(42,)]:
            raise RuntimeError("database contents changed")


def wait_for_phase(target, process, expected):
    deadline = time.monotonic() + 1200
    last = None
    while time.monotonic() < deadline:
        state = _load_journal(target)
        phase = state["phase"] if state else None
        if phase != last:
            emit("GUI_TRANSACTION_PHASE", phase=phase, pid=process.pid)
            last = phase
        if phase == expected:
            return time.monotonic()
        if expected == "complete" and phase == "rolled-back":
            raise RuntimeError("GUI update rolled back instead of completing")
        if process.poll() is not None:
            raise RuntimeError("GUI exited before the required transaction phase")
        time.sleep(0.25)
    raise TimeoutError("GUI transaction did not reach " + expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bridge-overlay", required=True, type=Path)
    parser.add_argument("--bridge-manifest", required=True, type=Path)
    parser.add_argument("--trial", required=True, type=Path)
    parser.add_argument("--bridge", required=True, type=Path)
    parser.add_argument("--parent", required=True, type=Path)
    parser.add_argument("--prepare-probe", type=Path)
    parser.add_argument("--draft-release", type=int)
    parser.add_argument("--draft-tag")
    args = parser.parse_args()
    if bool(args.draft_release) != bool(args.draft_tag):
        parser.error("--draft-release and --draft-tag must be provided together")
    source = args.source.resolve()
    contract.reject_reparse_path(source)
    if (source / "VERSION").read_text().strip() != "7.5.3":
        raise ValueError("expected the unchanged 7.5.3 program source")
    work = Path(tempfile.mkdtemp(prefix="gui-trial-", dir=args.parent))
    target = work / "LAKIS"
    descriptor = args.trial / "update.json"
    document = json.loads(descriptor.read_text(encoding="utf-8"))
    bundle = document["runtime_bundle"]
    archive = args.trial / bundle["name"]
    if digest(archive).upper() != bundle["sha256"]:
        raise ValueError("retained research archive changed")
    with zipfile.ZipFile(archive) as zipped:
        expanded_bytes = sum(row.file_size for row in zipped.infolist())
        manifest_bytes = zipped.read(contract.MANIFEST_NAME)
    if hashlib.sha256(manifest_bytes).hexdigest().upper() != bundle["manifest_sha256"]:
        raise ValueError("research runtime manifest changed")
    scopes = [group["path"] for group in component_plan(json.loads(manifest_bytes))]
    entries = list(program_files(source, scopes))
    overlay = json.loads(args.bridge_manifest.read_text(encoding="utf-8-sig"))
    if overlay["version"] != "7.5.4":
        raise ValueError("expected the frozen 7.5.4 bridge manifest")
    retired = {contract.normalized_path(relative) for relative in overlay["delete"]}
    if any(contract.protected_path(relative) or contract.generated_path(relative)
           for relative in retired):
        raise ValueError("bridge removal list contains protected data")
    # Construct the post-bridge fixture without copying retired program files.
    # Nothing in the original installation is removed or changed.
    entries = [(relative, path) for relative, path in entries if relative not in retired]
    source_bytes = sum(path.stat().st_size for _, path in entries)
    overlay_files = []
    with zipfile.ZipFile(args.bridge_overlay) as bridge_archive:
        for row in overlay["files"]:
            relative = contract.normalized_path(row["path"])
            if contract.protected_path(relative) or contract.generated_path(relative):
                raise ValueError("bridge overlay contains protected data")
            content = bridge_archive.read(relative)
            if hashlib.sha256(content).hexdigest().upper() != row["sha256"].upper():
                raise ValueError("bridge overlay does not match the release: " + relative)
            overlay_files.append((relative, content, row["sha256"].upper()))
    required = source_bytes + 3 * expanded_bytes + 2 * bundle["bytes"]
    if shutil.disk_usage(work).free < required:
        raise RuntimeError("insufficient space for clone, candidate, staging and retained recovery")
    emit("GUI_FIXTURE_STARTED", workspace=str(work), source=str(source),
         source_files=len(entries), source_bytes=source_bytes, required_free_bytes=required)
    before = copy_program(source, target, entries)
    source_before = dict(before)
    for relative, content, expected in overlay_files:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        if digest(destination) != expected:
            raise RuntimeError("bridge overlay copy mismatch: " + relative)
        before[relative] = expected
    (target / "VERSION").write_bytes(b"7.5.4")
    before["VERSION"] = digest(target / "VERSION")
    emit("GUI_FIXTURE_READY", workspace=str(work), program_files=len(before),
         origin="managed public program scopes from 7.5.3 plus hash-verified 7.5.4 bridge",
         source_version_unchanged="7.5.3", user_data_copied=False)
    fixtures = {
        "ComfyUI/models/checkpoints/model.bin": b"gui-model-preserved",
        "ComfyUI/models/loras/lora.bin": b"gui-lora-preserved",
        "ComfyUI/input/input.png": b"gui-input-preserved",
        "ComfyUI/output/output.png": b"gui-output-preserved",
        "ComfyUI/user/default/workflows/saved.json": b'{"preserved":42}',
        "ComfyUI/user/runtime-health-profile/lora-manager/recipes.db": b"must-not-open",
        "ComfyUI/LAKIS/external_ui_user_state.json": b'{"custom":"preserved"}',
    }
    for relative, content in fixtures.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    identities = {relative: (target / relative).stat().st_ino for relative in fixtures}
    database = target / "ComfyUI/user/comfyui.db"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("create table preservation_fixture(value integer)")
        db.execute("insert into preservation_fixture values (42)")
    database_before = digest(database)
    cache = work / "cache"
    cache.mkdir()
    temporary = work / "temp"
    temporary.mkdir()
    parent = work / "parent/LAKIS_Updater.exe"
    parent.parent.mkdir()
    shutil.copyfile(args.prepare_probe or args.bridge / "BridgeProbe.exe", parent)
    offsets, position = {}, 0
    for part in bundle["parts"]:
        offsets["/" + part["name"]] = (position, part["bytes"])
        position += part["bytes"]
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in offsets or self.headers.get("Range"):
                self.send_error(400)
                return
            requests.append(self.path)
            offset, remaining = offsets[self.path]
            self.send_response(200)
            self.send_header("Content-Length", str(remaining))
            self.end_headers()
            with archive.open("rb") as incoming:
                incoming.seek(offset)
                while remaining:
                    block = incoming.read(min(1024 * 1024, remaining))
                    if not block:
                        raise EOFError("retained archive ended early")
                    self.wfile.write(block)
                    remaining -= len(block)

        def log_message(self, *_):
            pass

    relay = None
    if args.draft_release:
        from private_draft_relay import PrivateDraftRelay
        relay = PrivateDraftRelay(
            "Jeong-Luke/LAKIS", args.draft_release, args.draft_tag, bundle)
        http = relay.server
        requests = relay.requests
    else:
        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    environment = dict(os.environ, TEMP=str(temporary), TMP=str(temporary),
                       LOCALAPPDATA=str(work / "localappdata"), APPDATA=str(work / "appdata"),
                       LAKIS_RC_RELEASE_BASE_URL=f"http://127.0.0.1:{http.server_port}")
    try:
        last, prepare_seconds = invoke(
            parent, "runtime-prepare-gui" if args.prepare_probe else "runtime-prepare",
            target / "python_embeded/python.exe",
            descriptor, target, cache, environment=environment)
    finally:
        http.shutdown()
        http.server_close()
        worker.join()
    if relay is not None:
        relay.verify_complete(bundle)
    handoff = json.loads(last)
    native = args.bridge / "LAKIS_Updater.exe"
    pins = {name: digest(args.bridge / name) for name in NATIVE_NAMES}
    started = time.monotonic()
    process = subprocess.Popen([str(native), "--finish-runtime-transition",
                                handoff["path"], handoff["sha256"]],
                               cwd=work, env=environment)
    emit("GUI_UPDATE_RUNNING", pid=process.pid, workspace=str(work),
         target=str(target), handoff=handoff, prepare_seconds=prepare_seconds,
         executable=str(native), updater_sha256=pins["LAKIS_Updater.exe"])
    finished = wait_for_phase(target, process, "complete")
    for name, expected in pins.items():
        if digest(target / name) != expected:
            raise RuntimeError("updated native binary mismatch: " + name)
    if (target / "VERSION").read_text().strip() != document["version"]:
        raise RuntimeError("updated version mismatch")
    check_preservation(target, fixtures, identities, database)
    emit("GUI_UPDATE_VERIFIED", gui_apply_seconds=finished - started,
         prepare_seconds=prepare_seconds,
         local_prepare_plus_gui_apply_seconds=prepare_seconds + finished - started,
         protected_files=len(fixtures), database_integrity="ok",
         awaiting="observe completion, dismiss dialog and close this test window")
    process.wait(timeout=1800)
    if process.returncode != 0:
        raise RuntimeError("updater GUI process exited with an error")
    new_output = target / "ComfyUI/output/new-after-update.png"
    new_output.write_bytes(b"gui-new-image")
    recovery = subprocess.Popen([str(native), "--recover-runtime-transition",
                                 handoff["path"], handoff["sha256"]],
                                cwd=work, env=environment)
    emit("GUI_RECOVERY_RUNNING", pid=recovery.pid, workspace=str(work),
         awaiting="approve recovery in this test window")
    wait_for_phase(target, recovery, "rolled-back")
    check_preservation(target, fixtures, identities, database)
    if digest(database) != database_before or new_output.read_bytes() != b"gui-new-image":
        raise RuntimeError("recovery changed database or newly generated output")
    restored = {relative: digest(path) for relative, path in program_files(target)}
    if restored != before:
        raise RuntimeError("recovered program files differ from the original clone")
    for relative in ("VERSION", "ComfyUI/main.py", "python_embeded/python.exe", *NATIVE_NAMES):
        if digest(source / relative) != source_before[relative]:
            raise RuntimeError("preserved source anchor changed: " + relative)
    emit("GUI_RECOVERY_VERIFIED", program_files=len(before), database_integrity="ok",
         protected_data_preserved=True, new_output_preserved=True,
         awaiting="observe recovered state and close this test window")
    recovery.wait(timeout=1800)
    if recovery.returncode != 0:
        raise RuntimeError("recovery GUI process exited with an error")
    emit("GUI_BENCHMARK_COMPLETE", workspace=str(work),
         fixture_scope="real 7.5.3 managed programs plus verified 7.5.4 bridge; synthetic user data; real new runtime",
         native_prepare_seconds=prepare_seconds, gui_apply_seconds=finished - started,
         internet_download_included=relay is not None,
         initial_download_gui_included=args.prepare_probe is not None,
         transport="authenticated GitHub CLI through loopback RC relay" if relay else "local HTTP",
         relay_transfers=relay.events if relay else [],
         update_and_recovery_gui=True, database_integrity="ok",
         original_source_preserved=True, local_http_requests=requests)


if __name__ == "__main__":
    main()
