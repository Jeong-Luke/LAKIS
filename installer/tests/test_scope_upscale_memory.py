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
        self.mm = types.ModuleType("comfy.model_management")
        self.mm.get_torch_device = Mock(return_value=torch.device("cpu"))
        self.mm.intermediate_device = Mock(return_value=torch.device("cpu"))
        self.mm.intermediate_dtype = Mock(return_value=torch.float32)
        self.mm.module_size = Mock(return_value=1024)
        self.mm.free_memory = Mock()
        self.mm.raise_non_oom = Mock(side_effect=self.raise_non_oom)
        self.utils = types.ModuleType("comfy.utils")
        self.utils.get_tiled_scale_steps = Mock(return_value=1)
        self.utils.ProgressBar = Mock()
        self.utils.tiled_scale = Mock(return_value=torch.ones((1, 3, 16, 16)))
        modules = {"comfy": self.comfy, "comfy.sample": self.sample,
                   "comfy.samplers": self.samplers, "comfy.model_management": self.mm,
                   "comfy.utils": self.utils}
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
        self.image = torch.zeros((1, 16, 16, 3), dtype=torch.float16)

    @staticmethod
    def raise_non_oom(error):
        if not isinstance(error, torch.OutOfMemoryError):
            raise error

    def test_reserves_float32_activations_before_model_transfer(self):
        order = []
        self.mm.free_memory.side_effect = lambda *args: order.append("reserve")
        self.model.to.side_effect = lambda device: order.append(str(device))
        result = self.scope._upscale_learned(self.model, self.image)
        reserved = self.mm.free_memory.call_args.args[0]
        self.assertGreaterEqual(reserved, 4.5 * 1024 ** 3)
        self.assertEqual("reserve", order[0])
        self.assertEqual(512, self.utils.tiled_scale.call_args.kwargs["tile_x"])
        self.assertEqual((1, 16, 16, 3), tuple(result.shape))
        self.assertEqual("cpu", self.model.to.call_args.args[0])

    def test_large_requested_tile_cannot_bypass_safe_limit(self):
        self.scope._upscale_learned(self.model, self.image, preferred_tile=768)
        self.assertLessEqual(self.utils.tiled_scale.call_args.kwargs["tile_x"], 512)

    def test_oom_reduces_work_and_keeps_model_cleanup(self):
        self.utils.tiled_scale.side_effect = [torch.OutOfMemoryError("oom"),
                                             torch.OutOfMemoryError("oom"),
                                             torch.ones((1, 3, 16, 16))]
        self.scope._upscale_learned(self.model, self.image)
        self.assertEqual([512, 256, 128],
                         [call.kwargs["tile_x"] for call in self.utils.tiled_scale.call_args_list])
        self.assertEqual("cpu", self.model.to.call_args.args[0])

    def test_non_oom_failure_is_not_retried(self):
        self.utils.tiled_scale.side_effect = RuntimeError("CUDA device lost")
        with self.assertRaisesRegex(RuntimeError, "CUDA device lost"):
            self.scope._upscale_learned(self.model, self.image)
        self.assertEqual(1, self.utils.tiled_scale.call_count)
        self.assertEqual("cpu", self.model.to.call_args.args[0])

    def test_transfer_failure_still_returns_model_to_cpu(self):
        self.model.to.side_effect = [RuntimeError("transfer failed"), None]
        with self.assertRaisesRegex(RuntimeError, "transfer failed"):
            self.scope._upscale_learned(self.model, self.image)
        self.assertEqual("cpu", self.model.to.call_args.args[0])
        self.utils.tiled_scale.assert_not_called()


if __name__ == "__main__":
    unittest.main()
