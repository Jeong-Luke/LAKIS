"""Request lifetime and actual independent forecasts through the public wrapper."""
import importlib
from types import SimpleNamespace
import unittest

import torch

from installer.tests.test_regional_reference_predictions import package
from installer.tests.test_regional_reference_forecast import Executor, Predictor


Session = importlib.import_module(package.__name__ + ".forecast_session").ForecastSession
make_wrapper = importlib.import_module(package.__name__ + ".runtime").make_wrapper


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.predictors = []
        self.projections = []

        def factory(**settings):
            predictor = Predictor(torch.zeros(settings["feature_shape"], device=settings["device"]))
            self.predictors.append((predictor, settings))
            return predictor

        def project(dm, t, feature):
            self.projections.append(feature.clone())
            return dm.project(t, feature)

        self.session = Session(SimpleNamespace(
            SpectrumPredictor=factory, _spectrum_fast_forward=project))
        self.executor = Executor()
        self.x = torch.zeros(1, 2, 1, 2, 4)
        self.context = torch.zeros(1, 3, 4)
        left = torch.tensor([[[1., 1., 0., 0.], [1., 1., 0., 0.]]])
        kv = torch.zeros(1, 2, 1, 1)
        self.state = {"cache": [(kv, kv)], "sizes": [1, 1], "biases": [0., 0.]}
        self.attn = SimpleNamespace(_ref_kv_state=self.state)
        self.executor.class_obj.blocks = [SimpleNamespace(self_attn=self.attn)]
        self.wrapper = make_wrapper((left, 1. - left), forecast=self.session)

    def execute_steps(self, steps=20):
        for step in range(steps):
            for flag, uid in ((1, "negative"), (0, "positive")):
                self.wrapper(
                    self.executor, self.x, torch.tensor([100. - step]), self.context,
                    transformer_options={"cond_or_uncond": [flag], "uuids": [uid]})
        return self.x

    def sample(self, executor=None, steps=20):
        return self.session.sample(
            executor or (lambda *args, **kwargs: self.execute_steps(steps)),
            self.x, self.x, object(), torch.linspace(1, 0, steps + 1))

    def test_each_sample_creates_independent_branches_and_releases_all_features(self):
        for run in range(2):
            before = len(self.predictors)
            self.sample()
            new = self.predictors[before:]
            # Two masks, each with independent conditional/unconditional history.
            self.assertEqual(len(new), 4)
            self.assertTrue(all(p.predictions for p, _ in new))
            self.assertTrue(all(s["total_steps"] == 20 for _, s in new))
            self.assertTrue(all(p.updates[0][0] == 0 for p, _ in new))
            self.assertIsNone(self.session.forecast)
            self.assertIs(self.attn._ref_kv_state, self.state)
            self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)
        self.assertGreater(len(self.projections), 0)

    def test_cancel_releases_state_and_next_sample_starts_fresh(self):
        def cancelled(*args, **kwargs):
            self.wrapper(
                self.executor, self.x, torch.tensor([100.]), self.context,
                transformer_options={"cond_or_uncond": [0], "uuids": ["positive"]})
            self.executor.error = KeyboardInterrupt("cancelled")
            self.execute_steps()
        with self.assertRaises(KeyboardInterrupt):
            self.sample(cancelled)
        self.assertIsNone(self.session.forecast)
        self.assertIs(self.attn._ref_kv_state, self.state)
        self.assertFalse(self.executor.class_obj.final_layer._forward_pre_hooks)
        self.executor.error = None
        self.sample()
        self.assertIsNone(self.session.forecast)

    def test_schedule_comes_from_sigmas_and_preserves_executor_arguments(self):
        marker, sampler = object(), object()
        sigmas = torch.tensor([1., .5, 0.])
        def execute(noise, latent, actual_sampler, actual_sigmas, *args, **kwargs):
            self.assertEqual(self.session.forecast.num_steps, 2)
            self.assertIs(noise, self.x)
            self.assertIs(latent, self.x)
            self.assertIs(actual_sampler, sampler)
            self.assertIs(actual_sigmas, sigmas)
            self.assertEqual(args, (marker,))
            self.assertEqual(kwargs, {"seed": 42})
            return marker
        self.assertIs(self.session.sample(execute, self.x, self.x, sampler, sigmas, marker, seed=42), marker)
        self.assertIsNone(self.session.forecast)

    def test_reentry_is_rejected_and_short_or_extra_evaluations_finish_natively(self):
        def reentrant(*args, **kwargs):
            with self.assertRaisesRegex(RuntimeError, "serial"):
                self.sample()
            self.assertIsNotNone(self.session.forecast)
            return self.execute_steps(3)
        self.sample(reentrant, steps=3)
        # A solver may evaluate the model more often than its nominal steps.
        self.sample(lambda *args, **kwargs: self.execute_steps(6), steps=3)
        self.assertEqual(len(self.projections), 0)
        self.assertIsNone(self.session.forecast)
        self.sample(lambda *args, **kwargs: self.x, steps=0)
        self.assertIsNone(self.session.forecast)


if __name__ == "__main__":
    unittest.main()
