"""Build the pinned 8.0.0 migration bridge without changing public channels."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from build_updater_bridge import ROOT, compile_native, digest


def build(manifest_path, parent):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    names = {
        "LAKIS.exe": "LAKIS_RuntimeBridge_Launcher.exe",
        "LAKIS_Updater.exe": "LAKIS_RuntimeBridge_Updater.exe",
        "LAKIS_Patcher.exe": "LAKIS_RuntimeBridge_Patcher.exe",
    }
    if (manifest.get("schema") != 2 or manifest.get("kind") != "file-patch"
            or manifest.get("version") != "7.5.4.1"
            or manifest.get("minimum_version") != "7.5.4"
            or manifest.get("minimum_updater_version") != "7.5.4"
            or manifest.get("delete") != []
            or len(manifest.get("files", [])) != len(names)
            or {row["path"] for row in manifest["files"]} != set(names)):
        raise ValueError("unexpected published runtime bridge manifest")
    output = Path(tempfile.mkdtemp(prefix="pinned-runtime-bridge-", dir=parent))
    defines = ("LAKIS_RUNTIME_BRIDGE",)
    compile_native(output / names["LAKIS.exe"],
                   [ROOT / "installer/LAKIS_Launcher.cs"], defines=defines)
    compile_native(output / names["LAKIS_Updater.exe"],
                   [ROOT / "installer/LAKIS_Updater.cs"], defines=defines)
    shutil.copyfile(output / names["LAKIS_Updater.exe"], output / names["LAKIS_Patcher.exe"])
    for row in manifest["files"]:
        name = names[row["path"]]
        row["url"] = f"https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.1/{name}"
        row["sha256"] = digest(output / name).upper()
    (output / "update-v2-latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-parent", required=True, type=Path)
    args = parser.parse_args()
    print(build(args.manifest, args.output_parent))
