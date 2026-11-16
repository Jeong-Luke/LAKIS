"""SCOPE gets an independent upscaler without changing the shared loader."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/external_ui"))
from scope_upscale import bind_scope_upscalers


class ScopeWiringTests(unittest.TestCase):
    def test_scopes_keep_weights_but_do_not_replace_other_consumers(self):
        prompt = {
            "loader": {"class_type": "UpscaleModelLoader",
                       "inputs": {"model_name": "same.pth"},
                       "_meta": {"title": "User model", "lakis_source_id": "loader", "custom": 42}},
            "scope-a": {"class_type": "LAKIS_SCOPE",
                        "inputs": {"upscale_model": ["loader", 0], "quality_mode": True}},
            "scope-b": {"class_type": "LAKIS_SCOPE",
                        "inputs": {"upscale_model": ["loader", 0], "quality_mode": False}},
            "ultimate": {"class_type": "UltimateSDUpscale",
                         "inputs": {"upscale_model": ["loader", 0]}},
        }
        original = deepcopy(prompt)
        bind_scope_upscalers(prompt)
        self.assertEqual(prompt["loader"], original["loader"])
        self.assertEqual(prompt["ultimate"], original["ultimate"])
        added = []
        for key in ("scope-a", "scope-b"):
            static_id = prompt[key]["inputs"]["upscale_model"][0]
            added.append(static_id)
            loader = prompt[static_id]
            self.assertEqual(loader["class_type"], "LAKISScopeUpscaleModelLoader")
            self.assertEqual(loader["inputs"], original["loader"]["inputs"])
            self.assertEqual(loader["_meta"]["custom"], 42)
            self.assertEqual(loader["_meta"]["lakis_source_id"], static_id)
            self.assertEqual(prompt[key]["inputs"]["quality_mode"],
                             original[key]["inputs"]["quality_mode"])
        self.assertNotEqual(*added)
        prompt[added[0]]["inputs"]["model_name"] = "changed.pth"
        self.assertEqual(prompt["loader"]["inputs"]["model_name"], "same.pth")
        self.assertEqual(prompt[added[1]]["inputs"]["model_name"], "same.pth")

    def test_non_scope_graph_is_unchanged(self):
        prompt = {"upscale": {"class_type": "ImageUpscaleWithModel", "inputs": {}}}
        original = deepcopy(prompt)
        bind_scope_upscalers(prompt)
        self.assertEqual(prompt, original)

    def test_contiguous_tiles_are_enabled_only_on_request_and_only_for_scope(self):
        source = {
            "loader": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "same.pth"}},
            "scope": {"class_type": "LAKIS_SCOPE", "inputs": {"upscale_model": ["loader", 0]}},
            "other": {"class_type": "UltimateSDUpscale", "inputs": {"upscale_model": ["loader", 0]}},
        }
        for enabled in (False, True):
            prompt = deepcopy(source)
            bind_scope_upscalers(prompt, contiguous_tiles=enabled)
            if enabled:
                self.assertIs(prompt["scope"]["inputs"]["contiguous_tiles"], True)
            else:
                self.assertNotIn("contiguous_tiles", prompt["scope"]["inputs"])
            self.assertEqual(prompt["loader"], source["loader"])
            self.assertEqual(prompt["other"], source["other"])


if __name__ == "__main__":
    unittest.main()
