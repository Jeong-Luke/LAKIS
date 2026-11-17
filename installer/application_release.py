"""Compose a build-pinned application on its independently authenticated runtime.

Only pristine release inputs are accepted here. Installed user data is handled
later by runtime_transition, never used to manufacture an expected checksum.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from lakis_cmd_installer import (
    cache_path, copy_file, download, reject_reparse_path, zip_extraction_plan,
)
from runtime_manifest import (
    EDITABLE_TEMPLATE_FILES, MANIFEST_NAME, PROTECTED_DIRECTORIES, PROTECTED_FILES,
    _pinned_path, _stream_digest, editable_template_contract, generated_path, normalized_path, protected_path,
    validate_runtime_manifest, verify_runtime,
)


ASSETS = {"payload": "LAKIS_RepairPack.zip", "layout": "release-layout.json",
          "manifest": MANIFEST_NAME}


def validate_release(release: dict, bundle: dict) -> dict:
    """Bind the exact component pair, not the revision of the installer helpers."""
    if (not isinstance(release, dict) or type(release.get("schema")) is not int or release["schema"] != 1
            or release.get("product") != "LAKIS"
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(release.get("version", "")))
            or not re.fullmatch(r"[a-fA-F0-9]{40}", str(release.get("source_revision", "")))
            or release.get("runtime_version") != bundle["version"]
            or tuple(map(int, release["version"].split("."))) <
               tuple(map(int, bundle["version"].split(".")))):
        raise ValueError("application release identity mismatch")
    for field, baseline_field in (("runtime_sha256", "sha256"),
                                  ("runtime_manifest_sha256", "manifest_sha256")):
        value = release.get(field)
        if (not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value)
                or value.upper() != bundle[baseline_field].upper()):
            raise ValueError("application release is not bound to this runtime")
    for field, name in ASSETS.items():
        asset = release.get(field)
        if (not isinstance(asset, dict) or asset.get("name") != name
                or asset.get("url") !=
                f"https://github.com/Jeong-Luke/LAKIS/releases/download/v{release['version']}/{name}"
                or type(asset.get("bytes")) is not int or asset["bytes"] <= 0
                or not re.fullmatch(r"[a-fA-F0-9]{64}", str(asset.get("sha256", "")))):
            raise ValueError(f"invalid pinned application {field}")
    return release


def installer_identity(manifest: dict) -> tuple[dict, dict | None, str, str]:
    from runtime_install import validate_bundle
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("unsupported installer manifest")
    bundle = validate_bundle(manifest.get("runtime_bundle"), manifest.get("version"))
    release = None
    if "application_release" in manifest:
        release = validate_release(manifest["application_release"], bundle)
    return (bundle, release, release["version"] if release else bundle["version"],
            release["manifest"]["sha256"] if release else bundle["manifest_sha256"])


def _asset(asset: dict, cache: Path) -> Path:
    from runtime_install import asset_url
    path = download(asset_url(asset), cache_path(cache, asset["name"], asset["sha256"]),
                    asset["sha256"], asset["bytes"], display_name=asset["name"])
    return reject_reparse_path(path)


@contextmanager
def _asset_stream(path: Path, asset: dict):
    # Verify the very handle being parsed/decompressed, while its ancestry and
    # file deny replacement/writes. A cache check before opening is not enough.
    with ExitStack() as pins:
        for parent in reversed(path.parents):
            pins.enter_context(_pinned_path(parent, directory=True))
        stream = pins.enter_context(_pinned_path(path, read_file=True))
        if (os.fstat(stream.fileno()).st_size != asset["bytes"]
                or _stream_digest(stream).upper() != asset["sha256"].upper()):
            raise ValueError("application asset size or hash mismatch")
        stream.seek(0)
        yield stream


def _managed_path(value: str) -> str:
    relative = normalized_path(value)
    if relative.casefold() == MANIFEST_NAME.casefold() or protected_path(relative) or generated_path(relative):
        raise ValueError(f"non-release application path: {relative}")
    return relative


def read_release_metadata(bundle: dict, release: dict, cache: Path) -> dict:
    """Authenticate the small release contracts before downloading a runtime."""
    validate_release(release, bundle)
    cache = reject_reparse_path(cache)
    assets = {name: _asset(release[name], cache) for name in ("manifest", "layout")}
    with _asset_stream(assets["manifest"], release["manifest"]) as stream:
        target_manifest = json.load(stream)
    expected = validate_runtime_manifest(target_manifest, release["version"])
    if target_manifest["source_revision"].lower() != release["source_revision"].lower():
        raise ValueError("application source revision mismatch")
    with _asset_stream(assets["layout"], release["layout"]) as stream:
        layout = json.load(stream)
    if (not isinstance(layout, dict) or layout.get("schema") != 1
            or layout.get("product") != "LAKIS" or layout.get("version") != release["version"]
            or not isinstance(layout.get("files"), list) or not layout["files"]
            or not isinstance(layout.get("retired"), list)):
        raise ValueError("application layout identity mismatch")
    if ("editable_template_policy" in layout
            and layout["editable_template_policy"] != "preserve-v1"):
        raise ValueError("unsupported application editable-template policy")
    rows = {}
    for row in layout["files"]:
        if not isinstance(row, dict):
            raise ValueError("invalid application layout entry")
        relative = _managed_path(row.get("path"))
        key = relative.casefold()
        if (key in rows or key not in expected or type(row.get("size")) is not int
                or row["size"] != expected[key]["size"]
                or relative != expected[key]["path"]):
            raise ValueError("application layout does not match the trusted complete manifest")
        rows[key] = expected[key]
    retired = []
    boundaries = (*PROTECTED_DIRECTORIES, *PROTECTED_FILES, *EDITABLE_TEMPLATE_FILES)
    for value in layout["retired"]:
        relative = _managed_path(value)
        key = relative.casefold()
        if (key in {p.casefold() for p in retired}
                or any(p == key or p.startswith(key + "/") for p in expected)
                or any(p.casefold() == key or p.casefold().startswith(key + "/") for p in boundaries)):
            raise ValueError("retired application path conflicts with release or user data")
        retired.append(relative)
    return {
        "assets": assets, "rows": rows, "retired": retired,
        # Only layout-listed defaults constrain a legacy launcher's startup
        # contract. Other exact known template paths remain protected user data.
        "editable_templates": editable_template_contract(
            rows.values(), release["manifest"]["sha256"], layout.get("editable_template_policy")),
    }


def compose(baseline: Path, bundle: dict, release: dict, cache: Path, *, metadata=None) -> Path:
    """Overlay only authenticated release inputs, never installed user data."""
    validate_release(release, bundle)
    cache = reject_reparse_path(cache)
    metadata = read_release_metadata(bundle, release, cache) if metadata is None else metadata
    assets, rows, retired = metadata["assets"], metadata["rows"], metadata["retired"]
    archive_path = _asset(release["payload"], cache)
    workspace = Path(tempfile.mkdtemp(prefix="application-", dir=cache))
    payload, candidate = workspace / "payload", workspace / "candidate"
    # No code from the ZIP is executed. Inspect the entire central directory
    # before writing, and permit decompression only at manifest-declared sizes.
    with ExitStack() as pins:
        incoming = pins.enter_context(_asset_stream(archive_path, release["payload"]))
        archive = pins.enter_context(zipfile.ZipFile(incoming))
        plan = zip_extraction_plan(archive, archive_path, payload)
        files = [(entry, output) for entry, output in plan if not entry.is_dir()]
        found = {output.relative_to(payload).as_posix().casefold() for _, output in files}
        if found != rows.keys():
            raise ValueError("application archive file set differs from layout")
        for entry, output in files:
            relative = output.relative_to(payload).as_posix()
            row = rows[relative.casefold()]
            if relative != row["path"] or entry.file_size != row["size"]:
                raise ValueError("application archive path or expanded size mismatch")
        for entry, output in files:
            with archive.open(entry) as stream:
                if _stream_digest(stream, output).upper() != rows[
                        output.relative_to(payload).as_posix().casefold()]["sha256"].upper():
                    raise ValueError("application payload file hash mismatch")

    # This copies only authenticated baseline files, never an installed tree.
    verify_runtime(baseline, bundle["manifest_sha256"], bundle["version"], stage_root=candidate)
    for relative in retired:
        path = reject_reparse_path(candidate / relative)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for row in rows.values():
        copy_file(payload / row["path"], candidate / row["path"])
    copy_file(assets["manifest"], candidate / MANIFEST_NAME)
    verify_runtime(candidate, release["manifest"]["sha256"], release["version"])
    return candidate
