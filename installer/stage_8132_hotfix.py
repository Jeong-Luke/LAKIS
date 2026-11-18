"""Stage private v8.1.3.2 file-patch and repair assets. Do not publish or install."""
import argparse
import io
import json
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from build_813_file_patch import (
    ALIASES, LAYOUT, PACK, ROOT, RUNTIME_HELPERS, canonical_source, compile_updater,
    managed_path, sha256, write_json, write_repair,
)
from lakis_cmd_installer import reject_reparse_path
from runtime_manifest import editable_template_path
from stage_8131_hotfix import (
    ASSETS as PREVIOUS_ASSETS, HELPER, MANIFEST, MINIMUM_VERSION,
    RELEASE as PREVIOUS_RELEASE, SOURCE, VERSION as BASE_VERSION,
)

VERSION = "8.1.3.2"
RELEASE = f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{VERSION}"
REPORT = "finisher-overlays.json"
BASELINE = {
    LAYOUT: (20_944, "54EC54823740CA0E521144CCE143765D04272767AFF90EA7AFB4D16BBC39D01F"),
    PACK: (36_761_052, "9940251498D91AE20217DD54846A6D32C2FEB0C543EC41BCB4C32CA170E79097"),
}
PRE_RUNTIME = ("8.1.0", "8.1.1", "8.1.2")
SUPPORTED = (*PRE_RUNTIME, "8.1.3", BASE_VERSION)
UI_SOURCES = {f"ComfyUI/LAKIS/external_ui/{name}": f"src/external_ui/{name}" for name in (
    "index.html", "anima-reference.js", "anima-reference.css",
)}
TEXT_SOURCES = {**UI_SOURCES, "COMPLIANCE.md": "COMPLIANCE.md", HELPER: SOURCE}
ASSETS = {**PREVIOUS_ASSETS, **{path: Path(path).name for path in UI_SOURCES}, "COMPLIANCE.md": "COMPLIANCE.md"}
# 8.1.0 and 8.1.1 reject both COMPLIANCE.md and the SnapRef installer path.
PATCH_PATHS = (*ALIASES, *UI_SOURCES)
RELEASE_NOTES = (
    "8.1.0~8.1.3.1에서 8.1.3.1을 중간에 설치하지 않고 바로 업데이트합니다.\n"
    "공식 게시자의 SnapRef 추론 노드(Apache-2.0), 라이선스·고지문 및 v2a 가중치(약 382 MB)를 "
    "준비합니다. 가중치에는 CircleStone Labs Non-Commercial License v1.2가 적용되며, "
    "별도 허가 없이 상업적 이용이나 프로덕션 운영을 할 수 없습니다. 레퍼런스 최초 사용 시 별도로 동의합니다."
)


def load_baseline(site):
    # The predecessor's reader is pinned to v8.1.3; the same flat layout/ZIP
    # contract here is authenticated against the public v8.1.3.1 asset pair.
    assets = {}
    for name, (size, digest) in BASELINE.items():
        with reject_reparse_path(site / name).open("rb") as stream:
            data = stream.read(size + 1)
        if (len(data), sha256(data)) != (size, digest):
            raise ValueError(f"baseline {BASE_VERSION} asset size or SHA-256 mismatch: {name}")
        assets[name] = data
    layout = json.loads(assets[LAYOUT])
    if (layout["schema"], layout["product"], layout["version"], layout["editable_template_policy"]) != (
            1, "LAKIS", BASE_VERSION, "preserve-v1"):
        raise ValueError("unexpected baseline layout identity")
    remaining, seen = {}, set()
    for row in layout["files"]:
        path = managed_path(row["path"])
        if path != row["path"] or path.casefold() in seen:
            raise ValueError(f"duplicate or noncanonical baseline path: {path}")
        seen.add(path.casefold())
        remaining[path] = row["size"]
    payload = {}
    with zipfile.ZipFile(io.BytesIO(assets[PACK])) as archive:
        for entry in archive.infolist():
            if (entry.is_dir() or remaining.pop(entry.filename, None) != entry.file_size
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError(f"baseline repair entry does not match layout: {entry.filename}")
            payload[entry.filename] = archive.read(entry)
    if remaining or payload.get("VERSION") != BASE_VERSION.encode("ascii"):
        raise ValueError("incomplete baseline repair payload")
    return layout, payload


def asset_record(path, data):
    return {"path": path, "url": f"{RELEASE}/{ASSETS[path]}", "sha256": sha256(data)}


def patch_manifest(payload):
    return {
        "schema": 2, "kind": "file-patch", "version": VERSION,
        "minimum_version": MINIMUM_VERSION, "minimum_updater_version": MINIMUM_VERSION,
        "release_notes": RELEASE_NOTES, "files": [asset_record(path, payload[path]) for path in sorted(PATCH_PATHS)],
        "delete": [],
    }


def build_report(payload, native_inputs):
    updater = (native_inputs / "installer/LAKIS_Updater.cs").read_text(encoding="utf-8-sig")

    def pin(name):
        (value,) = re.findall(rf'\bconst string {name}\s*=\s*"([^"]+)";', updater)
        return value

    if pin("SnapRefUpdateVersion") != VERSION or pin("PreviousSnapRefUpdateVersion") != BASE_VERSION:
        raise ValueError("compiled finisher does not target this hotfix")
    helper_url = f"{PREVIOUS_RELEASE}/{ASSETS[HELPER]}"
    helper_hash = sha256(payload[HELPER])
    if (pin("SnapRefHelperUrl"), pin("SnapRefHelperSha256")) != (helper_url, helper_hash):
        raise ValueError("staged helper does not match the native finisher pin")

    runtime_helpers = {}
    for name in RUNTIME_HELPERS:
        source = f"installer/{name}"
        # compile_updater embeds the raw copied inputs, not their Git-clean bytes.
        data = (native_inputs / source).read_bytes()
        runtime_helpers[f"LAKIS.Runtime.{name}"] = {"source": source, "bytes": len(data), "sha256": sha256(data)}

    return {
        "version": VERSION,
        "status": "private-draft-release-blocked",
        "baseline": {
            "version": BASE_VERSION,
            "assets": {name: {"bytes": size, "sha256": digest} for name, (size, digest) in BASELINE.items()},
        },
        "supported_sources": list(SUPPORTED),
        "embedded_runtime_helpers": runtime_helpers,
        "runtime_replacement": {
            "source_versions": list(PRE_RUNTIME), "runtime_version": pin("SnapRefSourceVersion"),
            "descriptor_url": pin("HotfixRuntimeUrl"), "descriptor_sha256": pin("HotfixRuntimeSha256"),
        },
        "required_finisher_overlays": [
            {
                **asset_record(path, payload[path]), "bytes": len(payload[path]),
                **({"url": pin("HotfixNoticeUrl")} if path == "COMPLIANCE.md" else {}),
                "source_versions": list(SUPPORTED if path == "COMPLIANCE.md" else PRE_RUNTIME),
                "reason": ("Not accepted by stock 8.1.0/8.1.1; intentionally absent from the common patch."
                           if path == "COMPLIANCE.md" else
                           "The pinned 8.1.3 runtime overwrites the file applied by the stock patcher."),
            }
            for path in sorted((*UI_SOURCES, "COMPLIANCE.md"))
        ],
        "existing_finisher_work": {
            "aliases": [asset_record(path, payload[path]) for path in ALIASES],
            "helper": {"path": HELPER, "url": helper_url, "sha256": helper_hash},
            "version_marker": {"path": "VERSION", "value": VERSION, "sha256": sha256(payload["VERSION"])},
        },
        "release_prerequisites": [
            "Wire the required overlays into the finisher with pinned digests. Apply them after any "
            "runtime replacement and before the final VERSION write or relaunch. Rebuild and restage the aliases.",
            "Verify the pinned 8.1.3 runtime, the existing helper fallback, and all final asset URLs and digests.",
            "In a disposable Windows environment, verify stock updater handoff from all supported sources, "
            "both aliases, final integrity, relaunch, repair, and user-data preservation.",
            "Obtain separate publication approval before switching the public update channel.",
        ],
    }


def verify_stage(stage, layout, payload, report):
    if {file.name for file in stage.iterdir()} != set(ASSETS.values()) | {LAYOUT, PACK, MANIFEST, REPORT}:
        raise ValueError("unexpected files in the flat staging directory")
    if json.loads((stage / LAYOUT).read_bytes()) != dict(layout, version=VERSION, files=[
        {"path": path, "size": len(data)} for path, data in sorted(payload.items())
    ]):
        raise ValueError("repair layout does not match the expected overlay")
    with zipfile.ZipFile(stage / PACK) as archive:
        if sorted(archive.namelist()) != sorted(payload) or any(
                archive.read(path) != data for path, data in payload.items()):
            raise ValueError("repair archive does not match the expected overlay")
    flat = {path: (stage / leaf).read_bytes() for path, leaf in ASSETS.items()}
    if any(data != payload[path] for path, data in flat.items()):
        raise ValueError("flat assets do not match repair bytes")
    if json.loads((stage / MANIFEST).read_bytes()) != patch_manifest(flat):
        raise ValueError("file-patch manifest does not match the staged bytes")
    if json.loads((stage / REPORT).read_bytes()) != report:
        raise ValueError("finisher report does not match the staged inputs")


def stage_hotfix(site, output_parent):
    layout, baseline = load_baseline(site)
    if canonical_source("VERSION").decode("utf-8-sig").strip() != VERSION:
        raise ValueError(f"expected source VERSION {VERSION}")
    if any(path not in baseline or editable_template_path(path) for path in ASSETS):
        raise ValueError("hotfix must replace existing non-editable managed files only")

    overlay = {path: canonical_source(source) for path, source in TEXT_SOURCES.items()}
    compile(overlay[HELPER], SOURCE, "exec")  # Do not run the helper.
    if overlay[HELPER] != baseline[HELPER]:
        raise ValueError("hotfix must keep the v8.1.3.1 SnapRef helper bytes")
    with tempfile.TemporaryDirectory(prefix="lakis-8132-compile-") as tmp:
        scratch = Path(tmp)
        executable = scratch / ALIASES[0]
        inputs = scratch / "native-inputs"
        compile_updater(executable, inputs)
        updater = executable.read_bytes()
        overlay.update({path: updater for path in ALIASES})
        overlay["VERSION"] = VERSION.encode("ascii")  # Written by the finisher, not downloaded.
        report = build_report(overlay, inputs)

    payload = {**baseline, **overlay}
    stage = Path(tempfile.mkdtemp(prefix="lakis-8132-hotfix-private-", dir=reject_reparse_path(output_parent)))
    try:
        for path, leaf in sorted(ASSETS.items()):
            with (stage / leaf).open("xb") as stream:
                stream.write(overlay[path])
        write_repair(stage, layout, payload, VERSION)
        write_json(stage / MANIFEST, patch_manifest(payload))
        write_json(stage / REPORT, report)
        verify_stage(stage, layout, payload, report)
        artifacts = {}
        for file in sorted(stage.iterdir()):
            data = file.read_bytes()
            artifacts[file.name] = {"path": str(file), "bytes": len(data), "sha256": sha256(data)}
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {"stage": str(stage), "managed_files": len(payload), "artifacts": artifacts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="local public v8.1.3.1 layout and repair ZIP")
    parser.add_argument("--output-parent", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    print(json.dumps(stage_hotfix(args.baseline, args.output_parent)))
