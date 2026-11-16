"""Prompt Studio override normalization and authoritative-field protection."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))
import prompt_fields


class PromptFieldOverrideTests(unittest.TestCase):
    def test_normalize_removes_all_ui_ids_legacy_character_fields_and_camera(self):
        ui_ids = (
            "positive_general_lakis_external",
            "positive_general_lakis_external_base",
            "positive_general_lakis_external_fixed",
            "positive_quality_lakis_external",
            "positive_artist_lakis_external",
            "positive_trigger_lakis_external",
            "negative_general_lakis_external",
            "negative_general_lakis_external_fixed",
            "negative_quality_lakis_external",
            "negative_artist_lakis_external",
        )
        fields = [{"id": field_id, "text": "stale"} for field_id in ui_ids]
        fields.extend((
            {"id": "positive_general_kr_camera_bridge", "text": "stale camera"},
            {"id": "old-positive-character", "pane": "positive", "type": "general", "text": "old"},
            {"id": "old-negative-character", "pane": "negative", "type": "artist", "text": "old"},
        ))
        self.assertIsNone(prompt_fields.normalize_override(json.dumps(fields)))

    def test_normalize_preserves_naia_unknown_and_nested_fields(self):
        fields = [
            {
                "id": "naia-region",
                "type": "naia",
                "text": "edited",
                "custom": {"nested": [{"value": "保留"}]},
            },
            {"id": "future-field", "other": {"enabled": True}},
            {"id": "positive_general_kr_camera_bridge", "text": "current camera"},
        ]
        normalized = prompt_fields.normalize_override(json.dumps(fields, ensure_ascii=False))
        self.assertEqual(
            json.loads(normalized),
            [
                {
                    "id": "naia-region",
                    "type": "naia",
                    "text": "edited",
                    "custom": {"nested": [{"value": "保留"}]},
                },
                {"id": "future-field", "other": {"enabled": True}},
            ],
        )
        self.assertEqual(
            normalized,
            '[{"custom":{"nested":[{"value":"保留"}]},"id":"naia-region","text":"edited","type":"naia"},'
            '{"id":"future-field","other":{"enabled":true}}]',
        )

    def test_merge_preserves_current_authoritative_fields_and_only_applies_editable_items(self):
        current = [
            {"id": "positive_general_lakis_external", "text": "current main prompt"},
            {"id": "naia-region", "type": "naia", "text": "old", "extra": {"keep": True}},
            {"id": "positive_general_kr_camera_bridge", "text": "current camera"},
            {"id": "legacy-character", "pane": "positive", "type": "general", "text": "current character"},
        ]
        requested = [
            {"id": "positive_general_lakis_external", "text": "stale main prompt"},
            {"id": "positive_general_kr_camera_bridge", "text": "stale camera"},
            {"id": "legacy-character", "text": "stale character"},
            {"id": "naia-region", "type": "naia", "text": "edited"},
            {"id": "new-naia", "type": "naia", "text": "added"},
        ]

        merged = json.loads(prompt_fields.merge_override(
            json.dumps(current), json.dumps(requested),
        ))
        self.assertEqual([item["id"] for item in merged], [
            "positive_general_lakis_external", "naia-region",
            "positive_general_kr_camera_bridge", "legacy-character", "new-naia",
        ])
        self.assertEqual(merged[0], current[0])
        self.assertEqual(merged[1], {
            "id": "naia-region", "type": "naia", "text": "edited", "extra": {"keep": True},
        })
        self.assertEqual(merged[2], current[2])
        self.assertEqual(merged[3], current[3])
        self.assertEqual(merged[4], requested[4])

    def test_equivalent_json_is_a_canonical_no_op(self):
        current = '[{"id":"naia","text":"same","extra":{"nested":{"value":1}}}]'
        requested = '[ { "extra": { "nested": { "value": 1 } }, "text": "same", "id": "naia" } ]'
        self.assertEqual(
            prompt_fields.merge_override(current, requested),
            '[{"extra":{"nested":{"value":1}},"id":"naia","text":"same"}]',
        )

    def test_malformed_inputs_raise_value_error_for_both_functions(self):
        valid = "[]"
        malformed = (
            None,
            {},
            "{",
            "{}",
            "[1]",
            '[{"text":"missing id"}]',
            '[{"id":""}]',
            '[{"id":"  "}]',
            '[{"id":4}]',
            '[{"id":"field","nested":NaN}]',
        )
        for serialized in malformed:
            with self.subTest(serialized=serialized):
                with self.assertRaises(ValueError):
                    prompt_fields.normalize_override(serialized)
                with self.assertRaises(ValueError):
                    prompt_fields.merge_override(valid, serialized)
                with self.assertRaises(ValueError):
                    prompt_fields.merge_override(serialized, valid)

    def test_input_serializations_are_not_mutated(self):
        current = '[ { "id": "naia", "text": "old", "extra": { "keep": true } } ]'
        requested = '[ { "id": "naia", "text": "new" } ]'
        current_before, requested_before = current, requested

        prompt_fields.normalize_override(requested)
        prompt_fields.merge_override(current, requested)

        self.assertEqual(current, current_before)
        self.assertEqual(requested, requested_before)


if __name__ == "__main__":
    unittest.main()
