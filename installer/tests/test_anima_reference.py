"""Request-local reference wiring, source validation and settings preservation."""
import base64
from copy import deepcopy
import io
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/external_ui"))
import anima_reference as reference
import workflow_bridge as bridge
import serve_ui


def graph():
    return {
        "890:164": {"class_type": "CLIPLoader", "inputs": {}},
        "890:159": {"class_type": "VAELoader", "inputs": {}},
        "1634:1721": {"class_type": "DiTSpectrumPatch", "inputs": {"model": ["base", 0], "enabled": True}},
        "1633:1612": {"class_type": "KSampler", "inputs": {"model": ["turbo", 0]}},
        "775": {"class_type": "SaveImage", "inputs": {"images": ["output", 0]}},
    }


class ReferenceTests(unittest.TestCase):
    def test_normalization_preserves_unknowns_and_rejects_invalid_input(self):
        state = {"future": {"keep": 1}}
        self.assertEqual(reference.normalize(state)["future"], state["future"])
        for changes in ({"enabled": "false"}, {"weight": math.nan},
                        {"strength": -3.01}, {"strength": 3.01}, {"strength": math.nan},
                        {"strength": math.inf}, {"strength": True}, {"strength": None},
                        {"fidelity": -1}, {"weight": True}, {"ref_megapixels": 3},
                        {"image_name": "../file.png"}, {"mode": "other"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                reference.normalize(changes)
        for entries in (None, {}, [], [None], [{}] * 4):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                reference.normalize({"references": entries})
        state = {"future": {"keep": [1]}, "references": [
            {"image_name": "", "strength": -2, "future_entry": {"keep": [2]}},
            {"image_name": "", "strength": 3},
        ]}
        before = deepcopy(state)
        cleaned = reference.normalize(state)
        self.assertEqual(cleaned["references"], state["references"])
        self.assertEqual(reference.normalize(cleaned), cleaned)
        cleaned["references"][0]["future_entry"]["keep"].append(3)
        self.assertEqual(state, before)

    def test_log_strength_defaults_boundaries_and_legacy_settings_preserve_effect(self):
        self.assertEqual(reference.normalize(None), reference.DEFAULTS)
        for strength in (-3, -1, 0, 1, 3):
            self.assertEqual(reference.normalize({"strength": strength})["references"][0]["strength"], strength)
        for weight, expected in ((0, 0), (.01, -3), (.5, math.log(.5)),
                                 (1, 0), (1.2, math.log(1.2)), (2, math.log(2))):
            with self.subTest(weight=weight):
                saved = {"enabled": True, "weight": weight, "future": {"keep": [1]}}
                before = deepcopy(saved)
                migrated = reference.normalize(saved)
                self.assertAlmostEqual(migrated["references"][0]["strength"], expected)
                self.assertEqual(migrated["enabled"], weight != 0)
                self.assertNotIn("weight", migrated)
                self.assertNotIn("strength", migrated)
                self.assertNotIn("image_name", migrated)
                self.assertEqual(migrated["future"], saved["future"])
                self.assertEqual(reference.normalize(migrated), migrated)
                self.assertEqual(saved, before)
        self.assertEqual(reference.normalize({"strength": -2, "weight": 2})["references"][0]["strength"], -2)
        for weight in (-.1, 2.1, None):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                reference.normalize({"weight": weight})

    def test_canonical_references_take_precedence_over_obsolete_flat_fields(self):
        value = {"enabled": True, "weight": 0, "strength": 3, "image_name": "old.png",
                 "references": [{"image_name": "", "strength": -1}]}
        normalized = reference.normalize(value)
        self.assertTrue(normalized["enabled"])
        self.assertEqual(normalized["references"], [{"image_name": "", "strength": -1}])
        self.assertFalse({"weight", "strength", "image_name"} & normalized.keys())

    def test_disabled_or_unavailable_experiment_is_noop(self):
        for settings, env in (({}, "1"), ({"enabled": True}, "0"), ({"enabled": True, "weight": 0}, "1")):
            prompt = graph()
            before = deepcopy(prompt)
            with patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": env}):
                self.assertFalse(reference.apply(prompt, {"anima_reference": settings}, {}, ROOT)["anima_reference_enabled"])
            self.assertEqual(prompt, before)

    def test_both_model_stages_preserve_spectrum_turbo_and_final_saver(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": "1"}):
            root = Path(tmp)
            image = root / "input" / ("LAKIS_reference_" + "1" * 64 + ".png")
            image.parent.mkdir()
            image.write_bytes(b"validated upload fixture")
            state = {"generation": {"engine": "anima"}, "anima_reference": {
                "enabled": True, "image_name": image.name, "strength": 3, "future": "keep"}}
            before = deepcopy(state)
            prompt = graph()
            with patch.object(reference, "configuration", return_value={"ready": True}):
                result = reference.apply(prompt, state, {}, root)
            self.assertEqual(result["anima_reference_stages"], ["initial", "highrez"])
            self.assertTrue(prompt["1634:1721"]["inputs"]["enabled"])
            for stage, owner, original in (("initial", "1634:1721", "base"), ("highrez", "1633:1612", "turbo")):
                node_id = "lakis:anima_reference:" + stage
                self.assertEqual(prompt[owner]["inputs"]["model"], [node_id, 0])
                inputs = prompt[node_id]["inputs"]
                self.assertEqual(inputs["model"], [original, 0])
                self.assertFalse(inputs["ref_guidance_on"])
                self.assertEqual(inputs["strength"], 3)
                self.assertEqual(inputs["clip"], ["890:164", 0])
            self.assertEqual(prompt["775"], graph()["775"])
            self.assertEqual(state, before)
            for strength in (-3, -1, 0, 1.5):
                with self.subTest(strength=strength):
                    state["anima_reference"]["strength"] = strength
                    with patch.object(reference, "configuration", return_value={"ready": True}):
                        request = graph()
                        reference.apply(request, state, {}, root)
                    for stage in ("initial", "highrez"):
                        self.assertEqual(request["lakis:anima_reference:" + stage]["inputs"]["strength"], strength)
                    self.assertEqual(request["775"], graph()["775"])

    def test_conflicts_missing_dependencies_and_missing_image_fail_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": "1"}):
            settings = {"enabled": True, "image_name": "LAKIS_reference_" + "2" * 64 + ".png"}
            for conflict in ({}, {"generation": {"engine": "moss"}}, {"i2i": {"enabled": True}}, {"inpaint": {"enabled": True}}):
                prompt = graph()
                with self.assertRaises(ValueError):
                    reference.apply(prompt, {**conflict, "anima_reference": settings}, {}, Path(tmp))
                self.assertEqual(prompt, graph())
            with self.assertRaises(ValueError):
                reference.image_path(tmp, settings["image_name"])

    def test_three_images_and_individual_strengths_reach_each_stage_in_one_snapref(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": "1"}):
            root = Path(tmp)
            (root / "input").mkdir()
            entries = []
            for index, strength in enumerate((-3, 0, 3), 1):
                name = "LAKIS_reference_" + str(index) * 64 + ".png"
                (root / "input" / name).write_bytes(b"validated upload fixture")
                entries.append({"image_name": name, "strength": strength})
            state = {"anima_reference": {
                "enabled": True, "mode": "char", "fidelity": .6, "ref_megapixels": .5,
                "references": entries,
            }}
            before = deepcopy(state)
            info = {"SnapRef": {"input": {"optional": {
                name: [] for name in ("image_2", "image_3", "weight_1", "weight_2",
                                     "weight_3", "use_batch", "multi_layout")
            }}}}
            for count in (2, 3):
                with self.subTest(count=count):
                    state["anima_reference"]["references"] = entries[:count]
                    prompt = graph()
                    with patch.object(reference, "configuration", return_value={"ready": True}):
                        report = reference.apply(prompt, state, info, root)
                    self.assertEqual(report["anima_reference_count"], count)
                    self.assertEqual(sum(n["class_type"] == "SnapRef" for n in prompt.values()), 2)
                    for stage, owner, original in (("initial", "1634:1721", "base"),
                                                    ("highrez", "1633:1612", "turbo")):
                        inputs = prompt["lakis:anima_reference:" + stage]["inputs"]
                        self.assertEqual(inputs["model"], [original, 0])
                        self.assertEqual(inputs["mode"], "char")
                        self.assertEqual(inputs["fidelity"], .6)
                        self.assertEqual(inputs["ref_megapixels"], .5)
                        self.assertFalse(inputs["use_batch"])
                        self.assertEqual(inputs["multi_layout"], "separate")
                        for index, entry in enumerate(entries[:count], 1):
                            port = "image" if index == 1 else f"image_{index}"
                            image_id = inputs[port][0]
                            self.assertEqual(prompt[image_id]["inputs"]["image"], entry["image_name"])
                            weight = inputs[f"weight_{index}"]
                            self.assertTrue(0 < weight <= 2)
                            self.assertAlmostEqual(inputs["strength"] + math.log(weight), entry["strength"])
                    self.assertTrue(prompt["1634:1721"]["inputs"]["enabled"])
                    self.assertEqual(prompt["775"], graph()["775"])
            self.assertEqual(state, before)

    def test_empty_slots_are_retained_in_state_but_not_sent_as_images(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": "1"}):
            root = Path(tmp)
            (root / "input").mkdir()
            name = "LAKIS_reference_" + "1" * 64 + ".png"
            (root / "input" / name).write_bytes(b"validated upload fixture")
            state = {"anima_reference": {"enabled": True, "references": [
                {"image_name": "", "strength": 3}, {"image_name": name, "strength": -2}, {},
            ]}}
            before = deepcopy(state)
            with patch.object(reference, "configuration", return_value={"ready": True}):
                prompt = graph()
                result = reference.apply(prompt, state, {}, root)
                self.assertEqual(result["anima_reference_count"], 1)
                self.assertEqual(prompt["lakis:anima_reference:initial"]["inputs"]["strength"], -2)
                self.assertEqual(prompt["lakis:anima_reference:image"]["inputs"]["image"], name)
                self.assertEqual(state, before)
                with self.assertRaisesRegex(ValueError, "한 장 이상"):
                    reference.apply(graph(), {"anima_reference": {"enabled": True}}, {}, root)

    def test_unsupported_multi_node_or_missing_last_image_never_partially_mutates_graph(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": "1"}):
            root = Path(tmp)
            (root / "input").mkdir()
            names = ["LAKIS_reference_" + str(i) * 64 + ".png" for i in (1, 2)]
            (root / "input" / names[0]).write_bytes(b"validated upload fixture")
            state = {"anima_reference": {"enabled": True, "references": [
                {"image_name": name, "strength": 0} for name in names
            ]}}
            info = {"SnapRef": {"input": {"optional": {
                name: [] for name in ("image_2", "weight_1", "weight_2", "use_batch", "multi_layout")
            }}}}
            with patch.object(reference, "configuration", return_value={"ready": True}):
                for schema in ({}, info):
                    prompt = graph()
                    with self.assertRaises(ValueError):
                        reference.apply(prompt, state, schema, root)
                    self.assertEqual(prompt, graph())

    def test_server_save_and_generation_reject_a_fourth_reference_even_when_disabled(self):
        value = {"enabled": False, "references": [{}] * 4}
        with patch.object(bridge, "_load_external_ui_payload", return_value={}), \
                patch.object(bridge, "_write_external_ui_payload") as write, \
                patch.object(bridge, "_clean_generation_model_output", return_value=({}, {})), \
                patch.object(bridge, "_clean_advanced_node_overrides", return_value={}):
            with self.assertRaisesRegex(ValueError, "최대 3개"):
                bridge.save_external_generation_state({}, {}, anima_reference=value)
        write.assert_not_called()
        prompt = graph()
        with self.assertRaisesRegex(ValueError, "최대 3개"):
            reference.apply(prompt, {"anima_reference": value}, {}, ROOT)
        self.assertEqual(prompt, graph())

    def test_upload_is_validated_content_addressed_and_temp_directory_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(serve_ui, "INPUT_ROOT", Path(tmp)):
            stream = io.BytesIO()
            Image.new("RGB", (32, 48), "orange").save(stream, "PNG")
            data = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
            first = serve_ui.save_source_image(data, reference=True)
            second = serve_ui.save_source_image(data, reference=True)
            self.assertEqual(first, second)
            self.assertEqual((first["width"], first["height"]), (32, 48))
            self.assertEqual(reference.image_path(tmp, first["image_name"]).read_bytes(), stream.getvalue())
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)
            invalid = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nbroken").decode("ascii")
            with self.assertRaises(OSError):
                serve_ui.save_source_image(invalid, reference=True)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)
            for name in ("../secret.png", "LAKIS_i2i_input.png", str(Path(tmp).parent)):
                with self.assertRaises(ValueError):
                    reference.image_path(tmp, name)

    def test_adapter_is_not_an_ordinary_lora_and_reference_state_survives_save(self):
        with patch.object(bridge, "_live_loader_inventory", return_value=["character.safetensors", reference.ADAPTER]):
            self.assertEqual(bridge._live_lora_inventory({}), ["character.safetensors"])
        payload = {"unknown": "keep", "anima_reference": {"enabled": False, "future": "keep"}}
        with patch.object(bridge, "_load_external_ui_payload", return_value=deepcopy(payload)), \
                patch.object(bridge, "_write_external_ui_payload") as write, \
                patch.object(bridge, "_clean_generation_model_output", return_value=({}, {})), \
                patch.object(bridge, "_clean_advanced_node_overrides", return_value={}):
            bridge.save_external_generation_state({}, {}, anima_reference=payload["anima_reference"])
        saved = write.call_args.args[0]
        self.assertEqual(saved["unknown"], "keep")
        self.assertEqual(saved["anima_reference"], payload["anima_reference"])


if __name__ == "__main__":
    unittest.main()
