"""LAKIS local crop/composite nodes for Local Inpaint V2."""
from __future__ import annotations

import json
import math
import torch
import torch.nn.functional as F


def _resize_image(image, height, width):
    return F.interpolate(image[..., :3].permute(0, 3, 1, 2), size=(int(height), int(width)),
                         mode="bicubic", align_corners=False, antialias=True).permute(0, 2, 3, 1).clamp(0, 1)


def _resize_mask(mask, height, width):
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    return F.interpolate(mask.unsqueeze(1), size=(int(height), int(width)),
                         mode="bilinear", align_corners=False)[:, 0].clamp(0, 1)


class LAKISLocalInpaintPrepare:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",), "mask": ("MASK",),
            "minimum_padding": ("INT", {"default": 96, "min": 0, "max": 1024, "step": 8}),
            "padding_ratio": ("FLOAT", {"default": 0.60, "min": 0.0, "max": 4.0, "step": 0.05}),
            "maximum_crop_ratio": ("FLOAT", {"default": 0.70, "min": 0.10, "max": 1.0, "step": 0.05}),
            "alignment": ("INT", {"default": 16, "min": 8, "max": 64, "step": 8}),
            "minimum_work_edge": ("INT", {"default": 768, "min": 256, "max": 2048, "step": 64}),
            "maximum_work_edge": ("INT", {"default": 1280, "min": 512, "max": 4096, "step": 64}),
            "large_edit_ratio": ("FLOAT", {"default": 0.35, "min": 0.05, "max": 1.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "INT", "INT", "INT", "INT", "FLOAT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("crop", "crop_mask", "x", "y", "crop_width", "crop_height", "process_width", "process_height", "mask_ratio", "large_edit", "metadata")
    FUNCTION = "prepare"
    CATEGORY = "LAKIS/Inpaint V2"

    def prepare(self, image, mask, minimum_padding, padding_ratio, maximum_crop_ratio,
                alignment, minimum_work_edge, maximum_work_edge, large_edit_ratio):
        image = image[..., :3]
        batch, height, width, _ = image.shape
        mask = mask.to(image.device, image.dtype)
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        if mask.shape[1:3] != (height, width):
            mask = _resize_mask(mask, height, width)
        if mask.shape[0] != batch:
            mask = mask[:1].expand(batch, -1, -1)
        active = torch.nonzero(mask.amax(dim=0) > 1e-4, as_tuple=False)
        if active.numel() == 0:
            raise ValueError("수정할 영역을 칠해 주세요.")
        y1, x1 = active.amin(dim=0).tolist()
        y2, x2 = (active.amax(dim=0) + 1).tolist()
        bbox_w, bbox_h = x2 - x1, y2 - y1
        pad = max(int(minimum_padding), int(math.ceil(max(bbox_w, bbox_h) * float(padding_ratio))))
        x1, y1, x2, y2 = max(0, x1 - pad), max(0, y1 - pad), min(width, x2 + pad), min(height, y2 + pad)
        max_area = max(1, int(width * height * float(maximum_crop_ratio)))
        crop_w, crop_h = x2 - x1, y2 - y1
        if crop_w * crop_h > max_area and bbox_w * bbox_h < max_area:
            scale = math.sqrt(max_area / max(1, crop_w * crop_h))
            wanted_w, wanted_h = max(bbox_w, int(crop_w * scale)), max(bbox_h, int(crop_h * scale))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            x1, y1 = max(0, min(width - wanted_w, cx - wanted_w // 2)), max(0, min(height - wanted_h, cy - wanted_h // 2))
            x2, y2 = x1 + wanted_w, y1 + wanted_h
        # The area cap is an optimisation, never permission to terminate an
        # active edit mask at an internal crop edge. That creates a visible
        # rectangular transition when the edited crop is pasted back. Restore
        # a small context/feather safety margin around every non-source-boundary
        # side of the effective mask, even when this exceeds maximum_crop_ratio.
        edge_margin = max(16, min(int(minimum_padding), 96))
        x1 = min(x1, max(0, int(active[:, 1].min()) - edge_margin))
        y1 = min(y1, max(0, int(active[:, 0].min()) - edge_margin))
        x2 = max(x2, min(width, int(active[:, 1].max()) + 1 + edge_margin))
        y2 = max(y2, min(height, int(active[:, 0].max()) + 1 + edge_margin))
        align = max(8, int(alignment))
        crop_w, crop_h = x2 - x1, y2 - y1
        aligned_w, aligned_h = min(width, int(math.ceil(crop_w / align) * align)), min(height, int(math.ceil(crop_h / align) * align))
        x1 = max(0, min(width - aligned_w, x1 - (aligned_w - crop_w) // 2))
        y1 = max(0, min(height - aligned_h, y1 - (aligned_h - crop_h) // 2))
        crop_w, crop_h = aligned_w, aligned_h
        crop = image[:, y1:y1 + crop_h, x1:x1 + crop_w, :]
        crop_mask = mask[:, y1:y1 + crop_h, x1:x1 + crop_w]
        longest, scale = max(crop_w, crop_h), 1.0
        if longest < int(minimum_work_edge):
            scale = int(minimum_work_edge) / longest
        elif longest > int(maximum_work_edge):
            scale = int(maximum_work_edge) / longest
        process_w = max(align, int(math.ceil(crop_w * scale / align) * align))
        process_h = max(align, int(math.ceil(crop_h * scale / align) * align))
        if (process_h, process_w) != (crop_h, crop_w):
            crop, crop_mask = _resize_image(crop, process_h, process_w), _resize_mask(crop_mask, process_h, process_w)
        mask_ratio = float((mask > 1e-4).float().mean().item())
        large_edit = mask_ratio >= float(large_edit_ratio)
        metadata = json.dumps({"inpaint_pipeline": "local_v2",
            "original_size": {"width": width, "height": height},
            "mask_bbox": {"x": int(active[:, 1].min()), "y": int(active[:, 0].min()), "width": bbox_w, "height": bbox_h},
            "crop": {"x": x1, "y": y1, "width": crop_w, "height": crop_h},
            "processing_size": {"width": process_w, "height": process_h},
            "mask_ratio": round(mask_ratio, 6), "large_edit": large_edit},
            ensure_ascii=False, separators=(",", ":"))
        return crop, crop_mask, x1, y1, crop_w, crop_h, process_w, process_h, mask_ratio, large_edit, metadata


class LAKISLocalInpaintComposite:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"original": ("IMAGE",), "edited_crop": ("IMAGE",), "crop_mask": ("MASK",),
            "x": ("INT", {"default": 0, "min": 0, "max": 16384}), "y": ("INT", {"default": 0, "min": 0, "max": 16384}),
            "crop_width": ("INT", {"default": 512, "min": 8, "max": 16384}), "crop_height": ("INT", {"default": 512, "min": 8, "max": 16384}),
            "feather": ("INT", {"default": 12, "min": 0, "max": 128}),
            "color_match_strength": ("FLOAT", {"default": 0.65, "min": 0.0, "max": 1.0, "step": 0.05})}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "composite"
    CATEGORY = "LAKIS/Inpaint V2"

    def composite(self, original, edited_crop, crop_mask, x, y, crop_width, crop_height, feather, color_match_strength):
        result = original[..., :3].clone()
        height, width = result.shape[1:3]
        x, y = max(0, int(x)), max(0, int(y))
        crop_width, crop_height = min(int(crop_width), width - x), min(int(crop_height), height - y)
        edited = _resize_image(edited_crop, crop_height, crop_width)
        mask = _resize_mask(crop_mask.to(edited.device, edited.dtype), crop_height, crop_width)
        reference = result[:, y:y + crop_height, x:x + crop_width, :].to(edited.device, edited.dtype)
        if float(color_match_strength) > 0:
            outside = (1 - mask).unsqueeze(-1)
            shift = ((reference - edited) * outside).sum((1, 2), keepdim=True) / outside.sum((1, 2), keepdim=True).clamp_min(1.0)
            edited = (edited + shift.clamp(-0.18, 0.18) * float(color_match_strength)).clamp(0, 1)
        if int(feather) > 0:
            radius, kernel = int(feather), int(feather) * 2 + 1
            # Zero padding turns a valid mask that reaches a crop boundary into
            # a fading rectangular band. At the bottom edge this restores the
            # original pixels as a perfectly horizontal seam. Replicate the
            # real boundary alpha before feathering so only an actual mask edge
            # is softened; the crop rectangle itself never becomes an edge.
            padded = F.pad(mask.unsqueeze(1), (radius, radius, radius, radius), mode="replicate")
            mask = F.avg_pool2d(padded, kernel, 1, 0)[:, 0].clamp(0, 1)
        result[:, y:y + crop_height, x:x + crop_width, :] = torch.lerp(reference, edited, mask.unsqueeze(-1)).to(result.device, result.dtype)
        return (result,)


NODE_CLASS_MAPPINGS = {
    "LAKIS_LocalInpaintPrepare": LAKISLocalInpaintPrepare,
    "LAKIS_LocalInpaintComposite": LAKISLocalInpaintComposite,
    # Compatibility aliases for existing DEKIS development workflows.
    "DEKIS_LocalInpaintPrepare": LAKISLocalInpaintPrepare,
    "DEKIS_LocalInpaintComposite": LAKISLocalInpaintComposite,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LAKIS_LocalInpaintPrepare": "LAKIS Local Inpaint V2 · Prepare",
    "LAKIS_LocalInpaintComposite": "LAKIS Local Inpaint V2 · Composite",
    "DEKIS_LocalInpaintPrepare": "LAKIS Local Inpaint V2 · Prepare (DEKIS alias)",
    "DEKIS_LocalInpaintComposite": "LAKIS Local Inpaint V2 · Composite (DEKIS alias)",
}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
