"""Overlay the selective pose implementation onto an authorized disposable RC.

This is a development integration fixture, not Fresh/Update/Repair evidence.
The previous source, manifests and original candidate artifacts remain intact.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "installer"))
sys.path.insert(0, str(REPOSITORY / "src/external_ui"))
import build_pose_dependency
import runtime_manifest as contract
import runtime_transition
import scene_controls


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--expected-root", type=Path, required=True)
    parser.add_argument("--dependency", type=Path, required=True)
    parser.add_argument("--dependency-sha256", required=True)
    parser.add_argument("--model-source", type=Path, required=True)
    parser.add_argument("--workspace-parent", type=Path, required=True)
    args = parser.parse_args()
    previous = json.loads(args.context.read_text(encoding="utf-8"))
    root = Path(previous["root"]).resolve()
    assert root == args.expected_root.resolve()
    assert root.name == "LAKIS" and root.parent.name.startswith("lakis-fresh-ssd-")
    assert sha(root / contract.MANIFEST_NAME) == previous["manifest_sha256"]
    assert sha(args.dependency) == args.dependency_sha256.upper()
    fixture = Path(previous["manifest_fixture"])
    assert sha(fixture) == previous["manifest_sha256"]
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    assert manifest["version"] == "8.0.0"
    assert (root / "VERSION").read_text(encoding="utf-8-sig").strip() == "8.0.0"
    build = Path(previous["source_build"])
    receipt = json.loads((build / "validation-receipt.json").read_text(encoding="utf-8"))
    probe_python = Path(receipt["prepared_candidate"]) / "python_embeded/python.exe"
    # The probe itself must not run from the installation whose idleness it checks.
    assert not probe_python.resolve().is_relative_to(root)
    runtime_transition.assert_idle(root, probe_python)

    workspace = Path(tempfile.mkdtemp(prefix="pose-rc-", dir=args.workspace_parent))
    staged = workspace / "overlay"
    sources = {}
    for source in sorted((REPOSITORY / "src/external_ui").rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(REPOSITORY / "src/external_ui").as_posix()
        assert "__pycache__" not in source.parts and source.suffix != ".pyc"
        sources["ComfyUI/LAKIS/external_ui/" + relative] = source
    for relative in (
        "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md",
        "third_party_licenses/Meta-SAM-3D-Body-License.txt",
    ):
        sources[relative] = REPOSITORY / relative
    entries = {row["path"]: row for row in manifest["files"]}
    overlay = {}
    for relative, source in sources.items():
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest().upper()
        old = entries.get(relative)
        if old and (old["size"], old["sha256"].upper()) == (len(data), digest):
            continue
        target = staged / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        overlay[relative] = {"size": len(data), "sha256": digest, "source": str(source)}

    with zipfile.ZipFile(args.dependency) as archive:
        expected_names = {
            build_pose_dependency.PREFIX + name
            for name in (*build_pose_dependency.FILES, "__init__.py", "LAKIS_POSE_SOURCE.json")
        }
        assert set(archive.namelist()) == expected_names
        assert len(archive.namelist()) == len(expected_names)
        for relative in sorted(expected_names):
            data = archive.read(relative)
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            overlay[relative] = {
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest().upper(),
                "source": str(args.dependency) + ":" + relative,
            }

    # Validate every replacement against the frozen baseline before any RC write.
    for relative in overlay:
        target = root / relative
        old = entries.get(relative)
        if old:
            assert target.is_file() and sha(target) == old["sha256"].upper(), relative
        else:
            assert not target.exists(), relative
    runtime_transition.assert_idle(
        root, probe_python,
        file_paths=[root / name for name in overlay if name in entries],
    )

    # These are explicit test fixtures, not payload entries or public downloads.
    model_fixtures = []
    for name, spec in scene_controls.MODELS.items():
        source = args.model_source / name
        assert sha(source) == spec["sha256"].upper()
        target = root / "ComfyUI/models/controlnet" / name
        if target.exists():
            assert sha(target) == spec["sha256"].upper()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = workspace / name
            shutil.copyfile(source, temporary)
            assert sha(temporary) == spec["sha256"].upper()
            os.replace(temporary, target)
        model_fixtures.append({"model": name, "sha256": spec["sha256"], "source": str(source)})
    protected = runtime_transition._data_snapshot(root)
    for relative, row in overlay.items():
        entries[relative] = {"path": relative, "size": row["size"], "sha256": row["sha256"]}
    manifest["files"] = sorted(entries.values(), key=lambda row: row["path"])
    serialized = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    expected_manifest = hashlib.sha256(serialized).hexdigest().upper()
    frozen_manifest = workspace / contract.MANIFEST_NAME
    frozen_manifest.write_bytes(serialized)
    (workspace / "overlay-inputs.json").write_text(
        json.dumps({"files": overlay, "model_fixtures": model_fixtures}, indent=2) + "\n",
        encoding="utf-8",
    )
    for relative in overlay:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged / relative, target)
    staged_manifest = workspace / "manifest-to-install.json"
    staged_manifest.write_bytes(serialized)
    os.replace(staged_manifest, root / contract.MANIFEST_NAME)
    verified = contract.verify_runtime(root, expected_manifest, "8.0.0", allow_user_data=True)
    assert runtime_transition._data_snapshot(root) == protected
    context = copy.deepcopy(previous)
    context.update({
        "base_manifest_sha256": previous["manifest_sha256"],
        "manifest_sha256": expected_manifest,
        "manifest_fixture": str(frozen_manifest),
        "program_files": len(verified["files"]),
        "source_root": str(REPOSITORY),
        "pose_dependency_sha256": args.dependency_sha256.upper(),
        "overlay_inputs": str(workspace / "overlay-inputs.json"),
        "protected_before_launch": protected,
        "scope": "pose integration overlay on existing disposable RC; not final Fresh/Update/Repair evidence",
        "public_release": "NOT PERFORMED",
    })
    context_path = workspace / "context.json"
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "POSE_INTEGRATION_RC_READY", "context": str(context_path),
        "root": str(root), "manifest_sha256": expected_manifest,
        "changed_or_added_files": len(overlay), "program_files": len(verified["files"]),
        "protected_entries_unchanged": len(protected), "test_model_fixtures": model_fixtures,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
