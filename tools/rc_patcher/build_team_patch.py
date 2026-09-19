from __future__ import annotations

import argparse, hashlib, json, zipfile
from pathlib import Path
from rc_patch import FORMAT, PatchError, digest, normalize, protected


def load_inventory(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("files"), list): raise PatchError("invalid inventory")
    return data


def mapped(data: dict) -> dict[str, dict]:
    return {normalize(e["relative_path"]): e for e in data["files"]}


def resolve_source(inventory_path: Path, entry: dict, source_root: Path) -> Path:
    raw = entry.get("source_path") or entry.get("relative_path")
    path = Path(raw)
    if not path.is_absolute(): path = source_root / path
    return path.resolve()


def build(base_path: Path, target_path: Path, source_root: Path, output: Path, display: str, internal: str, base_version: str) -> dict:
    base, target = load_inventory(base_path), load_inventory(target_path)
    base_map, target_map = mapped(base), mapped(target)
    changed = [p for p,e in target_map.items() if p not in base_map or base_map[p].get("sha256", "").upper() != e.get("sha256", "").upper()]
    removed = sorted(set(base_map) - set(target_map))
    for rel in changed + removed:
        if protected(rel): raise PatchError(f"protected path in inventory diff: {rel}")
    manifest_files=[]
    sources={}
    for rel in sorted(changed):
        entry=target_map[rel]; src=resolve_source(target_path, entry, source_root)
        if not src.is_file() or digest(src) != entry["sha256"].upper() or src.stat().st_size != entry["size"]:
            raise PatchError(f"STALE INVENTORY: {rel}")
        sources[rel]=src; manifest_files.append({"path":rel,"sha256":entry["sha256"].upper(),"size":entry["size"]})
    base_hashes=[]
    for rel in sorted(set(changed) & set(base_map)):
        base_hashes.append({"path":rel,"sha256":base_map[rel]["sha256"].upper()})
    manifest={"format":FORMAT,"display_version":display,"internal_version":internal,"base_version":base_version,"files":manifest_files,"delete":removed,"base_hashes":base_hashes}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("patch_manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
        for rel,src in sources.items(): archive.write(src,"payload/"+rel)
    result={"ok":True,"output":str(output),"sha256":digest(output),"modified_or_added":len(changed),"removed":len(removed)}
    output.with_suffix(output.suffix+".sha256.txt").write_text(f"{result['sha256']}  {output.name}\n",encoding="ascii")
    return result


def main():
    p=argparse.ArgumentParser(); p.add_argument("--base-inventory",required=True); p.add_argument("--target-inventory",required=True); p.add_argument("--source-root",required=True); p.add_argument("--output",required=True); p.add_argument("--display-version",required=True); p.add_argument("--internal-version",required=True); p.add_argument("--base-version",required=True); a=p.parse_args()
    try: print(json.dumps(build(Path(a.base_inventory).resolve(),Path(a.target_inventory).resolve(),Path(a.source_root).resolve(),Path(a.output).resolve(),a.display_version,a.internal_version,a.base_version),ensure_ascii=False)); return 0
    except Exception as e: print(json.dumps({"ok":False,"error":str(e)},ensure_ascii=False)); return 1
if __name__=="__main__": raise SystemExit(main())
