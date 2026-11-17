"""SCOPE must bound GPU convolution work and reserve activation memory."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

import torch


SOURCE = Path(__file__).resolve().parents[2] / "src/custom_nodes/ComfyUI-LAKIS-Fast-Refiner/__init__.py"


class ScopeUpscaleMemoryTests(unittest.TestCase):
    def setUp(self):
        self.comfy = types.ModuleType("comfy")
        self.comfy.__path__ = []
        self.sample = types.ModuleType("comfy.sample")
        self.samplers = types.ModuleType("comfy.samplers")
        self.samplers.CFGGuider = object
        self.mp = types.ModuleType("comfy.model_patcher")
        self.mp.ModelPatcher = Mock()
        self.mm = types.ModuleType("comfy.model_management")
        self.mm.get_torch_device = Mock(return_value=torch.device("cpu"))
        self.mm.intermediate_device = Mock(return_value=torch.device("cpu"))
        self.mm.intermediate_dtype = Mock(return_value=torch.float32)
        self.mm.load_models_gpu = Mock()
        self.mm.soft_empty_cache = Mock()
        self.mm.raise_non_oom = Mock(side_effect=self.raise_non_oom)
        self.utils = types.ModuleType("comfy.utils")
        self.utils.get_tiled_scale_steps = Mock(return_value=1)
        self.utils.ProgressBar = Mock()
        self.utils.tiled_scale = Mock(return_value=torch.ones((1, 3, 16, 16)))
        modules = {"comfy": self.comfy, "comfy.sample": self.sample,
                   "comfy.samplers": self.samplers, "comfy.model_management": self.mm,
                   "comfy.utils": self.utils, "comfy.model_patcher": self.mp}
        for name, module in modules.items():
            if name.startswith("comfy."):
                setattr(self.comfy, name.split(".")[1], module)
        self.modules_patch = patch.dict(sys.modules, modules)
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        spec = importlib.util.spec_from_file_location("scope_memory_test", SOURCE)
        self.scope = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.scope)
        self.model = Mock()
        self.model.scale = 4
        self.model.patcher = types.SimpleNamespace(load_device=torch.device("cpu"))
        self.image = torch.zeros((1, 16, 16, 3), dtype=torch.float16)

    @staticmethod
    def raise_non_oom(error):
        if not isinstance(error, torch.OutOfMemoryError):
            raise error

    def test_static_loader_preserves_the_fresh_standard_descriptor(self):
        fresh = types.SimpleNamespace(
            model=object(), scale=4, size_requirements=object(),
            patcher=types.SimpleNamespace(
                load_device=torch.device("cuda"), offload_device=torch.device("cpu"),
                fast_disk=True))
        standard = types.ModuleType("comfy_extras.nodes_upscale_model")
        standard.UpscaleModelLoader = types.SimpleNamespace(
            execute=Mock(return_value=types.SimpleNamespace(result=(fresh,))))
        with patch.dict(sys.modules, {"comfy_extras.nodes_upscale_model": standard}):
            result, = self.scope.LAKISScopeUpscaleModelLoader().load_model("same-checkpoint.pth")
        self.assertIs(result, fresh)
        self.assertEqual(result.scale, 4)
        self.mp.ModelPatcher.assert_called_once_with(
            fresh.model, torch.device("cuda"), torch.device("cpu"), fast_disk=True)
        self.assertIs(result.patcher, self.mp.ModelPatcher.return_value)
        standard.UpscaleModelLoader.execute.assert_called_once_with("same-checkpoint.pth")

    def test_reserves_float32_activations_before_model_transfer(self):
        order = []
        self.mm.soft_empty_cache.side_effect = lambda **kwargs: order.append("cache_release")
        self.mm.load_models_gpu.side_effect = lambda *args, **kwargs: order.append("managed_load")
        def infer(*args, **kwargs):
            order.append("inference")
            return torch.ones((1, 3, 16, 16))
        self.utils.tiled_scale.side_effect = infer
        result = self.scope._upscale_learned(self.model, self.image)
        reserved = self.mm.load_models_gpu.call_args.kwargs["memory_required"]
        self.assertGreaterEqual(reserved, 4.5 * 1024 ** 3)
        self.assertEqual(["cache_release", "managed_load", "inference"], order)
        self.mm.soft_empty_cache.assert_called_once_with(force=True)
        self.mm.load_models_gpu.assert_called_once_with(
            [self.model.patcher], memory_required=reserved, force_full_load=True)
        self.assertEqual(512, self.utils.tiled_scale.call_args.kwargs["tile_x"])
        self.assertEqual((1, 16, 16, 3), tuple(result.shape))
        self.model.to.assert_not_called()

    def test_cache_release_preserves_input_and_the_native_tiled_result(self):
        cached = {"reference_kv": torch.ones(8)}
        self.mm.soft_empty_cache.side_effect = lambda **kwargs: cached.clear()
        source = self.image.clone()
        tiled = torch.linspace(-0.2, 1.2, 16 * 16 * 3).reshape(1, 3, 16, 16)
        self.utils.tiled_scale.return_value = tiled
        result = self.scope._upscale_learned(self.model, self.image)
        self.assertFalse(cached)
        torch.testing.assert_close(self.image, source, rtol=0, atol=0)
        torch.testing.assert_close(
            result, tiled.clamp(0, 1).movedim(-3, -1), rtol=0, atol=0)
        self.assertEqual(512, self.utils.tiled_scale.call_args.kwargs["tile_x"])
        self.assertEqual(32, self.utils.tiled_scale.call_args.kwargs["overlap"])

    def test_contiguous_tile_option_preserves_values_and_default_layout(self):
        image = torch.arange(16 * 16 * 3).reshape(1, 16, 16, 3).float() / (16 * 16 * 3)
        self.utils.tiled_scale.side_effect = lambda value, function, **kwargs: function(value)
        for enabled in (False, True):
            received = []

            def infer(value):
                received.append(value)
                return value

            self.model.side_effect = infer
            self.scope._upscale_learned(self.model, image, contiguous_tiles=enabled)
            self.assertTrue(torch.equal(received[0], image.movedim(-1, -3)))
            self.assertEqual(received[0].is_contiguous(), enabled)
            self.assertEqual(received[0].dtype, torch.float32)
            self.assertEqual(self.utils.tiled_scale.call_args.kwargs["tile_x"], 512)
            self.assertEqual(self.utils.tiled_scale.call_args.kwargs["overlap"], 32)

    def test_large_requested_tile_cannot_bypass_safe_limit(self):
        self.scope._upscale_learned(self.model, self.image, preferred_tile=768)
        self.assertLessEqual(self.utils.tiled_scale.call_args.kwargs["tile_x"], 512)

    def test_low_step_low_denoise_shortcut_applies_to_both_quality_modes(self):
        generator = torch.Generator().manual_seed(7)
        texture = torch.rand((1, 24, 24, 3), generator=generator) * 0.4 + 0.3
        outputs = []
        for quality_mode in (False, True):
            with self.subTest(quality_mode=quality_mode):
                vae = Mock()
                with patch.object(self.scope, "_upscale_learned", return_value=texture):
                    result = self.scope.LAKISScope().refine(
                        self.image, Mock(), [], [], vae, self.model, 1.5, 1, 2, 5.0,
                        "euler", "normal", 0.08, 768, 192, 2, quality_mode,
                    )[0]
                vae.encode.assert_not_called()
                self.assertEqual(tuple(result.shape), (1, 64, 64, 3))
                outputs.append(result)
        self.assertFalse(torch.equal(outputs[0], outputs[1]))

    def test_higher_step_or_denoise_uses_diffusion_refinement(self):
        generator = torch.Generator().manual_seed(7)
        texture = torch.rand((1, 24, 24, 3), generator=generator) * 0.4 + 0.3
        cases = ((3, 0.08), (2, 0.081))
        for steps, denoise in cases:
            with self.subTest(steps=steps, denoise=denoise):
                source = torch.zeros((1, 4, 3, 3))
                vae = Mock()
                vae.encode.return_value = source
                vae.decode.return_value = texture
                self.sample.prepare_noise = Mock(return_value=source)
                self.samplers.sampler_object = Mock(return_value=object())
                self.samplers.KSampler = Mock(return_value=types.SimpleNamespace(
                    sampler=object(), sigmas=object(),
                ))
                guider = Mock()
                guider.sample.return_value = source
                with (
                    patch.object(self.scope, "_upscale_learned", return_value=texture),
                    patch.object(self.scope, "_MultiDiffusionGuider", return_value=guider),
                ):
                    self.scope.LAKISScope().refine(
                        self.image, Mock(), [], [], vae, self.model, 1.5, 1, steps, 5.0,
                        "euler", "normal", denoise, 768, 192, 2, False,
                    )
                vae.encode.assert_called_once()
                self.samplers.KSampler.assert_called_once()
                self.assertEqual(self.samplers.KSampler.call_args.args[1], steps)
                guider.sample.assert_called_once()

    def test_oom_reduces_work_without_desynchronizing_managed_residency(self):
        self.utils.tiled_scale.side_effect = [torch.OutOfMemoryError("oom"),
                                             torch.OutOfMemoryError("oom"),
                                             torch.ones((1, 3, 16, 16))]
        self.scope._upscale_learned(self.model, self.image)
        self.assertEqual([512, 256, 128],
                         [call.kwargs["tile_x"] for call in self.utils.tiled_scale.call_args_list])
        self.mm.load_models_gpu.assert_called_once()
        self.model.to.assert_not_called()

    def test_non_oom_failure_is_not_retried(self):
        self.utils.tiled_scale.side_effect = RuntimeError("CUDA device lost")
        with self.assertRaisesRegex(RuntimeError, "CUDA device lost"):
            self.scope._upscale_learned(self.model, self.image)
        self.assertEqual(1, self.utils.tiled_scale.call_count)
        self.mm.load_models_gpu.assert_called_once()
        self.model.to.assert_not_called()

    def test_managed_load_failure_does_not_start_inference_or_direct_transfer(self):
        self.mm.load_models_gpu.side_effect = RuntimeError("transfer failed")
        with self.assertRaisesRegex(RuntimeError, "transfer failed"):
            self.scope._upscale_learned(self.model, self.image)
        self.model.to.assert_not_called()
        self.utils.tiled_scale.assert_not_called()


if __name__ == "__main__":
    unittest.main()
