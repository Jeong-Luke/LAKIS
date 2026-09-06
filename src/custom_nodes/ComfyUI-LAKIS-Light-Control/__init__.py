# SPDX-FileCopyrightText: 2026 灰暗x
# SPDX-FileCopyrightText: 2026 Luke Jeong
# SPDX-License-Identifier: AGPL-3.0-or-later
# LAKIS Light Control - LightMap v0.3.19 + production/debug execution settings
#
# Prompt generation has intentionally been removed.
# The controller outputs a LAKIS_LIGHT data object.
# LAKIS Relight applies screen-space / normal-map / depth-derived relighting.

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn.functional as F


# ---------------------------------------------------------------------
# Optional AI geometry estimator (Depth Anything V2 Small, Hugging Face)
# ---------------------------------------------------------------------
_GEOM_PROCESSOR = None
_GEOM_MODEL = None
_GEOM_DEVICE = None
_GEOM_MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"


def _geometry_cache_dir():
    try:
        import folder_paths
        from pathlib import Path
        root = Path(folder_paths.models_dir) / "lakis" / "depth-anything-v2-small-hf"
    except Exception:
        from pathlib import Path
        root = Path(__file__).resolve().parent / "models" / "depth-anything-v2-small-hf"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def _get_comfy_device():
    try:
        import comfy.model_management as mm
        return mm.get_torch_device()
    except Exception:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _load_geometry_model(allow_download=True):
    global _GEOM_PROCESSOR, _GEOM_MODEL, _GEOM_DEVICE

    if _GEOM_PROCESSOR is not None and _GEOM_MODEL is not None:
        return _GEOM_PROCESSOR, _GEOM_MODEL, _GEOM_DEVICE

    try:
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    except Exception as e:
        raise RuntimeError(
            "LAKIS Geometry Estimator requires 'transformers'. "
            "Run INSTALL_REQUIREMENTS.bat inside ComfyUI-LAKIS-Light-Control, "
            "then restart ComfyUI."
        ) from e

    cache_dir = _geometry_cache_dir()
    kwargs = {
        "cache_dir": cache_dir,
        "local_files_only": not bool(allow_download),
    }

    try:
        processor = AutoImageProcessor.from_pretrained(_GEOM_MODEL_ID, **kwargs)
        model = AutoModelForDepthEstimation.from_pretrained(_GEOM_MODEL_ID, **kwargs)
    except Exception as e:
        if not bool(allow_download):
            raise RuntimeError(
                "Depth Anything V2 Small is not cached locally. "
                "Enable 'allow_download' once, or place the model in the LAKIS model cache."
            ) from e
        raise RuntimeError(
            "Could not download/load Depth Anything V2 Small. "
            "Check internet access and Hugging Face connectivity."
        ) from e

    device = _get_comfy_device()
    model = model.eval().to(device)

    _GEOM_PROCESSOR = processor
    _GEOM_MODEL = model
    _GEOM_DEVICE = device
    return processor, model, device


def _release_geometry_model():
    global _GEOM_PROCESSOR, _GEOM_MODEL, _GEOM_DEVICE
    _GEOM_PROCESSOR = None
    _GEOM_MODEL = None
    _GEOM_DEVICE = None
    try:
        import comfy.model_management as mm
        mm.soft_empty_cache()
    except Exception:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _image_tensor_to_pil_list(image):
    try:
        import numpy as np
        from PIL import Image
    except Exception as e:
        raise RuntimeError("Pillow and NumPy are required for LAKIS Geometry Estimator.") from e

    result = []
    cpu = image[..., :3].detach().clamp(0.0, 1.0).cpu()
    for item in cpu:
        arr = (item.numpy() * 255.0 + 0.5).astype(np.uint8)
        result.append(Image.fromarray(arr, mode="RGB"))
    return result


def _normalize_depth_per_image(depth):
    # depth: B,H,W
    b = depth.shape[0]
    flat = depth.reshape(b, -1)
    lo = flat.amin(dim=1).view(b, 1, 1)
    hi = flat.amax(dim=1).view(b, 1, 1)
    return ((depth - lo) / (hi - lo).clamp_min(1e-6)).clamp(0.0, 1.0)


def _depth_to_normal(depth, strength=6.0, smoothing=5):
    # depth is normalized with nearer areas brighter / larger.
    k = int(smoothing)
    if k < 1:
        k = 1
    if k % 2 == 0:
        k += 1

    d = depth.unsqueeze(1)
    if k > 1:
        d = F.avg_pool2d(d, kernel_size=k, stride=1, padding=k // 2)
    d = d[:, 0]

    left = F.pad(d[:, :, :-1], (1, 0), mode="replicate")
    right = F.pad(d[:, :, 1:], (0, 1), mode="replicate")
    up = F.pad(d[:, :-1, :], (0, 0, 1, 0), mode="replicate")
    down = F.pad(d[:, 1:, :], (0, 0, 0, 1), mode="replicate")

    dx = (right - left) * 0.5
    dy = (down - up) * 0.5

    s = max(0.01, float(strength))
    nx = -dx * s
    ny = dy * s
    nz = torch.ones_like(nx)

    n = torch.stack((nx, ny, nz), dim=-1)
    return F.normalize(n, dim=-1, eps=1e-6)


class LAKISGeometryEstimator:
    """
    AI depth estimation -> stable screen-space normal map.

    Uses Depth Anything V2 Small through Hugging Face Transformers.
    The first run can automatically download the model.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "allow_download": ("BOOLEAN", {"default": True}),
                "keep_model_loaded": ("BOOLEAN", {"default": True}),
                "depth_near": (["White", "Black"], {"default": "White"}),
                "normal_strength": ("FLOAT", {"default": 6.0, "min": 0.5, "max": 30.0, "step": 0.1}),
                "normal_smoothing": ([1, 3, 5, 7, 9, 11], {"default": 5}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("DEPTH_MAP", "NORMAL_MAP")
    FUNCTION = "estimate"
    CATEGORY = "LAKIS/Light"

    def estimate(
        self,
        image,
        allow_download,
        keep_model_loaded,
        depth_near,
        normal_strength,
        normal_smoothing,
    ):
        image = image[..., :3].clamp(0.0, 1.0)
        b, h, w, _ = image.shape

        processor, model, device = _load_geometry_model(bool(allow_download))
        pil_images = _image_tensor_to_pil_list(image)

        inputs = processor(images=pil_images, return_tensors="pt")
        inputs = {
            k: (v.to(device) if torch.is_tensor(v) else v)
            for k, v in inputs.items()
        }

        with torch.inference_mode():
            outputs = model(**inputs)
            depth = outputs.predicted_depth
            depth = F.interpolate(
                depth.unsqueeze(1),
                size=(h, w),
                mode="bicubic",
                align_corners=False,
            )[:, 0]

        depth = depth.float()
        depth = _normalize_depth_per_image(depth)

        # Depth Anything relative depth is used as near-white by default.
        if str(depth_near) == "Black":
            depth = 1.0 - depth

        # For normal generation, always use a "near = larger value" height field.
        normal_depth = depth if str(depth_near) == "White" else (1.0 - depth)
        normals = _depth_to_normal(
            normal_depth,
            strength=float(normal_strength),
            smoothing=int(normal_smoothing),
        )

        depth_rgb = depth.unsqueeze(-1).repeat(1, 1, 1, 3).to(image.device, image.dtype)
        normal_rgb = ((normals + 1.0) * 0.5).clamp(0.0, 1.0).to(image.device, image.dtype)

        if not bool(keep_model_loaded):
            _release_geometry_model()

        return depth_rgb, normal_rgb



def _clamp(v, lo, hi):
    try:
        v = float(v)
    except Exception:
        return lo
    return max(lo, min(hi, v))


def _light_vector(pos_x: float, pos_y: float):
    """
    Camera-space light direction, pointing FROM the surface TOWARD the light.

    UI convention retained from LAKIS:
      X +0.50 = camera-left light
      X -0.50 = camera-right light
      X  0.00 = frontal light
      X +/-1 = rear light
      Y + = upper light
      Y - = lower light

    Camera-space normal convention:
      +X = image-right
      +Y = image-up
      +Z = toward camera/front
    """
    az = _clamp(pos_x, -1.0, 1.0) * math.pi
    el = _clamp(pos_y, -1.0, 1.0) * (math.pi / 2.0)
    h = math.cos(el)

    # UI +X means light appears on camera-left, hence negative camera-space X.
    lx = -math.sin(az) * h
    ly = math.sin(el)
    lz = math.cos(az) * h

    length = math.sqrt(lx * lx + ly * ly + lz * lz) or 1.0
    return (lx / length, ly / length, lz / length)


def _light_color(mode: str):
    table = {
        "Neutral": (1.00, 1.00, 1.00),
        "Warm": (1.00, 0.78, 0.58),
        "Cool": (0.62, 0.78, 1.00),
        "Cyan": (0.38, 1.00, 1.00),
        "Magenta": (1.00, 0.38, 0.78),
        "Cyan + Magenta": (0.82, 0.64, 1.00),
        "Golden": (1.00, 0.72, 0.32),
        "Moonlight": (0.55, 0.68, 1.00),
    }
    return table.get(str(mode), table["Neutral"])


def _resize_image_like(tensor: torch.Tensor, h: int, w: int):
    # Comfy IMAGE: B,H,W,C
    if tensor is None:
        return None
    if tensor.shape[1] == h and tensor.shape[2] == w:
        return tensor
    t = tensor.permute(0, 3, 1, 2)
    t = F.interpolate(t, size=(h, w), mode="bilinear", align_corners=False)
    return t.permute(0, 2, 3, 1)


def _luma(image):
    rgb = image[..., :3]
    return (
        rgb[..., 0] * 0.2126
        + rgb[..., 1] * 0.7152
        + rgb[..., 2] * 0.0722
    )


def _depth_gray(depth):
    if depth.shape[-1] >= 3:
        return _luma(depth)
    return depth[..., 0]


def _gradient_normals(height_field: torch.Tensor, strength: float):
    """
    height_field: B,H,W in [0,1].
    Produces camera-space normals B,H,W,3.
    This is a 2.5D approximation.
    """
    s = max(0.01, float(strength))

    left = F.pad(height_field[:, :, :-1], (1, 0), mode="replicate")
    right = F.pad(height_field[:, :, 1:], (0, 1), mode="replicate")
    up = F.pad(height_field[:, :-1, :], (0, 0, 1, 0), mode="replicate")
    down = F.pad(height_field[:, 1:, :], (0, 0, 0, 1), mode="replicate")

    dx = (right - left) * 0.5
    dy = (down - up) * 0.5

    # Camera-space: +Y is image-up.
    nx = -dx * s
    ny = dy * s
    nz = torch.ones_like(nx)

    n = torch.stack((nx, ny, nz), dim=-1)
    return F.normalize(n, dim=-1, eps=1e-6)


def _normal_from_normal_image(normal_map, flip_y: bool):
    rgb = normal_map[..., :3].clamp(0.0, 1.0)
    n = rgb * 2.0 - 1.0
    if flip_y:
        n = n.clone()
        n[..., 1] = -n[..., 1]
    return F.normalize(n, dim=-1, eps=1e-6)


def _pseudo_normal_from_image(image, strength: float):
    # Dependency-free fallback. Not physically exact.
    # Luminance is treated as a shallow height field.
    lum = _luma(image).clamp(0.0, 1.0)
    # A small blur prevents texture/noise from dominating the pseudo geometry.
    t = lum.unsqueeze(1)
    t = F.avg_pool2d(t, kernel_size=7, stride=1, padding=3)
    return _gradient_normals(t[:, 0], strength)


def _normal_from_depth(depth_map, invert: bool, strength: float):
    d = _depth_gray(depth_map).clamp(0.0, 1.0)
    if invert:
        d = 1.0 - d
    t = d.unsqueeze(1)
    t = F.avg_pool2d(t, kernel_size=5, stride=1, padding=2)
    return _gradient_normals(t[:, 0], strength)


def _normal_preview(n):
    return ((n + 1.0) * 0.5).clamp(0.0, 1.0)


class LAKISLightControl:
    """
    Same mouse-driven light placement concept as the prompt prototype,
    but now outputs numerical light data only.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True}),
                "pos_x": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01}),
                "pos_y": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01}),
                "pos_z": ("FLOAT", {"default": 0.10, "min": -1.0, "max": 1.0, "step": 0.01}),
                "intensity": ("FLOAT", {"default": 0.80, "min": 0.0, "max": 2.0, "step": 0.01}),
                "ambient": ("FLOAT", {"default": 0.20, "min": 0.0, "max": 1.0, "step": 0.01}),
                "shadow": ("FLOAT", {"default": 0.65, "min": 0.0, "max": 1.0, "step": 0.01}),
                "exposure": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01}),
                "rim": ("FLOAT", {"default": 0.00, "min": 0.0, "max": 1.0, "step": 0.01}),
                "color_mode": (
                    ["Neutral", "Warm", "Cool", "Cyan", "Magenta", "Cyan + Magenta", "Golden", "Moonlight"],
                    {"default": "Neutral"},
                ),
            }
        }

    RETURN_TYPES = ("LAKIS_LIGHT",)
    RETURN_NAMES = ("LIGHT",)
    FUNCTION = "build"
    CATEGORY = "LAKIS/Light"

    def build(
        self,
        enabled,
        pos_x,
        pos_y,
        pos_z,
        intensity,
        ambient,
        shadow,
        exposure,
        rim,
        color_mode,
    ):
        vec = _light_vector(pos_x, pos_y)
        color = _light_color(color_mode)

        light = {
            "enabled": bool(enabled),
            "pos_x": float(pos_x),
            "pos_y": float(pos_y),
            "pos_z": float(pos_z),
            "vector": tuple(float(v) for v in vec),
            "intensity": float(intensity),
            "ambient": float(ambient),
            "shadow": float(shadow),
            "exposure": float(exposure),
            "rim": float(rim),
            "color_mode": str(color_mode),
            "color": tuple(float(v) for v in color),
        }
        return (light,)



def _rear_depth_rim_mask(depth: torch.Tensor) -> torch.Tensor:
    """
    Build a soft silhouette/depth-discontinuity mask for rear-light rendering.

    depth: B,H,W normalized relative depth.
    returns: B,H,W,1 in [0,1]

    This is intentionally screen-space. A single image does not contain the
    hidden back-facing surface, so true rear diffuse lighting cannot be
    reconstructed. The stable approximation is to brighten depth silhouettes
    and grazing visible normals when the light moves behind the scene.
    """
    d = depth.unsqueeze(1)

    # Central-ish absolute gradient using neighboring pixels.
    dx_l = F.pad(d[..., :, 1:] - d[..., :, :-1], (0, 1, 0, 0))
    dy_t = F.pad(d[..., 1:, :] - d[..., :-1, :], (0, 0, 0, 1))
    grad = (dx_l.abs() + dy_t.abs()).clamp_min(0.0)

    # Relative-depth maps vary by scene. Scale enough to preserve major
    # silhouette/corner discontinuities while suppressing shallow surface noise.
    edge = (grad * 10.0).clamp(0.0, 1.0)

    # Expand a few pixels around the discontinuity then soften it.
    # At 1024px-wide images this yields a visible but not oversized rim.
    edge = F.max_pool2d(edge, kernel_size=9, stride=1, padding=4)
    edge = F.avg_pool2d(edge, kernel_size=7, stride=1, padding=3)

    return edge.permute(0, 2, 3, 1).clamp(0.0, 1.0)


def _odd_kernel(value: int, minimum: int = 3, maximum: int = 101) -> int:
    value = max(minimum, min(maximum, int(value)))
    if value % 2 == 0:
        value += 1
    return min(value, maximum if maximum % 2 == 1 else maximum - 1)


def _soft_blur_mask(mask_b1hw: torch.Tensor, kernel: int, passes: int = 2) -> torch.Tensor:
    kernel = _odd_kernel(kernel, 3, 101)
    out = mask_b1hw
    pad = kernel // 2
    for _ in range(max(1, int(passes))):
        out = F.avg_pool2d(out, kernel_size=kernel, stride=1, padding=pad)
    return out.clamp(0.0, 1.0)





def _flood_connected_mask(
    candidate_b1hw: torch.Tensor,
    seed_y: torch.Tensor,
    seed_x: torch.Tensor,
) -> torch.Tensor:
    """Flood candidate pixels connected to the seed."""
    b, _, h, w = candidate_b1hw.shape
    grown = torch.zeros_like(candidate_b1hw)

    for bi in range(b):
        sy = int(max(0, min(h - 1, int(seed_y[bi].item()))))
        sx = int(max(0, min(w - 1, int(seed_x[bi].item()))))
        grown[bi, 0, sy, sx] = 1.0

    # Small seed neighborhood only.
    grown = F.max_pool2d(grown, 5, 1, 2) * candidate_b1hw

    steps = min(160, max(32, int(max(h, w) / 3)))
    for _ in range(steps):
        nxt = F.max_pool2d(grown, 5, 1, 2) * candidate_b1hw
        if torch.equal((nxt > 0.5), (grown > 0.5)):
            grown = nxt
            break
        grown = nxt

    return grown.clamp(0.0, 1.0)


def _mask_validity(mask_bhw1: torch.Tensor, require_ground_contact: bool = False):
    """
    Per-image safety gate.

    If subject extraction accidentally becomes "the room", shadow processing is
    disabled instead of touching the image.
    """
    m = mask_bhw1[..., 0].float().clamp(0.0, 1.0)
    b, h, w = m.shape
    valid = torch.zeros((b,), device=m.device, dtype=torch.bool)

    for bi in range(b):
        hard = m[bi] > 0.38
        area = float(hard.float().mean().item())

        if area < 0.018 or area > 0.55:
            continue

        rows = torch.nonzero(hard.any(dim=1), as_tuple=False).flatten()
        cols = torch.nonzero(hard.any(dim=0), as_tuple=False).flatten()
        if rows.numel() < 2 or cols.numel() < 2:
            continue

        top = int(rows.min().item())
        bottom = int(rows.max().item())
        left = int(cols.min().item())
        right = int(cols.max().item())

        hfrac = (bottom - top + 1) / max(1, h)
        wfrac = (right - left + 1) / max(1, w)

        if hfrac < 0.18 or hfrac > 0.99:
            continue
        if wfrac < 0.035 or wfrac > 0.86:
            continue

        total = float(hard.sum().item())
        band_y = max(2, int(h * 0.035))
        band_x = max(2, int(w * 0.035))

        border_count = (
            hard[:band_y].sum()
            + hard[-band_y:].sum()
            + hard[:, :band_x].sum()
            + hard[:, -band_x:].sum()
        ).item()
        border_ratio = float(border_count) / max(1.0, total)

        if border_ratio > 0.22:
            continue

        cx = 0.5 * (left + right) / max(1, w - 1)
        cy = 0.5 * (top + bottom) / max(1, h - 1)
        if not (0.08 <= cx <= 0.92 and 0.08 <= cy <= 0.92):
            continue

        if require_ground_contact:
            # 2.5D floor projection is meaningful only if the visible subject
            # reaches reasonably low in the frame.
            if bottom / max(1, h - 1) < 0.58:
                continue

        valid[bi] = True

    return valid



def _normal_variation_score(normal_map: torch.Tensor, target_h: int, target_w: int):
    """
    Planar walls are broad nearly-uniform normal fields.
    A character has much higher local normal variation because face/hair/clothes/
    limbs turn through many orientations.

    Returns B,H,W variation in [0,1].
    """
    if normal_map is None:
        return None

    n = _resize_image_like(normal_map, target_h, target_w)
    if n is None:
        return None

    n = n[..., :3].float().clamp(0.0, 1.0)
    n = n * 2.0 - 1.0
    n = n / torch.linalg.norm(n, dim=-1, keepdim=True).clamp_min(1e-6)

    nchw = n.permute(0, 3, 1, 2)

    # Compare vector to its local mean normal. Flat room planes -> near zero.
    k1 = _odd_kernel(max(9, min(target_h, target_w) // 28), 9, 25)
    mean_n = F.avg_pool2d(nchw, k1, 1, k1 // 2)
    mean_n = mean_n / torch.linalg.norm(mean_n, dim=1, keepdim=True).clamp_min(1e-6)

    angular = (1.0 - (nchw * mean_n).sum(dim=1).clamp(-1.0, 1.0)) * 0.5

    # Broaden the signal so the seed can land inside the body rather than only
    # on a sharp silhouette contour.
    k2 = _odd_kernel(max(13, min(target_h, target_w) // 18), 13, 35)
    angular = F.avg_pool2d(
        angular.unsqueeze(1), k2, 1, k2 // 2
    )[:, 0]

    b = angular.shape[0]
    q = torch.quantile(
        angular.reshape(b, -1).float(), 0.93, dim=1
    ).clamp_min(1e-5)

    return (angular / q.view(b, 1, 1)).clamp(0.0, 1.0)


def _depth_objectness_score(d: torch.Tensor) -> torch.Tensor:
    """Fallback objectness from local Depth deviation; no background assumption."""
    b, h, w = d.shape
    large_k = _odd_kernel(max(31, min(h, w) // 4), 31, 91)
    broad = F.avg_pool2d(
        d.unsqueeze(1), large_k, 1, large_k // 2
    )[:, 0]
    residual = (d - broad).abs()

    q = torch.quantile(
        residual.reshape(b, -1).float(), 0.92, dim=1
    ).clamp_min(1e-5)
    return (residual / q.view(b, 1, 1)).clamp(0.0, 1.0)


def _subject_seed_score(d: torch.Tensor, normal_map=None) -> torch.Tensor:
    """
    Pick the SEED from a central, non-planar object.

    The 7.0.14 failure happened because Depth-only objectness could prefer a room
    plane/corner. Normal-map variation now dominates seed selection.
    """
    b, h, w = d.shape
    device = d.device

    depth_obj = _depth_objectness_score(d)
    normal_var = _normal_variation_score(normal_map, h, w)

    xs = torch.linspace(-1.0, 1.0, w, device=device)
    ys = torch.linspace(-1.0, 1.0, h, device=device)
    yy, xx = torch.meshgrid(ys, xs, indexing="ij")

    # Stronger central prior than 7.0.14. It affects seed selection only.
    center_prior = torch.exp(
        -((xx / 0.58) ** 2)
        - (((yy + 0.02) / 0.78) ** 2)
    ).view(1, h, w)

    border = torch.ones((1, h, w), device=device)
    bx = max(2, int(w * 0.15))
    by = max(2, int(h * 0.09))
    border[:, :by] = 0.0
    border[:, -by:] = 0.0
    border[:, :, :bx] = 0.0
    border[:, :, -bx:] = 0.0

    if normal_var is not None:
        # Normal-map variation is the primary discriminator between a person
        # and large planar room surfaces.
        score = (
            0.72 * normal_var
            + 0.28 * depth_obj
        )
        # Require at least a small amount of non-planarity.
        score = score * (0.18 + 0.82 * normal_var)
    else:
        score = depth_obj

    return score * (0.18 + 0.82 * center_prior) * border


def _depth_subject_mask(depth: torch.Tensor, normal_map=None) -> torch.Tensor:
    """
    v0.3.13:
      normal-map variation selects the subject seed;
      Depth continuity grows the connected subject.

    No global background-depth assumption is used.
    """
    depth = depth.float().clamp(0.0, 1.0)
    b, h, w = depth.shape
    device = depth.device

    scale = min(1.0, 360.0 / float(max(h, w)))
    sh = max(64, int(round(h * scale)))
    sw = max(64, int(round(w * scale)))

    d = F.interpolate(
        depth.unsqueeze(1),
        size=(sh, sw),
        mode="bilinear",
        align_corners=False,
    )[:, 0]
    d_smooth = F.avg_pool2d(d.unsqueeze(1), 5, 1, 2)[:, 0]

    normal_small = None
    if normal_map is not None:
        normal_small = _resize_image_like(normal_map, sh, sw)

    seed_score = _subject_seed_score(d_smooth, normal_small)
    flat_idx = seed_score.reshape(b, -1).argmax(dim=1)
    seed_y = torch.div(flat_idx, sw, rounding_mode="floor")
    seed_x = flat_idx % sw

    batch = torch.arange(b, device=device)
    seed_depth = d_smooth[batch, seed_y, seed_x].view(b, 1, 1)

    gx = F.pad((d_smooth[:, :, 1:] - d_smooth[:, :, :-1]).abs(), (0, 1))
    gy = F.pad((d_smooth[:, 1:, :] - d_smooth[:, :-1, :]).abs(), (0, 0, 0, 1))
    grad = gx + gy

    grad_q = torch.quantile(
        grad.reshape(b, -1).float(), 0.84, dim=1
    ).clamp(0.018, 0.13).view(b, 1, 1)

    normal_var = _normal_variation_score(normal_small, sh, sw) if normal_small is not None else None

    # More conservative first bands than 7.0.14; a room plane sharing the seed
    # depth is less likely to flood immediately.
    bands = (0.060, 0.085, 0.115, 0.155, 0.205)

    best = torch.zeros((b, 1, sh, sw), device=device, dtype=torch.float32)
    best_score = torch.full((b,), -1e9, device=device)

    for band in bands:
        depth_close = (d_smooth - seed_depth).abs() <= band
        continuous = grad <= (grad_q * 1.30 + 0.008)

        candidate = (depth_close & continuous).float().unsqueeze(1)

        # If a normal map exists, suppress broad planar regions weakly, but don't
        # require variation everywhere because shirt/legs can be locally smooth.
        if normal_var is not None:
            nv = normal_var.unsqueeze(1)
            candidate = candidate * (0.58 + 0.42 * nv)

        candidate = (candidate > 0.35).float()

        # Only tiny gap bridging.
        candidate = F.max_pool2d(candidate, 3, 1, 1)

        for bi in range(b):
            sy = int(seed_y[bi].item())
            sx = int(seed_x[bi].item())
            candidate[bi, 0, sy, sx] = 1.0

        comp = _flood_connected_mask(candidate, seed_y, seed_x)

        near = F.max_pool2d(comp, 7, 1, 3)
        relaxed = (
            ((d_smooth - seed_depth).abs() <= band * 1.18)
            & (grad <= (grad_q * 1.70 + 0.014))
        ).float().unsqueeze(1)

        comp = torch.maximum(comp, near * relaxed * 0.62)
        comp = _soft_blur_mask(comp, 5, passes=1)

        for bi in range(b):
            hard = comp[bi, 0] > 0.42
            area = float(hard.float().mean().item())

            if area < 0.012 or area > 0.46:
                score = -1000.0
            else:
                rows = torch.nonzero(hard.any(dim=1), as_tuple=False).flatten()
                cols = torch.nonzero(hard.any(dim=0), as_tuple=False).flatten()

                if rows.numel() < 2 or cols.numel() < 2:
                    score = -1000.0
                else:
                    top = int(rows.min().item())
                    bottom = int(rows.max().item())
                    left = int(cols.min().item())
                    right = int(cols.max().item())

                    hf = (bottom - top + 1) / sh
                    wf = (right - left + 1) / sw
                    cx = 0.5 * (left + right) / max(1, sw - 1)
                    cy = 0.5 * (top + bottom) / max(1, sh - 1)

                    if hf < 0.18 or wf < 0.035 or wf > 0.72:
                        score = -1000.0
                    else:
                        area_pref = 1.0 - min(1.0, abs(area - 0.16) / 0.23)
                        center_pref = 1.0 - min(
                            1.0,
                            (((cx - 0.5) / 0.43) ** 2 + ((cy - 0.52) / 0.52) ** 2) ** 0.5,
                        )
                        human_shape = min(1.0, hf / max(0.16, wf * 1.30))

                        # Reject room-like components whose bounding box is too
                        # wide relative to height.
                        aspect = hf / max(1e-5, wf)
                        aspect_pref = min(1.0, max(0.0, aspect / 1.45))

                        score = (
                            1.7 * area_pref
                            + 1.5 * center_pref
                            + 0.9 * human_shape
                            + 0.8 * aspect_pref
                        )

                        if normal_var is not None:
                            nv_inside = float(
                                (normal_var[bi] * hard.float()).sum().item()
                                / max(1.0, hard.float().sum().item())
                            )
                            score += 1.1 * nv_inside

            if score > float(best_score[bi].item()):
                best_score[bi] = score
                best[bi:bi+1] = comp[bi:bi+1]

    soft = F.interpolate(
        best,
        size=(h, w),
        mode="bilinear",
        align_corners=False,
    ).clamp(0.0, 1.0)

    return soft.permute(0, 2, 3, 1)



def _auto_occluder_mask(image: torch.Tensor, depth: torch.Tensor, normal_map=None) -> torch.Tensor:
    del image
    return _depth_subject_mask(depth, normal_map=normal_map)


def _project_25d_shadow(
    occluder: torch.Tensor,
    light_vector,
    projection_length: float,
    softness: float,
    contact: float,
) -> torch.Tensor:
    """
    Screen-space cast-shadow projection.

    v0.3.17 rear-light rule:
      - crop the actual SAM3 silhouette;
      - vertically flip it so feet begin at the contact point and head lands farthest;
      - compress the whole silhouette into the AVAILABLE foreground floor;
      - paste that floor footprint directly into the canvas.

    This avoids the sparse/scatter collapse that produced only a tiny contact
    blob in the real v7.0.19 test.
    """
    m = occluder[..., 0].float().clamp(0.0, 1.0)
    b, h, w = m.shape
    device = m.device

    lx, ly, lz = [float(v) for v in light_vector]
    plen = max(0.10, float(projection_length))

    yy = torch.arange(h, device=device, dtype=torch.float32).view(h, 1).expand(h, w)
    xx = torch.arange(w, device=device, dtype=torch.float32).view(1, w).expand(h, w)

    result = torch.zeros_like(m)

    for bi in range(b):
        mb = m[bi]

        row_mass = mb.sum(dim=1)
        col_mass = mb.sum(dim=0)
        if float(row_mass.max().item()) <= 1e-5 or float(col_mass.max().item()) <= 1e-5:
            continue

        active_rows = torch.nonzero(
            row_mass > max(1.5, float(row_mass.max().item()) * 0.055),
            as_tuple=False,
        ).flatten()
        active_cols = torch.nonzero(
            col_mass > max(1.5, float(col_mass.max().item()) * 0.055),
            as_tuple=False,
        ).flatten()

        if active_rows.numel() < 2 or active_cols.numel() < 2:
            continue

        top_i = int(active_rows.min().item())
        foot_i = int(active_rows.max().item())
        left_i = int(active_cols.min().item())
        right_i = int(active_cols.max().item())

        body_h = max(8, foot_i - top_i + 1)
        body_w = max(6, right_i - left_i + 1)
        cx = 0.5 * (left_i + right_i)

        # ----------------------------------------------------
        # A) Rear light: explicit flattened silhouette on floor.
        # ----------------------------------------------------
        if lz < -0.35 and abs(lz) >= max(abs(lx), abs(ly)) * 0.75:
            available = max(0, (h - 1) - foot_i)

            if available >= 6:
                crop = mb[top_i:foot_i + 1, left_i:right_i + 1]
                crop = crop.view(1, 1, crop.shape[0], crop.shape[1])

                # Use most of the visible foreground floor.
                desired_h = int(round(body_h * min(0.48, 0.34 * plen)))
                target_h = int(
                    max(
                        8,
                        min(
                            max(8, desired_h),
                            max(8, int(round(available * 0.90))),
                        ),
                    )
                )

                # If there is abundant floor, allow the shadow to extend farther.
                if available > body_h * 0.22:
                    target_h = min(
                        int(round(available * 0.92)),
                        max(target_h, int(round(body_h * 0.30))),
                    )

                floor_ratio = target_h / max(1.0, float(body_h))
                target_w = int(
                    round(
                        body_w
                        * (
                            1.00
                            + 0.28 * min(1.0, floor_ratio * 3.0)
                        )
                    )
                )
                target_w = max(8, min(w, target_w))

                # Resize the whole person silhouette, then flip vertically:
                # feet -> contact edge, head -> far edge of floor shadow.
                flat_shadow = F.interpolate(
                    crop,
                    size=(target_h, target_w),
                    mode="bilinear",
                    align_corners=False,
                )[0, 0]
                flat_shadow = torch.flip(flat_shadow, dims=[0])

                # Make the far end a little softer/weaker.
                fade = torch.linspace(
                    1.0,
                    0.62,
                    target_h,
                    device=device,
                    dtype=torch.float32,
                ).view(target_h, 1)
                flat_shadow = flat_shadow * fade

                # Rear-diagonal light may drift slightly sideways.
                side_shift = int(round((-lx) * target_h * 0.32))
                x0 = int(round(cx - target_w * 0.5 + side_shift))
                x1 = x0 + target_w
                y0 = foot_i + 1
                y1 = min(h, y0 + target_h)

                sx0 = 0
                sx1 = target_w

                if x0 < 0:
                    sx0 = -x0
                    x0 = 0
                if x1 > w:
                    sx1 -= (x1 - w)
                    x1 = w

                usable_h = max(0, y1 - y0)
                usable_w = max(0, x1 - x0)

                if usable_h > 0 and usable_w > 0:
                    patch = flat_shadow[:usable_h, sx0:sx1]
                    result[bi, y0:y1, x0:x1] = torch.maximum(
                        result[bi, y0:y1, x0:x1],
                        patch,
                    )

            # Add a small grounded contact patch independently of available floor.
            bottom_band = mb * (yy >= (foot_i - max(3, int(body_h * 0.035)))).float()
            contact_patch = F.max_pool2d(
                bottom_band.view(1, 1, h, w),
                kernel_size=13,
                stride=1,
                padding=6,
            )[0, 0]
            # Nudge contact below the feet by one/two pixels.
            contact_patch = torch.roll(contact_patch, shifts=2, dims=0)
            contact_patch[:2] = 0.0
            result[bi] = torch.maximum(
                result[bi],
                contact_patch * max(0.0, min(1.0, float(contact))),
            )

        # ----------------------------------------------------
        # B) Other directions: connected silhouette displacement.
        # ----------------------------------------------------
        else:
            top = float(top_i)
            foot = float(foot_i)
            left = float(left_i)
            right = float(right_i)
            body_hf = max(8.0, foot - top)

            height_factor = ((foot - yy) / body_hf).clamp(0.0, 1.0)

            sx = -lx
            sy = ly - 0.58 * max(0.0, lz)

            n = max(1e-6, (sx * sx + sy * sy) ** 0.5)
            sx /= n
            sy /= n

            desired = body_hf * plen * 0.72
            caps = [desired]

            if sx > 0.05:
                caps.append(max(4.0, ((w - 1.0) - right) / sx * 0.92))
            elif sx < -0.05:
                caps.append(max(4.0, left / (-sx) * 0.92))

            if sy > 0.05:
                caps.append(max(4.0, ((h - 1.0) - foot) / sy * 0.92))
            elif sy < -0.05:
                caps.append(max(4.0, top / (-sy) * 0.92))

            shadow_len = max(4.0, min(caps))
            dist = height_factor.pow(0.82)

            tx = torch.round(xx + sx * shadow_len * dist).long()
            ty = torch.round(yy + sy * shadow_len * dist).long()

            valid = (
                (mb > 0.025)
                & (tx >= 0)
                & (tx < w)
                & (ty >= 0)
                & (ty < h)
            )

            src = mb[valid]
            target_index = (ty[valid] * w + tx[valid]).flatten()

            flat = torch.zeros(h * w, device=device, dtype=torch.float32)
            flat.scatter_add_(0, target_index, src.float())
            projected = flat.view(h, w).clamp(0.0, 1.0)

            result[bi] = torch.maximum(result[bi], projected)

    softness = max(0.0, min(1.0, float(softness)))

    # Rear-floor footprints need less blur than the older sparse scatter map.
    k_small = _odd_kernel(3 + int(softness * 12), 3, 19)
    k_large = _odd_kernel(9 + int(softness * 24), 9, 35)

    r = result.unsqueeze(1)
    r = F.max_pool2d(r, kernel_size=3, stride=1, padding=1)
    blur_small = _soft_blur_mask(r, k_small, passes=1)
    blur_large = _soft_blur_mask(r, k_large, passes=1)
    r = (0.68 * blur_small + 0.32 * blur_large).clamp(0.0, 1.0)

    # Never darken the person itself.
    subject = occluder.permute(0, 3, 1, 2).float().clamp(0.0, 1.0)
    protected = F.max_pool2d(subject, 5, 1, 2)
    r = r * (1.0 - protected * 0.98)

    return r.permute(0, 2, 3, 1).clamp(0.0, 1.0)



def _normalize_subject_mask(mask, target_h: int, target_w: int, device, dtype):
    """
    Accept ComfyUI MASK or IMAGE-like mask and return B,H,W,1 in [0,1].
    SAM3 usually produces MASK as B,H,W.
    """
    if mask is None:
        return None

    if not torch.is_tensor(mask):
        return None

    m = mask.to(device=device, dtype=torch.float32)

    if m.ndim == 2:
        m = m.unsqueeze(0)

    if m.ndim == 3:
        # B,H,W
        m = m.unsqueeze(1)
    elif m.ndim == 4:
        if m.shape[-1] in (1, 3, 4):
            # B,H,W,C -> grayscale
            if m.shape[-1] == 1:
                m = m[..., 0].unsqueeze(1)
            else:
                m = m[..., :3].mean(dim=-1).unsqueeze(1)
        elif m.shape[1] == 1:
            # already B,1,H,W
            pass
        else:
            return None
    else:
        return None

    if m.shape[-2:] != (target_h, target_w):
        m = F.interpolate(
            m,
            size=(target_h, target_w),
            mode="bilinear",
            align_corners=False,
        )

    m = m.clamp(0.0, 1.0)

    # Close tiny segmentation holes, then soften one pixel-scale boundary.
    m = F.max_pool2d(m, 5, 1, 2)
    m = _soft_blur_mask(m, 5, passes=1)

    return m.permute(0, 2, 3, 1).to(dtype=dtype).clamp(0.0, 1.0)


def _background_reference(
    image: torch.Tensor,
    exclude_mask: torch.Tensor,
    radius_px: int,
) -> torch.Tensor:
    """
    Local bright-background estimate outside the subject.

    Combines normalized mean background with a softened local bright envelope.
    The bright envelope makes broad baked shadows detectable even when a large
    portion of the search window is itself shadowed.
    """
    rgb = image[..., :3].float().clamp(0.0, 1.0)
    bg = (1.0 - exclude_mask[..., 0]).clamp(0.0, 1.0)

    k = _odd_kernel(radius_px, 21, 101)
    pad = k // 2

    rgb_chw = rgb.permute(0, 3, 1, 2)
    bg_chw = bg.unsqueeze(1)

    weight = F.avg_pool2d(
        bg_chw, kernel_size=k, stride=1, padding=pad
    ).clamp_min(1e-4)

    mean_bg = F.avg_pool2d(
        rgb_chw * bg_chw,
        kernel_size=k,
        stride=1,
        padding=pad,
    ) / weight

    # Excluded subject pixels become zero, so they cannot create a false bright
    # reference. Local max finds nearby unshadowed background if available.
    bright = F.max_pool2d(
        rgb_chw * bg_chw,
        kernel_size=k,
        stride=1,
        padding=pad,
    )
    bright = F.avg_pool2d(
        bright,
        kernel_size=9,
        stride=1,
        padding=4,
    )

    ref = torch.maximum(mean_bg, bright * 0.90)
    return ref.permute(0, 2, 3, 1).clamp(0.0, 1.0)


def _flood_dark_component(
    candidate_bhw: torch.Tensor,
    seed_bhw: torch.Tensor,
) -> torch.Tensor:
    """Connected dark-region flood at reduced resolution."""
    b, h, w = candidate_bhw.shape
    scale = min(1.0, 384.0 / float(max(h, w)))
    sh = max(64, int(round(h * scale)))
    sw = max(64, int(round(w * scale)))

    cand = F.interpolate(
        candidate_bhw.unsqueeze(1),
        size=(sh, sw),
        mode="bilinear",
        align_corners=False,
    )
    seed = F.interpolate(
        seed_bhw.unsqueeze(1),
        size=(sh, sw),
        mode="bilinear",
        align_corners=False,
    )

    cand = (cand > 0.12).float()
    grown = (seed > 0.05).float() * cand

    # If the seed ring is very sparse, broaden it one step.
    grown = F.max_pool2d(grown, 5, 1, 2) * cand

    steps = min(160, max(36, int(max(sh, sw) / 2)))
    for _ in range(steps):
        nxt = F.max_pool2d(grown, 5, 1, 2) * cand
        if torch.equal((nxt > 0.5), (grown > 0.5)):
            grown = nxt
            break
        grown = nxt

    grown = F.interpolate(
        grown,
        size=(h, w),
        mode="bilinear",
        align_corners=False,
    )[:, 0]

    return grown.clamp(0.0, 1.0)


def _existing_shadow_candidate(
    detection_image: torch.Tensor,
    apply_image: torch.Tensor,
    subject_mask: torch.Tensor,
    search_radius: float,
    shadow_threshold: float,
    softness: float,
    semantic_shadow_mask=None,
):
    """
    Detect the KSampler's baked-in cast shadow from the ORIGINAL image.

    v0.3.15:
    - subject is protected with a wider SAM3 dilation;
    - broad low-frequency darkness is measured against local bright background;
    - only dark regions CONNECTED to a ring around the subject are retained;
    - the correction color/reference is calculated from the relit apply_image.
    """
    detect = detection_image[..., :3].float().clamp(0.0, 1.0)
    apply = apply_image[..., :3].float().clamp(0.0, 1.0)
    b, h, w, _ = detect.shape

    subject = subject_mask[..., 0].float().clamp(0.0, 1.0)
    subject_chw = subject.unsqueeze(1)

    # Wider protection than previous versions: line art / hair / boots should
    # never be interpreted as an old cast shadow.
    protect_k = _odd_kernel(
        max(15, int(min(h, w) * 0.038)),
        15,
        45,
    )
    protected = F.max_pool2d(
        subject_chw,
        kernel_size=protect_k,
        stride=1,
        padding=protect_k // 2,
    )[:, 0].clamp(0.0, 1.0)

    search_px = _odd_kernel(
        max(31, int(min(h, w) * max(0.10, min(0.38, float(search_radius))))),
        31,
        151,
    )
    near = F.max_pool2d(
        protected.unsqueeze(1),
        kernel_size=search_px,
        stride=1,
        padding=search_px // 2,
    )[:, 0]
    proximity = (near - protected).clamp(0.0, 1.0)

    # Reference for DETECTION from the untouched source image.
    ref_radius = _odd_kernel(
        max(61, int(min(h, w) * 0.18)),
        61,
        151,
    )
    detect_ref = _background_reference(
        detect,
        subject_mask,
        ref_radius,
    )

    detect_lum = (
        detect[..., 0] * 0.2126
        + detect[..., 1] * 0.7152
        + detect[..., 2] * 0.0722
    )
    ref_lum = (
        detect_ref[..., 0] * 0.2126
        + detect_ref[..., 1] * 0.7152
        + detect_ref[..., 2] * 0.0722
    )

    threshold = max(0.0, float(shadow_threshold))
    deficit = (ref_lum - detect_lum - threshold).clamp_min(0.0)

    # Reject narrow line-art responses: cast shadows are broad low-frequency
    # regions. The lowpass response dominates the candidate.
    low_k = _odd_kernel(
        13 + int(max(0.0, min(1.0, float(softness))) * 24),
        13,
        41,
    )
    low = F.avg_pool2d(
        deficit.unsqueeze(1),
        kernel_size=low_k,
        stride=1,
        padding=low_k // 2,
    )[:, 0]

    broad = (
        (0.30 * deficit + 0.92 * low)
        / max(0.035, 0.17 - threshold)
    ).clamp(0.0, 1.0)

    broad = broad * proximity * (1.0 - protected * 0.999)

    # Seed ring immediately outside protected subject. This keeps only the
    # broad shadow blob physically attached/near the character.
    seed_outer_k = _odd_kernel(
        max(21, int(min(h, w) * 0.070)),
        21,
        71,
    )
    seed_outer = F.max_pool2d(
        protected.unsqueeze(1),
        kernel_size=seed_outer_k,
        stride=1,
        padding=seed_outer_k // 2,
    )[:, 0]
    seed_ring = (seed_outer - protected).clamp(0.0, 1.0) * broad

    connected = _flood_dark_component(broad, seed_ring)

    # Preserve soft confidence inside the connected region.
    mask = connected * broad
    mask = F.max_pool2d(mask.unsqueeze(1), 7, 1, 3)
    k = _odd_kernel(
        11 + int(max(0.0, min(1.0, float(softness))) * 22),
        11,
        35,
    )
    mask = _soft_blur_mask(mask, k, passes=2)[:, 0]
    mask = mask * (1.0 - protected * 0.999)

    # --------------------------------------------------------
    # v0.3.16: semantic SAM3 shadow detection is PRIMARY.
    # Numerical connected-dark detection is fallback only.
    # --------------------------------------------------------
    semantic_used = torch.zeros((b,), device=detect.device, dtype=torch.bool)

    if semantic_shadow_mask is not None:
        sem = semantic_shadow_mask
        if torch.is_tensor(sem):
            sem = sem.to(device=detect.device, dtype=torch.float32)

            if sem.ndim == 2:
                sem = sem.unsqueeze(0)
            if sem.ndim == 4:
                if sem.shape[-1] in (1, 3, 4):
                    if sem.shape[-1] == 1:
                        sem = sem[..., 0]
                    else:
                        sem = sem[..., :3].mean(dim=-1)
                elif sem.shape[1] == 1:
                    sem = sem[:, 0]

            if sem.ndim == 3:
                if sem.shape[-2:] != (h, w):
                    sem = F.interpolate(
                        sem.unsqueeze(1),
                        size=(h, w),
                        mode="bilinear",
                        align_corners=False,
                    )[:, 0]

                sem = sem.clamp(0.0, 1.0)

                # Never allow semantic shadow mask to include the subject.
                sem = sem * proximity * (1.0 - protected * 0.999)

                # A semantic shadow still needs to be at least somewhat darker
                # than its local source background, but we intentionally keep
                # this gate weak because anime shadows may be soft.
                semantic_dark = sem * (0.32 + 0.68 * broad)

                # Remove isolated detection specks.
                semantic_dark = F.max_pool2d(
                    semantic_dark.unsqueeze(1), 7, 1, 3
                )
                semantic_dark = _soft_blur_mask(
                    semantic_dark, 11, passes=1
                )[:, 0]
                semantic_dark = semantic_dark * (1.0 - protected * 0.999)

                for bi in range(b):
                    hard = semantic_dark[bi] > 0.12
                    area = float(hard.float().mean().item())

                    # Reasonable old cast-shadow footprint:
                    # neither empty nor most of the room.
                    if 0.0010 <= area <= 0.42:
                        semantic_used[bi] = True
                        # Use semantic segmentation as the main mask.
                        # Numerical detector only adds a small amount of soft
                        # dark confidence near the same area.
                        semantic_soft = semantic_dark[bi]
                        numerical_soft = mask[bi] * F.max_pool2d(
                            hard.float().view(1, 1, h, w),
                            31, 1, 15
                        )[0, 0]
                        mask[bi] = torch.maximum(
                            semantic_soft,
                            numerical_soft * 0.28,
                        )

    # Correction reference is derived from the RELIT image so cleanup does not
    # undo the intended new lighting.
    apply_ref = _background_reference(
        apply,
        subject_mask,
        ref_radius,
    )

    return mask.unsqueeze(-1).clamp(0.0, 1.0), apply_ref



class LAKISShadowCleanup:
    """
    Conservative first-stage suppression of the KSampler's existing shadow.

    This is not generative inpainting. It only lifts broad, locally dark
    background regions near the detected Depth subject toward a local estimated
    unshadowed background.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "depth_map": ("IMAGE",),
                "removal_strength": (
                    "FLOAT",
                    {"default": 0.00, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "search_radius": (
                    "FLOAT",
                    {"default": 0.24, "min": 0.06, "max": 0.38, "step": 0.01},
                ),
                "shadow_threshold": (
                    "FLOAT",
                    {"default": 0.035, "min": 0.0, "max": 0.20, "step": 0.005},
                ),
                "softness": (
                    "FLOAT",
                    {"default": 0.66, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "depth_invert": ("BOOLEAN", {"default": False}),
                "mix": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
            },
            "optional": {
                "normal_map": ("IMAGE",),
                "subject_mask": ("MASK",),
                "shadow_source": ("IMAGE",),
                "semantic_shadow_mask": ("MASK",),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("CLEANED_IMAGE", "OLD_SHADOW_MASK", "OCCLUDER_MASK")
    FUNCTION = "clean_shadow"
    CATEGORY = "LAKIS/Light"

    def clean_shadow(
        self,
        image,
        depth_map,
        removal_strength,
        search_radius,
        shadow_threshold,
        softness,
        depth_invert,
        mix,
        normal_map=None,
        subject_mask=None,
        shadow_source=None,
        semantic_shadow_mask=None,
    ):
        image = image[..., :3].clamp(0.0, 1.0)
        h, w = image.shape[1], image.shape[2]
        dtype = image.dtype

        dm = _resize_image_like(depth_map, h, w)
        if dm is None:
            blank = torch.zeros_like(image)
            return image, blank, blank

        depth = _depth_gray(dm).clamp(0.0, 1.0)
        if bool(depth_invert):
            depth = 1.0 - depth

        external_subject = _normalize_subject_mask(
            subject_mask,
            h,
            w,
            image.device,
            image.dtype,
        )

        if external_subject is not None:
            # Preferred path in workflow 7.0.16+: SAM3 semantic person mask.
            subject = external_subject
        else:
            # Backward-compatible fallback only.
            subject = _depth_subject_mask(
                depth,
                normal_map=normal_map,
            ).to(image.device, image.dtype)

        valid = _mask_validity(subject, require_ground_contact=False)
        subject = subject * valid.view(-1, 1, 1, 1).to(subject.dtype)

        detect_image = image
        if shadow_source is not None:
            ss = _resize_image_like(shadow_source, h, w)
            if ss is not None:
                detect_image = ss[..., :3].clamp(0.0, 1.0)

        shadow_mask, reference = _existing_shadow_candidate(
            detect_image,
            image,
            subject,
            float(search_radius),
            float(shadow_threshold),
            float(softness),
            semantic_shadow_mask=semantic_shadow_mask,
        )

        strength = max(0.0, min(1.0, float(removal_strength)))
        mix = max(0.0, min(1.0, float(mix)))

        lift = (reference - image.float()).clamp_min(0.0)
        cleaned = (
            image.float()
            + lift * shadow_mask.float() * strength
        ).clamp(0.0, 1.0)

        out = image.float() * (1.0 - mix) + cleaned * mix

        return (
            out.to(dtype=dtype).clamp(0.0, 1.0),
            shadow_mask.repeat(1, 1, 1, 3).to(dtype=dtype),
            subject.repeat(1, 1, 1, 3).to(dtype=dtype),
        )


class LAKISShadowCleanupSwitch:
    """Lazy production router for the optional Existing Shadow subsystem."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "cleanup_enabled": ("BOOLEAN", {"default": False}),
                "debug_detection": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "cleanup_image": ("IMAGE", {"lazy": True}),
                "old_shadow_mask": ("IMAGE", {"lazy": True}),
                "semantic_shadow_preview": ("IMAGE", {"lazy": True}),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("PRODUCTION_IMAGE", "OLD_SHADOW_DEBUG", "SEMANTIC_SHADOW_DEBUG")
    FUNCTION = "route"
    CATEGORY = "LAKIS/Light"

    def check_lazy_status(
        self,
        image,
        cleanup_enabled,
        debug_detection,
        cleanup_image=None,
        old_shadow_mask=None,
        semantic_shadow_preview=None,
    ):
        needed = []
        if bool(cleanup_enabled) and cleanup_image is None:
            needed.append("cleanup_image")
        if bool(cleanup_enabled) and bool(debug_detection):
            if old_shadow_mask is None:
                needed.append("old_shadow_mask")
            if semantic_shadow_preview is None:
                needed.append("semantic_shadow_preview")
        return needed

    def route(
        self,
        image,
        cleanup_enabled,
        debug_detection,
        cleanup_image=None,
        old_shadow_mask=None,
        semantic_shadow_preview=None,
    ):
        enabled = bool(cleanup_enabled)
        debug = enabled and bool(debug_detection)
        production = cleanup_image if enabled and cleanup_image is not None else image
        # Disabled debug sockets use a constant 1x1 preview so the bypass does
        # not allocate full-resolution cleanup/debug buffers.
        blank = torch.zeros((1, 1, 1, 3), device=image.device, dtype=image.dtype)
        old_debug = old_shadow_mask if debug and old_shadow_mask is not None else blank
        semantic_debug = (
            semantic_shadow_preview
            if debug and semantic_shadow_preview is not None
            else blank
        )
        return production, old_debug, semantic_debug


class LAKISCastShadow:
    """
    Deterministic 2.5D cast-shadow approximation.

    This node intentionally does not use text prompts or generative inference.
    It estimates the main occluder from the source image + relative depth,
    then projects a soft attached shadow opposite the current LAKIS light.

    It cannot reconstruct hidden 3D geometry from a single image, but unlike
    prompt-based shadows it is stable, reproducible, and cannot invent a
    second detailed character.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "light": ("LAKIS_LIGHT",),
                "depth_map": ("IMAGE",),
                "strength": (
                    "FLOAT",
                    {"default": 0.52, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "projection_length": (
                    "FLOAT",
                    {"default": 1.30, "min": 0.10, "max": 2.50, "step": 0.05},
                ),
                "softness": (
                    "FLOAT",
                    {"default": 0.62, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "contact": (
                    "FLOAT",
                    {"default": 0.28, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "depth_invert": ("BOOLEAN", {"default": False}),
                "linear_shadow": ("BOOLEAN", {"default": True}),
                "mix": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
            },
            "optional": {
                # Preferred production contract. The legacy IMAGE socket remains
                # for workflows saved before LightMap v0.3.18.
                "occluder_mask_input": ("MASK",),
                "occluder_mask": ("IMAGE",),
                "normal_map": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("SHADOWED_IMAGE", "SHADOW_MAP", "OCCLUDER_MASK")
    FUNCTION = "cast_shadow"
    CATEGORY = "LAKIS/Light"

    def cast_shadow(
        self,
        image,
        light,
        depth_map,
        strength,
        projection_length,
        softness,
        contact,
        depth_invert,
        linear_shadow,
        mix,
        occluder_mask_input=None,
        occluder_mask=None,
        normal_map=None,
    ):
        image = image[..., :3].clamp(0.0, 1.0)
        b, h, w, _ = image.shape
        dtype = image.dtype

        if not light or not bool(light.get("enabled", True)):
            blank = torch.zeros_like(image)
            return image, blank, blank

        dm = _resize_image_like(depth_map, h, w)
        if dm is None:
            blank = torch.zeros_like(image)
            return image, blank, blank

        depth = _depth_gray(dm).clamp(0.0, 1.0)
        if bool(depth_invert):
            depth = 1.0 - depth

        preferred_mask = occluder_mask_input if occluder_mask_input is not None else occluder_mask
        if preferred_mask is not None:
            occluder = _normalize_subject_mask(
                preferred_mask, h, w, image.device, image.dtype
            )
        else:
            occluder = _depth_subject_mask(
                depth,
                normal_map=normal_map,
            ).to(image.device, image.dtype)

        valid = _mask_validity(occluder, require_ground_contact=True)
        occluder = occluder * valid.view(-1, 1, 1, 1).to(occluder.dtype)

        shadow = _project_25d_shadow(
            occluder,
            light.get("vector", (0.0, 0.0, 1.0)),
            float(projection_length),
            float(softness),
            float(contact),
        )

        strength = max(0.0, min(1.0, float(strength)))
        mix = max(0.0, min(1.0, float(mix)))

        # A slightly nonlinear density keeps the contact area readable while
        # retaining soft edges.
        density = shadow.pow(0.82) * strength

        if bool(linear_shadow):
            linear = image.float().clamp(0.0, 1.0).pow(2.2)
            shadowed = (
                linear * (1.0 - density * 0.82)
            ).clamp(0.0, 1.0).pow(1.0 / 2.2)
        else:
            shadowed = image.float() * (1.0 - density * 0.72)

        out = image.float() * (1.0 - mix) + shadowed * mix

        shadow_rgb = shadow.repeat(1, 1, 1, 3).to(dtype=dtype)
        occ_rgb = occluder.repeat(1, 1, 1, 3).to(dtype=dtype)

        return (
            out.to(dtype=dtype).clamp(0.0, 1.0),
            shadow_rgb.clamp(0.0, 1.0),
            occ_rgb.clamp(0.0, 1.0),
        )


class LAKISRelight:
    """
    Deterministic, non-prompt relighting.

    Geometry source priority in Auto:
      1. connected normal_map
      2. connected depth_map
      3. image-gradient pseudo normal

    With a depth map, pos_z also changes approximate point-light distance.
    Without depth, pos_z changes global direct-light strength/falloff only.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "light": ("LAKIS_LIGHT",),
                "geometry_source": (
                    ["Auto", "Normal Map", "Depth Map", "Image Gradient"],
                    {"default": "Auto"},
                ),
                "geometry_strength": ("FLOAT", {"default": 8.0, "min": 0.1, "max": 40.0, "step": 0.1}),
                "depth_invert": ("BOOLEAN", {"default": False}),
                "normal_flip_y": ("BOOLEAN", {"default": False}),
                "linear_light": ("BOOLEAN", {"default": True}),
                "mix": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            },
            "optional": {
                "normal_map": ("IMAGE",),
                "depth_map": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("RELIT_IMAGE", "LIGHT_MAP", "NORMAL_PREVIEW")
    FUNCTION = "relight"
    CATEGORY = "LAKIS/Light"

    def relight(
        self,
        image,
        light,
        geometry_source,
        geometry_strength,
        depth_invert,
        normal_flip_y,
        linear_light,
        mix,
        normal_map=None,
        depth_map=None,
    ):
        image = image[..., :3].clamp(0.0, 1.0)
        b, h, w, _ = image.shape
        device = image.device
        dtype = image.dtype

        if not light or not bool(light.get("enabled", True)):
            neutral = torch.ones_like(image)
            flat_n = torch.zeros_like(image)
            flat_n[..., 2] = 1.0
            return image, neutral, _normal_preview(flat_n)

        nm = _resize_image_like(normal_map, h, w) if normal_map is not None else None
        dm = _resize_image_like(depth_map, h, w) if depth_map is not None else None

        source = str(geometry_source)
        if source == "Auto":
            if nm is not None:
                source = "Normal Map"
            elif dm is not None:
                source = "Depth Map"
            else:
                source = "Image Gradient"

        if source == "Normal Map" and nm is not None:
            normals = _normal_from_normal_image(nm, bool(normal_flip_y))
        elif source == "Depth Map" and dm is not None:
            normals = _normal_from_depth(dm, bool(depth_invert), float(geometry_strength))
        else:
            normals = _pseudo_normal_from_image(image, float(geometry_strength))

        lx, ly, lz = light.get("vector", (0.0, 0.0, 1.0))
        base_l = torch.tensor([lx, ly, lz], device=device, dtype=dtype)
        base_l = F.normalize(base_l, dim=0, eps=1e-6)

        pos_z = _clamp(light.get("pos_z", 0.10), -1.0, 1.0)
        intensity = max(0.0, float(light.get("intensity", 0.8)))
        ambient = _clamp(light.get("ambient", 0.2), 0.0, 1.0)
        shadow = _clamp(light.get("shadow", 0.65), 0.0, 1.0)
        exposure = _clamp(light.get("exposure", 0.0), -1.0, 1.0)
        rim_strength = _clamp(light.get("rim", 0.1), 0.0, 1.0)
        color = torch.tensor(light.get("color", (1.0, 1.0, 1.0)), device=device, dtype=dtype)
        color = color.view(1, 1, 1, 3)

        attenuation = None

        # If depth is available, approximate a point light in 2.5D.
        # This allows Z distance to have a real spatial effect.
        if dm is not None:
            depth = _depth_gray(dm).clamp(0.0, 1.0)
            if bool(depth_invert):
                depth = 1.0 - depth

            xs = torch.linspace(-1.0, 1.0, w, device=device, dtype=dtype)
            ys = torch.linspace(1.0, -1.0, h, device=device, dtype=dtype)
            yy, xx = torch.meshgrid(ys, xs, indexing="ij")
            xx = xx.view(1, h, w).expand(b, -1, -1)
            yy = yy.view(1, h, w).expand(b, -1, -1)

            # Center depth around the subject/image plane.
            zz = (depth - 0.5) * 1.2

            # Z+: closer light, Z-: farther light.
            light_distance = 2.0 - 1.15 * pos_z
            light_pos = base_l * float(light_distance)

            px = xx
            py = yy
            pz = zz

            vx = light_pos[0] - px
            vy = light_pos[1] - py
            vz = light_pos[2] - pz
            v = torch.stack((vx, vy, vz), dim=-1)

            dist = torch.linalg.vector_norm(v, dim=-1, keepdim=True).clamp_min(1e-5)
            l_field = v / dist

            # Soft inverse-square-ish falloff, normalized for practical image editing.
            attenuation = 1.0 / (1.0 + 0.45 * (dist / max(0.25, light_distance)) ** 2)
        else:
            l_field = base_l.view(1, 1, 1, 3)
            # Directional fallback: make Z distance still useful.
            distance_gain = 1.0 + 0.35 * pos_z
            attenuation = torch.full((1, 1, 1, 1), distance_gain, device=device, dtype=dtype)

        ndotl = (normals * l_field).sum(dim=-1, keepdim=True).clamp(0.0, 1.0)

        # 'shadow' now means how strongly unilluminated surfaces separate from lit ones.
        gamma = 1.0 + shadow * 2.5
        direct = ndotl.pow(gamma) * attenuation

        # User rim: screen-space grazing-angle highlight.
        view_abs = normals[..., 2:3].abs().clamp(0.0, 1.0)
        rim = (1.0 - view_abs).pow(2.2) * rim_strength

        # -----------------------------------------------------------------
        # Automatic rear-light approximation
        # -----------------------------------------------------------------
        # Visible normal maps describe only the camera-facing surface.
        # For a pure rear light, ordinary max(N·L,0) therefore goes to zero.
        # Instead of pretending the hidden backside is known, use a stable
        # screen-space approximation:
        #   1) depth silhouette / depth-discontinuity mask
        #   2) visible grazing-angle mask
        #   3) strength proportional to how far the light is behind camera-space Z
        #
        # This gives the expected backlight/rim-light appearance around hair,
        # shoulders, arms, legs, and scene geometry without regenerating pixels.
        backness = float(max(0.0, min(1.0, -float(base_l[2].item()))))
        backness = backness ** 1.15

        grazing = (1.0 - view_abs).pow(1.45)

        if dm is not None:
            rear_edge = _rear_depth_rim_mask(depth)
            # Keep major silhouettes dominant, but allow grazing normals to
            # reinforce the rim around curved character contours.
            rear_mask = rear_edge * (0.40 + 0.60 * grazing)
            # A small pure-grazing term prevents thin hair/cloth contours from
            # disappearing when the depth estimator smooths their boundary.
            rear_mask = torch.maximum(rear_mask, grazing * 0.18)
        else:
            rear_mask = grazing * 0.70

        rear_mask = (rear_mask * backness).clamp(0.0, 1.0)

        direct_rgb = direct * color
        rim_rgb = rim * color
        rear_rgb = rear_mask * color

        # Normalize so fully lit neutral surfaces stay near original exposure.
        # Rear light is deliberately an extra rim contribution: the front-facing
        # interior remains dark while silhouettes can reach near-normal exposure.
        denom = max(1e-4, ambient + intensity)
        rear_gain = intensity * 1.35
        light_rgb = (
            ambient
            + intensity * direct_rgb
            + 0.45 * rim_rgb
            + rear_gain * rear_rgb
        ) / denom
        light_rgb = light_rgb.clamp(0.02, 2.5)

        exposure_gain = 2.0 ** (exposure * 2.0)
        light_rgb = light_rgb * exposure_gain

        if bool(linear_light):
            linear = image.clamp(0.0, 1.0).pow(2.2)
            relit = (linear * light_rgb).clamp(0.0, 1.0).pow(1.0 / 2.2)
        else:
            relit = (image * light_rgb).clamp(0.0, 1.0)

        m = _clamp(mix, 0.0, 1.0)
        relit = image * (1.0 - m) + relit * m

        # Light-map preview normalized for viewing.
        light_preview = (light_rgb / 1.5).clamp(0.0, 1.0)
        normal_preview = _normal_preview(normals)

        return relit.clamp(0.0, 1.0), light_preview, normal_preview




# Surface-normal estimation is intentionally unavailable in this release.
# The lighting UI remains locked until a replacement with suitable terms is selected.

class LAKISMaskToImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mask": ("MASK",)}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("IMAGE",)
    FUNCTION = "convert"
    CATEGORY = "LAKIS/Utility"

    def convert(self, mask):
        if not torch.is_tensor(mask):
            return (torch.zeros((1, 64, 64, 3), dtype=torch.float32),)

        m = mask.float()
        if m.ndim == 2:
            m = m.unsqueeze(0)
        if m.ndim == 4 and m.shape[-1] in (1, 3, 4):
            if m.shape[-1] == 1:
                m = m[..., 0]
            else:
                m = m[..., :3].mean(dim=-1)
        elif m.ndim == 4 and m.shape[1] == 1:
            m = m[:, 0]

        if m.ndim != 3:
            return (torch.zeros((1, 64, 64, 3), dtype=torch.float32),)

        m = m.clamp(0.0, 1.0)
        return (m.unsqueeze(-1).repeat(1, 1, 1, 3),)


class LAKISExecutionSettings:
    """Serializable execution policy shared by ComfyUI and external LAKIS clients.

    The object deliberately contains no workflow node IDs.  Selecting concrete
    output roots is the bridge's responsibility, keeping the public application
    state independent of a particular saved workflow layout.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "debug_outputs_enabled": (
                    "BOOLEAN",
                    {"default": False, "label_on": "디버그", "label_off": "프로덕션"},
                ),
            }
        }

    RETURN_TYPES = ("LAKIS_EXECUTION_SETTINGS",)
    RETURN_NAMES = ("EXECUTION_SETTINGS",)
    FUNCTION = "settings"
    CATEGORY = "LAKIS/Settings"

    def settings(self, debug_outputs_enabled=False):
        return ({"debug_outputs_enabled": bool(debug_outputs_enabled)},)


NODE_CLASS_MAPPINGS = {
    "LAKIS_LightControl": LAKISLightControl,
    "LAKIS_GeometryEstimator": LAKISGeometryEstimator,
    "LAKIS_Relight": LAKISRelight,
    "LAKIS_ShadowCleanup": LAKISShadowCleanup,
    "LAKIS_ShadowCleanupSwitch": LAKISShadowCleanupSwitch,
    "LAKIS_CastShadow": LAKISCastShadow,
    "LAKIS_MaskToImage": LAKISMaskToImage,
    "LAKIS_ExecutionSettings": LAKISExecutionSettings,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LAKIS_LightControl": "LAKIS Light Control",
    "LAKIS_GeometryEstimator": "LAKIS Depth Estimator (Depth Anything V2)",
    "LAKIS_Relight": "LAKIS Relight (LightMap)",
    "LAKIS_ShadowCleanup": "LAKIS Existing Shadow Cleanup",
    "LAKIS_ShadowCleanupSwitch": "LAKIS Existing Shadow Cleanup Switch",
    "LAKIS_CastShadow": "LAKIS Cast Shadow (2.5D)",
    "LAKIS_MaskToImage": "LAKIS Mask To Image",
    "LAKIS_ExecutionSettings": "LAKIS 실행 설정 (프로덕션 / 디버그)",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
