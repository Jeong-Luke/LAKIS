"""Focused tests for the shared CSV prompt helpers."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "external_ui"))

import prompt_service  # noqa: E402
from prompt_service import (  # noqa: E402
    TagDictionary,
    normalized_tag_identity,
    translate_korean_text,
    translate_prompt_payload,
)


class TestTagDictionary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv_path = Path(self.temp.name) / "autocomplete.csv"
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerows(
                [
                    [
                        " Long Hair ",
                        "0",
                        "17",
                        "[패션 > 헤어스타일] 긴 머리. 키워드: <헤어스타일>, 긴 머리, 장발",
                    ],
                    ["red_eyes", "3", "not-a-count", "[색상] 붉은 눈: 눈 색"],
                    ["short_row", "1", "1"],
                    ["", "0", "1", "empty tag"],
                ]
            )
        self.dictionary = TagDictionary(self.csv_path)

    def test_csv_entries_labels_sections_and_lookup(self):
        entries = self.dictionary.entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries[0],
            (
                "Long Hair",
                "긴 머리",
                17,
                "[패션 > 헤어스타일] 긴 머리. 키워드: <헤어스타일>, 긴 머리, 장발",
                "general",
            ),
        )
        self.assertEqual(entries[1][1:], ("붉은 눈", 0, "[색상] 붉은 눈: 눈 색", "copyright"))
        lookup = self.dictionary.lookup()
        self.assertEqual(lookup["long_hair"], entries[0])
        self.assertEqual(lookup["red_eyes"], entries[1])

    def test_suggestions_and_exact_normalization(self):
        self.assertEqual(normalized_tag_identity(r"  Long__Hair  "), "long_hair")
        self.assertEqual(normalized_tag_identity(r"\(Blue Eyes\)"), "(blue_eyes)")
        self.assertEqual(self.dictionary.suggestions("long h")[0]["tag"], "Long Hair")
        self.assertEqual(self.dictionary.suggestions("장발")[0]["ko"], "긴 머리")
        self.assertEqual(self.dictionary.suggestions("x"), ())
        self.assertEqual(
            TagDictionary(Path(self.temp.name) / "missing.csv").entries(), ()
        )


class TestPromptTranslation(unittest.TestCase):
    def test_korean_translation_preserves_english_commas_and_newlines(self):
        provider = Mock()
        provider.translate.return_value = "woman"
        translated = translate_prompt_payload(
            {"general": "blue eyes, 여자,\nlong hair"}, provider=provider
        )
        self.assertEqual(
            translated["general"], "blue eyes, woman,\nlong hair"
        )
        provider.translate.assert_called_once_with("여자", "auto", "en")

        self.assertEqual(
            translate_korean_text("blue eyes, long hair\nsmile", provider=provider),
            "blue eyes, long hair\nsmile",
        )
        provider.translate.assert_called_once()

    def test_fallback_provider_is_mocked_and_used_after_provider_failure(self):
        provider_error = RuntimeError("primary provider unavailable")
        provider = Mock()
        provider.translate.side_effect = provider_error
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps([[["woman", "여자"]]]).encode("utf-8")
        with patch.object(prompt_service, "urlopen", return_value=response) as fallback:
            self.assertEqual(
                translate_korean_text("여자, blue eyes", provider=provider),
                "woman, blue eyes",
            )
        provider.translate.assert_called_once_with("여자", "auto", "en")
        fallback.assert_called_once()

    def test_malformed_and_oversize_payloads_are_rejected_before_translation(self):
        provider = Mock()
        for prompt in (["not", "an", "object"], {"general": "x" * 20_001}):
            with self.subTest(prompt_type=type(prompt).__name__):
                with self.assertRaises(ValueError):
                    translate_prompt_payload(prompt, provider=provider)
        provider.translate.assert_not_called()

    def test_translation_failure_propagates_without_real_network_access(self):
        provider_error = RuntimeError("primary provider unavailable")
        provider = Mock()
        provider.translate.side_effect = provider_error
        with patch.object(
            prompt_service, "urlopen", side_effect=OSError("fallback unavailable")
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Google prompt translation providers failed"
            ) as raised:
                translate_korean_text("여자", provider=provider)
        self.assertIs(raised.exception.__cause__, provider_error)
        provider.translate.assert_called_once_with("여자", "auto", "en")


if __name__ == "__main__":
    unittest.main(verbosity=2)
