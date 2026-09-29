#!/usr/bin/env python3
"""Serve one exact Private RC layout/RepairPack as a loopback-only update source."""

import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit
import zipfile


def sha256(data):
    return hashlib.sha256(data).hexdigest().upper()


def load_artifacts(directory):
    directory = directory.resolve()
    layout_path = directory / "release-layout.json"
    pack_path = directory / "LAKIS_RepairPack.zip"
    record_path = directory / "private-rc-build.json"
    layout_bytes = layout_path.read_bytes()
    pack_bytes = pack_path.read_bytes()
    layout = json.loads(layout_bytes.decode("utf-8-sig"))
    record = json.loads(record_path.read_text(encoding="utf-8-sig"))
    recorded = {item["name"]: item["sha256"].upper() for item in record.get("files", [])}
    for name, data in ((layout_path.name, layout_bytes), (pack_path.name, pack_bytes)):
        if recorded.get(name) != sha256(data):
            raise ValueError(f"private-rc-build.json hash mismatch: {name}")
    if str(record.get("version")) != str(layout.get("version")):
        raise ValueError("Private RC record/layout version mismatch")
    with zipfile.ZipFile(pack_path) as archive:
        payload = {
            info.filename.replace("\\", "/").rstrip("/"): archive.read(info)
            for info in archive.infolist() if not info.is_dir()
        }
    expected = {item["path"]: int(item["size"]) for item in layout.get("files", [])}
    if set(payload) != set(expected):
        raise ValueError("RepairPack file set does not match release-layout.json")
    for path, size in expected.items():
        if len(payload[path]) != size:
            raise ValueError(f"RepairPack size mismatch: {path}")
    return layout, layout_bytes, pack_bytes, payload


def make_manifest(layout, payload, base_url):
    return {
        "version": layout["version"],
        "minimum_version": "7.4.5",
        "release_notes": "Tester-only Private RC route; exact candidate payload.",
        "files": [
            {
                "path": item["path"],
                "url": base_url + "/files/" + quote(item["path"], safe="/"),
                "sha256": sha256(payload[item["path"]]),
            }
            for item in layout["files"]
        ],
        "delete": layout.get("retired", []),
    }


def handler_factory(layout_bytes, pack_bytes, payload, manifest_bytes):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path == "/release-layout.json":
                data, content_type = layout_bytes, "application/json"
            elif path == "/LAKIS_RepairPack.zip":
                data, content_type = pack_bytes, "application/zip"
            elif path == "/update-latest.json":
                data, content_type = manifest_bytes, "application/json"
            elif path.startswith("/files/") and path[7:] in payload:
                data, content_type = payload[path[7:]], "application/octet-stream"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format_string, *args):
            sys.stderr.write("RC server: " + format_string % args + "\n")

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--launch", type=Path, help="tester-bootstrapped LAKIS install root")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    layout, layout_bytes, pack_bytes, payload = load_artifacts(args.artifact_dir)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), http.server.BaseHTTPRequestHandler)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    manifest = make_manifest(layout, payload, base_url)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    server.RequestHandlerClass = handler_factory(layout_bytes, pack_bytes, payload, manifest_bytes)
    rc_environment = {
        "LAKIS_RC_RELEASE_BASE_URL": base_url,
        "LAKIS_RC_MANIFEST_URL": base_url + "/update-latest.json",
    }
    print(json.dumps({"status": "READY", "version": layout["version"], **rc_environment}), flush=True)
    if args.launch:
        launcher = args.launch.resolve() / "LAKIS.exe"
        if not launcher.is_file():
            raise FileNotFoundError(f"Missing tester-bootstrapped Launcher: {launcher}")
        environment = os.environ.copy()
        environment.update(rc_environment)
        subprocess.Popen([str(launcher)], cwd=str(launcher.parent), env=environment)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
