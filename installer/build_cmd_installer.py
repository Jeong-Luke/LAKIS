"""Build the transparent CMD package from the same frozen assets as Setup."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

PACKAGE_FILES = ("LAKIS_CMD_Install.cmd", "lakis_cmd_installer.py", "CMD_INSTALL_README_KO.txt")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def build(repo: Path, dist: Path, archive: Path, contract_path: Path, pinned_setup: Path) -> Path:
    version = (repo / "VERSION").read_text(encoding="utf-8-sig").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("invalid public version")
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    revision = contract["revision"]
    digest = sha256(archive)
    if (not isinstance(revision, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", revision)
            or contract["sha256"] != digest or contract["bytes"] != archive.stat().st_size):
        raise ValueError("source archive does not match Setup build contract")
    compiled_source = pinned_setup.read_text(encoding="utf-8-sig")
    if (f'private const string Revision = "{revision}";' not in compiled_source
            or f'private const string SourceArchiveSha256 = "{digest}";' not in compiled_source):
        raise ValueError("Setup and CMD source pins differ")
    with zipfile.ZipFile(archive) as source:
        if source.read(f"LAKIS-{revision}/VERSION").decode("utf-8-sig").strip() != version:
            raise ValueError("source archive version mismatch")

    installer = repo / "installer"
    manifest = json.loads((installer / "cmd-installer-manifest.json").read_text(encoding="utf-8"))
    setup = (installer / "Setup_LAKIS_Safe.cs").read_text(encoding="utf-8-sig")
    required_setup = re.sub(r'private static readonly DownloadItem OptionalAnimeSharp\s*=\s*new DownloadItem\([^;]+;', '', setup)
    declared = set(re.findall(r'new DownloadItem\(\s*"[^"]+"\s*,\s*"([^"]+)"\s*,\s*"([A-Fa-f0-9]{64})"', required_setup))
    dependencies = [(manifest["base"]["url"], manifest["base"]["sha256"])]
    dependencies += [(row[1], row[2]) for row in [*manifest["nodes"], manifest["nested_node"], *manifest["models"]]]
    if set(dependencies) != declared:
        raise ValueError("CMD dependency template is stale relative to Setup")
    webview_record = contract_path.parent / 'webview2-bootstrapper.json'
    webview = json.loads(webview_record.read_text(encoding='utf-8-sig'))
    webview_path = contract_path.parent / 'MicrosoftEdgeWebview2Setup.exe'
    if (webview.get('name') != webview_path.name or not str(webview.get('url', '')).startswith('https://')
            or webview.get('sha256') != sha256(webview_path) or webview.get('bytes') != webview_path.stat().st_size):
        raise ValueError('WebView2 bootstrapper build contract mismatch')
    for declaration in (
        f'private const string WebView2BootstrapperUrl = "{webview["url"]}";',
        f'private const string WebView2BootstrapperSha256 = "{webview["sha256"]}";',
        f'private const long WebView2BootstrapperBytes = {webview["bytes"]};',
    ):
        if declaration not in compiled_source:
            raise ValueError('Setup and CMD WebView2 pins differ')
    manifest['webview2'] = webview
    cmd_bytes = (installer / "LAKIS_CMD_Install.cmd").read_bytes()
    cmd = cmd_bytes.decode("cp949")
    if b"\n" in cmd_bytes.replace(b"\r\n", b""):
        raise ValueError("CMD must preserve CRLF")
    if manifest["base"]["url"] not in cmd or manifest["base"]["sha256"] not in cmd:
        raise ValueError("CMD bootstrap differs from the dependency template")
    layout = json.loads((dist / "release-layout.json").read_text(encoding="utf-8-sig"))
    if layout["version"] != version:
        raise ValueError("release layout version mismatch")
    manifest.update(version=version, release_base=f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{version}")
    manifest["source"] = {"name": f"LAKIS-{revision}.zip",
                          "url": f"https://api.github.com/repos/Jeong-Luke/LAKIS/zipball/{revision}",
                          "sha256": digest, "bytes": archive.stat().st_size}
    for key, name in (("repair_pack", "LAKIS_RepairPack.zip"), ("release_layout", "release-layout.json")):
        asset = dist / name
        manifest[key] = {"name": name, "sha256": sha256(asset), "bytes": asset.stat().st_size}
    payload = {name: (installer / name).read_bytes() for name in PACKAGE_FILES}
    payload["cmd-installer-manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    destination = dist / f"LAKIS_CMD_Installer_{version}.zip"
    temporary = destination.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, data)
    with zipfile.ZipFile(temporary) as bundle:
        if sorted(bundle.namelist()) != sorted(payload) or bundle.testzip() is not None:
            raise ValueError("invalid CMD package")
        for name, data in payload.items():
            if bundle.read(name) != data:
                raise ValueError("CMD package byte mismatch")
    temporary.replace(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--source-archive", required=True, type=Path)
    parser.add_argument("--source-contract", required=True, type=Path)
    parser.add_argument("--pinned-setup", required=True, type=Path)
    args = parser.parse_args()
    result = build(Path(__file__).resolve().parents[1], args.dist, args.source_archive,
                   args.source_contract, args.pinned_setup)
    print(json.dumps({"path": str(result), "sha256": sha256(result), "bytes": result.stat().st_size}))
