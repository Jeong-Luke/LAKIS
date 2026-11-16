"""Keep Spectrum observations in RAM; bound temporary GPU regression storage."""
from __future__ import annotations

import torch


class HostHistoryPredictor:
    def __init__(self, native, factory, device, settings, *, chunk_features=1048576):
        if type(chunk_features) is not int or chunk_features < 1:
            raise ValueError("chunk_features must be a positive integer.")
        self.native = native
        self.factory = factory
        self.device = device
        self.settings = dict(settings)
        self.chunk_features = chunk_features

    def update(self, step, feature):
        self.native.update(step, feature.detach().to(device="cpu"))

    @torch.no_grad()
    def predict(self, step):
        # Ridge regression and Taylor blending are independent per feature
        # column. Reuse the installed predictor and all observations, but fit
        # only one bounded column range on the GPU at a time.
        source = self.native.cheb
        history = source._H_buf
        times = source.t_buf.to(self.device)
        width = history.shape[1]
        output = None
        for start in range(0, width, self.chunk_features):
            end = min(start + self.chunk_features, width)
            settings = {
                **self.settings, "device": self.device, "feature_shape": (1, end - start)}
            predictor = self.factory(**settings)
            predictor.cheb.t_buf = times
            predictor.cheb._H_buf = history[:, start:end].to(self.device)
            predictor.cheb._shape = torch.Size((1, end - start))
            prediction = predictor.predict(step).reshape(-1)
            if output is None:
                # Taylor/chebyshev blending may promote fp16 history to fp32.
                # Preserve the installed predictor's result, not storage dtype.
                output = torch.empty(width, device=self.device, dtype=prediction.dtype)
            output[start:end].copy_(prediction)
            del predictor
        return output.reshape(source._shape)
