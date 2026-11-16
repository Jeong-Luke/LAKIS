"""Separate native model predictions, then mix them by output-frame masks."""
from __future__ import annotations

from contextlib import contextmanager

import torch

from .masking import mixing_plan

WRAPPER_KEY = "lakis_regional_snapref"


class _ReferenceCacheView:
    """Select reference tokens lazily, without duplicating every block's K/V."""
    def __init__(self, cache, sizes, keep):
        self.cache = cache
        self.spans = []
        start = 0
        for index, size in enumerate(sizes):
            end = start + size
            if index in keep:
                if self.spans and self.spans[-1][1] == start:
                    self.spans[-1] = (self.spans[-1][0], end)
                else:
                    self.spans.append((start, end))
            start = end

    def __len__(self):
        return len(self.cache)

    def __getitem__(self, index):
        pair = self.cache[index]
        if len(self.spans) == 1:
            start, end = self.spans[0]
            return tuple(tensor[:, start:end] for tensor in pair)
        return tuple(torch.cat([tensor[:, start:end] for start, end in self.spans], dim=1)
                     for tensor in pair)


def _reference_state(original, keep):
    if not keep:
        return None
    if len(keep) == len(original["sizes"]):
        return original
    indices = [index for index in range(len(original["sizes"])) if index in keep]
    return {
        **original,
        "cache": _ReferenceCacheView(original["cache"], original["sizes"], indices),
        "sizes": [original["sizes"][index] for index in indices],
        "biases": [original["biases"][index] for index in indices],
    }


@contextmanager
def _without_spectrum_capture(dm, suppressed):
    """Spectrum cannot forecast mixed predictions; do not collect unused features.

    This is the tested Spectrum capture-hook protocol, not a replacement hook.
    Suppress it for the whole call, including reference-free CFG/background.
    """
    layer = getattr(dm, "final_layer", None)
    state = getattr(layer, "_spectrum_state", None) if suppressed else None
    if state is None:
        yield
        return
    layer._spectrum_state = None
    try:
        yield
    finally:
        layer._spectrum_state = state


def cfg_safe_wrapper(native):
    """Repair metadata on the tested SnapRef revision's sequential CFG split.

    Keep the native cache, LoRA and full-batch paths. Only downstream calls
    that SnapRef sliced receive branch-local flags and conditioning UUIDs.
    """
    def wrapper(executor, x, timesteps, context, fps=None, padding_mask=None, **kwargs):
        flags = tuple(kwargs.get("transformer_options", {}).get("cond_or_uncond", ()))
        split_index = 0

        def downstream(xs, ts, ctx, fps=None, padding_mask=None, **branch_kwargs):
            nonlocal split_index
            if xs.shape[0] != x.shape[0]:
                if (len(flags) < 2 or x.shape[0] != xs.shape[0] * len(flags)
                        or split_index >= len(flags)):
                    raise ValueError("Regional SnapRef: incompatible upstream CFG split.")
                if (branch_kwargs.get("control") is not None or fps is not None
                        or padding_mask is not None):
                    raise ValueError(
                        "Regional SnapRef: split CFG with ControlNet, fps or padding masks is not supported.")
                options = dict(branch_kwargs.get("transformer_options", {}))
                options["cond_or_uncond"] = [flags[split_index]]
                if "uuids" in options:
                    options["uuids"] = [options["uuids"][split_index]]
                branch_kwargs["transformer_options"] = options
                split_index += 1
            return executor(xs, ts, ctx, fps, padding_mask, **branch_kwargs)

        downstream.class_obj = executor.class_obj
        result = native(downstream, x, timesteps, context, fps, padding_mask, **kwargs)
        if split_index not in (0, len(flags)):
            raise ValueError("Regional SnapRef: incomplete upstream CFG split.")
        return result

    return wrapper


def make_wrapper(masks, *, forecast=None):
    plans = {}

    def plan_for(x):
        key = (*x.shape[-2:], x.device)
        if key not in plans:
            plans.clear()
            plans[key] = mixing_plan(masks, *x.shape[-2:], x.device)
        return plans[key]

    def spectrum_cache_veto(*, input_x, **_kwargs):
        # Spectrum captures only the final branch's pre-final feature and
        # bypasses this wrapper on forecast steps. A mixed prediction must
        # therefore run the real branches, not forecast that single feature.
        return len(plan_for(input_x)) == 1

    def wrapper(executor, x, timesteps, context, fps=None, padding_mask=None, **kwargs):
        dm = executor.class_obj
        plan = plan_for(x)

        def predict(keep):
            if forecast is None:
                return executor(x, timesteps, context, fps, padding_mask, **kwargs)
            return forecast.run(executor, x, timesteps, context, fps, padding_mask,
                                branch_key=keep, **kwargs)

        with _without_spectrum_capture(dm, len(plan) > 1):
            originals = [(block.self_attn, block.self_attn._ref_kv_state) for block in dm.blocks]
            state = originals[0][1]
            # SnapRef owns its native hooks, cache and target LoRA. No module
            # forward or attention kernel is replaced by this extension.
            if state is None:
                return predict(())
            if "record" in state:
                return executor(x, timesteps, context, fps, padding_mask, **kwargs)
            if x.ndim != 5 or x.shape[2] != 1 or dm.patch_temporal != 1:
                raise ValueError("Regional SnapRef currently supports ANIMA still images only.")
            metadata = kwargs.get("transformer_options", {}).get("comfycouple_regions_v2", {})
            if metadata.get("anima_region_mode") == "full_block":
                raise ValueError("Regional SnapRef: use ComfyCouple cross_attention, not full_block.")
            if len(state["sizes"]) != len(masks) or len(state["biases"]) != len(masks):
                raise ValueError("Regional SnapRef: reference cache does not match the mask list.")
            output, output_dtype = None, None
            try:
                for keep, weight in plan:
                    for attn, original in originals:
                        attn._ref_kv_state = _reference_state(original, keep)
                    prediction = predict(keep)
                    if prediction.shape != x.shape:
                        raise ValueError("Regional SnapRef: model prediction frame changed.")
                    if len(plan) == 1:
                        return prediction
                    output_dtype = prediction.dtype
                    contribution = prediction.float() * weight
                    output = contribution if output is None else output + contribution
                return output.to(output_dtype)
            finally:
                for attn, original in originals:
                    attn._ref_kv_state = original

    wrapper.spectrum_cache_veto = spectrum_cache_veto
    return wrapper
