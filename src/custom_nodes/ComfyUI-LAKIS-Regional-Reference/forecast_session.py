"""Opt-in Spectrum predictors whose lifetime is one outer sampler invocation."""
from __future__ import annotations

import importlib
import logging
from threading import Lock
from uuid import uuid4

import torch

from .experimental_forecast import RegionalForecast
from .host_history import HostHistoryPredictor


logger = logging.getLogger(__name__)


class ForecastSession:
    def __init__(self, spectrum):
        self.spectrum = spectrum
        self.forecast = None
        self._lock = Lock()

    def sample(self, executor, noise, latent_image, sampler, sigmas, *args, **kwargs):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Regional SnapRef forecasting requires serial sampler invocations.")
        try:
            steps = len(sigmas) - 1
            if steps < 1:
                return executor(noise, latent_image, sampler, sigmas, *args, **kwargs)

            def predictor(feature):
                settings = {
                    "m": 3, "lam": .1, "w": .3, "device": torch.device("cpu"),
                    "feature_shape": feature.shape, "total_steps": steps, "K": 100}
                native = self.spectrum.SpectrumPredictor(**settings)
                if feature.device.type == "cpu":
                    return native
                return HostHistoryPredictor(
                    native, self.spectrum.SpectrumPredictor, feature.device, settings)

            self.forecast = RegionalForecast(
                uuid4().hex, steps, predictor, self._project_feature, mod_guidance=True)
            return executor(noise, latent_image, sampler, sigmas, *args, **kwargs)
        finally:
            # Success, error and cancellation all release every branch's features.
            if self.forecast is not None:
                logger.info("Regional SnapRef acceleration calls: %s", self.forecast.counts)
                self.forecast.reset(uuid4().hex)
            self.forecast = None
            self._lock.release()

    def _project_feature(self, dm, timesteps, feature):
        # We run INSIDE Mod Guidance's APPLY_MODEL wrapper. Its live norm
        # and final-layer hooks already apply the current text/steering once.
        # Spectrum's outer-cache path adds _mod_pooled_proj separately; that
        # addition would double the norm hook here. Never disable the hooks.
        pooled = getattr(dm, "_mod_pooled_proj", None)
        if pooled is None:
            return self.spectrum._spectrum_fast_forward(dm, timesteps, feature)
        dm._mod_pooled_proj = None
        try:
            return self.spectrum._spectrum_fast_forward(dm, timesteps, feature)
        finally:
            dm._mod_pooled_proj = pooled

    def run(self, executor, x, timesteps, context, fps=None, padding_mask=None, *,
            branch_key, **kwargs):
        forecast = self.forecast
        # Direct model calls have no sampler schedule. Multi-evaluation solvers
        # may exhaust the nominal schedule: finish natively rather than reuse
        # predictions beyond the measured window.
        if forecast is None or forecast._closing:
            return executor(x, timesteps, context, fps, padding_mask, **kwargs)
        return forecast.run(executor, x, timesteps, context, fps, padding_mask,
                            branch_key=branch_key, **kwargs)


def create_session():
    import nodes

    try:
        sampler = nodes.NODE_CLASS_MAPPINGS["SpectrumKSampler"]
    except KeyError as error:
        raise RuntimeError(
            "Regional SnapRef acceleration requires comfyui-spectrum-ksampler.") from error
    module = importlib.import_module(sampler.__module__)
    spectrum = importlib.import_module(module.__package__ + ".spectrum")
    return ForecastSession(spectrum)
