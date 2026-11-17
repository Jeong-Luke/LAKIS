"""ComfyUI sockets are the public boundary; LAKIS is not a dependency."""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import math

import torch

from .runtime import WRAPPER_KEY, cfg_safe_wrapper, make_wrapper
from .cache_lifetime import release_encoding_records

BUNDLE_TYPE = "LAKIS_REGIONAL_REFERENCES"
MAX_REFERENCES = 3


@dataclass(frozen=True)
class Reference:
    image: torch.Tensor
    mask: torch.Tensor
    strength: float


def validate_bundle(references):
    if (not isinstance(references, tuple) or not 1 <= len(references) <= MAX_REFERENCES
            or any(not isinstance(item, Reference) for item in references)):
        raise ValueError("Regional SnapRef requires one to three Reference nodes.")
    return references


class RegionalReference:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK", {"tooltip": "White = reference prediction in the OUTPUT frame; black = excluded."}),
            "strength": ("FLOAT", {"default": 0.0, "min": -3.0, "max": 3.0, "step": 0.1}),
        }, "optional": {"previous": (BUNDLE_TYPE,)}}

    RETURN_TYPES = (BUNDLE_TYPE,)
    FUNCTION = "build"
    CATEGORY = "LAKIS/Regional Reference"

    def build(self, image, mask, strength=0.0, previous=None):
        entries = () if previous is None else validate_bundle(previous)
        if len(entries) >= MAX_REFERENCES:
            raise ValueError("Regional SnapRef supports at most three reference images.")
        if (not isinstance(image, torch.Tensor) or image.ndim != 4
                or image.shape[0] != 1 or image.shape[-1] not in (3, 4)
                or min(image.shape[1:3]) < 1):
            raise ValueError("Regional SnapRef: connect one RGB/RGBA image per Reference node, not an image batch.")
        if (not isinstance(mask, torch.Tensor) or mask.ndim != 3 or mask.shape[0] != 1
                or min(mask.shape[-2:]) < 1 or mask.numel() > 4096 * 4096
                or not torch.isfinite(mask).all() or not ((mask >= 0) & (mask <= 1)).all()):
            raise ValueError("Regional SnapRef: MASK must be [1,H,W], finite, within 0..1 and at most 4096² pixels.")
        if (type(strength) not in (int, float) or not math.isfinite(strength)
                or not -3.0 <= strength <= 3.0):
            raise ValueError("Regional SnapRef: strength must be between -3 and 3.")
        return (entries + (Reference(image, mask.detach(), float(strength)),),)


class PoseReferenceMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "region_painter": ("TOYXYZ_REGION_PAINTER",),
            "body_id": ("STRING", {"default": "", "tooltip": "Stable body ID; a missing saved ID raises an error."}),
            "body_number": ("INT", {"default": 1, "min": 1, "max": 256,
                                    "tooltip": "Used only when body_id is empty. Output body_id can be saved for stable binding."}),
        }}

    RETURN_TYPES = ("MASK", "STRING")
    RETURN_NAMES = ("mask", "body_id")
    FUNCTION = "extract"
    CATEGORY = "LAKIS/Regional Reference"

    def extract(self, region_painter, body_id="", body_number=1):
        source = region_painter
        if not isinstance(source, dict) or type(source.get("version")) is not int or source["version"] != 1:
            raise ValueError("Regional SnapRef: invalid 3D person-region input.")
        if source.get("error"):
            raise ValueError(str(source["error"]))
        labels, bodies = source.get("labels"), source.get("bodies")
        width, height = source.get("width"), source.get("height")
        if (type(width) is not int or type(height) is not int or not 64 <= width <= 4096
                or not 64 <= height <= 4096 or not isinstance(labels, torch.Tensor)
                or labels.dtype not in (torch.int32, torch.int64) or labels.shape != (height, width)
                or not isinstance(bodies, list) or not 1 <= len(bodies) <= 256):
            raise ValueError("Regional SnapRef: refresh the 3D editor to obtain its body-ID label tensor.")
        ids, numbers = set(), set()
        for body in bodies:
            if (not isinstance(body, dict) or not isinstance(body.get("id"), str) or not body["id"]
                    or body["id"] in ids or type(body.get("label")) is not int
                    or not 1 <= body["label"] <= 256 or body["label"] in numbers):
                raise ValueError("Regional SnapRef: duplicate or invalid body identities.")
            ids.add(body["id"])
            numbers.add(body["label"])
        if not torch.isin(labels, torch.tensor([0, *numbers], device=labels.device)).all():
            raise ValueError("Regional SnapRef: the ID map contains an unknown person.")
        if not isinstance(body_id, str):
            raise ValueError("Regional SnapRef: body_id must be text.")
        if body_id:
            matches = [body for body in bodies if body["id"] == body_id]
            if not matches:
                raise ValueError("Regional SnapRef: the selected 3D person no longer exists. Select a person again.")
            body = matches[0]
        else:
            if type(body_number) is not int or not 1 <= body_number <= len(bodies):
                raise ValueError("Regional SnapRef: body number is outside the current person list.")
            body = bodies[body_number - 1]
        # Already depth-tested by the 3D renderer. Do not infer identities
        # from preview colors, bounding rectangles, or the person's list index.
        return (labels.eq(body["label"]).float().unsqueeze(0), body["id"])


class RegionalSnapRef:
    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        adapters = [name for name in folder_paths.get_filename_list("loras")
                    if "snapref" in name.lower() or "anima_ref_kv" in name]
        return {"required": {
            "model": ("MODEL",), "clip": ("CLIP",), "vae": ("VAE",),
            "references": (BUNDLE_TYPE,), "adapter": (adapters,),
            "mode": (["cs", "char"],),
            "ref_megapixels": ("FLOAT", {"default": 1.0, "min": 0.25, "max": 2.0, "step": 0.05}),
            "fidelity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
        }, "optional": {
            "experimental_forecast": ("BOOLEAN", {
                "default": False,
                "tooltip": "Independent regional/CFG Spectrum caches. Changes image details and uses more VRAM.",
            }),
        }}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "LAKIS/Regional Reference"

    def apply(self, model, clip, vae, references, adapter, mode="cs", ref_megapixels=1.0, fidelity=1.0,
              experimental_forecast=False):
        import nodes
        from comfy.patcher_extension import WrappersMP

        entries = validate_bundle(references)
        if type(experimental_forecast) is not bool:
            raise ValueError("Regional SnapRef: experimental_forecast must be boolean.")
        if mode not in ("cs", "char"):
            raise ValueError("Regional SnapRef: mode must be cs or char.")
        for name, value, low, high in (("fidelity", fidelity, 0., 1.),
                                       ("ref_megapixels", ref_megapixels, .25, 2.)):
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Regional SnapRef: invalid {name}.")
        try:
            snapref = nodes.NODE_CLASS_MAPPINGS["SnapRef"]
        except KeyError as error:
            raise RuntimeError("Install ArcAnima/SnapRef and its adapter separately before using Regional SnapRef.") from error
        core = importlib.import_module(snapref.__module__)
        # Protocol of the tested upstream revision; do not silently substitute
        # ordinary/global SnapRef if a different version is incompatible.
        snapref_key = core.WRAPPER_KEY
        existing = model.wrappers.get(WrappersMP.DIFFUSION_MODEL, {})
        if snapref_key in existing or WRAPPER_KEY in existing:
            raise ValueError("Connect the pre-SnapRef model; do not stack SnapRef/Regional SnapRef applications.")
        strength = max(item.strength for item in entries)
        options = {
            "model": model, "clip": clip, "vae": vae, "image": entries[0].image,
            "adapter": adapter, "mode": mode, "ref_in_uncond": False,
            "ref_megapixels": ref_megapixels, "strength": strength,
            "fidelity": fidelity, "ref_caption": "", "ref_guidance_on": False,
            "use_batch": False, "multi_layout": "separate",
        }
        for index, item in enumerate(entries, 1):
            options[f"weight_{index}"] = math.exp(item.strength - strength)
            if index > 1:
                options[f"image_{index}"] = item.image
        session = None
        if experimental_forecast:
            from .forecast_session import create_session
            session = create_session()
        patched, = snapref().apply(**options)
        regional_wrapper = make_wrapper(tuple(item.mask for item in entries), forecast=session)
        patched.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, WRAPPER_KEY, regional_wrapper)
        if session is not None:
            patched.add_wrapper_with_key(WrappersMP.OUTER_SAMPLE, WRAPPER_KEY, session.sample)
        existing_vetoes = patched.model_options.get("spectrum_cache_vetoes")
        vetoes = ([] if existing_vetoes is None else
                  [existing_vetoes] if callable(existing_vetoes) else list(existing_vetoes))
        patched.model_options = {
            **patched.model_options,
            "spectrum_cache_vetoes": [*vetoes, regional_wrapper.spectrum_cache_veto],
        }
        wrappers = patched.wrappers[WrappersMP.DIFFUSION_MODEL]
        # Regional prediction must precede wrappers which run blocks directly
        # without executor(), while remaining inside SnapRef's cache/state scope.
        patched.wrappers[WrappersMP.DIFFUSION_MODEL] = {
            snapref_key: [cfg_safe_wrapper(release_encoding_records(
                              native, core._concat_kv,
                              offload_reference_weights=experimental_forecast))
                          for native in wrappers[snapref_key]],
            WRAPPER_KEY: wrappers[WRAPPER_KEY],
            **{key: value for key, value in wrappers.items() if key not in (snapref_key, WRAPPER_KEY)},
        }
        return (patched,)
