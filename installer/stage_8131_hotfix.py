"""Stage the flat v8.1.3.1 file-patch assets locally, without publishing."""
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
    ALIASES, LAYOUT, PACK, ROOT, canonical_source, compile_updater, managed_path,
    sha256, write_json, write_repair,
)
from lakis_cmd_installer import reject_reparse_path
from runtime_manifest import editable_template_path

BASE_VERSION = "8.1.3"
VERSION = "8.1.3.1"
MINIMUM_VERSION = "8.1.0"
HELPER = "ComfyUI/LAKIS/install_snapref.py"
SOURCE = "installer/install_snapref_experiment.py"
MANIFEST = "update-v4-latest.json"
RELEASE = f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{VERSION}"
ASSETS = {**{name: name for name in ALIASES}, HELPER: "install_snapref.py"}
BASELINE = {
    LAYOUT: (20_941, "426B9CBFEAD8EE854C3840FD609B1B78E5178D312ED92A18EA290951311AF356"),
    PACK: (36_759_315, "56043D16FF39232BE30177565E9A49AECE8BD65C43AEB72A11602CBDDE1336C9"),
}


def load_baseline(site):
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
        name = managed_path(row["path"])
        if name != row["path"] or name.casefold() in seen:
            raise ValueError(f"duplicate or noncanonical baseline path: {name}")
        seen.add(name.casefold())
        remaining[name] = row["size"]
    payload = {}
    with zipfile.ZipFile(io.BytesIO(assets[PACK])) as archive:
        for entry in archive.infolist():
            name = managed_path(entry.filename)
            if (name != entry.filename or remaining.pop(name, None) != entry.file_size
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError(f"baseline repair entry does not match layout: {entry.filename}")
            payload[name] = archive.read(entry)
    if remaining or payload.get("VERSION") != BASE_VERSION.encode("ascii"):
        raise ValueError("incomplete baseline repair payload")
    return layout, payload


def verify_stage(stage, layout, baseline, overlay):
    draft = json.loads((stage / MANIFEST).read_bytes())
    if (draft["schema"], draft["kind"], draft["version"], draft["minimum_version"],
            draft["minimum_updater_version"], draft["delete"], draft["release_notes"]) != (
            2, "file-patch", VERSION, MINIMUM_VERSION, MINIMUM_VERSION, [], ""):
        raise ValueError("unexpected hotfix file-patch identity")
    if {path.name for path in stage.iterdir()} != set(ASSETS.values()) | {LAYOUT, PACK, MANIFEST}:
        raise ValueError("unexpected files in the flat staging directory")
    expected = {**baseline, **overlay}
    if {name for name in expected if expected[name] != baseline[name]} != set(ASSETS) | {"VERSION"}:
        raise ValueError("repair overlay did not replace exactly the hotfix files")
    new_layout = json.loads((stage / LAYOUT).read_bytes())
    if new_layout != dict(layout, version=VERSION, files=[
        {"path": name, "size": len(expected[name])} for name in sorted(expected)
    ]):
        raise ValueError("new repair layout differs from the expected overlay")
    with zipfile.ZipFile(stage / PACK) as archive:
        names = archive.namelist()
        if sorted(names) != sorted(expected) or any(archive.read(name) != expected[name] for name in names):
            raise ValueError("new repair archive differs from the expected overlay")
    records = []
    for name, leaf in sorted(ASSETS.items()):
        data = (stage / leaf).read_bytes()
        if data != overlay[name]:
            raise ValueError(f"flat asset differs from repair bytes: {leaf}")
        if name in ALIASES:
            records.append({"path": name, "url": f"{RELEASE}/{leaf}", "sha256": sha256(data)})
    if draft["files"] != records:
        raise ValueError("update URLs or digests differ from the flat release assets")
    return {path.name: sha256(path.read_bytes()) for path in sorted(stage.iterdir())}


def stage_hotfix(site, output_parent):
    layout, baseline = load_baseline(site)
    if (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip() != VERSION:
        raise ValueError(f"expected source VERSION {VERSION}")
    if any(path not in baseline or editable_template_path(path) for path in ASSETS):
        raise ValueError("hotfix must replace existing non-editable managed files only")
    script = canonical_source(SOURCE)
    compile(script, SOURCE, "exec")  # Syntax check; do not run the helper.
    updater = (ROOT / "installer/LAKIS_Updater.cs").read_text(encoding="utf-8-sig")
    if re.findall(r'SnapRefHelperSha256\s*=\s*"([A-F0-9]{64})"', updater) != [sha256(script)]:
        raise ValueError("hotfix helper bytes do not match the native finisher pin")
    with tempfile.TemporaryDirectory(prefix="lakis-8131-compile-") as tmp:
        scratch = Path(tmp)
        executable = scratch / ALIASES[0]
        compile_updater(executable, scratch / "native-inputs")
        update = executable.read_bytes()

    overlay = {**{name: update for name in ALIASES}, HELPER: script, "VERSION": VERSION.encode("ascii")}
    stage = Path(tempfile.mkdtemp(prefix="lakis-8131-publication-private-",
                                  dir=reject_reparse_path(output_parent)))
    try:
        records = []
        for name, leaf in sorted(ASSETS.items()):
            data = overlay[name]
            with (stage / leaf).open("xb") as stream:
                stream.write(data)
            if name in ALIASES:
                records.append({"path": name, "url": f"{RELEASE}/{leaf}", "sha256": sha256(data)})
        write_repair(stage, layout, {**baseline, **overlay}, VERSION)
        write_json(stage / MANIFEST, {
            "schema": 2, "kind": "file-patch", "version": VERSION,
            "minimum_version": MINIMUM_VERSION, "minimum_updater_version": MINIMUM_VERSION,
            "release_notes": "", "files": records, "delete": [],
        })
        hashes = verify_stage(stage, layout, baseline, overlay)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {"stage": str(stage), "managed_files": len(baseline), "sha256": hashes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="verified v8.1.3 site with layout and repair ZIP")
    parser.add_argument("--output-parent", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    print(json.dumps(stage_hotfix(args.baseline, args.output_parent)))
