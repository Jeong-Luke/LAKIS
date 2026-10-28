"""Build the transparent CMD package from the same frozen assets as Setup."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from runtime_install import validate_bundle

PACKAGE_FILES = (
    "LAKIS_CMD_Install.cmd", "lakis_cmd_installer.py", "CMD_INSTALL_README_KO.txt",
    "runtime_install.py", "runtime_transition.py", "runtime_manifest.py",
    "runtime_health.py", "runtime_patch.py", "runtime_update.py",
)


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
        roots = {name.split("/", 1)[0] for name in source.namelist() if "/" in name}
        if len(roots) != 1:
            raise ValueError("source archive must contain one repository root")
        source_root = next(iter(roots))
        if source.read(f"{source_root}/VERSION").decode("utf-8-sig").strip() != version:
            raise ValueError("source archive version mismatch")
        for name in PACKAGE_FILES:
            archived = source.read(f"{source_root}/installer/{name}").replace(b"\r\n", b"\n")
            checked_out = (repo / "installer" / name).read_bytes().replace(b"\r\n", b"\n")
            if archived != checked_out:
                raise ValueError("CMD source changed after the frozen source archive: " + name)

    installer = repo / "installer"
    template = json.loads((installer / "cmd-installer-manifest.json").read_text(encoding="utf-8"))
    manifest_path = contract_path.parent / "runtime-installer-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    runtime_contract = json.loads(
        (contract_path.parent / "runtime-installer-contract.json").read_text(encoding="utf-8-sig")
    )
    if (runtime_contract.get("schema") != 1 or runtime_contract.get("version") != version
            or runtime_contract.get("manifest_sha256") != sha256(manifest_path)
            or runtime_contract.get("setup_sha256") != sha256(dist / "LAKIS_Setup.exe")):
        raise ValueError("GUI and CMD runtime installer contracts differ")
    if (manifest.get("schema") != 1 or manifest.get("version") != version
            or template.get("version") != version):
        raise ValueError("runtime installer version mismatch")
    validate_bundle(manifest.get("runtime_bundle"), version)
    for key in ("base", "models", "optional_animesharp"):
        if manifest.get(key) != template[key]:
            raise ValueError("runtime installer dependency template is stale: " + key)
    if any(key in manifest for key in ("nodes", "nested_node", "source", "repair_pack", "release_layout")):
        raise ValueError("legacy installation fields are not allowed")
    setup = (installer / "Setup_LAKIS_Safe.cs").read_text(encoding="utf-8-sig")
    if manifest["base"]["url"] not in setup or manifest["base"]["sha256"] not in setup:
        raise ValueError("GUI and CMD bootstrap pins differ")
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
    if manifest.get("webview2") != webview:
        raise ValueError("runtime installer WebView2 pin differs")
    cmd_bytes = (installer / "LAKIS_CMD_Install.cmd").read_bytes().replace(
        b"\r\n", b"\n"
    ).replace(b"\n", b"\r\n")
    # Pin the generated script without transcoding its CP949 source template.
    seven_url = b'set "SEVEN_URL=https://www.7-zip.org/a/7zr.exe"'
    if cmd_bytes.count(seven_url) != 1:
        raise ValueError("CMD 7-Zip source declaration is ambiguous")
    cmd_bytes = cmd_bytes.replace(
        seven_url,
        b'set "SEVEN_URL=https://github.com/ip7z/7zip/releases/download/26.03/7zr.exe"',
    )
    cmd = cmd_bytes.decode("cp949")
    if manifest["base"]["url"] not in cmd or manifest["base"]["sha256"] not in cmd:
        raise ValueError("CMD bootstrap differs from the dependency template")
    payload = {name: (installer / name).read_bytes() for name in PACKAGE_FILES}
    payload["LAKIS_CMD_Install.cmd"] = cmd_bytes
    payload["cmd-installer-manifest.json"] = manifest_bytes
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
