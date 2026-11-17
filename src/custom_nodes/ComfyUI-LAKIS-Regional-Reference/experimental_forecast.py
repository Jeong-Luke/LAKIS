"""Opt-in, request-scoped forecasting of *unmixed* regional branch features.

Nothing imports or enables this experiment by default. Inject the installed
SpectrumPredictor through ``predictor_factory(detached_feature)`` and inject
Spectrum's ``_spectrum_fast_forward`` as ``project_feature(dm, t, feature)``.
The factory owns Spectrum parameters/readiness (the default six real warmup
observations suit its default degree four). No predictor/projection is copied.

Steps are zero-based, counted independently for (branch_key, CFG flag tuple).
Each stable signature has its own whole-batch predictor, including ordered
conditioning UUIDs. Signatures changing mid-request discard that lane's
features, not its schedule. Unsupported calls invalidate the branch's features;
untrackable/nonmonotonic timesteps or invalid CFG flags disable that branch for
the rest of the request. Repeated timesteps run natively without training or
moving the refresh clock. A completed lane cannot run again, even at the same
timestep; other already-started lanes may finish. Explicit reset is mandatory
before another generation. Failures also require reset.

The caller must serialize use of the diffusion model (including outside this
object), preserve conditioning UUID meaning, and pass a stable branch_key for
each keep tuple. Concurrent/reentrant calls on this instance are rejected.
This is inference-only and offers no generated-image quality guarantee.

Mod Guidance is opt-in through a projector that preserves its live hooks.
Only the installed hook protocol is supported; changing its values discards
history, and modulation that appears inside an executor cannot train history.
"""
from __future__ import annotations

import math
from threading import Lock
from uuid import UUID

import torch


class _Lane:
    def __init__(self):
        self.step = -1
        self.timestep = None
        self.direction = None
        self.complete = False
        self.clear_history()

    def clear_history(self):
        self.key = None
        self.model = None  # Retain identity while id(model) is in the key.
        self.predictor = None
        self.feature_spec = None
        self.output_dtype = None
        self.observations = 0
        self.last_actual = -1
        self.modulation = None


class RegionalForecast:
    def __init__(self, run_token, num_steps, predictor_factory, project_feature, *,
                 warmup=6, tail_actual_steps=3, refresh_interval=2, mod_guidance=False):
        for name, value, minimum in (
                ("num_steps", num_steps, 1), ("warmup", warmup, 0),
                ("tail_actual_steps", tail_actual_steps, 0),
                ("refresh_interval", refresh_interval, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}.")
        if not callable(predictor_factory) or not callable(project_feature):
            raise TypeError("predictor_factory and project_feature must be callable.")
        if type(mod_guidance) is not bool:
            raise TypeError("mod_guidance must be boolean.")
        self.num_steps = num_steps
        self.warmup = warmup
        self.tail_actual_steps = tail_actual_steps
        self.refresh_interval = refresh_interval
        self.predictor_factory = predictor_factory
        self.project_feature = project_feature
        self.mod_guidance = mod_guidance
        self._lock = Lock()
        self.reset(run_token)

    def reset(self, run_token):
        """Discard every lane/history and explicitly arm one generation request."""
        if run_token is None:
            raise ValueError("An explicit, non-None run_token is required.")
        hash(run_token)
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("RegionalForecast requires serial calls and resets.")
        try:
            self.run_token = run_token
            self._lanes = {}
            self._disabled = set()
            self._closing = False
            self._failed = False
            self.counts = {"actual": 0, "forecast": 0, "fallback": 0}
        finally:
            self._lock.release()

    def _invalidate(self, branch_key):
        for (branch, _flags), lane in self._lanes.items():
            if branch == branch_key:
                lane.clear_history()

    @staticmethod
    def _flags(options, batch_size):
        flags = options.get("cond_or_uncond")
        if (not isinstance(flags, (list, tuple)) or not flags
                or any(type(flag) is not int or flag not in (0, 1) for flag in flags)
                or batch_size % len(flags)):
            return None
        return tuple(flags)

    @staticmethod
    def _uuids(options, flags):
        values = options.get("uuids")
        if not isinstance(values, (list, tuple)) or len(values) != len(flags):
            return None
        if any(not isinstance(uid, (str, UUID)) or not str(uid).strip() for uid in values):
            return None
        values = tuple(str(uid) for uid in values)
        if len(set(zip(flags, values))) != len(values):
            return None
        return values

    @staticmethod
    def _timestep(timesteps, batch_size):
        if (not torch.is_tensor(timesteps) or timesteps.ndim not in (1, 2)
                or timesteps.numel() not in (1, batch_size)
                or not torch.isfinite(timesteps).all().item()):
            return None
        first = timesteps.reshape(-1)[0]
        if not (timesteps == first).all().item():
            return None
        return float(first.item())

    @staticmethod
    def _mod_active(dm):
        return (getattr(dm, "_mod_pooled_proj", None) is not None
                or getattr(dm, "_anima_mod_block_state", None) is not None
                or getattr(getattr(dm, "t_embedding_norm", None),
                           "_anima_mod_delta", None) is not None)

    def _mod_context(self, dm, batch_size):
        if not self._mod_active(dm):
            return ()
        if not self.mod_guidance:
            return None
        norm = getattr(dm, "t_embedding_norm", None)
        delta = getattr(norm, "_anima_mod_delta", None)
        state = getattr(dm, "_anima_mod_block_state", None)
        unit = getattr(state, "delta_unit", None)
        schedule = getattr(state, "schedule", None)
        final_w = getattr(state, "final_w", None)
        if (getattr(norm, "_anima_mod_hook_installed", False) is not True
                or getattr(dm, "_anima_mod_block_hooks_installed", False) is not True
                or not torch.is_tensor(delta) or delta.ndim != 3
                or delta.shape[0] not in (1, batch_size) or delta.shape[1] != 1
                or delta.shape[2] < 1 or not delta.is_floating_point()
                or not torch.is_tensor(unit) or tuple(unit.shape) != (1, delta.shape[2])
                or not unit.is_floating_point()
                or not isinstance(schedule, (list, tuple))
                or len(schedule) != len(dm.blocks)
                or any(type(w) not in (int, float) or not math.isfinite(w) for w in schedule)
                or type(final_w) not in (int, float) or not math.isfinite(final_w)
                or not torch.isfinite(delta).all().item()
                or not torch.isfinite(unit).all().item()):
            return None
        return tuple(schedule), final_w, delta, unit

    @staticmethod
    def _same_mod_context(left, right):
        if left is None or right is None or len(left) != len(right):
            return False
        if not left:
            return True
        return (left[:2] == right[:2]
                and all((tuple(a.shape), a.dtype, a.device) == (tuple(b.shape), b.dtype, b.device)
                        and torch.equal(a, b) for a, b in zip(left[2:], right[2:])))

    @staticmethod
    def _snapshot_mod_context(context):
        if not context:
            return context
        return (*context[:2], *(tensor.detach().clone() for tensor in context[2:]))

    @staticmethod
    def _spec(tensor):
        return tuple(tensor.shape), tensor.dtype, tensor.device

    @staticmethod
    def _validate(tensor, shape, device, *, dtype=None, label):
        if (not torch.is_tensor(tensor) or tuple(tensor.shape) != tuple(shape)
                or tensor.device != device or not tensor.is_floating_point()
                or (dtype is not None and tensor.dtype != dtype)
                or not torch.isfinite(tensor).all().item()):
            raise ValueError(f"RegionalForecast: invalid {label} shape/dtype/device/finiteness.")

    def _actual(self, executor, x, timesteps, context, fps, padding_mask, kwargs, modulation):
        dm = executor.class_obj
        captured = []
        stable_modulation = True

        def capture(_module, args):
            nonlocal stable_modulation
            if captured or not args or not torch.is_tensor(args[0]):
                raise ValueError("RegionalForecast requires exactly one final-layer feature.")
            captured.append(args[0].detach().clone())
            stable_modulation = self._same_mod_context(
                modulation, self._mod_context(dm, x.shape[0]))

        handle = dm.final_layer.register_forward_pre_hook(capture)
        try:
            result = executor(x, timesteps, context, fps, padding_mask, **kwargs)
        finally:
            # Includes BaseException cancellations, and leaves upstream hooks intact.
            handle.remove()
        if len(captured) != 1:
            raise ValueError("RegionalForecast did not capture a final-layer feature.")
        return result, captured[0], stable_modulation and self._same_mod_context(
            modulation, self._mod_context(dm, x.shape[0]))

    def run(self, executor, x, timesteps, context, fps=None, padding_mask=None, *,
            branch_key, **kwargs):
        """Return this branch's native-space prediction, never a masked mixture.

        Actual calls return the executor's original tensor; forecast calls return
        the injected projection unchanged after validation against a real output.
        CFG metadata is ``kwargs['transformer_options']`` with ordered
        ``cond_or_uncond`` (0/1) and equally sized nonempty string/UUID ``uuids``.
        """
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("RegionalForecast requires serial, non-reentrant calls.")
        try:
            if self._failed:
                raise RuntimeError("RegionalForecast failed; call reset(run_token).")
            hash(branch_key)
            options = kwargs.get("transformer_options", {})
            options = options if isinstance(options, dict) else {}
            flags = self._flags(options, x.shape[0])
            lane_key = (branch_key, flags)
            lane = self._lanes.get(lane_key) if flags is not None else None
            if lane is None and self._closing:
                raise RuntimeError("RegionalForecast schedule completed; call reset(run_token).")
            if lane is not None and lane.complete:
                raise RuntimeError("RegionalForecast schedule completed; call reset(run_token).")
            if lane is None and flags is not None:
                lane = self._lanes[lane_key] = _Lane()

            timestep = self._timestep(timesteps, x.shape[0])
            repeated = lane is not None and timestep is not None and timestep == lane.timestep
            if lane is not None and timestep is not None and not repeated:
                if lane.timestep is not None:
                    direction = 1 if timestep > lane.timestep else -1
                    if lane.direction is not None and lane.direction != direction:
                        self._disabled.add(branch_key)
                    lane.direction = direction
                lane.step += 1
                lane.timestep = timestep
            if flags is None or timestep is None:
                self._disabled.add(branch_key)

            dm = getattr(executor, "class_obj", None)
            modulation = self._mod_context(dm, x.shape[0])
            uuids = self._uuids(options, flags) if flags is not None else None
            supported = (
                branch_key not in self._disabled and uuids is not None
                and x.ndim == 5 and x.shape[2] == 1 and x.is_floating_point()
                and all(size > 0 for size in x.shape)
                and x.shape[-2] % 2 == 0 and x.shape[-1] % 2 == 0
                and getattr(dm, "patch_temporal", None) == 1
                and callable(getattr(getattr(dm, "final_layer", None),
                                     "register_forward_pre_hook", None))
                and torch.is_tensor(context) and context.ndim == 3
                and context.shape[0] == x.shape[0] and context.is_floating_point()
                and fps is None and padding_mask is None
                and kwargs.get("control") is None and modulation is not None)
            if not supported:
                self._invalidate(branch_key)
                self.counts["fallback"] += 1
                result = executor(x, timesteps, context, fps, padding_mask, **kwargs)
            elif self.num_steps <= max(1, self.warmup) + self.tail_actual_steps:
                # No forecast can occur between warmup and the real-step tail.
                # In particular, a three-step HighRez needs no feature history.
                self.counts["actual"] += 1
                result = executor(x, timesteps, context, fps, padding_mask, **kwargs)
            else:
                key = (branch_key, id(dm), *self._spec(x), flags, uuids, *self._spec(context))
                if lane.key != key or not self._same_mod_context(lane.modulation, modulation):
                    lane.clear_history()
                    lane.key, lane.model = key, dm
                    lane.modulation = self._snapshot_mod_context(modulation)
                actual = (
                    repeated or lane.predictor is None
                    or lane.observations < max(1, self.warmup) or lane.step < self.warmup
                    or lane.step >= self.num_steps - self.tail_actual_steps
                    or lane.step - lane.last_actual >= self.refresh_interval)
                if actual:
                    self.counts["actual"] += 1
                    result, feature, stable_modulation = self._actual(
                        executor, x, timesteps, context, fps, padding_mask, kwargs, lane.modulation)
                    self._validate(result, x.shape, x.device, label="native output")
                    self._validate(feature, feature.shape, x.device, label="captured feature")
                    if feature.shape[0] != x.shape[0]:
                        raise ValueError("RegionalForecast: captured feature batch changed.")
                    if not stable_modulation:
                        self._invalidate(branch_key)
                    elif not repeated:
                        spec = self._spec(feature)
                        if lane.feature_spec is not None and (
                                spec != lane.feature_spec or result.dtype != lane.output_dtype):
                            lane.clear_history()
                            lane.key, lane.model = key, dm
                            lane.modulation = self._snapshot_mod_context(modulation)
                        with torch.no_grad():
                            if lane.predictor is None:
                                lane.predictor = self.predictor_factory(feature)
                            lane.predictor.update(float(lane.step), feature)
                        lane.feature_spec, lane.output_dtype = spec, result.dtype
                        lane.observations += 1
                        lane.last_actual = lane.step
                else:
                    self.counts["forecast"] += 1
                    with torch.no_grad():
                        feature = lane.predictor.predict(float(lane.step))
                        shape, _dtype, device = lane.feature_spec
                        self._validate(feature, shape, device, label="predicted feature")
                        result = self.project_feature(dm, timesteps, feature)
                    self._validate(result, x.shape, x.device, dtype=lane.output_dtype,
                                   label="projected output")

            if lane is not None and timestep is not None and lane.step == self.num_steps - 1:
                lane.complete = True
                lane.clear_history()
                self._closing = True
            return result
        except BaseException:
            for lane in self._lanes.values():
                lane.clear_history()
            self._failed = True
            raise
        finally:
            self._lock.release()
