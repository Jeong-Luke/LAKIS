"""Shared, engine-independent wildcard inventory and deterministic resolution."""

import hashlib
from pathlib import Path
import re


WILDCARD_TOKEN_PATTERN = re.compile(r"__([A-Za-z0-9_][A-Za-z0-9_\-/]{0,199})__")
ANY_WILDCARD_TOKEN_PATTERN = re.compile(r"__([^\r\n]{1,240}?)__")
BUILTIN_WILDCARD_LABELS = {
    "background": "배경", "composition": "구도", "expression": "표정",
    "hair_style_female": "여성 헤어스타일", "outfit": "의상",
    "pose": "포즈", "prop": "소품",
}


def _wildcard_file(root: Path, relative_name: str) -> Path:
    if not isinstance(relative_name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_\-/]{0,199}", relative_name):
        raise ValueError("잘못된 와일드카드 이름입니다.")
    if ".." in relative_name.split("/"):
        raise ValueError("잘못된 와일드카드 경로입니다.")
    candidate = (root / (relative_name + ".txt")).resolve()
    if candidate.parent != root and root not in candidate.parents:
        raise ValueError("와일드카드 폴더 밖의 파일은 사용할 수 없습니다.")
    if candidate.is_symlink():
        raise ValueError("심볼릭 링크 와일드카드는 사용할 수 없습니다.")
    return candidate


def _read_wildcard(path: Path) -> tuple[list[str], str]:
    payload = path.read_bytes()
    if len(payload) > 1024 * 1024:
        raise ValueError("와일드카드 파일은 1MB 이하여야 합니다.")
    text = payload.decode("utf-8-sig")
    entries = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not entries:
        raise ValueError(f"와일드카드 '{path.stem}'에 선택할 항목이 없습니다.")
    return entries, hashlib.sha256(payload).hexdigest().upper()


def inventory(builtin_root: Path, user_root: Path) -> dict:
    builtin_root, user_root = builtin_root.resolve(), user_root.resolve()
    user_root.mkdir(parents=True, exist_ok=True)
    items = []
    for source, root in (("BUILT_IN", builtin_root), ("USER", user_root)):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.txt"), key=lambda item: item.as_posix().lower()):
            try:
                relative = path.relative_to(root).with_suffix("").as_posix()
                safe_path = _wildcard_file(root, relative)
                if safe_path != path.resolve():
                    continue
                entries, digest = _read_wildcard(safe_path)
            except (OSError, UnicodeError, ValueError):
                continue
            english_name = relative.replace("_", " ")
            korean_name = BUILTIN_WILDCARD_LABELS.get(relative) if source == "BUILT_IN" else None
            items.append({
                "name": relative, "display_name": f"{korean_name} | {english_name}" if korean_name else english_name,
                "source": source, "relative_path": relative + ".txt",
                "entry_count": len(entries), "entries": entries, "sha256": digest,
            })
    return {"ok": True, "items": items, "user_root": str(user_root)}


def resolve(incoming: dict, items: list[dict]) -> dict:
    if not isinstance(incoming, dict):
        raise ValueError("와일드카드 요청은 JSON 객체여야 합니다.")
    prompt = incoming.get("prompt")
    if not isinstance(prompt, dict):
        raise ValueError("프롬프트 형식이 올바르지 않습니다.")
    inpaint = incoming.get("inpaint") if isinstance(incoming.get("inpaint"), dict) else {}
    texts = {str(key): str(value or "") for key, value in prompt.items()}
    if str(inpaint.get("operation", "regenerate")) != "remove":
        texts["__inpaint_positive"] = str(inpaint.get("prompt") or "")
        texts["__inpaint_negative"] = str(inpaint.get("negative_prompt") or "")
    names = []
    for value in texts.values():
        for match in ANY_WILDCARD_TOKEN_PATTERN.finditer(value):
            name = match.group(1)
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_\-/]{0,199}", name) or ".." in name.split("/"):
                raise ValueError(f"잘못된 와일드카드 경로입니다: '{name}'")
            if name not in names:
                names.append(name)
    if names and not bool(incoming.get("enabled")):
        raise ValueError("프롬프트에 와일드카드가 있지만 랜덤 선택 기능이 꺼져 있습니다.")
    lookup = {}
    for item in items:
        if item["source"] == "BUILT_IN":
            lookup.setdefault(item["name"], item)
    for item in items:
        if item["source"] == "USER":
            lookup[item["name"]] = item
    seed = int(incoming.get("seed", 0))
    excluded = incoming.get("excluded") if isinstance(incoming.get("excluded"), dict) else {}
    selections = []
    selected = {}
    for name in names:
        item = lookup.get(name)
        if not item:
            raise ValueError(f"와일드카드 '{name}'을 찾을 수 없습니다.")
        blocked = {str(value) for value in excluded.get(name, []) if isinstance(value, str)} if isinstance(excluded.get(name, []), list) else set()
        entries = [value for value in item["entries"] if value not in blocked]
        if not entries:
            raise ValueError(f"와일드카드 '{name}'에 사용할 후보가 없습니다.")
        digest = hashlib.sha256(f"{seed}\0{name}\0{item['sha256']}".encode("utf-8")).digest()
        value = entries[int.from_bytes(digest[:8], "big") % len(entries)]
        if WILDCARD_TOKEN_PATTERN.search(value):
            raise ValueError(f"와일드카드 '{name}'에 지원하지 않는 중첩 토큰이 있습니다.")
        selected[name] = value
        selections.append({
            "name": name, "value": value, "source": item["source"],
            "relative_file": item["relative_path"], "file_sha256": item["sha256"],
        })
    resolved = {key: WILDCARD_TOKEN_PATTERN.sub(lambda match: selected[match.group(1)], value) for key, value in texts.items()}
    resolved_inpaint = dict(inpaint)
    if "__inpaint_positive" in resolved:
        resolved_inpaint["prompt"] = resolved.pop("__inpaint_positive")
        resolved_inpaint["negative_prompt"] = resolved.pop("__inpaint_negative")
    return {"ok": True, "prompt": resolved, "inpaint": resolved_inpaint, "selections": selections}
