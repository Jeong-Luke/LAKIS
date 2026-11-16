"""Request-local upscaler ownership for SCOPE; other consumers stay unchanged."""
from copy import deepcopy


def bind_scope_upscalers(prompt, *, contiguous_tiles=False):
    for scope_id, scope in list(prompt.items()):
        if scope["class_type"] != "LAKIS_SCOPE":
            continue
        loader_id, _slot = scope["inputs"]["upscale_model"]
        static_id = f"lakis:scope_upscaler:{scope_id}"
        loader = deepcopy(prompt[loader_id])
        loader["class_type"] = "LAKISScopeUpscaleModelLoader"
        loader["_meta"] = {
            **loader.get("_meta", {}),
            "lakis_source_id": static_id,
        }
        prompt[static_id] = loader
        scope["inputs"]["upscale_model"] = [static_id, 0]
        if contiguous_tiles:
            scope["inputs"]["contiguous_tiles"] = True
