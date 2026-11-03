# SPDX-License-Identifier: GPL-3.0-only
"""Small native controls shared by standalone graphs and the external UI.

These nodes choose branches; they never queue prompts, download models or read
LAKIS UI state. The diffusion implementation stays in the connected graph.
"""
from __future__ import annotations

from copy import deepcopy


class GenerationControls:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mode": (["FAST", "DETAIL", "LAKIS DETAIL"], {"default": "FAST"}),
            "composition": ("BOOLEAN", {"default": True}),
            "i2i": ("BOOLEAN", {"default": False}),
            "inpaint": ("BOOLEAN", {"default": False}),
            "pose": ("BOOLEAN", {"default": False}),
            "i2i_denoise": ("FLOAT", {"default": .5, "min": 0., "max": 1., "step": .01}),
        }}

    RETURN_NAMES = ("legacy_detail", "detail", "lakis_detail", "composition",
                    "i2i", "inpaint", "pose", "source", "source_denoise",
                    "highrez_steps", "highrez_cfg", "highrez_sampler", "highrez_denoise")
    FUNCTION = "resolve"
    CATEGORY = "LAKIS/Standalone"

    def resolve(self, mode, composition, i2i, inpaint, pose, i2i_denoise):
        if mode not in {"FAST", "DETAIL", "LAKIS DETAIL"}:
            raise ValueError("Unknown LAKIS generation mode")
        detail = mode != "FAST"
        # Source editing wins over composition, regardless of stale UI state.
        i2i = bool(i2i) and not inpaint
        pose = bool(pose) and not (inpaint or i2i)
        composition = bool(composition) and not (inpaint or i2i or pose)
        return (mode == "DETAIL", detail, mode == "LAKIS DETAIL", composition,
                i2i, bool(inpaint), pose, i2i,
                float(i2i_denoise) if i2i else 1.,
                (16 if detail else 12) if i2i else 3,
                (6. if detail else 5.) if i2i else 1.,
                "euler" if i2i else "gradient_estimation",
                (.31 if detail else .28) if i2i else .2)


class Canvas:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "width": ("INT", {"default": 1024, "min": 256, "max": 4096, "step": 16}),
            "height": ("INT", {"default": 1536, "min": 256, "max": 4096, "step": 16}),
        }}

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "resolve"
    CATEGORY = "LAKIS/Standalone"

    def resolve(self, width, height):
        return tuple(max(256, min(4096, round(int(v) / 16) * 16)) for v in (width, height))


class CompositionPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"positive": ("STRING", {"forceInput": True}),
                             "enabled": ("BOOLEAN", {"default": True})},
                "optional": {"camera": ("STRING", {"forceInput": True, "lazy": True})}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "combine"
    CATEGORY = "LAKIS/Standalone"

    def check_lazy_status(self, positive, enabled, camera=None):
        return ["camera"] if enabled and camera is None else []

    def combine(self, positive, enabled, camera=""):
        return (", ".join(str(s).strip() for s in (positive, camera if enabled else "") if str(s).strip()),)


class InpaintPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "operation": (["regenerate", "remove"],),
            "positive": ("STRING", {"multiline": True, "default": ""}),
            "negative": ("STRING", {"multiline": True, "default": ""}),
            "denoise": ("FLOAT", {"default": .65, "min": 0., "max": 1., "step": .01}),
            "grow_mask_by": ("INT", {"default": 8, "min": 0, "max": 64}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "FLOAT", "INT", "FLOAT", "BOOLEAN", "INT")
    RETURN_NAMES = ("positive", "negative", "denoise", "feather", "color_match_strength",
                    "use_loras", "mask_expand")
    FUNCTION = "resolve"
    CATEGORY = "LAKIS/Standalone"

    def resolve(self, operation, positive, negative, denoise, grow_mask_by=8):
        if operation == "remove":
            positive = (
                "remove the unwanted object inside the masked area completely, "
                "background only, reconstruct the natural surrounding floor or wall, "
                "continue the nearby surface, lighting, shadow, texture and perspective, "
                "plain empty unobstructed background in the masked area, seamless clean "
                "restoration, no foreground object"
            )
            negative = (
                "duplicate body parts, extra limbs, extra arms, extra legs, extra "
                "hands, extra feet, residual anatomy, "
                "person, character, body, clothing, shoes, object remnants, floating "
                "object, black object, geometric object, symbol, icon, logo, text"
            )
            denoise = max(.72, float(denoise))
        elif operation != "regenerate":
            raise ValueError("Unknown inpaint operation")
        return (positive, negative, float(denoise), 16 if operation == "remove" else 10,
                .8 if operation == "remove" else .55, operation != "remove",
                max(16, int(grow_mask_by)) if operation == "remove" else int(grow_mask_by))


class LoraGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"stack": ("LORA_STACK",), "enabled": ("BOOLEAN", {"default": True}),
                             "inpaint": ("BOOLEAN", {"default": False}),
                             "paint_loras": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("LORA_STACK",)
    FUNCTION = "resolve"
    CATEGORY = "LAKIS/Standalone"

    def resolve(self, stack, enabled, inpaint, paint_loras):
        return (stack if enabled and (not inpaint or paint_loras) else [],)


class SourceSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("BOOLEAN", {"default": False}),
                             "steps": ("INT", {"default": 30, "min": 1, "max": 10000}),
                             "cfg": ("FLOAT", {"default": 5., "min": 0., "max": 100.}),
                             "sampler": (cls.SAMPLERS, {"forceInput": True}),
                             "scheduler": (cls.SCHEDULERS, {"forceInput": True})}}

    RETURN_NAMES = ("steps", "cfg", "sampler", "scheduler")
    FUNCTION = "resolve"
    CATEGORY = "LAKIS/Standalone"

    def resolve(self, source, steps, cfg, sampler, scheduler):
        return (20, 8., "euler", "simple") if source else (steps, cfg, sampler, scheduler)


def bind_sampler_contract(samplers, schedulers):
    """Bind real enum contracts before registration or source-only export.

    The runtime supplies comfy.samplers.KSampler's lists; the source builder
    supplies the equivalent KSampler input schemas from its object_info capture.
    """
    # Plugins may append options after this provider is imported. All input
    # and return contracts must observe those same live registry objects.
    SourceSampler.SAMPLERS = samplers
    SourceSampler.SCHEDULERS = schedulers
    SourceSampler.RETURN_TYPES = ("INT", "FLOAT", SourceSampler.SAMPLERS, SourceSampler.SCHEDULERS)
    GenerationControls.RETURN_TYPES = ("BOOLEAN",) * 8 + (
        "FLOAT", "INT", "FLOAT", SourceSampler.SAMPLERS, "FLOAT")


class DiffusionModelLoader:
    """Keep the proven KJ loader and expose its selected name for metadata."""
    @classmethod
    def INPUT_TYPES(cls):
        import nodes
        return nodes.NODE_CLASS_MAPPINGS["DiffusionModelLoaderKJ"].INPUT_TYPES()

    RETURN_TYPES = ("MODEL", "STRING")
    RETURN_NAMES = ("model", "model_name")
    FUNCTION = "load"
    CATEGORY = "LAKIS/Standalone"

    def load(self, **inputs):
        import nodes
        provider = nodes.NODE_CLASS_MAPPINGS["DiffusionModelLoaderKJ"]()
        result = getattr(provider, provider.FUNCTION)(**inputs)
        return result[0], inputs["model_name"]


def native_lllite_inputs(provider_inputs):
    """Keep the provider contract except for deferred filename selection."""
    inputs = deepcopy(provider_inputs)
    inputs["required"]["lllite_name"] = ("STRING", {"default": ""})
    return inputs


class NativeLLLiteApply:
    @classmethod
    def INPUT_TYPES(cls):
        import nodes
        return native_lllite_inputs(nodes.NODE_CLASS_MAPPINGS["AnimaLLLiteApply_sdscripts"].INPUT_TYPES())

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "LAKIS/Standalone"

    def apply(self, **inputs):
        import folder_paths
        import nodes
        name = inputs["lllite_name"]
        if name not in folder_paths.get_filename_list("controlnet"):
            raise ValueError(
                f"Active LAKIS control weight '{name}' is not installed in this ComfyUI controlnet inventory. "
                "Install the required weight under its applicable terms, or turn that control OFF."
            )
        provider = nodes.NODE_CLASS_MAPPINGS["AnimaLLLiteApply_sdscripts"]()
        # The existing provider performs its path/file checks and all model
        # patching. An unavailable active weight never becomes a passthrough.
        return getattr(provider, provider.FUNCTION)(**inputs)


class OptionalImage:
    """A disabled input does not require an example image on a clean install."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "enabled": ("BOOLEAN", {"default": False}),
            "image": ("STRING", {"default": ""}),
            "mask_channel": (["alpha", "red", "green", "blue"], {"default": "alpha"}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "load"
    CATEGORY = "LAKIS/Standalone"

    def load(self, enabled, image, mask_channel):
        import torch
        if not enabled:
            return torch.zeros((1, 64, 64, 3)), torch.zeros((1, 64, 64))
        import nodes
        pixels, alpha = nodes.LoadImage().load_image(image)
        if mask_channel == "alpha":
            return pixels, alpha
        return pixels, nodes.LoadImageMask().load_image_mask(image, mask_channel)[0]

    @classmethod
    def IS_CHANGED(cls, enabled, image, mask_channel):
        if not enabled:
            return False
        import nodes
        return nodes.LoadImage.IS_CHANGED(image)


NODE_CLASS_MAPPINGS = {
    "LAKIS_GenerationControls": GenerationControls,
    "LAKIS_Canvas": Canvas,
    "LAKIS_CompositionPrompt": CompositionPrompt,
    "LAKIS_InpaintPrompt": InpaintPrompt,
    "LAKIS_OptionalImage": OptionalImage,
    "LAKIS_LoraGate": LoraGate,
    "LAKIS_SourceSampler": SourceSampler,
    "LAKIS_DiffusionModelLoader": DiffusionModelLoader,
    "LAKIS_NativeLLLiteApply": NativeLLLiteApply,
}
