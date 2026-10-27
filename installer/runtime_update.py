"""Schema-2 updater entry point; never use the full-tree installer for updates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_install import prepare_bundle, prepare_pose_models, validate_bundle
from runtime_patch import activate
from runtime_transition import _assert_original, _load_journal, _target_path, recover
from runtime_transition import _version as version_tuple

ENGINE_VERSION = (8, 0, 0)
BRIDGE_VERSION = (7, 5, 4)


def validate_update(manifest):
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int
            or manifest["schema"] != 2 or manifest.get("kind") != "runtime-update"
            or manifest.get("files") != [] or manifest.get("delete") != []):
        raise ValueError("unsupported runtime update manifest")
    engine = ENGINE_VERSION + (0,)
    minimum = version_tuple(manifest.get("minimum_version"))
    if (version_tuple(manifest.get("minimum_updater_version")) > engine
            or minimum < BRIDGE_VERSION + (0,)
            or minimum > version_tuple(manifest.get("version"))):
        raise ValueError("runtime update requires a different updater or bridge")
    return validate_bundle(manifest.get("runtime_bundle"), manifest["version"])


def run(manifest, target, cache, *, prepared_root=None, prepare_only=False, rollback=False):
    bundle = validate_update(manifest)
    target = _target_path(target, prepare_only=prepare_only)
    if rollback:
        state = _load_journal(target)
        if (prepared_root is None or not state or state.get("schema") != 2
                or state.get("version") != manifest["version"]
                or state.get("manifest_sha256", "").upper() != bundle["manifest_sha256"].upper()):
            raise ValueError("rollback journal does not match this update")
        return recover(target, prepared_root / "python_embeded/python.exe")
    _assert_original(target, manifest["version"], "update")
    current = (target / "VERSION").read_text(encoding="utf-8-sig").strip()
    if version_tuple(current) < version_tuple(manifest["minimum_version"]):
        raise ValueError("install the required updater bridge first")
    if prepare_only:
        candidate = prepare_bundle(bundle, manifest["version"], cache)
        prepare_pose_models(cache, target)
        return {"status": "prepared", "candidate": str(candidate)}
    if prepared_root is None:
        raise ValueError("runtime update requires a verified prepared candidate")
    model_files = prepare_pose_models(cache, target)
    return activate(prepared_root, target, bundle["manifest_sha256"], manifest["version"],
                    model_files=model_files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--prepared-root", type=Path)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        if args.rollback and args.prepared_root is None:
            raise ValueError("rollback requires the retained candidate")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        result = run(manifest, args.target, args.cache, prepared_root=args.prepared_root,
                     prepare_only=args.prepare_only, rollback=args.rollback)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        print(f"LAKIS runtime update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
