"""Exercise installed ComfyUI/SnapRef forwards with a tiny untrained model.

LAKIS_COMFY_ROOT points to an existing ComfyUI installation. No checkpoint,
adapter weight, application process, output image or user state is used.
This verifies runtime compatibility, not generated-image quality.
"""
import __future__
import ast
import importlib.util
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import torch


class InstalledComfyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["LAKIS_COMFY_ROOT"])
        sys.path.insert(0, str(root))
        from comfy.ldm.anima.model import Anima
        from comfy.ldm.cosmos.predict2 import MiniTrainDIT
        from comfy.ops import disable_weight_init
        cls.Anima, cls.MiniTrainDIT = Anima, MiniTrainDIT
        cls.operations = disable_weight_init
        source = root / "custom_nodes/snapref/__init__.py"
        spec = importlib.util.spec_from_file_location(
            "regional_reference_installed_snapref", source,
            submodule_search_locations=[str(source.parent)])
        cls.snapref = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.snapref
        spec.loader.exec_module(cls.snapref)
        package = Path(__file__).resolve().parents[2] / "src/custom_nodes/ComfyUI-LAKIS-Regional-Reference"
        spec = importlib.util.spec_from_file_location(
            "regional_reference_comfy_test", package / "__init__.py",
            submodule_search_locations=[str(package)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        from regional_reference_comfy_test.runtime import cfg_safe_wrapper, make_wrapper
        cls.make_wrapper = staticmethod(make_wrapper)
        cls.cfg_safe_wrapper = staticmethod(cfg_safe_wrapper)

    def test_installed_spectrum_never_forecasts_a_multi_prediction_regional_plan(self):
        source = (Path(os.environ["LAKIS_COMFY_ROOT"]) /
                  "custom_nodes/comfyui-spectrum-ksampler/spectrum.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {"_iter_cache_vetoes", "_passes_cache_vetoes", "_can_use_cached_prediction"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in functions}, names)
        namespace = {"torch": torch, "logger": logging.getLogger(__name__)}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec",
                     flags=__future__.annotations.compiler_flag), namespace)
        can_forecast = namespace["_can_use_cached_prediction"]
        state = SimpleNamespace(mode="cached", compat_policy="legacy", has_forecasters=lambda keys: True)
        latent, timestep = torch.zeros(1, 1, 1, 4), torch.ones(1)
        self.assertTrue(can_forecast(state, [0], latent, timestep, {}, None, {}, {}, True))
        left = torch.tensor([[[1., 1., 0., 0.]]])
        for masks, expected in (
                ((left, 1. - left), False), ((left,), False),
                ((torch.ones_like(left),), True), ((torch.zeros_like(left),), True)):
            wrapper = self.make_wrapper(masks)
            options = {"spectrum_cache_vetoes": [wrapper.spectrum_cache_veto]}
            with self.subTest(expected=expected):
                self.assertEqual(can_forecast(
                    state, [0], latent, timestep, {}, None, options, {}, True), expected)
                if not expected:
                    state.compat_policy = "safe"
                    self.assertFalse(can_forecast(
                        state, [0], latent, timestep, {}, None, options, {}, True))
                    state.compat_policy = "legacy"

    def test_native_spectrum_capture_and_history_are_absent_only_for_mixed_plans(self):
        root = Path(os.environ["LAKIS_COMFY_ROOT"]) / "custom_nodes/comfyui-spectrum-ksampler"
        forecast_spec = importlib.util.spec_from_file_location(
            "regional_native_spectrum_forecast", root / "_vendor/networks/spectrum_forecast.py")
        forecast = importlib.util.module_from_spec(forecast_spec)
        forecast_spec.loader.exec_module(forecast)
        tree = ast.parse((root / "spectrum.py").read_text(encoding="utf-8"))
        names = {"_capture_pre_hook", "_update_forecasters_from_feature"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in functions}, names)
        namespace = {"torch": torch, "logger": logging.getLogger(__name__),
                     "SpectrumPredictor": forecast.SpectrumPredictor}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(root / "spectrum.py"), "exec",
                     flags=__future__.annotations.compiler_flag), namespace)
        left = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        for mixed in (False, True):
            for reference_free in (False, True):
                with self.subTest(mixed=mixed, reference_free=reference_free):
                    state = SimpleNamespace(
                        active=True, captured_feat=None, forecasters={}, m_param=3, lam=.1,
                        w=.3, num_steps=30, history_size=100, step_idx=0, verbose=False,
                        record_context=lambda *args: None)
                    layer = torch.nn.Identity()
                    layer._spectrum_state = state
                    layer.register_forward_pre_hook(namespace["_capture_pre_hook"])
                    kv = torch.zeros(1, 2, 1, 1)
                    reference = {"cache": [(kv, kv)], "sizes": [1, 1], "biases": [0., 0.]}
                    attn = SimpleNamespace(_ref_kv_state=None if reference_free else reference)
                    dm = SimpleNamespace(blocks=[SimpleNamespace(self_attn=attn)],
                                         patch_temporal=1, final_layer=layer)
                    def execute(xs, *args, **kwargs):
                        return layer(xs)
                    execute.class_obj = dm
                    masks = (left, 1. - left) if mixed else (torch.ones_like(left),) * 2
                    wrapper = self.make_wrapper(masks)
                    latent = torch.zeros(2, 1, 1, 2, 4)
                    for step in range(12):
                        state.step_idx, state.captured_feat = step, None
                        wrapper(execute, latent, torch.ones(2), None)
                        self.assertIs(layer._spectrum_state, state)
                        namespace["_update_forecasters_from_feature"](
                            state, state.captured_feat, latent, [int(reference_free)], True, "test")
                    if mixed:
                        self.assertIsNone(state.captured_feat)
                        self.assertEqual(state.forecasters, {})
                    else:
                        predictor = state.forecasters[int(reference_free)]
                        self.assertEqual(predictor.cheb.t_buf.numel(), 12)

    def cached_native(self, latent, uncond_bias=None):
        attn = SimpleNamespace(_ref_kv_state=None)
        dm = SimpleNamespace(blocks=[SimpleNamespace(self_attn=attn)], patch_temporal=1)
        key = ("reference", "model", tuple(latent.shape[-2:]), latent.dtype, latent.device)
        adapter = SimpleNamespace(install=lambda dm: None, cache={key: ([object()], [1])})
        native = self.snapref._make_wrapper(
            adapter, [None], (None, {}), "char", False, uncond_bias=uncond_bias)
        return native, dm, attn

    def test_native_mixed_cfg_preserves_regional_prompts_rows_and_caller_metadata(self):
        with patch.object(self.snapref, "_ref_digest", return_value="reference"), \
                patch.object(self.snapref, "_model_token", return_value="model"):
            for batch_size in (1, 2):
                for flags in ([0, 1], [1, 0]):
                    for spatial in (False, True):
                        with self.subTest(batch_size=batch_size, flags=flags, spatial=spatial):
                            latent = torch.zeros(batch_size * 2, 4, 1, 2, 4)
                            native, dm, attn = self.cached_native(latent)
                            mask = torch.ones(1, 2, 4)
                            if spatial:
                                mask[..., 2:] = 0
                            regional = self.make_wrapper((mask,))
                            sigmas = torch.ones(batch_size)
                            options = {"cond_or_uncond": flags, "uuids": [f"id-{flag}" for flag in flags],
                                       "sigmas": sigmas}
                            calls = []

                            def target(xs, ts, ctx, fps=None, padding_mask=None, **kwargs):
                                local = kwargs["transformer_options"]
                                self.assertEqual(len(local["cond_or_uncond"]), 1)
                                flag = local["cond_or_uncond"][0]
                                self.assertEqual(local["uuids"], [f"id-{flag}"])
                                self.assertIs(local["sigmas"], sigmas)
                                self.assertEqual(xs.shape[0], batch_size)
                                calls.append(flag)
                                # Regional text is 7; negative text is -3.
                                # The reference contributes another 4 only to
                                # the selected positive prediction.
                                value = -3. if flag else 7. + (4. if attn._ref_kv_state else 0.)
                                return torch.full_like(xs, value)
                            target.class_obj = dm

                            def downstream(*args, **kwargs):
                                return regional(target, *args, **kwargs)
                            downstream.class_obj = dm
                            result = self.cfg_safe_wrapper(native)(
                                downstream, latent, torch.ones(batch_size * 2),
                                torch.zeros(batch_size * 2, 1, 32), transformer_options=options)
                            for index, flag in enumerate(flags):
                                expected = torch.full_like(result[index * batch_size:(index + 1) * batch_size], -3.)
                                if flag == 0:
                                    expected = 7. + 4. * mask[None, :, None].expand_as(expected)
                                torch.testing.assert_close(result[index * batch_size:(index + 1) * batch_size],
                                                           expected, atol=0, rtol=0)
                            self.assertEqual(options["cond_or_uncond"], flags)
                            self.assertEqual(options["uuids"], [f"id-{flag}" for flag in flags])
                            self.assertEqual(calls.count(1), 1)
                            self.assertIsNone(attn._ref_kv_state)

    def test_native_full_cfg_paths_keep_original_metadata(self):
        with patch.object(self.snapref, "_ref_digest", return_value="reference"), \
                patch.object(self.snapref, "_model_token", return_value="model"):
            for ambient in (False, True):
                latent = torch.zeros(2, 4, 1, 2, 4)
                native, dm, attn = self.cached_native(latent, None if ambient else -.7)
                if ambient:
                    dm.t_embedding_norm = SimpleNamespace(_anima_mod_delta=torch.ones(1))
                options = {"cond_or_uncond": [0, 1], "uuids": ["positive", "negative"]}
                calls = []

                def target(xs, ts, ctx, fps=None, padding_mask=None, **kwargs):
                    calls.append(xs.shape[0])
                    self.assertIs(kwargs["transformer_options"], options)
                    return xs
                target.class_obj = dm
                result = self.cfg_safe_wrapper(native)(
                    target, latent, torch.ones(2), torch.zeros(2, 1, 32), transformer_options=options)
                torch.testing.assert_close(result, latent, atol=0, rtol=0)
                self.assertEqual(calls, [2])
                self.assertIsNone(attn._ref_kv_state)

    def test_native_cfg_cancellation_restores_upstream_state(self):
        with patch.object(self.snapref, "_ref_digest", return_value="reference"), \
                patch.object(self.snapref, "_model_token", return_value="model"):
            latent = torch.zeros(2, 4, 1, 2, 4)
            native, dm, attn = self.cached_native(latent)
            options = {"cond_or_uncond": [0, 1], "uuids": ["positive", "negative"]}

            def target(xs, ts, ctx, fps=None, padding_mask=None, **kwargs):
                if kwargs["transformer_options"]["cond_or_uncond"] == [1]:
                    raise InterruptedError("cancelled")
                return xs
            target.class_obj = dm
            with self.assertRaises(InterruptedError):
                self.cfg_safe_wrapper(native)(
                    target, latent, torch.ones(2), torch.zeros(2, 1, 32), transformer_options=options)
            self.assertIsNone(attn._ref_kv_state)
            self.assertEqual(self.snapref._STATE, {"adapter": None, "stream": None})
            self.assertEqual(options["cond_or_uncond"], [0, 1])

    def test_native_cfg_rejects_unsliced_control_instead_of_forwarding_it(self):
        with patch.object(self.snapref, "_ref_digest", return_value="reference"), \
                patch.object(self.snapref, "_model_token", return_value="model"):
            latent = torch.zeros(2, 4, 1, 2, 4)
            native, dm, attn = self.cached_native(latent)

            def target(*args, **kwargs):
                self.fail("Misaligned ControlNet data reached the target")
            target.class_obj = dm
            with self.assertRaisesRegex(ValueError, "ControlNet"):
                self.cfg_safe_wrapper(native)(
                    target, latent, torch.ones(2), torch.zeros(2, 1, 32), control={"input": [latent]},
                    transformer_options={"cond_or_uncond": [0, 1]})
            self.assertIsNone(attn._ref_kv_state)
            self.assertEqual(self.snapref._STATE, {"adapter": None, "stream": None})

    @torch.no_grad()
    def test_actual_attention_hooks_padding_stages_cfg_and_restoration(self):
        torch.manual_seed(892)
        # Use the actual Anima forward and inherited diffusion blocks, but omit
        # the large LLM adapter: text IDs/LLM adaptation are not exercised here.
        dm = self.Anima.__new__(self.Anima)
        self.MiniTrainDIT.__init__(
            dm, max_img_h=32, max_img_w=32, max_frames=1,
            in_channels=4, out_channels=4, patch_spatial=2, patch_temporal=1,
            model_channels=96, num_blocks=2, num_heads=2,
            crossattn_emb_channels=32, pos_emb_cls="rope3d",
            dtype=torch.float32, device="cpu", operations=self.operations)
        # Comfy operators deliberately skip initialization when loading real
        # checkpoints. Initialize this weight-free fixture explicitly.
        for name, parameter in dm.named_parameters():
            if parameter.ndim > 1:
                torch.nn.init.normal_(parameter, mean=0., std=.02)
            elif name.endswith(".weight"):
                parameter.fill_(1.)
            else:
                parameter.zero_()
        dm.eval()
        self.assertLess(sum(parameter.numel() for parameter in dm.parameters()), 1_000_000)
        # Install the real SnapRef attention code without loading adapter
        # weights. Empty LoRAs isolate reference K/V and wrapper behavior.
        adapter = self.snapref._Adapter.__new__(self.snapref._Adapter)
        adapter.block_indices = {0, 1}
        adapter.lora = {}
        adapter.hooked = weakref.WeakSet()
        adapter.install(dm)
        originals = [block.self_attn.forward for block in dm.blocks]
        record = [None, None]
        self.snapref._set_attn_state(dm, {"record": record})
        dm(torch.randn(1, 4, 1, 4, 4), torch.zeros(1), torch.randn(1, 3, 32))
        self.assertTrue(all(pair[0].shape == (1, 4, 2, 48) for pair in record))
        state = {"cache": record, "sizes": [4], "biases": [.6]}
        for height, width in ((4, 6), (5, 7), (8, 12)):
            with self.subTest(latent=(height, width)):
                latent = torch.randn(2, 4, 1, height, width)
                times, context = torch.ones(2), torch.randn(2, 3, 32)
                self.snapref._set_attn_state(dm, None)
                plain = dm(latent, times, context)
                self.snapref._set_attn_state(dm, state)
                global_result = dm(latent, times, context)

                def run(mask):
                    options = {"wrappers": {"diffusion_model": {
                        "regional": [self.make_wrapper((mask,))]}}}
                    result = dm(latent, times, context, transformer_options=options)
                    self.assertEqual(result.shape, latent.shape)
                    self.assertTrue(torch.isfinite(result).all())
                    for block, original in zip(dm.blocks, originals):
                        self.assertIs(block.self_attn.forward, original)
                        self.assertFalse(block.self_attn._forward_pre_hooks)
                    return result

                white = torch.ones(1, 64, 96)
                torch.testing.assert_close(run(white), global_result, atol=2e-5, rtol=2e-5)
                torch.testing.assert_close(run(white * 0), plain, atol=2e-5, rtol=2e-5)
                left = white.clone()
                left[..., 48:] = 0
                self.assertFalse(torch.allclose(run(left), global_result))
                self.snapref._set_attn_state(dm, {**state, "rows": [0]})
                selected = run(left)
                torch.testing.assert_close(selected[1], plain[1], atol=2e-5, rtol=2e-5)
                self.snapref._set_attn_state(dm, state)
        self.snapref._set_attn_state(dm, None)

    @torch.inference_mode()
    def test_pruned_references_match_native_exclusion_through_actual_anima_blocks(self):
        torch.manual_seed(167)
        dm = self.Anima.__new__(self.Anima)
        self.MiniTrainDIT.__init__(
            dm, max_img_h=32, max_img_w=32, max_frames=1,
            in_channels=4, out_channels=4, patch_spatial=2, patch_temporal=1,
            model_channels=96, num_blocks=2, num_heads=2,
            crossattn_emb_channels=32, pos_emb_cls="rope3d",
            dtype=torch.float32, device="cpu", operations=self.operations)
        for name, parameter in dm.named_parameters():
            if parameter.ndim > 1:
                torch.nn.init.normal_(parameter, mean=0., std=.02)
            elif name.endswith(".weight"):
                parameter.fill_(1.)
            else:
                parameter.zero_()
        dm.eval()
        adapter = self.snapref._Adapter.__new__(self.snapref._Adapter)
        adapter.block_indices, adapter.lora, adapter.hooked = {0, 1}, {}, weakref.WeakSet()
        adapter.install(dm)
        records = []
        for _ in range(3):
            record = [None] * 2
            self.snapref._set_attn_state(dm, {"record": record})
            dm(torch.randn(1, 4, 1, 4, 4), torch.zeros(1), torch.randn(1, 3, 32))
            records.append(record)
        cache = self.snapref._concat_kv(records)
        left = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        masks = (left, 1. - left, torch.ones_like(left))
        from regional_reference_comfy_test.masking import mixing_plan
        for height, width in ((4, 6), (5, 7)):
            for rows in (None, [0]):
                with self.subTest(size=(height, width), rows=rows):
                    latent, times, text = torch.randn(2, 4, 1, height, width), torch.ones(2), torch.randn(2, 3, 32)
                    state = {"cache": cache, "sizes": [4] * 3, "biases": [-.7, 0., .4]}
                    if rows is not None:
                        state.update(rows=rows, row_biases=[-.2])
                    expected = torch.zeros_like(latent)
                    for keep, weight in mixing_plan(masks, height, width, "cpu"):
                        self.snapref._set_attn_state(dm, {
                            **state, "biases": [b if i in keep else -float("inf")
                                               for i, b in enumerate(state["biases"])]})
                        expected += dm(latent, times, text).float() * weight
                    self.snapref._set_attn_state(dm, state)
                    options = {"wrappers": {"diffusion_model": {
                        "regional": [self.make_wrapper(masks)]}}}
                    actual = dm(latent, times, text, transformer_options=options)
                    torch.testing.assert_close(actual, expected, atol=2e-5, rtol=2e-5)
                    self.assertTrue(all(block.self_attn._ref_kv_state is state for block in dm.blocks))
        self.snapref._set_attn_state(dm, None)


if __name__ == "__main__":
    unittest.main()
