"""Test-only authenticated GitHub transport; never publishes or exposes tokens."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import subprocess
import threading
import time


def github_json(endpoint):
    result = subprocess.run(
        ["gh", "api", endpoint], capture_output=True, text=True,
        encoding="utf-8", check=True, timeout=30)
    return json.loads(result.stdout)


def validate_assets(release, bundle, tag):
    if (release["draft"] is not True or release["published_at"] is not None
            or release["tag_name"] != tag):
        raise ValueError("expected the approved unpublished draft")
    assets = {row["name"]: row for row in release["assets"]}
    if len(assets) != len(release["assets"]) or set(assets) != {
            row["name"] for row in bundle["parts"]}:
        raise ValueError("draft asset set differs from the frozen bundle")
    for part in bundle["parts"]:
        asset = assets[part["name"]]
        if (asset["state"] != "uploaded" or asset["size"] != part["bytes"]
                or asset["digest"].lower() != "sha256:" + part["sha256"].lower()):
            raise ValueError("draft asset integrity mismatch: " + part["name"])
    return assets


def range_offset(value, total):
    if value is None:
        return 0
    match = re.fullmatch(r"bytes=(\d+)-", value)
    if not match or int(match[1]) >= total:
        raise ValueError("unsupported or out-of-bounds range")
    return int(match[1])


class PrivateDraftRelay:
    """Stream a fixed draft's assets through an explicit loopback RC endpoint.

    GitHub CLI owns authentication and TLS. The product downloader still checks
    the requested range, length and SHA-256. Upstream always reads the complete
    asset; a resumed request discards its prefix, so that overhead is measured.
    This is not the public, direct-Python HTTPS delivery path.
    """

    def __init__(self, repo, release_id, tag, bundle):
        release = github_json(f"repos/{repo}/releases/{release_id}")
        if release["id"] != release_id:
            raise ValueError("draft release identity mismatch")
        assets = validate_assets(release, bundle, tag)
        parts = {"/" + row["name"]: row for row in bundle["parts"]}
        self.requests = []
        self.events = []
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in parts:
                    self.send_error(404)
                    return
                part = parts[self.path]
                try:
                    offset = range_offset(self.headers.get("Range"), part["bytes"])
                except ValueError:
                    self.send_error(416)
                    return
                relay.requests.append(self.path)
                asset = assets[part["name"]]
                command = [
                    "gh", "api", "-H", "Accept: application/octet-stream",
                    f"repos/{repo}/releases/assets/{asset['id']}",
                ]
                started = time.monotonic()
                process = None
                error_reader = None
                errors = []
                count = sent = 0
                digest = hashlib.sha256()
                event = {
                    "asset": part["name"], "asset_id": asset["id"],
                    "offset": offset, "status": "failed",
                }
                try:
                    process = subprocess.Popen(
                        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                    def drain_error():
                        errors.append(process.stderr.read())

                    error_reader = threading.Thread(target=drain_error, daemon=True)
                    error_reader.start()
                    self.send_response(206 if offset else 200)
                    self.send_header("Content-Length", str(part["bytes"] - offset))
                    if offset:
                        self.send_header(
                            "Content-Range",
                            f"bytes {offset}-{part['bytes'] - 1}/{part['bytes']}")
                    self.end_headers()
                    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
                        previous = count
                        count += len(chunk)
                        if count > part["bytes"]:
                            raise ValueError("upstream asset exceeds its frozen size")
                        digest.update(chunk)
                        outgoing = chunk[max(0, offset - previous):]
                        if outgoing:
                            self.wfile.write(outgoing)
                            sent += len(outgoing)
                    code = process.wait(timeout=30)
                    error_reader.join(timeout=5)
                    event["exit_code"] = code
                    if (code != 0 or count != part["bytes"]
                            or digest.hexdigest().upper() != part["sha256"].upper()
                            or sent != part["bytes"] - offset):
                        raise RuntimeError("authenticated upstream transfer failed validation")
                    event["status"] = "complete"
                    event["sha256"] = digest.hexdigest().upper()
                except Exception as error:
                    event["error_type"] = type(error).__name__
                    event["error"] = str(error)
                    self.close_connection = True
                finally:
                    if process is not None:
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=10)
                        process.stdout.close()
                        if error_reader is not None:
                            error_reader.join(timeout=5)
                        process.stderr.close()
                    # Never print authenticated CLI diagnostics or signed URLs.
                    if errors and errors[0]:
                        event["stderr_bytes"] = len(errors[0])
                        event["stderr_sha256"] = hashlib.sha256(errors[0]).hexdigest()
                    event.update(
                        upstream_bytes=count, downstream_bytes=sent,
                        elapsed_seconds=time.monotonic() - started)
                    relay.events.append(event)
                    print(json.dumps({"status": "PRIVATE_RELAY_TRANSFER", **event}), flush=True)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = False

    def verify_complete(self, bundle):
        if (len(self.events) != len(bundle["parts"])
                or {row["asset"] for row in self.events}
                != {row["name"] for row in bundle["parts"]}
                or any(row["status"] != "complete" or row["offset"] != 0
                       for row in self.events)):
            raise RuntimeError("draft relay was incomplete, retried, or failed; timing is not a clean trial")
