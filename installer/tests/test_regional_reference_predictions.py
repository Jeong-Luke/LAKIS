"""Native prediction selection/mixing, no checkpoint or adapter loads."""
import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src/custom_nodes/ComfyUI-LAKIS-Regional-Reference"
spec = importlib.util.spec_from_file_location(
    "regional_prediction_test", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from regional_prediction_test.masking import mixing_plan
from regional_prediction_test.nodes import RegionalReference, RegionalSnapRef, PoseReferenceMask
from regional_prediction_test.runtime import make_wrapper, WRAPPER_KEY


class MixingTests(unittest.TestCase):
    def test_exclusive_masks_and_globals_preserve_identity_and_cover_the_frame(self):
        left = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        right = 1. - left
        for height, width in ((2, 4), (3, 5), (8, 16)):
            plan = mixing_plan([left, right, torch.ones_like(left)], height, width, "cpu")
            self.assertEqual([keep for keep, _ in plan], [(2, 0), (2, 1)])
            weights = torch.stack([weight for _, weight in plan])
            self.assertEqual(weights.shape, (2, 1, 1, 1, height, width))
            torch.testing.assert_close(weights.sum(dim=0), torch.ones_like(weights[0]), atol=0, rtol=0)
            self.assertEqual((weights[0] * weights[1]).sum().item(), 0)

    def test_soft_overlapping_and_black_masks_have_independent_expected_weights(self):
        left = torch.tensor([[[1., 0.]]])
        plan = mixing_plan([left, left], 1, 2, "cpu")
        self.assertEqual([keep for keep, _ in plan], [(), (0,), (1,)])
        for (_, actual), expected in zip(plan, ([0., 1.], [.5, 0.], [.5, 0.])):
            torch.testing.assert_close(actual.flatten(), torch.tensor(expected), atol=0, rtol=0)
        plan = mixing_plan([left * .25, left * 0], 1, 2, "cpu")
        self.assertEqual([keep for keep, _ in plan], [(), (0,)])
        torch.testing.assert_close(plan[0][1].flatten(), torch.tensor([.75, 1.]), atol=0, rtol=0)
        torch.testing.assert_close(plan[1][1].flatten(), torch.tensor([.25, 0.]), atol=0, rtol=0)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is not available")
    def test_cuda_half_and_bfloat_weights_form_finite_convex_predictions(self):
        for dtype in (torch.float16, torch.bfloat16):
            masks = [torch.tensor([[[.25, 1., 0.]]], device="cuda", dtype=dtype),
                     torch.tensor([[[.75, 1., 0.]]], device="cuda", dtype=dtype)]
            plan = mixing_plan(masks, 1, 3, "cuda")
            result = sum((len(keep) + (keep[0] if keep else 0)) * weight for keep, weight in plan)
            # At x=0: .25*1 + .75*2; x=1: .5*1 + .5*2; x=2: background 0.
            torch.testing.assert_close(result.flatten(), torch.tensor([1.75, 1.5, 0.], device="cuda"),
                                       atol=0, rtol=0)


class RuntimeTests(unittest.TestCase):
    def test_spectrum_forecasts_only_single_prediction_plans_at_the_current_latent_size(self):
        left = torch.tensor([[[1., 1., 0., 0.]]])
        for masks, expected in (
                ((left, 1. - left), False), ((left,), False),
                ((torch.ones_like(left),), True), ((torch.zeros_like(left),), True)):
            wrapper = make_wrapper(masks)
            for height, width in ((1, 4), (3, 5), (2, 8)):
                with self.subTest(expected=expected, size=(height, width)):
                    latent = torch.zeros(1, 1, height, width)
                    self.assertEqual(wrapper.spectrum_cache_veto(input_x=latent), expected)

    def fixture(self, count=2, rows=None):
        keys = torch.arange(1., count + 1).repeat_interleave(2).reshape(1, -1, 1, 1)
        state = {"cache": [(keys, keys.clone())], "sizes": [2] * count, "biases": [0.] * count}
        if rows is not None:
            state["rows"] = rows
        attn = types.SimpleNamespace(_ref_kv_state=state, forward=object())
        dm = types.SimpleNamespace(blocks=[types.SimpleNamespace(self_attn=attn)], patch_temporal=1)
        class Executor:
            class_obj = dm
            calls = 0
            fail_after = None
            tokens_read = 0
            def __call__(self, x, *args, **kwargs):
                self.calls += 1
                if self.calls == self.fail_after:
                    raise InterruptedError("cancelled")
                current = attn._ref_kv_state
                value = 0.
                if current is not None:
                    keys, _ = current["cache"][0]
                    self.tokens_read += keys.shape[1]
                    start = 0
                    for size, bias in zip(current["sizes"], current["biases"]):
                        value += keys[0, start, 0, 0].item() * math.exp(bias)
                        start += size
                prediction = torch.full_like(x, value)
                if current is not None and current.get("rows") is not None:
                    for row in range(x.shape[0]):
                        if row not in current["rows"]:
                            prediction[row] = 0.
                return prediction
        return Executor(), attn, state, torch.zeros(2, 4, 1, 2, 4)

    def test_native_predictions_are_selected_by_mask_without_changing_attention(self):
        executor, attn, state, latent = self.fixture()
        original_forward = attn.forward
        left = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        result = make_wrapper((left, 1. - left))(executor, latent, None, None)
        torch.testing.assert_close(result[..., :2], torch.ones_like(result[..., :2]), atol=0, rtol=0)
        torch.testing.assert_close(result[..., 2:], torch.full_like(result[..., 2:], 2.), atol=0, rtol=0)
        self.assertEqual(executor.calls, 2)
        self.assertIs(attn._ref_kv_state, state)
        self.assertIs(attn.forward, original_forward)

    def test_single_global_or_black_plan_uses_one_forward_and_cfg_rows_remain_reference_free(self):
        for white, expected in ((True, 3.), (False, 0.)):
            executor, attn, state, latent = self.fixture()
            mask = torch.ones(1, 2, 4) if white else torch.zeros(1, 2, 4)
            result = make_wrapper((mask, mask))(executor, latent, None, None)
            torch.testing.assert_close(result, torch.full_like(result, expected), atol=0, rtol=0)
            self.assertEqual(executor.calls, 1)
            self.assertIs(attn._ref_kv_state, state)
        executor, attn, state, latent = self.fixture(rows=[0])
        mask = torch.tensor([[[.5, .5, 0., 0.], [.5, .5, 0., 0.]]])
        result = make_wrapper((mask, mask * 0))(executor, latent, None, None)
        self.assertEqual(result[1].abs().sum().item(), 0.)
        torch.testing.assert_close(result[0, ..., :2], torch.full_like(result[0, ..., :2], .5), atol=0, rtol=0)
        self.assertIs(attn._ref_kv_state, state)

    def test_globals_are_available_in_every_spatial_branch_and_other_refs_have_zero_weight(self):
        executor, attn, state, latent = self.fixture(count=3)
        left = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        result = make_wrapper((left, 1. - left, torch.ones_like(left)))(executor, latent, None, None)
        torch.testing.assert_close(result[..., :2], torch.full_like(result[..., :2], 4.), atol=0, rtol=0)
        torch.testing.assert_close(result[..., 2:], torch.full_like(result[..., 2:], 5.), atol=0, rtol=0)
        self.assertEqual(executor.calls, 2)
        self.assertEqual(executor.tokens_read, 8)
        self.assertIs(attn._ref_kv_state, state)

    def test_excluded_reference_tokens_are_not_read_and_original_cache_is_unchanged(self):
        executor, attn, state, latent = self.fixture(count=3)
        original_keys = state["cache"][0][0]
        before = original_keys.clone()
        left = torch.zeros(1, 2, 4)
        left[..., :2] = 1
        result = make_wrapper((left, 1. - left, left * 0))(executor, latent, None, None)
        torch.testing.assert_close(result[..., :2], torch.ones_like(result[..., :2]), atol=0, rtol=0)
        torch.testing.assert_close(result[..., 2:], torch.full_like(result[..., 2:], 2.), atol=0, rtol=0)
        self.assertEqual(executor.tokens_read, 4)
        self.assertIs(attn._ref_kv_state, state)
        self.assertIs(state["cache"][0][0], original_keys)
        torch.testing.assert_close(original_keys, before, atol=0, rtol=0)

    def test_spectrum_capture_is_suppressed_only_for_mixed_plans_and_always_restored(self):
        left = torch.zeros(1, 2, 4)
        left[..., :2] = 1
        for mixed, reference_free, cancel in (
                (True, False, False), (True, True, False),
                (True, False, True), (False, False, False)):
            with self.subTest(mixed=mixed, reference_free=reference_free, cancel=cancel):
                inner, attn, original, latent = self.fixture()
                if reference_free:
                    attn._ref_kv_state = None
                spectrum = types.SimpleNamespace(captured_feat=None)
                layer = torch.nn.Identity()
                layer._spectrum_state = spectrum
                captures = []
                def capture(module, args):
                    if module._spectrum_state is not None:
                        captures.append(args[0].detach().clone())
                        module._spectrum_state.captured_feat = captures[-1]
                hook = layer.register_forward_pre_hook(capture)
                inner.class_obj.final_layer = layer
                inner.fail_after = 2 if cancel else None
                def execute(x, *args, **kwargs):
                    layer(x)
                    return inner(x, *args, **kwargs)
                execute.class_obj = inner.class_obj
                masks = (left, 1. - left) if mixed else (torch.ones_like(left),) * 2
                if cancel:
                    with self.assertRaises(InterruptedError):
                        make_wrapper(masks)(execute, latent, None, None)
                else:
                    make_wrapper(masks)(execute, latent, None, None)
                self.assertEqual(len(captures), 0 if mixed else 1)
                self.assertIs(layer._spectrum_state, spectrum)
                self.assertIs(attn._ref_kv_state, None if reference_free else original)
                hook.remove()

    def test_cancellation_restores_state_and_full_block_fails_instead_of_guessing_row_ids(self):
        executor, attn, state, latent = self.fixture()
        executor.fail_after = 2
        mask = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        with self.assertRaises(InterruptedError):
            make_wrapper((mask, 1. - mask))(executor, latent, None, None)
        self.assertIs(attn._ref_kv_state, state)
        with self.assertRaisesRegex(ValueError, "cross_attention"):
            make_wrapper((mask, 1. - mask))(executor, latent, None, None,
                transformer_options={"comfycouple_regions_v2": {"anima_region_mode": "full_block"}})
        self.assertIs(attn._ref_kv_state, state)


class NodeTests(unittest.TestCase):
    def test_pose_masks_respect_depth_labels_background_and_stable_ids(self):
        labels = torch.zeros(64, 64, dtype=torch.int32)
        labels[8:56, 8:40] = 1
        labels[16:48, 24:56] = 2
        source = {"version": 1, "width": 64, "height": 64, "labels": labels,
                  "bodies": [{"id": "a", "label": 1}, {"id": "b", "label": 2}, {"id": "hidden", "label": 3}]}
        first, identity = PoseReferenceMask().extract(source, "a")
        second, _ = PoseReferenceMask().extract(source, "b")
        hidden, _ = PoseReferenceMask().extract(source, "hidden")
        self.assertEqual(identity, "a")
        self.assertEqual((first * second).sum().item(), 0)
        self.assertEqual(first[0, 24, 32].item(), 0)
        self.assertEqual(second[0, 24, 32].item(), 1)
        self.assertEqual(hidden.sum().item(), 0)
        source["bodies"].reverse()
        reordered, _ = PoseReferenceMask().extract(source, "a")
        torch.testing.assert_close(reordered, first, atol=0, rtol=0)
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            PoseReferenceMask().extract(source, "removed")
        labels[0, 0] = 99
        with self.assertRaisesRegex(ValueError, "unknown person"):
            PoseReferenceMask().extract(source, "a")

    def test_bundle_limit_validation_and_input_preservation(self):
        image, mask = torch.zeros(1, 16, 16, 3), torch.ones(1, 32, 32)
        before = mask.clone()
        bundle = None
        for strength in (-3., 0., 3.):
            bundle, = RegionalReference().build(image, mask, strength, bundle)
        self.assertEqual([entry.strength for entry in bundle], [-3., 0., 3.])
        with self.assertRaisesRegex(ValueError, "at most three"):
            RegionalReference().build(image, mask, 0, bundle)
        for invalid in (mask * math.nan, mask * 2, mask.expand(2, -1, -1)):
            with self.assertRaises(ValueError):
                RegionalReference().build(image, invalid)
        with self.assertRaises(ValueError):
            RegionalReference().build(image.expand(2, -1, -1, -1), mask)
        torch.testing.assert_close(mask, before, atol=0, rtol=0)

    def test_apply_preserves_upstream_order_strengths_and_source_model(self):
        class Model:
            def __init__(self):
                self.wrappers = {"diffusion_model": {"other": [object()]}}
                self.model_options = {"preserved": {"keep": True}}
            def clone(self):
                result = Model()
                result.wrappers = {kind: {key: value[:] for key, value in groups.items()}
                                   for kind, groups in self.wrappers.items()}
                result.model_options = dict(self.model_options)
                return result
            def add_wrapper_with_key(self, kind, key, function):
                self.wrappers.setdefault(kind, {}).setdefault(key, []).append(function)
        calls = []
        adapter = types.SimpleNamespace(lora={})
        def native(executor, *args, **kwargs):
            if adapter is None:
                raise AssertionError("the native wrapper must capture its adapter")
            return executor(*args, **kwargs)
        class SnapRef:
            def apply(self, **kwargs):
                calls.append(kwargs)
                result = kwargs["model"].clone()
                result.add_wrapper_with_key("diffusion_model", "snapref", native)
                return (result,)
        core = types.ModuleType("regional_prediction_snapref_fixture")
        core.WRAPPER_KEY = "snapref"
        core._concat_kv = lambda records: records[0]
        SnapRef.__module__ = core.__name__
        registry = types.ModuleType("nodes")
        registry.NODE_CLASS_MAPPINGS = {"SnapRef": SnapRef}
        comfy = types.ModuleType("comfy")
        extension = types.ModuleType("comfy.patcher_extension")
        extension.WrappersMP = types.SimpleNamespace(DIFFUSION_MODEL="diffusion_model", OUTER_SAMPLE="outer_sample")
        model = Model()
        image, mask = torch.zeros(1, 16, 16, 3), torch.ones(1, 32, 32)
        bundle = None
        for strength in (-3., 0., 3.):
            bundle, = RegionalReference().build(image, mask, strength, bundle)
        with patch.dict(sys.modules, {"nodes": registry, "comfy": comfy,
                                     "comfy.patcher_extension": extension, core.__name__: core}):
            patched, = RegionalSnapRef().apply(model, object(), object(), bundle, "adapter", fidelity=.4)
            for index, strength in enumerate((-3., 0., 3.), 1):
                self.assertAlmostEqual(calls[0]["strength"] + math.log(calls[0][f"weight_{index}"]), strength)
            self.assertFalse(calls[0]["ref_guidance_on"])
            self.assertEqual(calls[0]["fidelity"], .4)
            self.assertEqual(list(patched.wrappers["diffusion_model"]), ["snapref", WRAPPER_KEY, "other"])
            self.assertEqual(list(model.wrappers["diffusion_model"]), ["other"])
            self.assertEqual(patched.model_options["preserved"], {"keep": True})
            self.assertNotIn("spectrum_cache_vetoes", model.model_options)
            self.assertTrue(patched.model_options["spectrum_cache_vetoes"][0](
                input_x=torch.zeros(1, 1, 32, 32)))
            with self.assertRaisesRegex(ValueError, "do not stack"):
                RegionalSnapRef().apply(patched, object(), object(), bundle, "adapter")
            spatial_mask = mask.clone()
            spatial_mask[..., 16:] = 0
            spatial, = RegionalReference().build(image, spatial_mask)
            previous_veto = lambda **kwargs: False
            for existing in (None, previous_veto, [previous_veto]):
                with self.subTest(existing=type(existing).__name__):
                    source = Model()
                    source.model_options["spectrum_cache_vetoes"] = existing
                    guarded, = RegionalSnapRef().apply(source, object(), object(), spatial, "adapter")
                    vetoes = guarded.model_options["spectrum_cache_vetoes"]
                    self.assertEqual(len(vetoes), 1 if existing is None else 2)
                    if existing is not None:
                        self.assertIs(vetoes[0], previous_veto)
                    self.assertFalse(vetoes[-1](input_x=torch.zeros(1, 1, 32, 32)))
                    self.assertIs(source.model_options["spectrum_cache_vetoes"], existing)
            self.assertNotIn("outer_sample", patched.wrappers)
            from regional_prediction_test import forecast_session
            session = types.SimpleNamespace(sample=object(), run=object())
            with patch.object(forecast_session, "create_session", return_value=session):
                accelerated, = RegionalSnapRef().apply(
                    model, object(), object(), bundle, "adapter", experimental_forecast=True)
            self.assertIs(accelerated.wrappers["outer_sample"][WRAPPER_KEY][0], session.sample)
            self.assertNotIn("outer_sample", model.wrappers)
            with self.assertRaisesRegex(ValueError, "boolean"):
                RegionalSnapRef().apply(
                    model, object(), object(), bundle, "adapter", experimental_forecast="true")


if __name__ == "__main__":
    unittest.main()
