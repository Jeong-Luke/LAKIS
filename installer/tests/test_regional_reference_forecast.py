"""CPU-only opt-in forecaster contract tests; no server or weight loads.

Run with:
python installer/run_installed_tests.py --install-root <LAKIS installation> \
    installer.tests.test_regional_reference_forecast
"""
import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from uuid import UUID

import torch
from torch import nn


SOURCE = (Path(__file__).resolve().parents[2] /
          "src/custom_nodes/ComfyUI-LAKIS-Regional-Reference/experimental_forecast.py")
SPEC = importlib.util.spec_from_file_location("regional_feature_forecast_test", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RegionalForecast = MODULE.RegionalForecast


class FinalLayer(nn.Module):
    def forward(self, feature, t_emb, adaln_lora_B_T_3D=None):
        # Nonlinear projection: averaging features before this is NOT equivalent
        # to blending this layer's independently projected predictions.
        return feature.square() + t_emb.reshape(-1, 1, 1, 1, 1)


class Embedding(nn.Module):
    def forward(self, t):
        return t + 2., None


class TinyDM(nn.Module):
    def __init__(self):
        super().__init__()
        self.patch_temporal = 1
        self.final_layer = FinalLayer()
        self.t_embedder = nn.ModuleList([nn.Identity(), Embedding()])
        self.t_embedding_norm = nn.Identity()

    def unpatchify(self, feature):
        return feature.movedim(-1, 1)

    def project(self, timesteps, feature):
        return self.unpatchify(self.final_layer(feature, timesteps.reshape(-1, 1) + 2.))


class Executor:
    def __init__(self, dm=None):
        self.class_obj = dm if dm is not None else TinyDM()
        self.calls = []
        self.value = 2.
        self.error = None
        self.error_after_capture = False
        self.skip_layer = False
        self.double_layer = False
        self.transient_mod = False
        self.last_output = None

    def __call__(self, x, timesteps, context, fps=None, padding_mask=None, **kwargs):
        self.calls.append((timesteps, context, fps, padding_mask, kwargs))
        if self.error is not None and not self.error_after_capture:
            raise self.error
        dm = self.class_obj
        if self.skip_layer:
            return x
        value = torch.as_tensor(self.value, dtype=x.dtype, device=x.device)
        if value.ndim:
            value = value.reshape(-1, 1, 1, 1, 1)
        feature = x.movedim(1, -1) + value
        if self.transient_mod:
            dm._mod_pooled_proj = torch.zeros(x.shape[0], 1)
        try:
            result = dm.project(timesteps, feature)
            if self.double_layer:
                dm.project(timesteps, feature)
        finally:
            if self.transient_mod:
                dm._mod_pooled_proj = None
        if self.error is not None:
            raise self.error
        self.last_output = result
        return result


class Predictor:
    def __init__(self, feature):
        self.initial = feature.clone()
        self.updates = []
        self.predictions = []
        self.feature = None
        self.bad_prediction = None

    def update(self, step, feature):
        if feature.requires_grad or feature.grad_fn is not None:
            raise AssertionError("Captured feature was not detached.")
        self.updates.append((step, feature.clone()))
        self.feature = feature.clone()

    def predict(self, step):
        self.predictions.append(step)
        return self.feature.clone() if self.bad_prediction is None else self.bad_prediction


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.predictors = []
        self.projections = []
        self.executor = Executor()
        self.x = torch.zeros(1, 2, 1, 2, 4, device="cpu")
        self.context = torch.zeros(1, 3, 4, device="cpu")

    def factory(self, feature):
        predictor = Predictor(feature)
        self.predictors.append(predictor)
        return predictor

    def project(self, dm, timesteps, feature):
        self.projections.append((dm, timesteps, feature.clone()))
        return dm.project(timesteps, feature)

    def forecaster(self, **kwargs):
        settings = dict(num_steps=20, warmup=2, tail_actual_steps=2)
        settings.update(kwargs)
        return RegionalForecast("request-one", predictor_factory=self.factory,
                                project_feature=self.project, **settings)

    def run_step(self, forecaster, t, branch=(0,), *, flags=(0,), uuids=("positive",),
                 x=None, context=None, executor=None, **kwargs):
        x = self.x if x is None else x
        context = self.context if context is None else context
        executor = self.executor if executor is None else executor
        timesteps = t if torch.is_tensor(t) else torch.full((x.shape[0],), float(t))
        options = {"cond_or_uncond": list(flags), "uuids": uuids}
        return forecaster.run(executor, x, timesteps, context, branch_key=branch,
                              transformer_options=options, **kwargs)

    def assert_value(self, result, value, t):
        # Independent invariant from FinalLayer: feature^2 + timestep + 2.
        expected = torch.as_tensor(value, dtype=result.dtype).square() + t + 2.
        if expected.ndim:
            expected = expected.reshape(-1, 1, 1, 1, 1)
        torch.testing.assert_close(result, expected.expand_as(result), atol=0, rtol=0)

    def test_two_branches_default_warmup_refresh_tail_and_independent_projection(self):
        forecast = RegionalForecast("generation", 12, self.factory, self.project)
        actual_steps = [0, 1, 2, 3, 4, 5, 7, 9, 10, 11]
        for step in range(12):
            for branch, value in (((0,), 2.), ((1,), 7.)):
                self.executor.value = value
                before = len(self.executor.calls)
                result = self.run_step(forecast, 100 - step, branch)
                self.assert_value(result, value, 100 - step)
                self.assertEqual(len(self.executor.calls) - before, int(step in actual_steps))
                if step in actual_steps:
                    self.assertIs(result, self.executor.last_output)
        self.assertEqual(len(self.predictors), 2)
        for predictor, value in zip(self.predictors, (2., 7.)):
            self.assertEqual([step for step, _ in predictor.updates], actual_steps)
            self.assertEqual(predictor.predictions, [6., 8.])
            for _, feature in predictor.updates:
                torch.testing.assert_close(feature, torch.full_like(feature, value))
        self.assertEqual(len(self.projections), 4)
        self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)

    def test_cfg_flags_and_uuid_order_do_not_share_predictions(self):
        forecast = self.forecaster()
        for step in range(4):
            for flag, value in ((0, 2.), (1, 7.)):
                self.executor.value = value
                result = self.run_step(forecast, 100 - step, flags=(flag,), uuids=("shared",))
                self.assert_value(result, value, 100 - step)
        self.assertEqual(len(self.predictors), 2)
        self.assertEqual([p.predictions for p in self.predictors], [[2.], [2.]])
        self.assertEqual([p.initial.flatten()[0].item() for p in self.predictors], [2., 7.])

        forecast.reset("mixed-cfg")
        x = self.x.repeat(2, 1, 1, 1, 1)
        context = self.context.repeat(2, 1, 1)
        uid = UUID("12345678-1234-5678-1234-567812345678")
        for step in range(3):
            for flags, ids, values in (
                    ((0, 1), (uid, "negative"), (2., 7.)),
                    ((1, 0), ("negative", uid), (7., 2.))):
                self.executor.value = values
                result = self.run_step(forecast, 100 - step, flags=flags, uuids=ids,
                                       x=x, context=context)
                self.assert_value(result, values, 100 - step)
        self.assertEqual(len(self.predictors), 4)
        self.assertEqual([p.predictions for p in self.predictors[2:]], [[2.], [2.]])

    def test_refresh_is_independent_of_other_branch_call_count(self):
        forecast = self.forecaster()
        for t in (100, 99, 98, 97):
            self.run_step(forecast, t, (0,))
        for t in (100, 99, 98):
            self.executor.value = 7.
            self.assert_value(self.run_step(forecast, t, (1,)), 7., t)
        self.assertEqual([s for s, _ in self.predictors[0].updates], [0., 1., 3.])
        self.assertEqual([s for s, _ in self.predictors[1].updates], [0., 1.])
        self.assertEqual([p.predictions for p in self.predictors], [[2.], [2.]])

    def test_repeated_timestep_is_actual_without_training_or_refresh_clock_changes(self):
        forecast = self.forecaster()
        for t in (100, 100, 99, 98):
            self.run_step(forecast, t)
        predictor = self.predictors[0]
        self.executor.value = 11.
        before = len(self.executor.calls)
        self.assert_value(self.run_step(forecast, 98), 11., 98)
        self.assertEqual(len(self.executor.calls), before + 1)
        self.assertEqual([s for s, _ in predictor.updates], [0., 1.])
        # The duplicate real call must not replace/append history at step two.
        self.assertEqual(predictor.feature.flatten()[0].item(), 2.)
        self.executor.value = 3.
        self.run_step(forecast, 97)  # Step three refresh, despite the duplicate.
        self.assert_value(self.run_step(forecast, 96), 3., 96)
        self.assertEqual([s for s, _ in predictor.updates], [0., 1., 3.])
        self.assertEqual(predictor.predictions, [2., 4.])

    def test_short_schedules_are_all_actual_and_never_create_forecasts(self):
        forecast = RegionalForecast("short", 8, self.factory, self.project)
        for t in range(100, 92, -1):
            self.assertIs(self.run_step(forecast, t), self.executor.last_output)
        self.assertEqual(len(self.executor.calls), 8)
        self.assertFalse(self.projections)

    def test_completed_lanes_drain_existing_branches_but_cannot_rearm_implicitly(self):
        forecast = self.forecaster(num_steps=3, warmup=1, tail_actual_steps=1)
        self.run_step(forecast, 100, (1,))
        for t in (100, 99, 98):
            self.run_step(forecast, t, (0,))
        for t in (99, 98):
            self.run_step(forecast, t, (1,))
        before = len(self.executor.calls)
        with self.assertRaisesRegex(RuntimeError, "reset"):
            self.run_step(forecast, 100, (0,))
        self.assertEqual(len(self.executor.calls), before)
        forecast.reset("request-two")
        self.executor.value = 9.
        self.assert_value(self.run_step(forecast, 100), 9., 100)
        self.assertEqual(forecast.run_token, "request-two")
        # An explicit reset with the same token is still a complete discard.
        count = len(self.predictors)
        forecast.reset("request-two")
        self.run_step(forecast, 100)
        self.assertEqual(len(self.predictors), count + 1)

    def test_completion_rejects_new_branch_and_final_timestep_reuse(self):
        for branch, t in (((1,), 100), ((0,), 98)):
            with self.subTest(branch=branch, t=t):
                forecast = self.forecaster(num_steps=3)
                for current in (100, 99, 98):
                    self.run_step(forecast, current)
                with self.assertRaisesRegex(RuntimeError, "reset"):
                    self.run_step(forecast, t, branch)

    def test_signature_changes_rewarm_without_resurrecting_old_features(self):
        for change in ("uuids", "model", "shape", "dtype", "context"):
            with self.subTest(change=change):
                forecast = self.forecaster()
                original = len(self.predictors)
                for t in (100, 99, 98):
                    self.run_step(forecast, t)
                options = {
                    "uuids": {"uuids": ("new-positive",)},
                    "model": {"executor": Executor()},
                    "shape": {"x": torch.zeros(1, 2, 1, 4, 4)},
                    "dtype": {"x": self.x.double()},
                    "context": {"context": torch.zeros(1, 5, 4)},
                }[change]
                self.run_step(forecast, 97, **options)
                self.run_step(forecast, 96)
                self.assertEqual(len(self.predictors), original + 3)
                self.assertEqual(self.predictors[-2].predictions, [])
                self.assertEqual(self.predictors[-1].predictions, [])
                self.assertEqual([s for s, _ in self.predictors[-1].updates], [4.])

    def test_unsupported_contexts_run_natively_and_invalidate_both_branch_cfg_histories(self):
        cases = (
            ("control", {"control": object()}),
            ("fps", {"fps": 24}),
            ("padding", {"padding_mask": torch.zeros(1)}),
            ("odd", {"x": torch.zeros(1, 2, 1, 2, 3)}),
            ("video", {"x": torch.zeros(1, 2, 2, 2, 4)}),
            ("missing_uuid", {"uuids": None}),
            ("blank_uuid", {"uuids": (" ",)}),
            ("numeric_uuid", {"uuids": (123,)}),
            ("tensor_uuid", {"uuids": torch.tensor([1])}),
            ("uuid_count", {"uuids": ("one", "two")}),
            ("context_batch", {"context": torch.zeros(2, 3, 4)}),
        )
        for name, unsupported in cases:
            with self.subTest(name=name):
                forecast = self.forecaster()
                initial = len(self.predictors)
                for t in (100, 99):
                    self.run_step(forecast, t, flags=(0,))
                    self.run_step(forecast, t, flags=(1,), uuids=("negative",))
                before = len(self.executor.calls)
                result = self.run_step(forecast, 98, **unsupported)
                self.assertIs(result, self.executor.last_output)
                self.assertEqual(len(self.executor.calls), before + 1)
                self.run_step(forecast, 97, flags=(0,))
                self.run_step(forecast, 98, flags=(1,), uuids=("negative",))
                self.assertEqual(len(self.predictors), initial + 4)
                self.assertFalse(self.predictors[-1].predictions)
                self.assertFalse(self.predictors[-2].predictions)
                self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)

    def test_unsupported_calls_keep_schedule_and_tail_positions(self):
        forecast = self.forecaster(num_steps=7, warmup=1, tail_actual_steps=2)
        self.run_step(forecast, 100)
        self.run_step(forecast, 99, control={})
        for t in (98, 97, 96, 95, 94):
            self.run_step(forecast, t)
        # Unsupported step one consumed its schedule position, not its history.
        self.assertEqual([s for s, _ in self.predictors[-1].updates], [2., 4., 5., 6.])
        self.assertEqual(self.predictors[-1].predictions, [3.])
        with self.assertRaisesRegex(RuntimeError, "reset"):
            self.run_step(forecast, 100)

    def test_invalid_cfg_or_untrackable_time_disables_forecasting_until_reset(self):
        for kwargs, timestep in (
                ({"flags": ()}, 98),
                ({"flags": (2,)}, 98),
                ({"flags": (True,)}, 98),
                ({"flags": (0, 1)}, 98),
                ({}, float("nan")),
                ({}, torch.tensor([[98., 97.]]))):
            with self.subTest(kwargs=kwargs, timestep=timestep):
                forecast = self.forecaster()
                initial = len(self.predictors)
                for t in (100, 99):
                    self.run_step(forecast, t)
                self.run_step(forecast, timestep, **kwargs)
                for t in (97, 96, 95):
                    self.run_step(forecast, t)
                self.assertEqual(len(self.predictors), initial + 1)
                self.assertFalse(self.predictors[-1].predictions)
                forecast.reset("next")
                self.run_step(forecast, 100)
                self.assertEqual(len(self.predictors), initial + 2)

    def test_nonmonotonic_time_never_starts_an_implicit_generation(self):
        forecast = self.forecaster()
        for t in (100, 99, 98, 100, 99, 98, 97):
            self.run_step(forecast, t)
        self.assertEqual(self.predictors[-1].predictions, [2.])
        self.assertEqual(len(self.executor.calls), 6)

    def test_temporal_patch_and_mod_guidance_states_veto_forecasting(self):
        dm = self.executor.class_obj
        for owner, attr, value in (
                (dm, "patch_temporal", 2),
                (dm, "_mod_pooled_proj", torch.zeros(1, 1)),
                (dm, "_anima_mod_block_state", {}),
                (dm.t_embedding_norm, "_anima_mod_delta", torch.zeros(1))):
            with self.subTest(attr=attr):
                forecast = self.forecaster()
                initial = len(self.predictors)
                for t in (100, 99):
                    self.run_step(forecast, t)
                previous = getattr(owner, attr, None)
                setattr(owner, attr, value)
                try:
                    self.assertIs(self.run_step(forecast, 98), self.executor.last_output)
                finally:
                    setattr(owner, attr, previous)
                self.run_step(forecast, 97)
                self.assertEqual(len(self.predictors), initial + 2)
                self.assertFalse(self.predictors[-1].predictions)

    def test_mod_guidance_enabled_inside_executor_does_not_train_a_history(self):
        forecast = self.forecaster()
        self.executor.transient_mod = True
        for t in (100, 99, 98):
            self.run_step(forecast, t)
        self.assertFalse(self.predictors)
        self.executor.transient_mod = False
        self.run_step(forecast, 97)
        self.assertEqual([s for s, _ in self.predictors[-1].updates], [3.])

    def test_cancellation_removes_only_our_hook_and_requires_explicit_reset(self):
        class Cancelled(BaseException):
            pass

        dm = self.executor.class_obj
        upstream_calls = []
        handle = dm.final_layer.register_forward_pre_hook(
            lambda _module, _args: upstream_calls.append(True))
        try:
            for error in (InterruptedError("cancelled"), KeyboardInterrupt(), Cancelled()):
                for after in (False, True):
                    with self.subTest(error=type(error).__name__, after=after):
                        forecast = self.forecaster()
                        self.executor.error = error
                        self.executor.error_after_capture = after
                        before = len(self.predictors)
                        with self.assertRaises(type(error)):
                            self.run_step(forecast, 100)
                        self.assertEqual(len(dm.final_layer._forward_pre_hooks), 1)
                        self.assertEqual(len(self.predictors), before)
                        self.executor.error = None
                        with self.assertRaisesRegex(RuntimeError, "reset"):
                            self.run_step(forecast, 99)
                        forecast.reset("recovered")
                        self.run_step(forecast, 100)
                        self.assertEqual(len(dm.final_layer._forward_pre_hooks), 1)
        finally:
            handle.remove()
        self.assertTrue(upstream_calls)
        self.assertFalse(dm.final_layer._forward_pre_hooks)

    def test_missing_or_multiple_final_layer_calls_fail_and_clean_up(self):
        for attr in ("skip_layer", "double_layer"):
            with self.subTest(attr=attr):
                forecast = self.forecaster()
                setattr(self.executor, attr, True)
                try:
                    with self.assertRaisesRegex(ValueError, "final-layer feature"):
                        self.run_step(forecast, 100)
                finally:
                    setattr(self.executor, attr, False)
                self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)

    def test_projection_validation_propagates_without_a_native_retry(self):
        for failure in ("shape", "dtype", "nan", "inf", "not_tensor", "raises"):
            with self.subTest(failure=failure):
                forecast = self.forecaster()
                for t in (100, 99):
                    self.run_step(forecast, t)

                def bad_project(dm, t, feature):
                    result = dm.project(t, feature)
                    if failure == "shape":
                        return result.flatten()
                    if failure == "dtype":
                        return result.double()
                    if failure in ("nan", "inf"):
                        return result * float(failure)
                    if failure == "not_tensor":
                        return None
                    raise ArithmeticError("projection failed")

                forecast.project_feature = bad_project
                before = len(self.executor.calls)
                expected = ArithmeticError if failure == "raises" else ValueError
                with self.assertRaises(expected):
                    self.run_step(forecast, 98)
                self.assertEqual(len(self.executor.calls), before)
                self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)
                with self.assertRaisesRegex(RuntimeError, "reset"):
                    self.run_step(forecast, 97)

    def test_predicted_feature_validation_and_dependency_failures_propagate(self):
        for failure in ("shape", "integer", "nan", "factory", "update", "predict"):
            with self.subTest(failure=failure):
                forecast = self.forecaster()

                def fail(*_args):
                    raise ArithmeticError("injected failure")

                if failure == "factory":
                    forecast.predictor_factory = fail
                    with self.assertRaises(ArithmeticError):
                        self.run_step(forecast, 100)
                else:
                    self.run_step(forecast, 100)
                    predictor = self.predictors[-1]
                    if failure == "update":
                        predictor.update = fail
                        with self.assertRaises(ArithmeticError):
                            self.run_step(forecast, 99)
                    else:
                        self.run_step(forecast, 99)
                        if failure == "predict":
                            predictor.predict = fail
                        else:
                            predictor.bad_prediction = {
                                "shape": torch.zeros(1),
                                "integer": torch.zeros_like(predictor.feature, dtype=torch.int64),
                                "nan": torch.full_like(predictor.feature, float("nan")),
                            }[failure]
                        with self.assertRaises(ArithmeticError if failure == "predict" else ValueError):
                            self.run_step(forecast, 98)
                self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)

    def test_non_reentrant_calls_are_rejected_without_leaking_hooks(self):
        forecast = self.forecaster()

        def reentrant(feature):
            self.run_step(forecast, 100)

        forecast.predictor_factory = reentrant
        with self.assertRaisesRegex(RuntimeError, "non-reentrant"):
            self.run_step(forecast, 100)
        self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)

    def test_opt_in_runtime_mixes_independent_projected_branches_and_mutes_outer_capture(self):
        package_name = "regional_forecast_runtime_integration"
        package = ModuleType(package_name)
        package.__path__ = [str(SOURCE.parent)]
        sys.modules[package_name] = package
        spec = importlib.util.spec_from_file_location(package_name + ".runtime", SOURCE.parent / "runtime.py")
        runtime = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = runtime
        spec.loader.exec_module(runtime)
        dm = self.executor.class_obj
        keys = torch.tensor([2., 7.]).reshape(1, 2, 1, 1)
        reference = {"cache": [(keys, keys)], "sizes": [1, 1], "biases": [0., 0.]}
        attn = SimpleNamespace(_ref_kv_state=reference)
        dm.blocks = [SimpleNamespace(self_attn=attn)]
        spectrum = SimpleNamespace(captured_feat=None)
        dm.final_layer._spectrum_state = spectrum
        outer_captures, native_calls = [], []
        def outer_capture(module, args):
            if module._spectrum_state is not None:
                outer_captures.append(args[0])
        handle = dm.final_layer.register_forward_pre_hook(outer_capture)
        def execute(x, timesteps, context, fps=None, padding_mask=None, **kwargs):
            state = attn._ref_kv_state
            active, _ = state["cache"][0]
            self.assertEqual(active.shape[1], 1)
            value = active[0, 0, 0, 0]
            native_calls.append(value.item())
            return dm.project(timesteps, x.movedim(1, -1) + value)
        execute.class_obj = dm
        left = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        forecast = self.forecaster(num_steps=12)
        wrapper = runtime.make_wrapper((left, 1. - left), forecast=forecast)
        try:
            for step in range(12):
                result = wrapper(
                    execute, self.x, torch.tensor([100. - step]), self.context,
                    transformer_options={"cond_or_uncond": [0], "uuids": ["positive"]})
                expected = torch.where(left[None, :, None].bool(), 4., 49.) + 102. - step
                torch.testing.assert_close(result, expected.expand_as(result), atol=0, rtol=0)
                self.assertIs(attn._ref_kv_state, reference)
                self.assertIs(dm.final_layer._spectrum_state, spectrum)
                self.assertEqual(len(dm.final_layer._forward_pre_hooks), 1)
            self.assertFalse(outer_captures)
            self.assertEqual(len(self.predictors), 2)
            self.assertTrue(all(p.predictor is None for p in forecast._lanes.values()))
            self.assertEqual(native_calls.count(2.), 8)
            self.assertEqual(native_calls.count(7.), 8)
        finally:
            handle.remove()

    def test_constructor_rejects_invalid_schedule_or_injection(self):
        for options in (
                {"num_steps": 0}, {"num_steps": True}, {"warmup": -1},
                {"tail_actual_steps": -1}, {"refresh_interval": 0},
                {"predictor_factory": None}, {"project_feature": None},
                {"run_token": None}):
            with self.subTest(options=options):
                args = dict(run_token="one", num_steps=20, predictor_factory=self.factory,
                            project_feature=self.project)
                args.update(options)
                with self.assertRaises((TypeError, ValueError)):
                    RegionalForecast(**args)

    def test_installed_spectrum_predictor_and_projection_are_injectable_on_cpu(self):
        # The documented runner uses <install>/python_embeded/python.exe.
        # Load only the predictor and projection definition, not ComfyUI or
        # Spectrum's node registration/sampler imports.
        root = (Path(sys.executable).resolve().parents[1] /
                "ComfyUI/custom_nodes/comfyui-spectrum-ksampler")
        spec = importlib.util.spec_from_file_location(
            "regional_installed_spectrum_predictor",
            root / "_vendor/networks/spectrum_forecast.py")
        predictor_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(predictor_module)
        source = root / "spectrum.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "_spectrum_fast_forward"]
        self.assertEqual(len(functions), 1)
        namespace = {"torch": torch}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
        installed_project = namespace["_spectrum_fast_forward"]
        instances = []

        def factory(feature):
            predictor = predictor_module.SpectrumPredictor(
                m=4, lam=1e-3, w=0., device=feature.device,
                feature_shape=feature.shape, total_steps=12)
            instances.append(predictor)
            return predictor

        forecast = RegionalForecast("installed-interface", 12, factory, installed_project)
        for step in range(12):
            for branch, value in (((0,), 2.), ((1,), 7.)):
                self.executor.value = value
                self.assert_value(self.run_step(forecast, 100 - step, branch), value, 100 - step)
        self.assertEqual(len(instances), 2)
        for predictor in instances:
            self.assertEqual(predictor.cheb.t_buf.device.type, "cpu")
            self.assertEqual(predictor.cheb.t_buf.tolist(),
                             [0., 1., 2., 3., 4., 5., 7., 9., 10., 11.])
        self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)


if __name__ == "__main__":
    unittest.main()
