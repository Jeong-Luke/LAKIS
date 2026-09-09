# SPDX-FileCopyrightText: 2026 Luke Jeong
# SPDX-License-Identifier: MIT
"""LAKIS_SCOPE v2: globally consistent tiled latent refinement."""
from __future__ import annotations
import torch
import torch.nn.functional as F
import comfy.sample
import comfy.samplers


def _upscale_learned(upscale_model, image, preferred_tile=768):
    """Run the same Spandrel model with less overlapping tile work.

    ComfyUI's generic node always starts at 512 px.  Anime6B fits a larger
    tile on the development 12 GB target, which reduces duplicated overlap
    while retaining the exact model and its native 4x inference.  OOM safely
    falls back through the stock 512/256/128 sequence.
    """
    import comfy.model_management as model_management
    import comfy.utils

    device = model_management.get_torch_device()
    model_management.free_memory(
        model_management.module_size(upscale_model.model)
        + image.nelement() * image.element_size(),
        device,
    )
    upscale_model.to(device)
    value = image.movedim(-1, -3).to(device)
    tile, overlap = max(512, int(preferred_tile)), 32
    output_device = model_management.intermediate_device()
    try:
        while True:
            try:
                steps = value.shape[0] * comfy.utils.get_tiled_scale_steps(
                    value.shape[3], value.shape[2], tile_x=tile, tile_y=tile, overlap=overlap
                )
                progress = comfy.utils.ProgressBar(steps)
                result = comfy.utils.tiled_scale(
                    value, lambda part: upscale_model(part.float()),
                    tile_x=tile, tile_y=tile, overlap=overlap,
                    upscale_amount=upscale_model.scale, pbar=progress,
                    output_device=output_device,
                )
                break
            except Exception as error:
                model_management.raise_non_oom(error)
                tile = 512 if tile > 512 else tile // 2
                if tile < 128:
                    raise
    finally:
        upscale_model.to("cpu")
    return result.clamp(0, 1).movedim(-3, -1).to(model_management.intermediate_dtype())

def _positions(length, tile, overlap, shift=0):
    if length <= tile: return [0]
    stride = max(1, tile - overlap)
    result, cursor = [0], max(1, stride - (shift % stride))
    while cursor < length - tile:
        result.append(cursor); cursor += stride
    result.append(length - tile)
    return sorted(set(result))

def _window(h, w, device, dtype, ndim):
    wy = torch.hann_window(h, periodic=False, device=device, dtype=dtype)
    wx = torch.hann_window(w, periodic=False, device=device, dtype=dtype)
    return (wy[:, None] * wx[None, :]).clamp_min(0.04).view(*([1] * (ndim - 2)), h, w)

def _as_bhwc(image):
    if image.ndim == 5:
        if image.shape[1] != 1: raise RuntimeError(f"LAKIS_SCOPE expected one frame, got {tuple(image.shape)}")
        image = image[:, 0]
    if image.ndim != 4: raise RuntimeError(f"LAKIS_SCOPE expected BHWC image, got {tuple(image.shape)}")
    return image

def _resize_bhwc(image, h, w):
    image = _as_bhwc(image)
    if image.shape[1:3] == (h, w): return image
    value = F.interpolate(image.permute(0, 3, 1, 2), size=(h, w), mode="bicubic", align_corners=False)
    return value.permute(0, 2, 3, 1).clamp(0, 1)

def _low_frequency(value):
    shape = value.shape
    flat = value.reshape(-1, 1, *shape[-2:])
    return F.avg_pool2d(flat, 5, 1, 2).reshape(shape)

class LAKISSafeMasksCombineBatch:
    """Combine a mask batch without failing when a detector finds nothing."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"masks": ("MASK",)}}

    RETURN_TYPES, RETURN_NAMES = ("MASK",), ("mask",)
    FUNCTION, CATEGORY = "combine_masks", "LAKIS/Mask"

    def combine_masks(self, masks):
        if isinstance(masks, torch.Tensor):
            if masks.ndim >= 3 and masks.shape[0] == 0:
                return (torch.zeros((1, masks.shape[-2], masks.shape[-1]),
                                    device=masks.device, dtype=masks.dtype),)
            if masks.ndim == 2:
                return (masks.unsqueeze(0).clamp(0, 1),)
            if masks.ndim >= 3:
                return (masks.sum(dim=0, keepdim=True).clamp(0, 1),)
        mask_list = list(masks)
        if not mask_list:
            # Comfy normally preserves H/W on an empty MASK tensor. This is a
            # last-resort shape only for third-party nodes returning [].
            return (torch.zeros((1, 64, 64), dtype=torch.float32),)
        return (torch.stack(mask_list, dim=0).sum(dim=0, keepdim=True).clamp(0, 1),)

class _MultiDiffusionGuider(comfy.samplers.CFGGuider):
    """MultiDiffusion fusion with a shifted grid for each denoising call."""
    def __init__(self, model, tile_h, tile_w, overlap_h, overlap_w, batch_size):
        super().__init__(model)
        self.tile_h, self.tile_w = tile_h, tile_w
        self.overlap_h, self.overlap_w = overlap_h, overlap_w
        self.batch_size, self.call_index = max(1, int(batch_size)), 0

    def predict_noise(self, x, timestep, model_options={}, seed=None):
        h, w = x.shape[-2:]
        if h <= self.tile_h and w <= self.tile_w:
            return super().predict_noise(x, timestep, model_options, seed)
        stride_h, stride_w = max(1, self.tile_h-self.overlap_h), max(1, self.tile_w-self.overlap_w)
        ys = _positions(h, self.tile_h, self.overlap_h, self.call_index * max(1, stride_h//2))
        xs = _positions(w, self.tile_w, self.overlap_w, self.call_index * max(1, stride_w//2))
        self.call_index += 1
        entries, base_batch = [(y, x0) for y in ys for x0 in xs], x.shape[0]
        output, weights = torch.zeros_like(x), torch.zeros_like(x[:, :1])
        weight = _window(self.tile_h, self.tile_w, x.device, x.dtype, x.ndim)
        for start in range(0, len(entries), self.batch_size):
            group = entries[start:start+self.batch_size]
            tiles = torch.cat([x[..., y:y+self.tile_h, x0:x0+self.tile_w] for y, x0 in group], 0)
            tile_t = timestep.repeat(len(group)) if timestep.numel() == base_batch else timestep
            prediction = super().predict_noise(tiles, tile_t, model_options, seed)
            for index, (y, x0) in enumerate(group):
                part = prediction[index*base_batch:(index+1)*base_batch]
                output[..., y:y+self.tile_h, x0:x0+self.tile_w] += part * weight
                weights[..., y:y+self.tile_h, x0:x0+self.tile_w] += weight
        return output / weights.clamp_min(1e-6)

class LAKISScope:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",), "model": ("MODEL",), "positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
            "vae": ("VAE",), "upscale_model": ("UPSCALE_MODEL",),
            "upscale_by": ("FLOAT", {"default": 1.5, "min": 1.0, "max": 4.0, "step": 0.05}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
            "steps": ("INT", {"default": 2, "min": 1, "max": 20}),
            "cfg": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 30.0, "step": 0.1}),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS,), "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "denoise": ("FLOAT", {"default": 0.06, "min": 0.0, "max": 1.0, "step": 0.01}),
            "tile_size": ("INT", {"default": 768, "min": 256, "max": 2048, "step": 8}),
            "overlap": ("INT", {"default": 192, "min": 32, "max": 384, "step": 16}),
            "tile_batch_size": ("INT", {"default": 2, "min": 1, "max": 8}),
            "quality_mode": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES, RETURN_NAMES, FUNCTION, CATEGORY = ("IMAGE",), ("IMAGE",), "refine", "LAKIS/Upscale"

    def refine(self, image, model, positive, negative, vae, upscale_model, upscale_by, seed,
               steps, cfg, sampler_name, scheduler, denoise, tile_size, overlap, tile_batch_size,
               quality_mode=False):
        source_h, source_w = image.shape[1:3]
        target_h = max(64, int(round(source_h*float(upscale_by)/8))*8)
        target_w = max(64, int(round(source_w*float(upscale_by)/8))*8)
        upscaled = _resize_bhwc(_upscale_learned(upscale_model, image), target_h, target_w)
        if float(denoise) <= 0: return (upscaled,)

        # Candidate v3 fast path. At the workflow's very low denoise (0.07),
        # the costly diffusion pass mostly reproduces structure already present
        # in the learned pixel upscaler. Preserve that result and restore detail
        # with bounded multi-scale residuals instead (no VAE round trip).
        # Quality mode must perform a real VAE/diffusion refinement.  Letting
        # it enter the pixel-only shortcut merely sharpens enlarged source
        # pixels and can look blocky on flat or weakly detailed checkpoints.
        if not quality_mode and int(steps) <= 2 and float(denoise) <= 0.08:
            base = upscaled.permute(0, 3, 1, 2)
            fine = base - F.avg_pool2d(base, 3, 1, 1)
            medium_blur = F.avg_pool2d(base, 9, 1, 4)
            medium = F.avg_pool2d(base, 3, 1, 1) - medium_blur
            fine_gain = 0.26 if quality_mode else 0.18
            medium_gain = 0.09 if quality_mode else 0.06
            smooth_mix = 0.22 if quality_mode else 0.30
            micro_gain = 0.10 if quality_mode else 0.06
            enhanced = base + fine * fine_gain + medium * medium_gain
            local_min = -F.max_pool2d(-base, 3, 1, 1)
            local_max = F.max_pool2d(base, 3, 1, 1)
            enhanced = torch.maximum(local_min, torch.minimum(local_max, enhanced))
            # A 30% local-mean blend preserves the measured reference edge
            # variance while suppressing halos from residual sharpening.
            enhanced = enhanced * (1.0 - smooth_mix) + F.avg_pool2d(enhanced, 3, 1, 1) * smooth_mix
            # Edge-selective micro-contrast: reinforce real linework and eye/
            # hair texture, while leaving flat skin and bokeh regions alone.
            luminance = enhanced[:, 0:1] * 0.299 + enhanced[:, 1:2] * 0.587 + enhanced[:, 2:3] * 0.114
            detail = luminance - F.avg_pool2d(luminance, 3, 1, 1)
            grad_x = F.pad((luminance[..., 1:] - luminance[..., :-1]).abs(), (0, 1, 0, 0))
            grad_y = F.pad((luminance[..., 1:, :] - luminance[..., :-1, :]).abs(), (0, 0, 0, 1))
            edge_mask = ((grad_x + grad_y - 0.01) / 0.08).clamp(0, 1)
            enhanced = enhanced + detail * edge_mask * micro_gain
            return (enhanced.permute(0, 2, 3, 1).clamp(0, 1),)

        source = vae.encode(upscaled[..., :3])
        ratio_h, ratio_w = target_h/source.shape[-2], target_w/source.shape[-1]
        tile_h = min(source.shape[-2], max(8, round(int(tile_size)/ratio_h)))
        tile_w = min(source.shape[-1], max(8, round(int(tile_size)/ratio_w)))
        # A two-step full-frame pass is considerably cheaper than many tile
        # predictions and gives the strongest global consistency. Use it while
        # the latent stays within the 12 GB development target.
        if source.shape[-2] * source.shape[-1] <= 24000:
            tile_h, tile_w = source.shape[-2], source.shape[-1]
        overlap_h = min(tile_h-1, max(2, round(int(overlap)/ratio_h)))
        overlap_w = min(tile_w-1, max(2, round(int(overlap)/ratio_w)))
        # Anima/Wan latents are B,C,T,H,W. Their conditioning path already
        # expands temporal batches, so combining multiple spatial tiles in the
        # same model call duplicates that batch a second time. Keep the
        # MultiDiffusion fusion, but use the safe single-tile prediction path.
        effective_batch = 1 if source.ndim == 5 else tile_batch_size
        guider = _MultiDiffusionGuider(model, tile_h, tile_w, overlap_h, overlap_w, effective_batch)
        guider.set_conds(positive, negative); guider.set_cfg(float(cfg))
        # Quality mode remains distinct on the normal DETAIL path as well as
        # the two-step fast path: one extra diffusion step gives texture a
        # chance to settle without changing the user's denoise strength.
        effective_steps = int(steps) + (1 if quality_mode else 0)
        ks = comfy.samplers.KSampler(model, effective_steps, model.load_device, sampler_name, scheduler, float(denoise), model.model_options)
        noise, anchor = comfy.sample.prepare_noise(source, int(seed)), (0.30 if quality_mode else 0.35)
        def preserve_structure(step, x0, x, total_steps):
            strength = anchor * (1.0-float(step)/max(1.0, float(total_steps)))
            current_low, source_low = _low_frequency(x), _low_frequency(source.to(x.device, x.dtype))
            x.copy_(x-current_low+torch.lerp(current_low, source_low, strength))
        sampled = guider.sample(noise, source, comfy.samplers.sampler_object(ks.sampler), ks.sigmas,
                                callback=preserve_structure, disable_pbar=False, seed=int(seed))
        decoded = _resize_bhwc(vae.decode(sampled), target_h, target_w)
        # Restore the inexpensive pixel-upscaler's high-frequency line detail
        # after the global VAE round trip, without discarding diffusion changes.
        base = upscaled.permute(0, 3, 1, 2)
        high = base - F.avg_pool2d(base, 5, 1, 2)
        decoded_mix = 0.62 if quality_mode else 0.55
        high_gain = 0.30 if quality_mode else 0.35
        result = decoded * decoded_mix + upscaled * (1.0 - decoded_mix) + high.permute(0, 2, 3, 1) * high_gain
        return (result.clamp(0, 1),)

NODE_CLASS_MAPPINGS = {
    "LAKIS_SCOPE": LAKISScope,
    "LAKIS_SafeMasksCombineBatch": LAKISSafeMasksCombineBatch,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LAKIS_SCOPE": "LAKIS_SCOPE v3 (Frequency Balanced / Quality)",
    "LAKIS_SafeMasksCombineBatch": "LAKIS Safe Masks Combine Batch",
}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
