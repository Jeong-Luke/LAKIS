"""Request-local node wiring for mixed global, person and box references."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/external_ui"))
import anima_reference as reference


def graph():
    return {
        "890:164": {"class_type": "CLIPLoader", "inputs": {}},
        "890:159": {"class_type": "VAELoader", "inputs": {}},
        "1634:1721": {"class_type": "DiTSpectrumPatch", "inputs": {"model": ["base", 0]}},
        "1633:1612": {"class_type": "KSampler", "inputs": {"model": ["turbo", 0]}},
        "775": {"class_type": "SaveImage", "inputs": {"images": ["output", 0]}},
    }


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        (self.root / "input").mkdir()
        entries = []
        for index in range(1, 4):
            name = "LAKIS_reference_" + str(index) * 64 + ".png"
            (self.root / "input" / name).write_bytes(b"already validated upload")
            entries.append({"image_name": name, "strength": index - 2})
        entries[1].update(target_type="pose", target_id="body-b")
        entries[2].update(target_type="box", target_id="box-a")
        capture = json.dumps({"region_painter": {
            "width": 128, "height": 64,
            "bodies": [{"id": "body-a"}, {"id": "body-b"}]}})
        self.state = {
            "anima_reference": {"enabled": True, "references": entries},
            "scene_controls": {"enabled": True, "toyxyz_enabled": True, "toyxyz_render_data": capture},
            "anima_regions": {"enabled": True, "regions": [
                {"id": "box-a", "label": "character", "caption": "", "bbox": [250, 0, 750, 1000]}]},
            "output": {"width": 128, "height": 64},
        }
        self.prompt = graph()
        self.prompt["pose"] = {"class_type": "ToyxyzPose3DEditor", "inputs": {"render_data": capture}}
        self.info = {key: {} for key in (
            "LAKISRegionalReference", "LAKISRegionalSnapRef", "LAKISPoseReferenceMask",
            "SolidMask", "MaskComposite")}
        self.info["SnapRef"] = {"input": {"optional": {key: [] for key in (
            "use_batch", "multi_layout", "weight_1", "weight_2", "weight_3", "image_2", "image_3")}}}
        self.env = patch.dict(os.environ, {"LAKIS_SNAPREF_EXPERIMENT": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ready = patch.object(reference, "configuration", return_value={"ready": True})
        self.ready.start()
        self.addCleanup(self.ready.stop)

    def test_mixed_targets_share_bundle_at_both_stages_and_preserve_inputs(self):
        before = deepcopy(self.state)
        final = deepcopy(self.prompt["775"])
        result = reference.apply(self.prompt, self.state, self.info, self.root)
        self.assertTrue(result["anima_reference_regional"])
        self.assertEqual(self.state, before)
        self.assertEqual(self.prompt["775"], final)
        for stage, owner, original in (("initial", "1634:1721", "base"), ("highrez", "1633:1612", "turbo")):
            patched = self.prompt[f"lakis:anima_reference:{stage}"]
            self.assertEqual(patched["class_type"], "LAKISRegionalSnapRef")
            self.assertEqual(patched["inputs"]["model"], [original, 0])
            self.assertEqual(patched["inputs"]["references"], ["lakis:anima_reference:reference:3", 0])
            self.assertEqual(self.prompt[owner]["inputs"]["model"], [f"lakis:anima_reference:{stage}", 0])
        pose = [node for node in self.prompt.values() if node["class_type"] == "LAKISPoseReferenceMask"]
        self.assertEqual(pose[0]["inputs"]["body_id"], "body-b")
        self.assertEqual(pose[0]["inputs"]["region_painter"], ["pose", 5])
        boxes = [node for node in self.prompt.values() if node["class_type"] == "MaskComposite"]
        self.assertEqual((boxes[0]["inputs"]["x"], boxes[0]["inputs"]["y"]), (32, 0))
        solid = self.prompt[boxes[0]["inputs"]["source"][0]]["inputs"]
        self.assertEqual((solid["width"], solid["height"]), (64, 64))

    def test_missing_target_disabled_source_stale_size_and_dependency_fail_atomically(self):
        for change in ("person", "box", "pose_off", "box_off", "size", "owner", "dependency"):
            with self.subTest(change=change):
                state, prompt, info = deepcopy(self.state), deepcopy(self.prompt), deepcopy(self.info)
                if change == "person":
                    state["anima_reference"]["references"][1]["target_id"] = "removed"
                elif change == "box":
                    state["anima_reference"]["references"][2]["target_id"] = "removed"
                elif change == "pose_off":
                    state["scene_controls"]["enabled"] = False
                elif change == "box_off":
                    state["anima_regions"]["enabled"] = False
                elif change == "size":
                    state["output"]["width"] = 256
                elif change == "owner":
                    del prompt["pose"]
                else:
                    del info["LAKISRegionalSnapRef"]
                before = deepcopy(prompt)
                with self.assertRaises(ValueError):
                    reference.apply(prompt, state, info, self.root)
                self.assertEqual(prompt, before)

    def test_missing_saved_target_never_becomes_global_and_unused_slots_are_retained(self):
        for target in ({"target_type": "other"}, {"target_type": "pose", "target_id": ""},
                       {"target_type": "box", "target_id": 1}):
            with self.subTest(target=target), self.assertRaises(ValueError):
                reference.normalize({"references": [target]})
        state = deepcopy(self.state)
        state["anima_reference"]["references"][1]["image_name"] = ""
        state["anima_reference"]["references"][1]["target_id"] = "removed-but-retained"
        before = deepcopy(state)
        reference.apply(self.prompt, state, self.info, self.root)
        self.assertEqual(state, before)
        self.assertFalse(any(node["class_type"] == "LAKISPoseReferenceMask" for node in self.prompt.values()))

    def test_three_numbered_pose_bindings_reach_both_stages_without_global_reference(self):
        state = deepcopy(self.state)
        ids = ["body-c", "body-a", "body-b"]
        capture = json.dumps({"region_painter": {
            "width": 128, "height": 64, "bodies": [{"id": body_id} for body_id in ids]}})
        state["scene_controls"]["toyxyz_render_data"] = capture
        for item, body_id in zip(state["anima_reference"]["references"], ids):
            item.update(target_type="pose", target_id=body_id)
        prompt = deepcopy(self.prompt)
        prompt["pose"]["inputs"]["render_data"] = capture
        before = deepcopy(state)
        result = reference.apply(prompt, state, self.info, self.root)
        self.assertTrue(result["anima_reference_regional"])
        self.assertEqual(state, before)
        self.assertFalse(any(node["class_type"] == "SolidMask" for node in prompt.values()))
        for index, body_id in enumerate(ids, 1):
            bundle = prompt[f"lakis:anima_reference:reference:{index}"]["inputs"]
            mask = prompt[bundle["mask"][0]]
            self.assertEqual(mask["class_type"], "LAKISPoseReferenceMask")
            self.assertEqual(mask["inputs"]["body_id"], body_id)
            self.assertEqual(bundle["image"], [
                "lakis:anima_reference:image" + (f":{index}" if index > 1 else ""), 0])
        for stage in ("initial", "highrez"):
            self.assertEqual(prompt[f"lakis:anima_reference:{stage}"]["class_type"],
                             "LAKISRegionalSnapRef")
        # Body list order may change, but saved identities must not.
        reordered = json.dumps({"region_painter": {
            "width": 128, "height": 64, "bodies": [{"id": body_id} for body_id in reversed(ids)]}})
        state["scene_controls"]["toyxyz_render_data"] = reordered
        prompt = deepcopy(self.prompt)
        prompt["pose"]["inputs"]["render_data"] = reordered
        reference.apply(prompt, state, self.info, self.root)
        actual_ids = [prompt[prompt[f"lakis:anima_reference:reference:{index}"]["inputs"]["mask"][0]]
                      ["inputs"]["body_id"] for index in range(1, 4)]
        self.assertEqual(actual_ids, ids)

    def test_same_person_reuses_mask_and_global_only_keeps_original_snapref(self):
        state = deepcopy(self.state)
        state["anima_reference"]["references"][2].update(target_type="pose", target_id="body-b")
        reference.apply(self.prompt, state, self.info, self.root)
        masks = [node for node in self.prompt.values() if node["class_type"] == "LAKISPoseReferenceMask"]
        self.assertEqual(len(masks), 1)
        for item in state["anima_reference"]["references"]:
            item.pop("target_type", None)
            item.pop("target_id", None)
        prompt = graph()
        reference.apply(prompt, state, {"SnapRef": self.info["SnapRef"]}, self.root)
        for stage in ("initial", "highrez"):
            self.assertEqual(prompt[f"lakis:anima_reference:{stage}"]["class_type"], "SnapRef")
        self.assertFalse(any(node["class_type"].startswith("LAKISRegional") for node in prompt.values()))

    def test_forecast_is_opt_in_wired_at_both_stages_and_keeps_global_path(self):
        self.assertIs(reference.normalize({})["experimental_forecast"], False)
        state = deepcopy(self.state)
        state["anima_reference"]["experimental_forecast"] = True
        info = deepcopy(self.info)
        info["LAKISRegionalSnapRef"] = {"input": {"optional": {"experimental_forecast": []}}}
        info["SpectrumKSampler"] = {}
        for enabled in (False, True):
            state["anima_reference"]["experimental_forecast"] = enabled
            before = deepcopy(state)
            prompt = deepcopy(self.prompt)
            report = reference.apply(prompt, state, info, self.root)
            self.assertEqual(state, before)
            self.assertIs(report["anima_reference_experimental_forecast"], enabled)
            for stage in ("initial", "highrez"):
                inputs = prompt[f"lakis:anima_reference:{stage}"]["inputs"]
                self.assertIs(inputs.get("experimental_forecast", False), enabled)
        for entry in state["anima_reference"]["references"]:
            entry["target_type"] = "global"
        prompt = graph()
        report = reference.apply(prompt, state, self.info, self.root)
        self.assertFalse(report["anima_reference_experimental_forecast"])
        self.assertTrue(state["anima_reference"]["experimental_forecast"])
        self.assertTrue(all("experimental_forecast" not in node["inputs"] for node in prompt.values()))

    def test_forecast_invalid_values_and_missing_dependency_reject_before_graph_mutation(self):
        for value in ("false", 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reference.normalize({"experimental_forecast": value})
        state = deepcopy(self.state)
        state["anima_reference"]["experimental_forecast"] = True
        before = deepcopy(self.prompt)
        with self.assertRaisesRegex(ValueError, "영역 생성 가속"):
            reference.apply(self.prompt, state, self.info, self.root)
        self.assertEqual(self.prompt, before)

    def test_regional_snapref_weight_offload_is_opted_in_only_by_experimental_forecast(self):
        import importlib
        import importlib.util
        import types
        from types import SimpleNamespace

        import torch

        package_name = "regional_reference_wiring_runtime_test"
        package_path = ROOT / "src/custom_nodes/ComfyUI-LAKIS-Regional-Reference"
        package_spec = importlib.util.spec_from_file_location(
            package_name, package_path / "__init__.py",
            submodule_search_locations=[str(package_path)])
        package = importlib.util.module_from_spec(package_spec)
        sys.modules[package_name] = package
        package_spec.loader.exec_module(package)
        node_module = importlib.import_module(f"{package_name}.nodes")
        RegionalReference = node_module.RegionalReference
        RegionalSnapRef = node_module.RegionalSnapRef

        core = types.ModuleType("regional_reference_wiring_snapref_fixture")
        core.WRAPPER_KEY = "snapref"
        core._concat_kv = lambda records: records[0]
        native_adapters = []
        native_wrappers = []

        def make_native(adapter):
            def native(executor, *args, **kwargs):
                if adapter is None:
                    raise AssertionError("the native wrapper must capture its adapter")
                return executor(*args, **kwargs)
            return native

        class SnapRef:
            def apply(self, **kwargs):
                patched = kwargs["model"].clone()
                native = make_native(kwargs["adapter"])
                native_adapters.append(kwargs["adapter"])
                native_wrappers.append(native)
                patched.add_wrapper_with_key("diffusion_model", core.WRAPPER_KEY, native)
                return (patched,)

        SnapRef.__module__ = core.__name__
        registry = types.ModuleType("nodes")
        registry.NODE_CLASS_MAPPINGS = {"SnapRef": SnapRef}
        comfy = types.ModuleType("comfy")
        extension = types.ModuleType("comfy.patcher_extension")
        extension.WrappersMP = SimpleNamespace(
            DIFFUSION_MODEL="diffusion_model", OUTER_SAMPLE="outer_sample")

        class Model:
            def __init__(self):
                self.wrappers = {"diffusion_model": {}}
                self.model_options = {}

            def clone(self):
                result = Model()
                result.wrappers = {
                    kind: {key: list(functions) for key, functions in groups.items()}
                    for kind, groups in self.wrappers.items()
                }
                result.model_options = dict(self.model_options)
                return result

            def add_wrapper_with_key(self, kind, key, function):
                self.wrappers.setdefault(kind, {}).setdefault(key, []).append(function)

        forecast_name = f"{package_name}.forecast_session"
        forecast = types.ModuleType(forecast_name)
        forecast.create_session = lambda: SimpleNamespace(sample=lambda *args, **kwargs: None)
        released_options = []

        def record_release(native, concat, *, offload_reference_weights=False):
            self.assertIn("adapter", native.__code__.co_freevars)
            adapter_index = native.__code__.co_freevars.index("adapter")
            self.assertEqual(
                native.__closure__[adapter_index].cell_contents, native_adapters[-1])
            self.assertIs(concat, core._concat_kv)
            released_options.append(offload_reference_weights)
            return native

        image = torch.zeros((1, 16, 16, 3))
        mask = torch.ones((1, 32, 32))
        bundle, = RegionalReference().build(image, mask)
        session = SimpleNamespace(sample=lambda *args, **kwargs: None)
        forecast.create_session = lambda: session

        with patch.dict(sys.modules, {
            "nodes": registry,
            "comfy": comfy,
            "comfy.patcher_extension": extension,
            core.__name__: core,
            forecast_name: forecast,
        }), patch.object(node_module, "release_encoding_records", side_effect=record_release):
            for options, expected in (
                    ({}, False), ({"experimental_forecast": False}, False),
                    ({"experimental_forecast": True}, True)):
                with self.subTest(options=options):
                    RegionalSnapRef().apply(
                        Model(), object(), object(), bundle, "test-adapter", **options)
                    self.assertIs(released_options[-1], expected)
                    self.assertIn("adapter", native_wrappers[-1].__code__.co_freevars)
        self.assertEqual(released_options, [False, False, True])


if __name__ == "__main__":
    unittest.main()
