"""Pin the same frozen runtime and default models for GUI and CMD Setup."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from runtime_install import validate_bundle


def build(repo: Path, bundle_path: Path, webview_path: Path, output: Path) -> dict:
    version = (repo / "VERSION").read_text(encoding="utf-8-sig").strip()
    template = json.loads(
        (repo / "installer/cmd-installer-manifest.json").read_text(encoding="utf-8")
    )
    if version != "8.0.0" or template["version"] != version:
        raise ValueError("installer template version mismatch")
    bundle = validate_bundle(
        json.loads(bundle_path.read_text(encoding="utf-8-sig")), version
    )
    webview = json.loads(webview_path.read_text(encoding="utf-8-sig"))
    executable = webview_path.parent / "MicrosoftEdgeWebview2Setup.exe"
    with executable.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest().upper()
    if (
        webview.get("name") != executable.name
        or not str(webview.get("url", "")).startswith("https://")
        or webview.get("sha256") != digest
        or webview.get("bytes") != executable.stat().st_size
    ):
        raise ValueError("WebView2 bootstrapper build contract mismatch")
    # Legacy per-node installation and repair-pack fields are not distributed.
    manifest = {
        "schema": 1,
        "version": version,
        "base": template["base"],
        "models": template["models"],
        "optional_animesharp": template["optional_animesharp"],
        "webview2": webview,
        "runtime_bundle": bundle,
    }
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with output.open("xb") as stream:
        stream.write(raw)
    return {
        "path": str(output),
        "version": version,
        "sha256": hashlib.sha256(raw).hexdigest().upper(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--webview2", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.bundle,
                           args.webview2, args.output)))
