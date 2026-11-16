"""CPU-only compatibility tests for Spectrum forecasting with Mod Guidance.

The installed Spectrum/Mod Guidance functions are extracted from the ComfyUI
installation named by LAKIS_COMFY_ROOT. No checkpoint, server, or GPU is used.
"""
import ast
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import weakref

import torch
from torch import nn

from installer.tests.test_regional_reference_forecast import (
    Executor,
    Predictor,
    RegionalForecast,
    TinyDM,
)
from installer.tests.test_regional_reference_predictions import package


ForecastSession = importlib.import_module(
    package.__name__ + ".forecast_session"
).ForecastSession


class _ModEmbedding(nn.Module):
    def forward(self, t):
        return (t + 2.).unsqueeze(-1), None


class _ModBlock(nn.Module):
    def forward(self, feature, t_emb):
        return feature + t_emb.reshape(t_emb.shape[0], 1, 1, 1, 1)


class _ModFinalLayer(nn.Module):
    def forward(self, feature, t_emb, adaln_lora_B_T_3D=None):
        # Reduce the embedding independently so malformed native states can
        # still be observed without making this tiny model depend on weights.
        value = t_emb.reshape(feature.shape[0], -1).sum(dim=1)
        return feature.square() + value.reshape(-1, 1, 1, 1, 1)


class _ModDM(TinyDM):
    def __init__(self, ensure_t_hook, ensure_block_hooks):
        super().__init__()
        self.t_embedder = nn.ModuleList([nn.Identity(), _ModEmbedding()])
        self.final_layer = _ModFinalLayer()
        self.blocks = nn.ModuleList([_ModBlock(), _ModBlock()])
        self._mod_pooled_proj = None
        ensure_t_hook(self)
        ensure_block_hooks(self)

    def project(self, timesteps, feature):
        if timesteps.ndim == 1:
            timesteps = timesteps.unsqueeze(1)
        t_emb, adaln = self.t_embedder[1](self.t_embedder[0](timesteps))
        t_emb = self.t_embedding_norm(t_emb)
        for block in self.blocks:
            feature = block(feature, t_emb)
        return self.unpatchify(self.final_layer(
            feature, t_emb, adaln_lora_B_T_3D=adaln))


class RegionalReferenceModGuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["LAKIS_COMFY_ROOT"])
        custom_nodes = root / "custom_nodes/comfyui-spectrum-ksampler"
        cls.spectrum_source = custom_nodes / "spectrum.py"
        cls.mod_guidance_source = custom_nodes / "mod_guidance.py"
        namespace = {"torch": torch, "weakref": weakref}
        cls._extract_functions(
            cls.spectrum_source, {"_spectrum_fast_forward"}, namespace)
        cls._extract_functions(
            cls.mod_guidance_source,
            {"_ensure_t_emb_hook", "_ensure_block_hooks",
             "_t_emb_forward_hook"},
            namespace,
        )
        cls.spectrum_project = staticmethod(namespace["_spectrum_fast_forward"])
        cls.ensure_t_hook = staticmethod(namespace["_ensure_t_emb_hook"])
        cls.ensure_block_hooks = staticmethod(namespace["_ensure_block_hooks"])

    @staticmethod
    def _extract_functions(source, names, namespace):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        if {node.name for node in functions} != names:
            raise AssertionError(f"{source} is missing one of {sorted(names)}")
        code = compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec")
        exec(code, namespace)

    def setUp(self):
        self.predictors = []
        self.projections = []
        self.dm, self.executor = self._new_model()
        self.executor.value = 0.25
        self.x = torch.zeros(1, 2, 1, 2, 4)
        self.context = torch.zeros(1, 3, 4)

    def _new_model(self):
        dm = _ModDM(self.ensure_t_hook, self.ensure_block_hooks)
        self.assertIs(dm.t_embedding_norm._anima_mod_hook_installed, True)
        self.assertIs(dm._anima_mod_block_hooks_installed, True)
        return dm, Executor(dm)

    def _set_mod_state(self, dm, *, combined=None, delta_unit=None,
                       schedule=(0.25, -0.5), final_w=1.5):
        combined = (torch.tensor([[1.]]) if combined is None else combined)
        delta_unit = (torch.tensor([[0.4]]) if delta_unit is None else delta_unit)
        dm._mod_pooled_proj = combined.clone()
        dm.t_embedding_norm._anima_mod_delta = combined.clone().unsqueeze(1)
        state = SimpleNamespace(
            delta_unit=delta_unit.clone(),
            schedule=tuple(schedule),
            final_w=final_w,
        )
        dm._anima_mod_block_state = state
        return state

    def _factory(self, feature):
        predictor = Predictor(feature)
        self.predictors.append(predictor)
        return predictor

    def _project(self, dm, timestep, feature):
        self.projections.append((dm, timestep.clone(), feature.clone()))
        session = ForecastSession(SimpleNamespace(_spectrum_fast_forward=self.spectrum_project))
        return session._project_feature(dm, timestep, feature)

    def _forecast(self, *, num_steps=20, warmup=1, tail=0,
                  refresh=100, mod_guidance=True):
        return RegionalForecast(
            "mod-guidance-test",
            num_steps,
            self._factory,
            self._project,
            warmup=warmup,
            tail_actual_steps=tail,
            refresh_interval=refresh,
            mod_guidance=mod_guidance,
        )

    def _run(self, forecast, timestep, *, branch=("regional",), flags=(0,),
             uuids=("positive",), executor=None, x=None, context=None):
        executor = self.executor if executor is None else executor
        x = self.x if x is None else x
        context = self.context if context is None else context
        times = torch.full((x.shape[0],), float(timestep))
        return forecast.run(
            executor, x, times, context, branch_key=branch,
            transformer_options={
                "cond_or_uncond": list(flags),
                "uuids": list(uuids),
            },
        )

    @staticmethod
    def _hook_snapshot(dm):
        modules = [dm.t_embedding_norm, *dm.blocks, dm.final_layer]
        return tuple(
            (module, tuple(module._forward_hooks.items()),
             tuple(module._forward_pre_hooks.items()))
            for module in modules
        )

    def _session(self):
        def factory(**settings):
            predictor = Predictor(torch.zeros(
                settings["feature_shape"], device=settings["device"]))
            self.predictors.append(predictor)
            return predictor

        return ForecastSession(SimpleNamespace(
            SpectrumPredictor=factory,
            _spectrum_fast_forward=self.spectrum_project,
        ))

    def test_default_forecast_keeps_valid_ambient_modulation_native(self):
        self._set_mod_state(self.dm)
        # Omitting mod_guidance must retain the native-only default.
        forecast = RegionalForecast(
            "native-default", 12, self._factory, self._project,
            warmup=1, tail_actual_steps=0, refresh_interval=2,
        )
        hooks = self._hook_snapshot(self.dm)
        for timestep in (100, 99, 98, 97):
            result = self._run(forecast, timestep)
            self.assertIs(result, self.executor.last_output)
        self.assertEqual(len(self.executor.calls), 4)
        self.assertFalse(self.predictors)
        self.assertFalse(self.projections)
        self.assertEqual(self._hook_snapshot(self.dm), hooks)

    def test_short_mod_enabled_schedule_runs_natively_without_capture_or_history(self):
        self._set_mod_state(self.dm)
        forecast = self._forecast(num_steps=3, warmup=2, tail=1)
        hooks = self._hook_snapshot(self.dm)

        for timestep in (100, 99, 98):
            result = self._run(forecast, timestep)
            self.assertIs(result, self.executor.last_output)

        self.assertEqual(len(self.executor.calls), 3)
        self.assertFalse(self.predictors)
        self.assertFalse(self.projections)
        self.assertEqual(self._hook_snapshot(self.dm), hooks)
        with self.assertRaisesRegex(RuntimeError, "reset"):
            self._run(forecast, 97)

        forecast.reset("short-mod-reset")
        result = self._run(forecast, 100)
        self.assertIs(result, self.executor.last_output)
        self.assertEqual(len(self.executor.calls), 4)
        self.assertFalse(self.predictors)
        self.assertFalse(self.projections)
        self.assertEqual(self._hook_snapshot(self.dm), hooks)

    def test_supported_modulation_has_independent_branch_and_cfg_histories(self):
        self._set_mod_state(self.dm)
        forecast = self._forecast(num_steps=12, warmup=1, refresh=20)
        lane_values = []
        for branch in ("left", "right"):
            for flag, uid in ((0, "positive"), (1, "negative")):
                value = float(len(lane_values) + 1)
                self.executor.value = value
                self._run(
                    forecast, 100, branch=(branch,), flags=(flag,), uuids=(uid,))
                self._run(
                    forecast, 99, branch=(branch,), flags=(flag,), uuids=(uid,))
                lane_values.append(value)

        self.assertEqual(len(self.predictors), 4)
        self.assertEqual(len(self.executor.calls), 4)
        self.assertEqual(len(self.projections), 4)
        self.assertTrue(all(p.predictions == [1.] for p in self.predictors))
        for predictor, value in zip(self.predictors, lane_values):
            self.assertAlmostEqual(
                predictor.initial.mean().item(),
                value + 2 * (100 + 2 + 1) + sum((0.25, -0.5)) * 0.4,
                places=4)

    def test_unused_pooled_cache_changes_do_not_change_live_modulation(self):
        self._set_mod_state(self.dm)
        forecast = self._forecast()
        self._run(forecast, 100)
        self._run(forecast, 99)
        self.dm._mod_pooled_proj.add_(10.)
        self._run(forecast, 98)
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(self.predictors[0].predictions, [1., 2.])

    def test_modulation_values_specs_schedule_and_final_weight_rewarm_history(self):
        def t_delta_value(dm, state):
            dm.t_embedding_norm._anima_mod_delta.add_(0.2)

        def block_delta_value(dm, state):
            state.delta_unit.add_(0.2)

        def tensor_dtype(dm, state):
            dm._mod_pooled_proj = dm._mod_pooled_proj.double()
            dm.t_embedding_norm._anima_mod_delta = (
                dm.t_embedding_norm._anima_mod_delta.double())
            state.delta_unit = state.delta_unit.double()

        def schedule_value(dm, state):
            state.schedule = (0.5, -0.25)

        def final_weight(dm, state):
            state.final_w = 0.75

        changes = (
            ("time-embedding tensor value", t_delta_value),
            ("block tensor value", block_delta_value),
            ("tensor dtype spec", tensor_dtype),
            ("schedule", schedule_value),
            ("final_w", final_weight),
        )
        for name, change in changes:
            with self.subTest(change=name):
                self.predictors = []
                self.projections = []
                self.dm, self.executor = self._new_model()
                self.executor.value = 0.25
                self.x = torch.zeros(1, 2, 1, 2, 4)
                self.context = torch.zeros(1, 3, 4)
                state = self._set_mod_state(self.dm)
                forecast = self._forecast()
                self._run(forecast, 100)
                self._run(forecast, 99)
                self.assertEqual(self.predictors[0].predictions, [1.])

                change(self.dm, state)
                before = len(self.executor.calls)
                self._run(forecast, 98)
                self.assertEqual(len(self.executor.calls), before + 1)
                self.assertEqual(len(self.predictors), 2)
                self.assertFalse(self.predictors[-1].predictions)
                self._run(forecast, 97)
                self.assertEqual(self.predictors[-1].predictions, [3.])

    def test_unsupported_and_transient_modulation_stay_native_without_training(self):
        def bad_t_delta_shape(dm, state):
            dm.t_embedding_norm._anima_mod_delta = torch.ones(1, 1)

        def bad_t_delta_dtype(dm, state):
            dm.t_embedding_norm._anima_mod_delta = torch.ones(
                1, 1, 1, dtype=torch.int64)

        def nonfinite_t_delta(dm, state):
            dm.t_embedding_norm._anima_mod_delta.fill_(float("nan"))

        def bad_block_delta_shape(dm, state):
            state.delta_unit = torch.ones(2, 1)

        def nonfinite_block_delta(dm, state):
            state.delta_unit.fill_(float("inf"))

        def wrong_schedule_length(dm, state):
            state.schedule = (0.25,)

        def nonfinite_schedule(dm, state):
            state.schedule = (float("inf"), -0.5)

        def nonfinite_final_weight(dm, state):
            state.final_w = float("nan")

        def missing_t_hook_flag(dm, state):
            dm.t_embedding_norm._anima_mod_hook_installed = False

        def missing_block_hook_flag(dm, state):
            dm._anima_mod_block_hooks_installed = False

        invalid = (
            ("time-delta shape", bad_t_delta_shape),
            ("time-delta dtype", bad_t_delta_dtype),
            ("time-delta finiteness", nonfinite_t_delta),
            ("block-delta shape", bad_block_delta_shape),
            ("block-delta finiteness", nonfinite_block_delta),
            ("schedule length", wrong_schedule_length),
            ("schedule finiteness", nonfinite_schedule),
            ("final weight finiteness", nonfinite_final_weight),
            ("time hook flag", missing_t_hook_flag),
            ("block hook flag", missing_block_hook_flag),
        )
        for name, make_invalid in invalid:
            with self.subTest(state=name):
                self.predictors = []
                self.projections = []
                self.dm, self.executor = self._new_model()
                state = self._set_mod_state(self.dm)
                make_invalid(self.dm, state)
                forecast = self._forecast()
                before = len(self.executor.calls)
                result = self._run(forecast, 100)
                self.assertEqual(len(self.executor.calls), before + 1)
                self.assertIs(result, self.executor.last_output)
                self.assertFalse(self.predictors)
                self.assertFalse(self.projections)

        self.predictors = []
        self.projections = []
        self.dm, self.executor = self._new_model()
        self.executor.transient_mod = True
        forecast = self._forecast()
        for timestep in (100, 99, 98):
            result = self._run(forecast, timestep)
            self.assertIs(result, self.executor.last_output)
        self.assertFalse(self.predictors)
        self.executor.transient_mod = False
        self._run(forecast, 97)
        self.assertEqual([step for step, _ in self.predictors[-1].updates], [3.])
        self._run(forecast, 96)
        self.assertEqual(self.predictors[-1].predictions, [4.])

    def test_session_projection_applies_base_once_and_restores_pool_on_baseexception(self):
        combined = torch.tensor([[1.25], [-0.5]])
        state = self._set_mod_state(
            self.dm, combined=combined, delta_unit=torch.tensor([[0.4]]),
            schedule=(0.25, -0.5), final_w=1.5)
        pooled = self.dm._mod_pooled_proj
        delta = self.dm.t_embedding_norm._anima_mod_delta
        hooks = self._hook_snapshot(self.dm)
        observed = []

        def observe_pool(dm, timestep, feature):
            observed.append(dm._mod_pooled_proj)
            return self.spectrum_project(dm, timestep, feature)

        spectrum = SimpleNamespace(_spectrum_fast_forward=observe_pool)
        session = ForecastSession(spectrum)
        feature = torch.arange(16, dtype=torch.float32).reshape(2, 1, 2, 4, 1) / 10
        timestep = torch.tensor([10., 10.])
        result = session._project_feature(self.dm, timestep, feature)

        self.assertEqual(observed, [None])
        self.assertIs(self.dm._mod_pooled_proj, pooled)
        scalar = timestep + 2. + combined[:, 0] + state.final_w * state.delta_unit[0, 0]
        expected = feature.square().movedim(-1, 1) + scalar.reshape(2, 1, 1, 1, 1)
        torch.testing.assert_close(result, expected)
        self.assertIs(self.dm.t_embedding_norm._anima_mod_delta, delta)
        self.assertEqual(self._hook_snapshot(self.dm), hooks)

        class Cancelled(BaseException):
            pass

        def fail_with_cancellation(dm, _timestep, _feature):
            self.assertIsNone(dm._mod_pooled_proj)
            raise Cancelled("projection cancelled")

        session.spectrum._spectrum_fast_forward = fail_with_cancellation
        with self.assertRaises(Cancelled):
            session._project_feature(self.dm, timestep, feature)
        self.assertIs(self.dm._mod_pooled_proj, pooled)
        self.assertIs(self.dm.t_embedding_norm._anima_mod_delta, delta)
        self.assertIs(self.dm._anima_mod_block_state, state)
        self.assertEqual(self._hook_snapshot(self.dm), hooks)

    def test_session_forecasts_mixed_cfg_with_mod_hooks_and_cleans_cancellation(self):
        combined = torch.tensor([[1.25], [-0.5]])
        state = self._set_mod_state(
            self.dm, combined=combined, delta_unit=torch.tensor([[0.4]]),
            schedule=(0.25, -0.5), final_w=1.5)
        self.executor.value = 0.25
        x = torch.zeros(2, 2, 1, 2, 4)
        context = torch.zeros(2, 3, 4)
        session = self._session()
        hooks = self._hook_snapshot(self.dm)
        forecasts_seen = []

        def sampler(*_args, **_kwargs):
            forecast = session.forecast
            forecasts_seen.append(forecast)
            outputs = []
            last_feature = None
            for step in range(14):
                before = len(self.executor.calls)
                timestep = torch.full((2,), 100. - step)
                result = session.run(
                    self.executor, x, timestep, context, branch_key=("mixed",),
                    transformer_options={
                        "cond_or_uncond": [0, 1],
                        "uuids": ["positive", "negative"],
                    },
                )
                actual = len(self.executor.calls) == before + 1
                if actual:
                    block_value = (
                        len(state.schedule) * (timestep + 2. + combined[:, 0])
                        + sum(state.schedule) * state.delta_unit[0, 0])
                    last_feature = (x.movedim(1, -1) + self.executor.value
                                    + block_value.reshape(2, 1, 1, 1, 1))
                scalar = (timestep + 2. + combined[:, 0]
                          + state.final_w * state.delta_unit[0, 0])
                expected = (
                    last_feature.square().movedim(-1, 1)
                    + scalar.reshape(2, 1, 1, 1, 1)
                )
                torch.testing.assert_close(result, expected)
                outputs.append(result)
            return outputs

        sigmas = torch.linspace(1., 0., 15)
        for _request in range(2):
            before_predictors = len(self.predictors)
            session.sample(sampler, x, x, object(), sigmas)
            new_predictors = self.predictors[before_predictors:]
            self.assertEqual(len(new_predictors), 1)
            self.assertTrue(new_predictors[0].predictions)
            self.assertTrue(forecasts_seen[-1] is not forecasts_seen[-2]
                            if len(forecasts_seen) > 1 else True)
            self.assertIsNone(session.forecast)
            self.assertEqual(self._hook_snapshot(self.dm), hooks)
        self.assertTrue(all(p.predictions for p in self.predictors))

        class Cancelled(BaseException):
            pass

        self.predictors = []
        self.dm, self.executor = self._new_model()
        state = self._set_mod_state(self.dm)
        self.executor.error = Cancelled("sampler cancelled")
        self.executor.error_after_capture = True
        session = self._session()
        hooks = self._hook_snapshot(self.dm)
        pooled = self.dm._mod_pooled_proj
        delta = self.dm.t_embedding_norm._anima_mod_delta

        def cancelled_sampler(*_args, **_kwargs):
            return session.run(
                self.executor, self.x, torch.tensor([100.]), self.context,
                branch_key=("cancelled",),
                transformer_options={
                    "cond_or_uncond": [0], "uuids": ["positive"],
                },
            )

        with self.assertRaises(Cancelled):
            session.sample(
                cancelled_sampler, self.x, self.x, object(),
                torch.linspace(1., 0., 10),
            )
        self.assertIsNone(session.forecast)
        self.assertFalse(self.predictors)
        self.assertIs(self.dm._mod_pooled_proj, pooled)
        self.assertIs(self.dm.t_embedding_norm._anima_mod_delta, delta)
        self.assertIs(self.dm._anima_mod_block_state, state)
        self.assertEqual(self._hook_snapshot(self.dm), hooks)


if __name__ == "__main__":
    unittest.main()
