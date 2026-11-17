"""Build a loopback-only 8.1.3 application patch against the public 8.1.2 release."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
import zipfile

from build_updater_bridge import ROOT, RUNTIME_HELPERS, compiler
from lakis_cmd_installer import reject_reparse_path
from runtime_manifest import (
    MANIFEST_NAME, editable_template_path, generated_path, normalized_path,
    protected_path, validate_runtime_manifest,
)

BASE_VERSION = "8.1.2"
VERSION = "8.1.3"
BASE_REVISION = "c7d84ee4c95d079ceb1ba648083c863c3fe28cc7"
REPOSITORY = "Jeong-Luke/LAKIS"
RELEASE_BASE = f"https://github.com/{REPOSITORY}/releases/download/v{BASE_VERSION}"
LAYOUT = "release-layout.json"
PACK = "LAKIS_RepairPack.zip"
PATCH = "update-8.1.3-local.json"
ALIASES = ("LAKIS_Updater.exe", "LAKIS_Patcher.exe")
# Public v8.1.2 release asset digests; the inventory is also pinned by its v4 channel.
BASE_ASSETS = {
    LAYOUT: (34448, "E4C67278814C965D811FBF3BAA00B45EC69C5A051D2F0B8F23F456DD7FF66545"),
    PACK: (36748588, "068A5BD44836C48582A0332303854A0D64246F252CFE39871DE25514575EF991"),
    MANIFEST_NAME: (13427866, "83DDABB941B97F08F1382E647A83F18417F2F59A0A4FFD503F32A113F37546F0"),
}
SOURCE_SCOPES = (
    "LICENSE.md", "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md", "third_party_licenses",
    "src/external_ui", "src/custom_nodes", "workflows", "src/runtime",
    "resources/STOP_AUTOMATION", "resources/PRODUCTION_NODE_PACKAGES.txt",
    "installer/install_snapref_experiment.py",
)
UPDATER_SOURCES = (
    "installer/SplashArtwork.cs", "installer/UpdateProtocol.cs",
    "installer/RuntimeBundleInstaller.cs", "installer/LAKIS_Updater.cs",
)
ARTWORK = ("resources/splash/lakis-splash-01.png", "resources/splash/lakis-splash-02.png")
ICON = "resources/LAKIS_windows_compatible.ico"


def sha256(data):
    return hashlib.sha256(data).hexdigest().upper()


def row(path, data):
    return {"path": path, "size": len(data), "sha256": sha256(data)}


def git(*arguments):
    return subprocess.check_output(["git", "-C", str(ROOT), *arguments])


def write_json(path, document):
    path.write_bytes((json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def write_repair(site, layout, payload, version):
    write_json(site / LAYOUT, dict(layout, version=version, files=[
        {"path": path, "size": len(data)} for path, data in sorted(payload.items())
    ]))
    with zipfile.ZipFile(site / PACK, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(path)  # fixed time and file order
            archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)


def read_baseline(directory):
    assets = {}
    for name, (size, digest) in BASE_ASSETS.items():
        if directory is None:
            request = Request(f"{RELEASE_BASE}/{name}", headers={"User-Agent": "LAKIS-LocalCandidate/8.1.3"})
            with urlopen(request, timeout=60) as stream:
                data = stream.read(size + 1)
        else:
            with reject_reparse_path(directory / name).open("rb") as stream:
                data = stream.read(size + 1)
        if (len(data), sha256(data)) != (size, digest):
            raise ValueError(f"public {BASE_VERSION} asset size or SHA-256 mismatch: {name}")
        assets[name] = data
    return assets


def managed_path(value):
    path = normalized_path(value)
    if (path.casefold() == MANIFEST_NAME.casefold() or protected_path(path)
            or generated_path(path)):
        raise ValueError(f"non-release application path: {value}")
    return path


def load_application(assets):
    layout = json.loads(assets[LAYOUT])
    inventory = json.loads(assets[MANIFEST_NAME])
    runtime = validate_runtime_manifest(inventory, BASE_VERSION)
    if (layout["schema"], layout["product"], layout["version"], layout["editable_template_policy"],
            inventory["source_revision"], len(runtime)) != (
            1, "LAKIS", BASE_VERSION, "preserve-v1", BASE_REVISION, 63039):
        raise ValueError("unexpected public baseline layout or runtime identity")
    remaining = {}
    for entry in layout["files"]:
        path = managed_path(entry["path"])
        key = path.casefold()
        if (key in remaining or key not in runtime or runtime[key]["path"] != path
                or runtime[key]["size"] != entry["size"]):
            raise ValueError(f"baseline layout/runtime mismatch: {path}")
        remaining[key] = path
    for path in layout["retired"]:
        path = managed_path(path)
        if path.casefold() in runtime or editable_template_path(path):
            raise ValueError(f"retired baseline path is live: {path}")

    payload = {}
    with zipfile.ZipFile(io.BytesIO(assets[PACK])) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = managed_path(info.filename)
            key = path.casefold()
            if (remaining.pop(key, None) != path or info.file_size != runtime[key]["size"]
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError(f"unexpected baseline ZIP entry: {path}")
            data = archive.read(info)
            if sha256(data) != runtime[key]["sha256"].upper():
                raise ValueError(f"baseline ZIP/runtime SHA-256 mismatch: {path}")
            payload[path] = data
    if remaining or payload["VERSION"] != BASE_VERSION.encode("ascii"):
        raise ValueError("incomplete baseline repair payload")
    return layout, inventory, runtime, payload


def git_paths(result):
    return set(result.decode("utf-8").rstrip("\0").split("\0")) - {""}


def canonical_source(path):
    file = reject_reparse_path(ROOT / path)
    data = file.read_bytes()
    expected = git("-c", "core.safecrlf=false", "hash-object", f"--path={path}", "--", str(file)).strip()
    # Validate any CRLF conversion against the repository's actual Git clean bytes.
    for candidate in (data, data.replace(b"\r\n", b"\n")):
        header = f"blob {len(candidate)}\0".encode("ascii")
        if hashlib.sha1(header + candidate).hexdigest().encode("ascii") == expected:
            return candidate
    raise ValueError(f"unsupported Git clean conversion or moving source: {path}")


def source_delta(contract, payload):
    raw = f"https://raw.githubusercontent.com/{REPOSITORY}/{BASE_REVISION}/"
    mapped = {}
    for entry in contract["files"]:
        if entry["url"].startswith(raw):
            source = unquote(entry["url"][len(raw):])
            path = managed_path(entry["path"])
            if source in mapped:
                raise ValueError(f"duplicate update source: {source}")
            mapped[source] = path
    changed = git_paths(git("diff", "--no-renames", "--name-only", "-z", BASE_REVISION, "--", *SOURCE_SCOPES))
    untracked = git_paths(git("ls-files", "--others", "--exclude-standard", "-z", "--", *SOURCE_SCOPES))
    replacements = {}
    for source in sorted(changed | untracked):
        path = mapped.get(source)
        if path is None or editable_template_path(path):
            raise ValueError(f"managed change is not eligible for this file patch: {source}")
        data = canonical_source(source)
        if payload.get(path) != data:
            replacements[path] = data
    return replacements


def compile_updater(output, inputs):
    sources = (*UPDATER_SOURCES, ICON, *ARTWORK, *(f"installer/{name}" for name in RUNTIME_HELPERS))
    for name in sources:
        path = inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(reject_reparse_path(ROOT / name).read_bytes())
    subprocess.run([
        str(compiler()), "/nologo", "/target:winexe", "/codepage:65001", f"/out:{output}",
        f"/win32icon:{inputs / ICON}", "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll",
        *(f"/resource:{inputs / path},LAKIS.Splash{index}" for index, path in enumerate(ARTWORK, 1)),
        *(f"/resource:{inputs / 'installer' / name},LAKIS.Runtime.{name}" for name in RUNTIME_HELPERS),
        *(str(inputs / path) for path in UPDATER_SOURCES),
    ], check=True)


def build(stage, baseline_dir, port):
    if (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip() != VERSION:
        raise ValueError(f"working tree VERSION must be {VERSION}")
    layout, inventory, runtime, payload = load_application(read_baseline(baseline_dir))
    # The repair pack retains the production launcher. Do not silently omit a
    # launcher/protocol change from a candidate that only rebuilds the updater.
    if git("diff", "--name-only", BASE_REVISION, "--", "installer/LAKIS_Launcher.cs",
           "installer/UpdateProtocol.cs", "installer/SplashArtwork.cs", ICON, *ARTWORK):
        raise ValueError("production launcher inputs differ from public 8.1.2")
    build_dir = stage / "build"
    site = stage / "www"
    dist = build_dir / "dist"
    dist.mkdir(parents=True)
    site.mkdir()
    compile_updater(dist / ALIASES[0], build_dir / "native-inputs")
    shutil.copyfile(dist / ALIASES[0], dist / ALIASES[1])
    for entry in layout["files"]:
        name = entry["path"]
        if "/" not in name and name.lower().endswith((".exe", ".dll")) and name not in ALIASES:
            (dist / name).write_bytes(payload[name])

    contract_path = build_dir / "managed-contract.json"
    subprocess.run([
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "installer/New-UpdateManifest.ps1"), "-Version", VERSION,
        "-DistDirectory", str(dist), "-OutputPath", str(contract_path),
        "-SourceRevision", BASE_REVISION, "-UseLocalWorkingTreeHashes",
    ], check=True)
    contract = json.loads(contract_path.read_bytes())
    replacements = {name: (dist / name).read_bytes() for name in ALIASES}
    replacements.update(source_delta(contract, payload))
    patch = {
        "schema": 2, "kind": "file-patch", "version": VERSION,
        "minimum_version": BASE_VERSION, "minimum_updater_version": "8.1.0",
        "release_notes": "LAKIS 8.1.3 local packaging candidate (not for distribution).",
        "files": [], "delete": [],
    }
    allowed = {entry["path"] for entry in contract["files"]}
    for path, data in sorted(replacements.items()):
        key = path.casefold()
        if (path not in allowed or (key in runtime and
                (runtime[key]["path"] != path or path not in payload))):
            raise ValueError(f"replacement is outside the managed application: {path}")
        file = site / "files" / path
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("xb") as stream:
            stream.write(data)
        patch["files"].append({
            "path": path, "sha256": sha256(data),
            "url": f"http://127.0.0.1:{port}/files/{quote(path, safe='/')}",
        })
    write_json(site / PATCH, patch)

    # VERSION is written by ApplyUpdate/FinishSelfUpdate, not downloaded.
    overlay = {**replacements, "VERSION": VERSION.encode("ascii")}
    payload.update(overlay)
    runtime.update({path.casefold(): row(path, data) for path, data in overlay.items()})
    # The complete inventory is an offline expectation only. It is not installed
    # by the patcher and must not be used as a release-pinned Setup descriptor.
    inventory.update(version=VERSION, files=sorted(runtime.values(), key=lambda item: item["path"]),
                     local_candidate={"working_tree": True,
                                      "base_head": git("rev-parse", "HEAD").decode("ascii").strip()})
    validate_runtime_manifest(inventory, VERSION)
    write_repair(site, layout, payload, VERSION)
    write_json(site / MANIFEST_NAME, inventory)
    artifacts = sorted(file for file in site.rglob("*") if file.is_file())
    (site / "SHA256SUMS.txt").write_bytes("".join(
        f"{sha256(file.read_bytes())}  {file.relative_to(site).as_posix()}\n" for file in artifacts
    ).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int, help="port for the loopback-only patch URLs")
    parser.add_argument("--baseline-dir", type=Path,
                        help="directory containing the three pinned v8.1.2 assets; otherwise download them")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    stage = Path(tempfile.mkdtemp(prefix="lakis-813-local-"))
    try:
        build(stage, args.baseline_dir, args.port)
    except BaseException:
        shutil.rmtree(stage)
        raise
    print(f"CANDIDATE={stage}")


if __name__ == "__main__":
    main()
