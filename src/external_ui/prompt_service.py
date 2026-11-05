"""Shared local tag dictionary and prompt translation helpers."""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

__all__ = (
    "TagDictionary",
    "normalized_tag_identity",
    "translate_korean_text",
    "translate_prompt_payload",
)

KOREAN_PATTERN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
TRANSLATION_SPLIT_PATTERN = re.compile(r"([,\n]+)")
_TAG_SECTIONS = {
    "0": "general",
    "1": "artist",
    "3": "copyright",
    "4": "character",
    "5": "meta",
}
_PROVIDER_NOT_LOADED = object()
_GOOGLE_TRANSLATOR = _PROVIDER_NOT_LOADED


def normalized_tag_identity(value: object) -> str:
    """Treat spaces, underscores, repeated whitespace and case as one tag."""
    unescaped = re.sub(r"\\([()\[\]{}])", r"\1", str(value or ""))
    return "_".join(unescaped.strip().casefold().replace("_", " ").split())


class TagDictionary:
    """Read and query the packaged LAKIS CSV tag dictionary."""

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._entries = self._load()

    def _load(self) -> tuple[tuple[str, str, int, str, str], ...]:
        entries: list[tuple[str, str, int, str, str]] = []
        if not self.csv_path.is_file():
            return tuple()
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.reader(stream):
                if len(row) < 4 or not row[0].strip():
                    continue
                tag, tag_type, count_text, description = row[:4]
                # Parse the current keyword marker before the legacy label form.
                keyword_match = re.search(
                    r"키워드:\s*(?:<[^>]+>\s*,?\s*)?([^,]+)", description
                )
                if keyword_match:
                    korean_label = keyword_match.group(1).strip()
                else:
                    label_match = re.match(
                        r"^\[[^\]]+\]\s*([^:/]{1,48}?)\s*:", description
                    )
                    korean_label = label_match.group(1).strip() if label_match else ""
                try:
                    count = int(count_text)
                except ValueError:
                    count = 0
                section = _TAG_SECTIONS.get(tag_type.strip(), "general")
                entries.append(
                    (
                        tag.strip(),
                        korean_label,
                        count,
                        description.strip(),
                        section,
                    )
                )
        return tuple(entries)

    def entries(self) -> tuple[tuple[str, str, int, str, str], ...]:
        return self._entries

    def suggestions(self, query: str, limit: int = 12) -> tuple[dict, ...]:
        normalized_text = query.strip().casefold()
        normalized_tag_query = normalized_text.replace(" ", "_")
        if len(normalized_text) < 2:
            return tuple()
        matches = []
        korean_query = bool(KOREAN_PATTERN.search(query))
        for tag, korean_label, count, description, _section in self._entries:
            normalized_tag = normalized_tag_identity(tag)
            matched = normalized_tag.startswith(
                normalized_tag_identity(normalized_tag_query)
            )
            if korean_query:
                matched = (
                    normalized_text in korean_label.casefold()
                    or normalized_text in description.casefold()
                )
            if matched:
                matches.append(
                    {
                        "tag": tag,
                        "ko": korean_label,
                        "count": count,
                        "description": description,
                        "source": "lakis_csv",
                    }
                )
                if len(matches) >= limit:
                    break
        return tuple(matches)

    def lookup(self) -> dict[str, tuple[str, str, int, str, str]]:
        return {normalized_tag_identity(row[0]): row for row in self._entries}


def _default_google_provider():
    global _GOOGLE_TRANSLATOR
    if _GOOGLE_TRANSLATOR is _PROVIDER_NOT_LOADED:
        try:
            comfy_root = Path(__file__).resolve().parents[2]
            easyuse_root = comfy_root / "custom_nodes" / "comfyui-easyuse-anima"
            if str(easyuse_root) not in sys.path:
                sys.path.insert(0, str(easyuse_root))
            from easyuse_anima.translation.providers.google import (
                GoogleTranslationProvider,
            )

            _GOOGLE_TRANSLATOR = GoogleTranslationProvider(timeout_seconds=10.0)
        except Exception:
            _GOOGLE_TRANSLATOR = None
    return _GOOGLE_TRANSLATOR


def translate_korean_text(value: str, provider=None) -> str:
    """Translate Hangul-containing comma/newline fields while preserving separators."""
    text = str(value or "")
    if not KOREAN_PATTERN.search(text):
        return text
    translator = provider if provider is not None else _default_google_provider()
    translated = []
    for part in TRANSLATION_SPLIT_PATTERN.split(text):
        if not part or TRANSLATION_SPLIT_PATTERN.fullmatch(part):
            translated.append(part)
            continue
        if not KOREAN_PATTERN.search(part):
            translated.append(part)
            continue
        leading = part[: len(part) - len(part.lstrip())]
        trailing = part[len(part.rstrip()) :]
        source_text = part.strip()
        translated_body = ""
        provider_error: Exception | None = None
        if translator is not None:
            try:
                translated_body = translator.translate(source_text, "auto", "en")
            except Exception as error:
                provider_error = error
        if not translated_body:
            try:
                endpoint = (
                    "https://translate.googleapis.com/translate_a/single"
                    f"?client=gtx&sl=auto&tl=en&dt=t&q={quote(source_text)}"
                )
                request = Request(endpoint, headers={"User-Agent": "LAKIS/7.3.6"})
                with urlopen(request, timeout=10.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                translated_body = "".join(
                    str(segment[0])
                    for segment in (payload[0] or [])
                    if isinstance(segment, list) and segment
                )
            except Exception as fallback_error:
                raise RuntimeError(
                    "Google prompt translation providers failed"
                ) from (provider_error or fallback_error)
        if not translated_body:
            raise RuntimeError("Google prompt translation returned an empty result")
        translated.append(leading + html.unescape(translated_body) + trailing)
    return "".join(translated)


def translate_prompt_payload(prompt: object, provider=None) -> dict:
    if not isinstance(prompt, dict):
        raise ValueError("Invalid prompt payload")
    if sum(len(str(value or "")) for value in prompt.values()) > 20_000:
        raise ValueError("번역할 프롬프트가 너무 깁니다.")
    return {
        str(key): translate_korean_text(value, provider)
        for key, value in prompt.items()
    }
