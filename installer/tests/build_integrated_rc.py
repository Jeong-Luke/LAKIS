"""Build a private integration package without modifying an installation.

This uses a frozen source snapshot, a frozen development-runtime manifest, and
freshly compiled native entry points. It does not publish anything or bypass
the committed-source guard of the production installer builder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def pinned_json(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != expected.upper():
        raise ValueError("frozen input changed: " + str(path))
    return json.loads(raw)


def write_json(path, document):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--source-snapshot-sha256", required=True)
    parser.add_argument("--source-diff", type=Path, required=True)
    parser.add_argument("--source-diff-sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--workspace-parent", type=Path, required=True)
    args = parser.parse_args()
    snapshot = pinned_json(args.source_snapshot, args.source_snapshot_sha256)
    if Path(snapshot["root"]).resolve() != REPOSITORY:
        raise ValueError("source snapshot belongs to another worktree")
    if digest(args.source_diff) != args.source_diff_sha256.upper():
        raise ValueError("source diff changed")
    source_manifest = pinned_json(
        args.runtime / "RUNTIME_SHA256SUMS.json", args.runtime_manifest_sha256
    )
    if source_manifest["version"] != "8.0.0":
        raise ValueError("expected the frozen 8.0.0 development runtime")

    work = Path(tempfile.mkdtemp(prefix="integrated800-", dir=args.workspace_parent))
    frozen = work / "source"
    frozen.mkdir()
    pins = {}
    for row in snapshot["files"]:
        relative = row["path"]
        original = (REPOSITORY / relative).resolve()
        destination = (frozen / relative).resolve()
        if not original.is_relative_to(REPOSITORY) or not destination.is_relative_to(frozen):
            raise ValueError("source snapshot path escapes its root")
        key = relative.casefold()
        if key in pins:
            raise ValueError("duplicate source snapshot path: " + relative)
        data = original.read_bytes()
        if len(data) != row["size"] or hashlib.sha256(data).hexdigest().upper() != row["sha256"].upper():
            raise ValueError("source changed after freeze: " + relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
        pins[key] = row
    if (frozen / "VERSION").read_text(encoding="utf-8-sig").strip() != "8.0.0":
        raise ValueError("source version does not match the integration candidate")
    shutil.copyfile(args.source_snapshot, work / "source-filesystem-manifest.json")
    shutil.copyfile(args.source_diff, work / "tracked.diff")
    print("INTEGRATED_RC_WORKSPACE=" + str(work), flush=True)

    # Import and compile only from the checked, private source copy.
    sys.path.insert(0, str(frozen / "installer"))
    sys.path.insert(0, str(frozen / "installer/tests"))
    import build_updater_bridge as bridge
    import benchmark_native_runtime as packaging
    import runtime_manifest as contract

    source_manifest["source_revision"] = args.source_revision
    source_manifest["source_snapshot_sha256"] = args.source_snapshot_sha256.upper()
    source_manifest["source_dirty_diff_sha256"] = args.source_diff_sha256.upper()
    contract._validate_identity(source_manifest, "8.0.0")
    native = work / "native"
    native.mkdir()
    bridge.compile_native(native / "LAKIS.exe", [frozen / "installer/LAKIS_Launcher.cs"])
    bridge.compile_native(native / "LAKIS_Updater.exe", [frozen / "installer/LAKIS_Updater.cs"])
    shutil.copyfile(native / "LAKIS_Updater.exe", native / "LAKIS_Patcher.exe")
    probe = work / "BridgeProbe.exe"
    bridge.compile_native(probe, [
        frozen / "installer/LAKIS_Updater.cs", frozen / "installer/LAKIS_Launcher.cs",
        frozen / "installer/tests/UpdaterBridgeProbe.cs",
    ], main="UpdaterBridgeProbe")
    subprocess.run([str(probe), "candidate-engine", str(native)], check=True, timeout=30)
    helpers = Path(subprocess.check_output([str(probe), "helpers"], timeout=30).decode().strip())
    for name in bridge.RUNTIME_HELPERS:
        if digest(helpers / name) != pins["installer/" + name]["sha256"].upper():
            raise ValueError("embedded helper differs from the frozen source: " + name)

    application_files = {}
    for row in snapshot["files"]:
        relative = row["path"]
        if relative.startswith("src/external_ui/"):
            target = "ComfyUI/LAKIS/external_ui/" + relative.removeprefix("src/external_ui/")
        elif relative == "src/custom_nodes/ComfyUI_toyxyz_test_nodes/__init__.py":
            target = "ComfyUI/custom_nodes/ComfyUI_toyxyz_test_nodes/__init__.py"
        elif relative in {"LICENSE.md", "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md"}:
            target = relative
        elif relative.startswith("third_party_licenses/"):
            if relative == "third_party_licenses/NVIDIA-Open-Model-License-2025-10-24.mixdog-edit.pdf":
                continue
            target = relative
        else:
            continue
        if contract.generated_path(target):
            continue
        application_files[target] = {
            "source": frozen / relative, "size": row["size"], "sha256": row["sha256"],
        }
    assets, bundle = packaging.package(
        args.runtime, source_manifest, native, work, application_files=application_files
    )
    native_hashes = {}
    for name in packaging.NATIVE_NAMES:
        shutil.copyfile(native / name, assets / name)
        native_hashes[name] = digest(assets / name)
    release_base = "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/"
    bootstrap = {
        "schema": 2, "kind": "file-patch", "version": "7.5.4.1",
        "minimum_version": "7.5.4", "minimum_updater_version": "7.5.4",
        "release_notes": "8.0.0 업데이트 1/2단계입니다. 새 업데이터로 전환한 뒤 실행 환경과 제어 모델 설치를 자동으로 이어갑니다.",
        "files": [{"path": name, "url": release_base + name, "sha256": native_hashes[name]}
                  for name in packaging.NATIVE_NAMES],
        "delete": [],
    }
    runtime_update = {
        "schema": 2, "kind": "runtime-update", "version": "8.0.0",
        "minimum_version": "7.5.4.1", "minimum_updater_version": "8.0.0",
        "release_notes": "8.0.0 업데이트 2/2단계입니다. 3D 포즈와 새 실행 환경을 설치합니다.",
        "files": [], "delete": [], "runtime_bundle": bundle,
    }
    write_json(assets / "update-v2-latest.json", bootstrap)
    write_json(assets / "update-v3-latest.json", runtime_update)
    write_json(work / "runtime-bundle.json", bundle)
    receipt = {
        "status": "private-integration-package-built", "published": False,
        "workspace": str(work), "source_revision": args.source_revision,
        "source_snapshot_sha256": args.source_snapshot_sha256.upper(),
        "source_dirty_diff_sha256": args.source_diff_sha256.upper(),
        "input_runtime": str(args.runtime),
        "input_manifest_sha256": args.runtime_manifest_sha256.upper(),
        "native_hashes": native_hashes, "bundle": bundle,
        "application_files": {
            name: {"size": pin["size"], "sha256": pin["sha256"].upper()}
            for name, pin in application_files.items()
        },
    }
    write_json(work / "build-receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "receipt": str(work / "build-receipt.json")}), flush=True)


if __name__ == "__main__":
    main()
