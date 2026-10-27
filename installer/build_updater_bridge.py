"""Build a local cumulative 7.5.4 bridge candidate; never publish or change channels."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "7.5.4"
RUNTIME_HELPERS = (
    "lakis_cmd_installer.py", "runtime_install.py", "runtime_transition.py",
    "runtime_manifest.py", "runtime_health.py", "runtime_patch.py", "runtime_update.py",
)
BASELINE_HASHES = {
    "LAKIS_Updater.exe": "fc842225c22d7c6ec58639cbbe2581f94b3825200f2520c81d2bd3e4798efc50",
    "release-layout.json": "c1949afc956e81c2595ad40508a580bfddc7c4e1ec988fb6454fb54c856dc2f4",
    "LAKIS_RepairPack.zip": "c7efe57bb5d9be43aca45c374c4b80d721f9bd04a3e4f204413b867e9905de64",
    "update-latest.json": "6f46aa3bc597dbd053329dea5e8f23936382c542560361606e7d5bae424fde05",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compiler():
    return Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


def compile_native(output, sources, *, main=None):
    command = [str(compiler()), "/nologo", "/target:" + ("exe" if main else "winexe"),
               "/out:" + str(output), "/win32icon:" + str(ROOT / "resources/LAKIS_windows_compatible.ico")]
    if main:
        command.append("/main:" + main)
    command += ["/reference:" + name for name in (
        "System.Windows.Forms.dll", "System.Drawing.dll", "System.Web.Extensions.dll",
        "System.IO.Compression.dll", "System.IO.Compression.FileSystem.dll")]
    command += [
        "/resource:" + str(ROOT / "resources/splash/lakis-splash-01.png") + ",LAKIS.Splash1",
        "/resource:" + str(ROOT / "resources/splash/lakis-splash-02.png") + ",LAKIS.Splash2",
        str(ROOT / "installer/SplashArtwork.cs"), str(ROOT / "installer/UpdateProtocol.cs"),
    ]
    command += [str(path) for path in sources]
    if any(Path(path).name == "LAKIS_Updater.cs" for path in sources):
        command.append(str(ROOT / "installer/RuntimeBundleInstaller.cs"))
        command += [
            "/resource:" + str(ROOT / "installer" / name) + ",LAKIS.Runtime." + name
            for name in RUNTIME_HELPERS
        ]
    subprocess.run(command, check=True)


def build(baseline, parent):
    baseline = Path(baseline)
    for name, expected in BASELINE_HASHES.items():
        if digest(baseline / name) != expected:
            raise ValueError("7.5.3 baseline hash mismatch: " + name)
    output = Path(tempfile.mkdtemp(prefix="bridge754-", dir=parent))
    compile_native(output / "LAKIS.exe", [ROOT / "installer/LAKIS_Launcher.cs"])
    compile_native(output / "LAKIS_Updater.exe", [ROOT / "installer/LAKIS_Updater.cs"])
    shutil.copyfile(output / "LAKIS_Updater.exe", output / "LAKIS_Patcher.exe")
    names = ("LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe")
    # Old clients cannot enforce a minimum source version. Preserve the
    # published cumulative 7.5.3 application payload so skipping that release
    # cannot leave old application files behind a new VERSION marker.
    legacy = json.loads((baseline / "update-latest.json").read_text(encoding="utf-8-sig"))
    if legacy["version"] != "7.5.3":
        raise ValueError("unexpected baseline update manifest")
    replaced = set()
    for item in legacy["files"]:
        if item["path"] in names:
            name = item["path"]
            item["url"] = f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{VERSION}/{name}"
            item["sha256"] = digest(output / name).upper()
            replaced.add(name)
    if replaced != set(names):
        raise ValueError("bridge executables missing from baseline manifest")
    legacy["version"] = VERSION
    legacy["release_notes"] = "안정판 앱 파일과 업데이터를 정비하고 새 업데이트 경로로 전환합니다. 모델과 ComfyUI 실행 환경은 교체하지 않습니다."
    modern = {
        "schema": 2, "kind": "file-patch", "version": VERSION,
        "minimum_version": VERSION, "minimum_updater_version": VERSION,
        "release_notes": "업데이터 전환 완료. 검증된 후속 업데이트를 기다립니다.",
        "files": [], "delete": [],
    }
    layout = json.loads((baseline / "release-layout.json").read_text(encoding="utf-8-sig"))
    if layout["version"] != "7.5.3" or layout["schema"] != 1 or layout["product"] != "LAKIS":
        raise ValueError("unexpected baseline layout")
    replacements = {name: (output / name).read_bytes() for name in names}
    replacements["VERSION"] = VERSION.encode("ascii")
    found = set()
    for row in layout["files"]:
        if row["path"] in replacements:
            found.add(row["path"])
            row["size"] = len(replacements[row["path"]])
    if found != set(replacements):
        raise ValueError("bridge files missing from baseline layout")
    layout["version"] = VERSION
    with zipfile.ZipFile(baseline / "LAKIS_RepairPack.zip") as original, zipfile.ZipFile(
        output / "LAKIS_RepairPack.zip", "w", compression=zipfile.ZIP_DEFLATED
    ) as updated:
        replaced = set()
        for entry in original.infolist():
            if entry.filename in replacements:
                data = replacements[entry.filename]
                replaced.add(entry.filename)
            else:
                data = original.read(entry)
            updated.writestr(entry, data)
        if replaced != set(replacements):
            raise ValueError("bridge files missing from baseline repair pack")
    for name, document in (
        ("legacy-update-7.5.4.json", legacy), ("update-v2-latest.json", modern),
        ("release-layout.json", layout),
    ):
        (output / name).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Keep the public stable manifest and the source VERSION untouched.
    # Only three application binaries differ from the pinned 7.5.3 baseline;
    # the legacy channel remains cumulative for clients that skipped 7.5.3.
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output-parent", required=True, type=Path)
    args = parser.parse_args()
    print(build(args.baseline, args.output_parent))
