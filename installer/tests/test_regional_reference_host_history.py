"""CPU-backed history tests for chunked GPU Spectrum prediction.

Uses the installed Spectrum predictor with small deterministic tensors only;
no checkpoints, ComfyUI server, or generated images are involved.
"""
import importlib
import importlib.util
import math
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

import torch
from torch import nn

from installer.tests.test_regional_reference_predictions import package


ForecastSession = importlib.import_module(
    package.__name__ + ".forecast_session"
).ForecastSession
HostHistoryPredictor = importlib.import_module(
    package.__name__ + ".host_history"
).HostHistoryPredictor


class _ForecastDM:
    def __init__(self):
        self.patch_temporal = 1
        self.final_layer = nn.Identity()


class _ForecastExecutor:
    def __init__(self, device):
        self.class_obj = _ForecastDM()
        self.device = torch.device(device)

    def __call__(self, x, _timesteps, _context, *_args, **_kwargs):
        feature = x.movedim(1, -1)
        return self.class_obj.final_layer(feature).movedim(-1, 1)


class RegionalReferenceHostHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["LAKIS_COMFY_ROOT"])
        source = (root / "custom_nodes/comfyui-spectrum-ksampler/"
                  "_vendor/networks/spectrum_forecast.py")
        spec = importlib.util.spec_from_file_location(
            "regional_installed_spectrum_forecast_host_history", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.spectrum = module

    @staticmethod
    def _feature(step, shape):
        index = torch.arange(math.prod(shape), dtype=torch.float32)
        value = (
            0.5 * torch.sin(index * 0.17 + step * 0.31)
            + 0.02 * step
            + 0.1 * torch.cos(index * 0.071 - step * 0.09)
        )
        return value.reshape(shape)

    def _new_spectrum(self, device, shape, settings):
        return self.spectrum.SpectrumPredictor(
            device=torch.device(device), feature_shape=shape, **settings)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is not available")
    def test_chunked_predictions_match_full_gpu_with_cpu_sliding_history(self):
        device = torch.device("cuda", torch.cuda.current_device())
        shape = (2, 3, 4, 5)
        feature_count = math.prod(shape)
        chunk_features = 17
        settings = {
            "m": 3,
            "lam": 0.02,
            "w": 0.35,
            "total_steps": 16,
            "K": 5,
        }
        native = self._new_spectrum("cpu", shape, settings)
        reference = self._new_spectrum(device, shape, settings)
        chunk_widths = []
        temporary_predictors = []
        installed_predictor = self.spectrum.SpectrumPredictor

        class RecordingPredictor(installed_predictor):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                temporary_predictors.append(self)

            def predict(self, timestep):
                chunk_widths.append(self.cheb._H_buf.shape[1])
                return super().predict(timestep)

        adapter = HostHistoryPredictor(
            native,
            RecordingPredictor,
            device,
            settings,
            chunk_features=chunk_features,
        )

        delegated_updates = []
        installed_update = native.update

        def observe_native_update(timestep, feature):
            delegated_updates.append((timestep, feature))
            return installed_update(timestep, feature)

        native.update = observe_native_update
        observations = []
        for step in range(9):
            cpu_feature = self._feature(step, shape)
            observations.append(cpu_feature.clone())
            gpu_feature = cpu_feature.to(device).requires_grad_()
            input_copy = gpu_feature.detach().clone()
            adapter.update(float(step), gpu_feature)
            reference.update(float(step), gpu_feature.detach())

            self.assertEqual(gpu_feature.device, device)
            torch.testing.assert_close(gpu_feature.detach(), input_copy, atol=0, rtol=0)

        self.assertEqual(len(delegated_updates), 9)
        for (step, feature), expected in zip(delegated_updates, observations):
            self.assertEqual(step, float(len([t for t, _ in delegated_updates[:int(step)]])))
            self.assertEqual(feature.device.type, "cpu")
            self.assertFalse(feature.requires_grad)
            self.assertIsNone(feature.grad_fn)
            torch.testing.assert_close(feature, expected, atol=0, rtol=0)

        retained_steps = torch.tensor([4., 5., 6., 7., 8.], dtype=native.cheb.t_buf.dtype)
        retained_features = torch.stack([item.reshape(-1) for item in observations[-settings["K"] :]])
        self.assertEqual(native.cheb.device, torch.device("cpu"))
        self.assertEqual(native.cheb.t_buf.device.type, "cpu")
        self.assertEqual(native.cheb._H_buf.device.type, "cpu")
        self.assertFalse(native.cheb._H_buf.requires_grad)
        self.assertEqual(native.cheb._shape, torch.Size(shape))
        torch.testing.assert_close(native.cheb.t_buf, retained_steps, atol=0, rtol=0)
        torch.testing.assert_close(native.cheb._H_buf, retained_features, atol=0, rtol=0)

        native_t_ref = native.cheb.t_buf
        native_h_ref = native.cheb._H_buf
        native_shape_ref = native.cheb._shape
        native_coef_ref = native.cheb._coef
        native_t_snapshot = native.cheb.t_buf.clone()
        native_h_snapshot = native.cheb._H_buf.clone()
        expected_chunk_widths = [chunk_features] * (feature_count // chunk_features)
        if feature_count % chunk_features:
            expected_chunk_widths.append(feature_count % chunk_features)
        self.assertEqual(expected_chunk_widths[-1], 1)

        for timestep in (9.5, 11.):
            expected = reference.predict(timestep)
            result = adapter.predict(timestep)
            self.assertEqual(result.shape, torch.Size(shape))
            self.assertEqual(result.dtype, observations[-1].dtype)
            self.assertEqual(result.device, device)
            # Installed Spectrum's coefficient dtype is bfloat16; allow its
            # expected rounding while still detecting missing or misordered chunks.
            torch.testing.assert_close(result, expected, atol=0.04, rtol=0.02)
            torch.testing.assert_close(
                result.reshape(-1)[-1], expected.reshape(-1)[-1],
                atol=0.04, rtol=0.02)
            self.assertIs(native.cheb.t_buf, native_t_ref)
            self.assertIs(native.cheb._H_buf, native_h_ref)
            self.assertIs(native.cheb._shape, native_shape_ref)
            self.assertIs(native.cheb._coef, native_coef_ref)
            torch.testing.assert_close(native.cheb.t_buf, native_t_snapshot, atol=0, rtol=0)
            torch.testing.assert_close(native.cheb._H_buf, native_h_snapshot, atol=0, rtol=0)

        self.assertEqual(chunk_widths, expected_chunk_widths * 2)
        self.assertTrue(temporary_predictors)
        for predictor in temporary_predictors:
            self.assertEqual(predictor.cheb.device, device)
            self.assertEqual(predictor.cheb.M, settings["m"])
            self.assertEqual(predictor.cheb.lam, settings["lam"])
            self.assertEqual(predictor.w, settings["w"])
            self.assertEqual(predictor.cheb.K, settings["K"])
            self.assertEqual(predictor.cheb.total_steps, settings["total_steps"])
            self.assertEqual(predictor.cheb.t_buf.device, device)
            self.assertEqual(predictor.cheb._H_buf.device, device)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is not available")
    def test_returned_dtype_matches_full_prediction_for_fp16_bf16_and_fp32_history(self):
        device = torch.device("cuda", torch.cuda.current_device())
        shape = (2, 3, 4, 5)
        settings = {
            "m": 3,
            "lam": 0.02,
            "w": 0.35,
            "total_steps": 16,
            "K": 5,
        }
        expected_dtypes = {
            torch.float16: torch.float32,
            torch.bfloat16: torch.bfloat16,
            torch.float32: torch.float32,
        }

        for history_dtype, output_dtype in expected_dtypes.items():
            with self.subTest(history_dtype=history_dtype):
                native = self._new_spectrum("cpu", shape, settings)
                reference = self._new_spectrum(device, shape, settings)
                adapter = HostHistoryPredictor(
                    native, self.spectrum.SpectrumPredictor, device, settings,
                    chunk_features=17,
                )
                for step in range(8):
                    feature = self._feature(step, shape).to(
                        device=device, dtype=history_dtype)
                    adapter.update(float(step), feature)
                    reference.update(float(step), feature)

                expected = reference.predict(10.5)
                result = adapter.predict(10.5)
                self.assertEqual(expected.dtype, output_dtype)
                self.assertEqual(result.dtype, expected.dtype)
                self.assertEqual(result.shape, torch.Size(shape))
                self.assertEqual(result.device, device)
                self.assertEqual(native.cheb._H_buf.dtype, history_dtype)
                torch.testing.assert_close(result, expected, atol=0.04, rtol=0.02)

    def _session(self, project):
        return ForecastSession(SimpleNamespace(
            SpectrumPredictor=self.spectrum.SpectrumPredictor,
            _spectrum_fast_forward=project,
        ))

    def _run_one_session_step(self, session, executor, x, context):
        return session.run(
            executor, x, torch.tensor([100.], device=x.device), context,
            branch_key=("host-history",),
            transformer_options={
                "cond_or_uncond": [0],
                "uuids": ["positive"],
            },
        )

    def test_session_keeps_ordinary_predictor_for_cpu_features(self):
        session = self._session(lambda _dm, _t, feature: feature.movedim(-1, 1))
        executor = _ForecastExecutor("cpu")
        x = torch.zeros(1, 2, 1, 2, 4)
        context = torch.zeros(1, 3, 4)
        captured = []

        def sampler(*_args, **_kwargs):
            result = self._run_one_session_step(session, executor, x, context)
            lane = next(iter(session.forecast._lanes.values()))
            captured.append(lane.predictor)
            return result

        session.sample(sampler, x, x, object(), torch.linspace(1., 0., 11))
        self.assertEqual(len(captured), 1)
        self.assertIs(type(captured[0]), self.spectrum.SpectrumPredictor)
        self.assertEqual(captured[0].cheb.device, torch.device("cpu"))
        self.assertIsNone(session.forecast)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is not available")
    def test_session_cuda_adapter_is_cpu_backed_and_cleans_up_on_projection_cancellation(self):
        class ProjectionCancelled(BaseException):
            pass

        def cancel_projection(_dm, _timestep, _feature):
            raise ProjectionCancelled("cancel cached projection")

        session = self._session(cancel_projection)
        device = torch.device("cuda", torch.cuda.current_device())
        executor = _ForecastExecutor(device)
        x = torch.zeros(1, 2, 1, 2, 4, device=device)
        context = torch.zeros(1, 3, 4, device=device)
        hooks_before = tuple(executor.class_obj.final_layer._forward_pre_hooks.items())
        captured = []

        def sampler(*_args, **_kwargs):
            for step in range(7):
                try:
                    result = session.run(
                        executor, x, torch.tensor([100. - step], device=device),
                        context, branch_key=("cuda-history",),
                        transformer_options={
                            "cond_or_uncond": [0],
                            "uuids": ["positive"],
                        },
                    )
                except ProjectionCancelled:
                    raise
                if step == 0:
                    lane = next(iter(session.forecast._lanes.values()))
                    captured.append(lane.predictor)
                    self.assertIsInstance(lane.predictor, HostHistoryPredictor)
                    self.assertEqual(lane.predictor.native.cheb.device, torch.device("cpu"))
                    self.assertEqual(lane.predictor.native.cheb._H_buf.device.type, "cpu")
                self.assertEqual(result.device, device)

        with self.assertRaises(ProjectionCancelled):
            session.sample(sampler, x, x, object(), torch.linspace(1., 0., 11))

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].native.cheb.t_buf.device.type, "cpu")
        self.assertEqual(captured[0].native.cheb._H_buf.device.type, "cpu")
        self.assertIsNone(session.forecast)
        self.assertEqual(
            tuple(executor.class_obj.final_layer._forward_pre_hooks.items()),
            hooks_before,
        )


if __name__ == "__main__":
    unittest.main()
