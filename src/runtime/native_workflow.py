"""Build and serialize the standalone v8 graph from LAKIS's proven node chain.

The v7.4 assets are immutable input references, not runtime fallbacks for v8.
Run with an actual ComfyUI /object_info capture to serialize installed widgets.
No UI state, model execution, installation or prompt submission occurs here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[2]
CONTROL_ID = "3000"
CANVAS_ID = "3001"
INPAINT_ID = "3013"
NAMES = ("LAKIS_custom_v8.0_editable.json", "LAKIS_runtime_visual_v8.0.json",
         "LAKIS_runtime_api_v8.0.json")


def is_link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)


def alias_view(prompt):
    """Compatibility view for inventory/advanced controls using stable old IDs."""
    names = {key: str(node.get("_meta", {}).get("lakis_source_id", key))
             for key, node in prompt.items()}
    result = deepcopy(prompt)
    for node in result.values():
        for name, value in node.get("inputs", {}).items():
            if is_link(value):
                node["inputs"][name] = [names[str(value[0])], value[1]]
    return {names[key]: node for key, node in result.items()}


def native_view(aliases, original):
    names = {str(node.get("_meta", {}).get("lakis_source_id", key)): key
             for key, node in original.items()}
    # Request-local metadata/path nodes do not belong to the saved graph.
    # String IDs are valid API IDs and cannot collide with native integer IDs.
    result = deepcopy(aliases)
    for node in result.values():
        for name, value in node.get("inputs", {}).items():
            if is_link(value):
                node["inputs"][name] = [names.get(str(value[0]), str(value[0])), value[1]]
    return {names.get(key, key): node for key, node in result.items()}


def dependency_graph(prompt, targets=("775", "1338")):
    keep, pending = set(), list(targets)
    while pending:
        key = pending.pop()
        if key in keep:
            continue
        keep.add(key)
        pending.extend(str(v[0]) for v in prompt[key]["inputs"].values() if is_link(v))
    return {key: node for key, node in prompt.items() if key in keep}


def validate_enum_edges(prompt, info):
    """Check complete backend enum contracts, including V3 COMBO/options."""
    for key, node in prompt.items():
        schema = info[node["class_type"]]["input"]
        specs = {**schema.get("required", {}), **schema.get("optional", {})}
        for name, value in node["inputs"].items():
            if not is_link(value) or name not in specs:
                continue
            spec = specs[name]
            options = spec[1] if len(spec) > 1 else {}
            choices = options.get("options") if spec[0] == "COMBO" else spec[0]
            if not isinstance(choices, (list, tuple)):
                continue
            source = prompt[str(value[0])]
            received = info[source["class_type"]]["output"][value[1]]
            if received == "COMBO" or (
                isinstance(received, (list, tuple)) and tuple(received) != tuple(choices)
            ):
                raise ValueError(
                    f"Enum contract mismatch: {value[0]}[{value[1]}] -> {key}.{name}"
                )


def build_graph(reference):
    p = deepcopy(reference)

    # Face/Eye contexts inherit the shared LoRA-applied Anima context. Keeping
    # these inactive branches independent would still require their own checkpoint.
    p["893:892"]["inputs"] = {"base_ctx": ["890:857", 0]}

    def add(key, kind, inputs, title=None):
        p[key] = {"class_type": kind, "inputs": inputs, "_meta": {"title": title or kind}}

    def switch(key, select, no, yes, title=None):
        add(key, "ComfySwitchNode", {"switch": select, "on_false": no, "on_true": yes}, title)

    add("3000", "LAKIS_GenerationControls", {
        "mode": "FAST", "composition": True, "i2i": False, "inpaint": False,
        "pose": False, "i2i_denoise": .5}, "01 · Generation mode / exclusive inputs")
    add("3001", "LAKIS_Canvas", {"width": 1024, "height": 1536}, "02 · Output canvas")
    add("3002", "LAKIS_CompositionPrompt", {
        "positive": ["2133", 0], "enabled": ["3000", 3], "camera": ["2135", 0]})
    p["890:2012"]["inputs"]["value"] = ["3002", 0]
    # Prompts live in the graph, including the camera connection. No frontend
    # copying of camera text or persisted LAKIS state is needed.
    studio = p["2133"]["inputs"]
    fields = json.loads(studio["advanced_fields"])
    fields = [f for f in fields if f.get("id") != "positive_general_kr_camera_bridge"
              and f.get("type") != "naia"]
    for field in fields:
        field["height"] = min(160, max(72, int(field.get("height", 80))))
        field["heightMode"] = "manual"
    studio.update(use_naia=False, resolution_bucket="Custom",
                  resolution_size="1024 * 1536 (custom)",
                  resolution_custom_width=1024, resolution_custom_height=1536,
                  advanced_fields=json.dumps(fields, ensure_ascii=False, separators=(",", ":")))
    p["1736:1987"]["inputs"].update(width=["3001", 0], height=["3001", 1])
    p["890:1365"]["inputs"]["model_name"] = "anima_baseV10.safetensors"
    p["890:1365"]["class_type"] = "LAKIS_DiffusionModelLoader"
    p["890:2127"]["inputs"]["value"] = ["890:1365", 1]
    p["890:1864"]["inputs"]["seed"] = 0
    # VAE encoding is intentionally rooted at the loader, not the context
    # containing that encoding's latent. This is an acyclic model/VAE path.
    for key, node in p.items():
        if node["class_type"] in {"VAEEncode", "VAEDecode"}:
            node["inputs"]["vae"] = ["890:159", 0]
        if node["class_type"] == "Masks Combine Batch":
            node["class_type"] = "LAKIS_SafeMasksCombineBatch"

    add("1744", "LAKIS_OptionalImage", {
        "enabled": ["3000", 4], "image": "", "mask_channel": "alpha"}, "I2I · upload source")
    add("1736:1741", "ImageScale", {
        "image": ["1744", 0], "upscale_method": "lanczos",
        "width": ["3001", 0], "height": ["3001", 1], "crop": "center"})
    p["1736:1740"]["inputs"]["vae"] = ["890:159", 0]
    p["1736:1737"]["inputs"]["value"] = ["3000", 4]
    p["1634:1758"]["inputs"] = {"switch": ["3000", 4],
                               "on_false": ["1634:1759", 0], "on_true": ["3000", 8]}
    add("3004", "LAKIS_SourceSampler", {
        "source": ["3000", 4], "steps": ["890:905", 0], "cfg": ["890:905", 2],
        "sampler": ["890:905", 3], "scheduler": ["890:905", 4]})
    context = p["890:857"]["inputs"]
    context.update(steps=["3004", 0], cfg=["3004", 1],
                   sampler=["3004", 2], scheduler=["3004", 3])
    for key, source in (("2138", 0), ("2139", 0), ("2140", 1)):
        p[key]["inputs"]["value"] = ["3000", source]
    # Never unload the global model registry inside an executing node.
    for key, image in (("lakis:vram:base_to_face", ["1633:1611", 0]),
                       ("lakis:vram:face_to_eye", ["1530:1830", 0]),
                       ("lakis:vram:eye_to_upscale", ["1836:2072", 0])):
        add(key, "LAKIS_VRAM_GATE", {"image": image, "min_free_gb": 1.5, "empty_cache": False})
    for node in p.values():
        for name, value in node["inputs"].items():
            if is_link(value) and str(value[0]).startswith("lakis:vram:"):
                node["inputs"][name] = [value[0], 0]
    p["1634:1721"]["inputs"].update(enabled=True, one_sampler_only=True, verbose=False)
    p["1633:1616"]["inputs"]["on_false"] = ["1634:1622", 0]
    p["1633:1790"]["inputs"]["samples"] = ["1634:1622", 0]
    add("3005", "LoraLoaderModelOnly", {
        "model": ["1633:1619", 0], "lora_name": "anima-turbo-lora-v0.2.safetensors",
        "strength_model": 1.}, "Turbo · HighRez only")
    switch("3006", ["3000", 4], ["3005", 0], ["1633:1619", 0])
    p["1633:1612"]["inputs"].update(
        model=["3006", 0], steps=["3000", 9], cfg=["3000", 10],
        sampler_name=["3000", 11], scheduler="simple", denoise=["3000", 12])

    add("3040", "LAKIS_DETAIL", {
        "image": ["lakis:vram:base_to_face", 0], "face_segs": ["1530:1827", 0],
        "model": ["1530:1832", 0], "clip": ["1530:1833", 2],
        "vae": ["890:159", 0], "positive": ["1530:1833", 4],
        "negative": ["1530:1833", 5], "seed": ["1530:1833", 8],
        "steps": 8, "cfg": ["1530:1833", 11], "sampler_name": ["1530:1833", 13],
        "scheduler": ["1530:1825", 0], "face_guide_size": 768, "face_max_size": 1280,
        "face_denoise": .24, "face_feather": 8, "eye_refine": True,
        "eye_strength": .22, "eye_y": .42, "eye_spacing": .34, "eye_width": .24,
        "eye_height": .14, "eye_radius": 2, "eye_color_preservation": .85,
        "unload_after": False, "detailer_hook": ["1530:2060", 0],
    }, "LAKIS DETAIL · face + eye frequency refinement")
    switch("3050", ["3000", 2], ["1836:2072", 0], ["3040", 0])
    p["1541:1531"]["inputs"]["image"] = ["3050", 0]
    p["1541:1538"]["inputs"]["image"] = ["3050", 0]
    old = p["1541:1538"]["inputs"]
    add("3051", "LAKIS_SCOPE", {
        **{name: deepcopy(old[name]) for name in (
            "image", "model", "positive", "negative", "vae", "upscale_model",
            "upscale_by", "seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")},
        "tile_size": old["tile_width"], "overlap": old["tile_padding"],
        "tile_batch_size": 2, "quality_mode": True}, "LAKIS DETAIL · SCOPE upscale")
    switch("3052", ["3000", 2], ["1541:1538", 0], ["3051", 0])
    switch("1541:1545", ["3000", 1], ["1633:1611", 0], ["3052", 0], "FAST / detail result")

    # Independent local inpaint V2 branch. It does not run HighRez/detail/USDU,
    # and its source, painted mask and prompts never reuse the I2I inputs.
    for key, channel, title in (("3011", "alpha", "Inpaint · source image"),
                                ("3012", "red", "Inpaint · mask (white = edit)")):
        add(key, "LAKIS_OptionalImage", {
            "enabled": ["3000", 5], "image": "", "mask_channel": channel}, title)
    add("3013", "LAKIS_InpaintPrompt", {
        "operation": "regenerate", "positive": "", "negative": "", "denoise": .65,
        "grow_mask_by": 8}, "Inpaint · independent prompts / BETA")
    add("3014", "GrowMask", {"mask": ["3012", 1], "expand": ["3013", 6], "tapered_corners": True})
    add("3015", "LAKIS_LocalInpaintPrepare", {
        "image": ["3011", 0], "mask": ["3014", 0], "minimum_padding": 96,
        "padding_ratio": .60, "maximum_crop_ratio": .70, "alignment": 16,
        "minimum_work_edge": 768, "maximum_work_edge": 1280, "large_edit_ratio": .35})
    add("3016", "VAEEncode", {"pixels": ["3015", 0], "vae": ["890:159", 0]})
    add("3017", "SetLatentNoiseMask", {"samples": ["3016", 0], "mask": ["3015", 1]})
    paint_model = deepcopy(p["1634:1626"]["inputs"])
    paint_model["model"] = ["890:1279", 0]
    add("3018", "DCWModelPatch", paint_model)
    add("3019", "LAKIS_NativeLLLiteApply", {
        "model": ["3018", 0], "lllite_name": "anima-lllite-inpainting-v2.safetensors",
        "image": ["3015", 0], "mask": ["3015", 1], "strength": 1.,
        "start_percent": 0., "end_percent": 1., "preserve_wrapper": True})
    for key, output in (("3020", 0), ("3021", 1)):
        add(key, "CLIPTextEncode", {"text": ["3013", output], "clip": ["890:1281", 1]})
    paint_spectrum = deepcopy(p["1634:1721"]["inputs"])
    paint_spectrum.update(model=["3019", 0], steps=20)
    add("3022", "DiTSpectrumPatch", paint_spectrum)
    add("3023", "KSampler", {
        "model": ["3022", 0], "positive": ["3020", 0], "negative": ["3021", 0],
        "latent_image": ["3017", 0], "seed": ["890:1864", 0],
        "steps": 20, "cfg": 8., "sampler_name": "euler", "scheduler": "simple",
        "denoise": ["3013", 2]})
    add("3024", "VAEDecode", {"samples": ["3023", 0], "vae": ["890:159", 0]})
    add("3025", "LAKIS_LocalInpaintComposite", {
        "original": ["3011", 0], "edited_crop": ["3024", 0], "crop_mask": ["3015", 1],
        "x": ["3015", 2], "y": ["3015", 3], "crop_width": ["3015", 4],
        "crop_height": ["3015", 5], "feather": ["3013", 3],
        "color_match_strength": ["3013", 4]})
    add("3026", "LAKIS_LoraGate", {"stack": ["1925", 1], "enabled": True,
                                 "inpaint": ["3000", 5], "paint_loras": ["3013", 5]})
    p["890:1281"]["inputs"]["lora_stack"] = ["3026", 0]

    # Native pose editor and region painter. Capture upstream model references
    # before wrapping them, so neither stage can feed its own model input.
    add("3030", "ToyxyzPose3DEditor", {
        "width": ["3001", 0], "height": ["3001", 1], "pose_data": "{}", "render_data": ""})
    add("3031", "ComfyCoupleBasePrompt", {"base_prompt_text": ["890:2012", 0]})
    add("3032", "ComfyCoupleRegionPainter", {
        "clip": ["890:1281", 1], "width": ["3001", 0], "height": ["3001", 1],
        "paint_data": "", "region_painter": ["3030", 5], "region": ["3031", 0]})
    add("3033", "PrimitiveFloat", {"value": 1.}, "Pose · strength")
    add("3034", "PrimitiveFloat", {"value": 1.}, "Region · strength")
    for index, owner, sampler in ((0, "1634:1721", "1634:1622"), (1, "1633:1612", "1633:1612")):
        base_model = deepcopy(p[owner]["inputs"]["model"])
        start = 3060 + index * 10
        add(str(start), "LAKIS_NativeLLLiteApply", {
            "model": base_model, "lllite_name": "anima_3dpose_6200.safetensors",
            "image": ["3030", 0], "strength": ["3033", 0],
            "start_percent": 0., "end_percent": 1., "preserve_wrapper": True})
        add(str(start+1), "LAKIS_NativeLLLiteApply", {
            "model": [str(start), 0], "lllite_name": "anima_regional_4335.safetensors",
            "image": ["3032", 0], "strength": ["3034", 0],
            "start_percent": 0., "end_percent": .3, "preserve_wrapper": True})
        add(str(start+2), "ComfyCoupleMask", {
            "model": [str(start+1), 0], "region": ["3032", 1],
            "negative": deepcopy(p[sampler]["inputs"]["negative"]),
            "cross_region_attention": 0., "cross_region_mode": "self_exclusion",
            "feather_mask": 0, "model_type": "anima", "skip_positive_conditioning": True})
        switch(str(start+3), ["3000", 6], base_model, [str(start+2), 0])
        p[owner]["inputs"]["model"] = [str(start+3), 0]
        for delta, name, output in ((4, "positive", 1), (5, "negative", 2)):
            switch(str(start+delta), ["3000", 6],
                   deepcopy(p[sampler]["inputs"][name]), [str(start+2), output])
            p[sampler]["inputs"][name] = [str(start+delta), 0]

    switch("3003", ["3000", 5], ["1541:1545", 0], ["3025", 0], "Terminal image · save + display")
    switch("3080", ["3000", 5], ["2133", 6], ["3013", 0])
    switch("3081", ["3000", 5], ["2133", 7], ["3013", 1])
    add("3083", "PrimitiveString", {"value": ""}, "Empty generation metadata")
    switch("3082", ["3000", 5], ["3083", 0], ["3015", 10])
    p["775"]["inputs"].update(images=["3003", 0], positive=["3080", 0],
                             negative=["3081", 0], custom=["3082", 0],
                             show_preview=True, download_civitai_data=False)
    p["921"]["inputs"]["image"] = ["3003", 0]
    p["1338"]["inputs"]["images"] = ["3003", 0]
    # Metadata must not require a network request to generate an image.
    p["775"]["inputs"]["additional_hashes"] = ""
    # These inherited debug displays are OUTPUT_NODEs, so ordinary ComfyUI
    # queueing would execute their inactive detail/upscale dependencies too.
    # They only forward a scheduler from the matching context's output 14.
    for debug_id in ("1634:1623", "1530:1825", "1836:2068", "1541:1537"):
        scheduler = p[debug_id]["inputs"]["anything"]
        for node in p.values():
            for name, value in node["inputs"].items():
                if value == [debug_id, 0]:
                    if name != "scheduler":
                        raise ValueError(f"Unexpected non-scheduler debug consumer: {debug_id}.{name}")
                    node["inputs"][name] = deepcopy(scheduler)
        del p[debug_id]
    # Impact detailers use an extended scheduler enum, not the base Context
    # contract. The installed adapter preserves the selected base scheduler
    # when extra_scheduler is None; LAKIS_DETAIL and base samplers stay direct.
    for adapter, detailer, context in (
        ("3041", "1530:1826", "1530:1833"),
        ("3042", "1836:2069", "1836:2075"),
    ):
        add(adapter, "ImpactSchedulerAdapter",
            {"scheduler": [context, 14], "extra_scheduler": "None"})
        p[detailer]["inputs"]["scheduler"] = [adapter, 0]
    p = dependency_graph(p)
    mapping = {key: key for key in p if key.isdecimal()}
    mapping.update({key: str(4000 + i) for i, key in enumerate(sorted(k for k in p if not k.isdecimal()))})
    for key, node in p.items():
        node.setdefault("_meta", {})["lakis_source_id"] = key
    return native_view(p, {mapping[key]: node for key, node in p.items()})


def normalize_widgets(prompt, info):
    """Normalize source-format numeric strings using the installed schema."""
    for node in prompt.values():
        schema = info[node["class_type"]]["input"]
        specs = {**schema.get("required", {}), **schema.get("optional", {})}
        for name, value in list(node["inputs"].items()):
            if is_link(value):
                continue
            kind = specs.get(name, [None])[0]
            if kind == "BOOLEAN" and isinstance(value, str):
                node["inputs"][name] = value.lower() == "true"
            elif kind in ("INT", "FLOAT") and isinstance(value, str):
                node["inputs"][name] = int(value) if kind == "INT" else float(value)


def native_widget_controls(class_type, name, kind, options):
    """Frontend 1.55.18 useInt/Float/ComboWidget and rgthree Seed contracts."""
    # rgthree's Seed.onNodeCreated removes the standard seed control widget.
    if class_type == "Seed (rgthree)":
        return []
    control = options.get("control_after_generate",
                          name in {"seed", "noise_seed"} if kind == "INT" else False)
    if not control:
        return []
    prefix = f"{options['control_prefix']} " if options.get("control_prefix") else ""
    control_name = control if isinstance(control, str) else prefix + "control_after_generate"
    controls = [(control_name, "fixed")]
    if isinstance(kind, list):
        controls.append((options.get("control_filter_list", prefix + "control_filter_list"), ""))
    return controls


def serialize_native(prompt, info):
    nodes, links, link_id = [], [], 0
    by_id = {}
    for key, node in prompt.items():
        schema = info[node["class_type"]]
        inputs, widgets, widget_names = [], [], []
        specs = {}
        for group in ("required", "optional"):
            declarations = schema["input"].get(group, {})
            for name in schema.get("input_order", {}).get(group, declarations):
                specs[name] = declarations[name]
        for name, value in node["inputs"].items():
            if name not in specs and is_link(value):
                # ComfyMathExpression's native V3 autogrow sockets.
                if node["class_type"] != "ComfyMathExpression" or not name.startswith("values."):
                    raise ValueError(f"Undeclared input: {node['class_type']}.{name}")
                specs[name] = ("FLOAT,INT,BOOLEAN",)
        for name, spec in specs.items():
            opts = spec[1] if len(spec) > 1 else {}
            # V3 exposes choices in options; legacy schemas put them in slot 0.
            kind = opts["options"] if spec[0] == "COMBO" and "options" in opts else spec[0]
            widget = not opts.get("forceInput") and (
                isinstance(kind, list) or kind in {"INT", "FLOAT", "STRING", "BOOLEAN"})
            value = node["inputs"].get(name)
            if name in node["inputs"] and not widget and not is_link(value):
                raise ValueError(
                    f"Native socket {key}.{name} needs a linked constant, not a literal value"
                )
            # Native sockets exist even when the API omits their values.
            # In particular rgthree restores every context socket in schema
            # order; compacting this array changes the meaning of target_slot.
            # Autogrow is a template, not a concrete socket (values.a etc. are
            # expanded above). Ordinary widgets remain widgets until linked.
            if (not widget and kind != "COMFY_AUTOGROW_V3") or is_link(value):
                entry = {"name": name, "type": "COMBO" if isinstance(kind, list) else kind, "link": None}
                if widget:
                    entry["widget"] = {"name": name}
                    widget_names.append(name)
                    widgets.append(opts.get("default", kind[0] if isinstance(kind, list) else
                                             0 if kind in {"INT", "FLOAT"} else False if kind == "BOOLEAN" else ""))
                inputs.append(entry)
            if name not in node["inputs"]:
                continue
            if widget and not is_link(value):
                widget_names.append(name)
                widgets.append(value)
            if widget:
                for control_name, control_value in native_widget_controls(node["class_type"], name, kind, opts):
                    widget_names.append(control_name)
                    widgets.append(control_value)
        outputs = [{"name": name, "type": "COMBO" if isinstance(kind, list) else kind, "links": []}
                   for kind, name in zip(schema["output"], schema.get("output_name", schema["output"]))]
        ui = {"id": int(key), "type": node["class_type"], "title": node["_meta"].get("title", node["class_type"]),
              "pos": [0, 0], "size": [320, 240], "flags": {"collapsed": True},
              "order": len(nodes), "mode": 0, "inputs": inputs, "outputs": outputs,
              "properties": {"Node name for S&R": node["class_type"],
                             "lakis_source_id": node["_meta"]["lakis_source_id"],
                             "lakis_widget_names": widget_names},
              "widgets_values": widgets}
        if node["class_type"] == "EasyUseAnimaPromptStudioAdvanced":
            # Display-only reference. Prompt Studio owns its dynamic sockets;
            # no generation dimensions flow through its width/height outputs.
            ui["properties"]["lakis_canvas_node_id"] = int(CANVAS_ID)
        nodes.append(ui)
        by_id[key] = ui
    # Resolve match-template types from a concrete upstream branch.
    def output_type(key, slot, seen=()):
        if key in seen:
            raise ValueError(f"Cycle resolving native type: {key}")
        kind = by_id[key]["outputs"][slot]["type"]
        if kind in ("COMFY_MATCHTYPE_V3", "*"):
            for name in ("on_false", "on_true"):
                value = prompt[key]["inputs"].get(name)
                if is_link(value):
                    return output_type(str(value[0]), value[1], (*seen, key))
            return "STRING"
        return kind
    for key, node in prompt.items():
        for slot, entry in enumerate(by_id[key]["inputs"]):
            value = node["inputs"].get(entry["name"])
            if not is_link(value):
                continue
            link_id += 1
            kind = output_type(str(value[0]), value[1])
            source = by_id[str(value[0])]["outputs"][value[1]]
            source["type"] = kind
            source["links"].append(link_id)
            if entry["type"] == "COMFY_MATCHTYPE_V3":
                entry["type"] = kind
            entry["link"] = link_id
            links.append([link_id, int(value[0]), value[1], int(key), slot, kind])
    groups = arrange(nodes)
    nodes.append({"id": 3999, "type": "PreviewMonitor", "pos": [4400, 80],
                  "size": [660, 760], "flags": {}, "order": len(nodes), "mode": 0,
                  "inputs": [], "outputs": [], "properties": {}, "widgets_values": [],
                  "title": "Live preview · retained after completion"})
    return {"id": "e6c09ee0-ce4a-4ec0-99db-9381da28e080", "revision": 1,
            "last_node_id": max(n["id"] for n in nodes), "last_link_id": link_id,
            "nodes": nodes, "links": links, "groups": groups, "config": {},
            "extra": {"ds": {"scale": .32, "offset": [80, 80]},
                      "lakis_native_version": "8.0", "lakis_terminal_image": 3003}, "version": .4}


def arrange(nodes):
    # Keep the aligned editing panels in front. Related wiring is collapsed
    # inside their footprints and placed earlier in LiteGraph's draw order.
    panels = {
        "3000": (0, 80, 380, 270), "3001": (0, 390, 380, 150),
        "890:1365": (0, 580, 380, 270), "890:159": (0, 890, 380, 100),
        "890:164": (0, 1030, 380, 160), "890:905": (0, 1230, 380, 220),
        "890:1864": (0, 1490, 380, 130), "1925": (440, 80, 600, 740),
        "2133": (1100, 80, 680, 1460), "2135": (1840, 80, 660, 700),
        "1744": (440, 890, 600, 220), "3011": (2560, 80, 540, 220),
        "3012": (2560, 340, 540, 220), "3013": (2560, 600, 540, 660),
        "3019": (2560, 1300, 540, 230), "3030": (3160, 80, 1180, 840),
        "3032": (3160, 960, 1180, 840), "3033": (1840, 840, 300, 100),
        "3034": (2200, 840, 300, 100), "3040": (1840, 1000, 660, 800),
        "1541:1536": (440, 1160, 600, 120), "1541:1535": (440, 1320, 280, 100),
        "1541:1838": (760, 1320, 280, 100), "3051": (440, 1470, 600, 360),
        "775": (4400, 900, 660, 820), "1338": (5120, 80, 900, 1240),
    }
    auxiliary_panels = {
        "2133": ("890:903", "890:904", "890:2012", "890:2013", "890:1745",
                 "890:2097", "890:2098", "890:2099", "890:2100", "890:2101"),
        "2135": ("3002",),
        "1744": ("3004",),
        "1925": ("3026",),
        "3040": ("215", "227", "256", "2136", "2138", "2139", "3041", "3042", "3050",
                 "lakis:vram:base_to_face", "lakis:vram:face_to_eye"),
        "3051": ("3005", "3006", "3052"),
        "3013": ("3014", "3015", "3016", "3017", "3018", "3020",
                 "3021", "3022", "3023", "3024", "3025"),
        "3030": ("3060", "3061", "3062", "3063", "3064", "3065"),
        "3032": ("3031", "3070", "3071", "3072", "3073", "3074", "3075"),
        "775": ("793", "919", "921", "935", "1221", "1560", "1784",
                "3003", "3080", "3081", "3082", "3083", "890:2127"),
    }
    owners = {source: panel for panel, sources in auxiliary_panels.items() for source in sources}
    # The legacy source-ID prefixes identify the original functional subgraphs.
    subgraph_panels = {
        "890": "1925", "1736": "1744", "1634": "1925", "1633": "3051",
        "893": "3040", "1530": "3040", "1836": "3040", "1541": "3051",
    }
    stacks = {}
    for node in nodes:
        source = node["properties"]["lakis_source_id"]
        if source in panels:
            x, y, w, h = panels[source]
            node.update(pos=[x, y], size=[w, h], flags={})
            if source == "2133":
                node["properties"]["easyuse_anima_advanced_fields"] = node["widgets_values"][8]
        else:
            owner = owners[source] if source in owners else subgraph_panels[source.split(":")[0]]
            x, y, w, h = panels[owner]
            index = stacks.get(owner, 0)
            rows = (h - 100) // 18
            # Stack titles wholly under the panel body, away from its exposed
            # title/ports. Front nodes receive pointer events before this layer.
            node.update(pos=[x + 24 + (index // rows) * 16, y + 56 + (index % rows) * 18],
                        flags={"collapsed": True})
            stacks[owner] = index + 1
    nodes.sort(key=lambda node: node["properties"]["lakis_source_id"] in panels)
    for order, node in enumerate(nodes):
        node["order"] = order
    return [{"title": title, "bounding": bounds, "color": color, "font_size": 28, "flags": {}}
            for title, bounds, color in (
                ("01 · Model / mode / I2I / LoRA", [-30, 0, 1100, 1880], "#335577"),
                ("02 · Prompts", [1070, 0, 740, 1880], "#446644"),
                ("03 · Camera / detail controls", [1810, 0, 720, 1880], "#665577"),
                ("04 · Inpaint · BETA", [2530, 0, 600, 1880], "#665577"),
                ("05 · Native 3D pose + regions", [3130, 0, 1240, 1880], "#336666"),
                ("06 · Live monitor / final display / saver 775", [4370, 0, 1700, 1880], "#665533"))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object-info", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "workflows")
    args = parser.parse_args()
    info = json.loads(args.object_info.read_text(encoding="utf-8"))
    controls = runpy.run_path(str(ROOT / "src/custom_nodes/ComfyUI-LAKIS-Detail/native_controls.py"))
    sampler_inputs = info["KSampler"]["input"]["required"]
    controls["bind_sampler_contract"](sampler_inputs["sampler_name"][0], sampler_inputs["scheduler"][0])
    for name, cls in controls["NODE_CLASS_MAPPINGS"].items():
        if name == "LAKIS_DiffusionModelLoader":
            inputs = info["DiffusionModelLoaderKJ"]["input"]
        elif name == "LAKIS_NativeLLLiteApply":
            inputs = controls["native_lllite_inputs"](info["AnimaLLLiteApply_sdscripts"]["input"])
        else:
            inputs = cls.INPUT_TYPES()
        info[name] = {"input": inputs, "output": cls.RETURN_TYPES,
                      "output_name": getattr(cls, "RETURN_NAMES", cls.RETURN_TYPES),
                      "output_node": getattr(cls, "OUTPUT_NODE", False)}
    p = build_graph(json.loads((ROOT / "workflows/LAKIS_runtime_api_v7.4.json").read_text(encoding="utf-8")))
    validate_enum_edges(p, info)
    outputs = {key for key, node in p.items() if info[node["class_type"]].get("output_node", False)}
    if outputs != {"775", "1338"}:
        raise ValueError(f"Unexpected executable native output roots: {sorted(outputs)}")
    normalize_widgets(p, info)
    ui = serialize_native(p, info)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in zip(NAMES, (ui, ui, p)):
        (args.output_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(p)} executable nodes, {len(ui['links'])} links, {len(ui['groups'])} native sections")


if __name__ == "__main__":
    main()
