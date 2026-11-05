"""Prepare a private, dirty-source integration test without publishing.

The production installer still requires committed source. This fixture records
the base commit, tracked diff and complete build-input snapshot separately;
it must not be represented as a release built from that base commit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "installer"))
from lakis_cmd_installer import reject_reparse_path
import runtime_manifest as contract


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest().upper()


def frozen_source(destination):
    files = [ROOT / name for name in (
        "VERSION", "LICENSE.md", "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md",
    )]
    for name in ("src", "installer", "resources", "workflows", "third_party_licenses"):
        files.extend(path for path in (ROOT / name).rglob("*") if path.is_file())
    pins = []
    for path in sorted(files):
        relative = path.relative_to(ROOT).as_posix()
        if contract.generated_path(relative):
            continue
        reject_reparse_path(path)
        data = path.read_bytes()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        pins.append({"path": relative, "size": len(data),
                     "sha256": hashlib.sha256(data).hexdigest().upper()})
    return pins


def overlay(source, target):
    reject_reparse_path(source)
    reject_reparse_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if digest(source) != digest(target):
        raise ValueError("application overlay mismatch: " + str(source))


def seed_model(source, target, expected_size, expected_hash):
    reject_reparse_path(source)
    reject_reparse_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    observed, size = hashlib.sha256(), 0
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        for block in iter(lambda: incoming.read(1024 * 1024), b""):
            outgoing.write(block)
            observed.update(block)
            size += len(block)
    if size != expected_size or observed.hexdigest().upper() != expected_hash.upper():
        raise ValueError("model input failed verification: " + str(source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-manifest-sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-diff", type=Path, required=True)
    parser.add_argument("--workspace-parent", type=Path, required=True)
    parser.add_argument("--moss-models", type=Path, required=True)
    parser.add_argument("--anima-models", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-fA-F0-9]{40}", args.source_revision):
        raise ValueError("a base source commit is required")
    diff = reject_reparse_path(args.source_diff).read_bytes()
    parent = reject_reparse_path(args.workspace_parent)
    work = Path(tempfile.mkdtemp(prefix="integrated810-private-", dir=parent))
    frozen, candidate = work / "source", work / "candidate"
    print("PRIVATE_PREVIEW_WORKSPACE=" + str(work), flush=True)
    pins = frozen_source(frozen)
    snapshot_hash = write_json(work / "source-snapshot.json", {
        "root": str(ROOT), "base_revision": args.source_revision,
        "uncommitted": True, "files": pins,
    })
    with (work / "tracked.diff").open("xb") as stream:
        stream.write(diff)
    version = (frozen / "VERSION").read_text(encoding="utf-8-sig").strip()
    if version != "8.1.0":
        raise ValueError("this fixture prepares only the 8.1.0 integration preview")
    baseline = contract.verify_runtime(
        args.baseline, args.baseline_manifest_sha256, "8.0.0",
        stage_root=candidate,
    )
    print("BASELINE_VERIFIED_AND_COPIED", flush=True)

    # Match the application's public New-ReleaseLayout.ps1 destinations.
    for name in ("VERSION", "LICENSE.md", "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md"):
        overlay(frozen / name, candidate / name)
    for tree, destination in (
        ("src/external_ui", "ComfyUI/LAKIS/external_ui"),
        ("third_party_licenses", "third_party_licenses"),
    ):
        for source in (frozen / tree).rglob("*"):
            if source.is_file() and source.name != "release-integrity.json":
                overlay(source, candidate / destination / source.relative_to(frozen / tree))
    for name in ("LAKIS_runtime_api_v7.4.json", "LAKIS_runtime_visual_v7.4.json"):
        overlay(frozen / "workflows" / name, candidate / "ComfyUI/LAKIS/workflows" / name)
    for name in ("LAKIS_custom_v8.0_editable.json", "LAKIS_runtime_visual_v8.0.json",
                 "LAKIS_runtime_api_v8.0.json", "LAKIS_MOSS_runtime_api_v8.1.json",
                 "LAKIS_MOSS_custom_v8.1_editable.json"):
        overlay(frozen / "workflows" / name,
                candidate / "ComfyUI/LAKIS/external_ui/workflows" / name)
    for source, destination in (
        ("resources/STOP_AUTOMATION", "ComfyUI/LAKIS/STOP_AUTOMATION"),
        ("src/runtime/sync_runtime_workflow.py", "ComfyUI/LAKIS/sync_runtime_workflow.py"),
        ("src/runtime/native_workflow.py", "ComfyUI/LAKIS/external_ui/runtime/native_workflow.py"),
        ("resources/LAKIS_windows_compatible.ico", "LAKIS.ico"),
    ):
        overlay(frozen / source, candidate / destination)
    packages = (frozen / "resources/PRODUCTION_NODE_PACKAGES.txt").read_text(encoding="utf-8")
    for package in packages.splitlines():
        package = package.strip()
        if not package or package.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", package):
            raise ValueError("invalid public node package: " + package)
        package_root = frozen / "src/custom_nodes" / package
        for source in package_root.rglob("*"):
            if source.is_file() and source.name != "startup_workflow.json":
                overlay(source, candidate / "ComfyUI/custom_nodes" / package
                        / source.relative_to(package_root))

    # Reuse the compiler helper from the frozen source, not the live checkout.
    sys.path.insert(0, str(frozen / "installer"))
    import build_updater_bridge as native
    for output, source in (
        ("LAKIS.exe", "LAKIS_Launcher.cs"), ("LAKIS_Updater.exe", "LAKIS_Updater.cs"),
        ("LAKIS_Model_Importer.exe", "LAKIS_Model_Importer.cs"),
        ("Uninstall_LAKIS.exe", "LAKIS_Uninstaller.cs"),
    ):
        native.compile_native(candidate / output, [frozen / "installer" / source])
    shutil.copyfile(candidate / "LAKIS_Updater.exe", candidate / "LAKIS_Patcher.exe")
    subprocess.run([
        str(native.compiler()), "/nologo", "/target:winexe",
        "/out:" + str(candidate / "LAKIS_Desktop.exe"),
        "/win32icon:" + str(frozen / "resources/LAKIS_windows_compatible.ico"),
        "/win32manifest:" + str(frozen / "installer/LAKIS_Desktop.manifest"),
        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
        "/reference:" + str(candidate / "Microsoft.Web.WebView2.Core.dll"),
        "/reference:" + str(candidate / "Microsoft.Web.WebView2.WinForms.dll"),
        str(frozen / "installer/LAKIS_Desktop.cs"),
    ], check=True)

    manifest = contract.create_manifest(
        candidate, version, args.source_revision, deepcopy(baseline["runtime"]),
    )
    manifest.update(private_preview=True, source_snapshot_sha256=snapshot_hash,
                    source_dirty_diff_sha256=hashlib.sha256(diff).hexdigest().upper())
    manifest_hash = write_json(candidate / contract.MANIFEST_NAME, manifest)
    config = json.loads((frozen / "installer/cmd-installer-manifest.json").read_text(encoding="utf-8"))
    for name, url, expected_hash, folder, size in config["models"]:
        model_root = args.moss_models if "/Comfy-Org/MOSS-Image/" in url else args.anima_models
        seed_model(model_root / folder / name, candidate / "ComfyUI/models" / folder / name,
                   size, expected_hash)
        print("MODEL_COPIED_AND_VERIFIED=" + name, flush=True)
    for relative, spec in contract.POSE_MODELS.items():
        source = args.anima_models / Path(relative).relative_to("ComfyUI/models")
        seed_model(source, candidate / relative, spec["size"], spec["sha256"])
    for name in ("input", "output", "user", "temp"):
        (candidate / "ComfyUI" / name).mkdir(parents=True, exist_ok=True)
    receipt = {
        "kind": "private-uncommitted-integration-preview", "published": False,
        "version": version, "workspace": str(work), "candidate": str(candidate),
        "base_revision": args.source_revision, "source_snapshot_sha256": snapshot_hash,
        "source_dirty_diff_sha256": manifest["source_dirty_diff_sha256"],
        "runtime_manifest_sha256": manifest_hash,
        "local_appdata": str(work / "local-appdata"),
        "roaming_appdata": str(work / "roaming-appdata"),
    }
    write_json(work / "private-preview.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
