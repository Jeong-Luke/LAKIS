# SPDX-FileCopyrightText: 2026 Luke Jeong
# SPDX-License-Identifier: GPL-3.0-only
"""Single diffusion face pass with lightweight, configurable eye refinement."""
from __future__ import annotations
import json, logging, time
import numpy as np
import torch
import torch.nn.functional as F
import comfy.samplers

def _ellipse(h, w, cx, cy, rx, ry, device, dtype):
    y=torch.arange(h,device=device,dtype=dtype).view(h,1); x=torch.arange(w,device=device,dtype=dtype).view(1,w)
    d=((x-cx)/max(rx,1.0))**2+((y-cy)/max(ry,1.0))**2
    return ((1.2-d)/.2).clamp(0,1)

def _eye_mask(image,segs,eye_y,spacing,eye_w,eye_h):
    b,h,w,_=image.shape; mask=torch.zeros((b,h,w),device=image.device,dtype=image.dtype)
    for seg in segs[1]:
        x1,y1,x2,y2=map(float,seg.bbox); fw=max(1.,x2-x1); fh=max(1.,y2-y1)
        mx=(x1+x2)*.5; cy=y1+fh*eye_y; off=fw*spacing*.5; rx=fw*eye_w*.5; ry=fh*eye_h*.5
        for cx in (mx-off,mx+off): mask=torch.maximum(mask,_ellipse(h,w,cx,cy,rx,ry,image.device,image.dtype).unsqueeze(0).expand(b,-1,-1))
    return mask

def _refine(image,mask,strength,radius,color_keep):
    if strength<=0 or not torch.any(mask>0): return image
    value=image.permute(0,3,1,2); k=max(3,int(radius)*2+1)
    blur=F.avg_pool2d(value,k,1,k//2); enhanced=(value+(value-blur)*float(strength)).clamp(0,1)
    if color_keep>0:
        corrected=(enhanced-F.avg_pool2d(enhanced,7,1,3)+F.avg_pool2d(value,7,1,3)).clamp(0,1)
        enhanced=torch.lerp(enhanced,corrected,float(color_keep))
    return torch.lerp(value,enhanced,mask.unsqueeze(1)).permute(0,2,3,1).clamp(0,1)

def _recrop_multiface_segs(segs, image_shape, crop_factor):
    """Tighten oversized detector crops so neighbouring faces do not overlap."""
    from impact import core, utils
    _,h,w,_=image_shape; rebuilt=[]
    for seg in segs[1]:
        old=list(map(int,seg.crop_region)); new=utils.make_crop_region(w,h,seg.bbox,float(crop_factor))
        full=np.zeros((h,w),dtype=np.float32)
        old_mask=np.asarray(seg.cropped_mask,dtype=np.float32)
        oh=max(0,old[3]-old[1]); ow=max(0,old[2]-old[0])
        if old_mask.shape[:2] != (oh,ow):
            mask_t=torch.from_numpy(old_mask).unsqueeze(0).unsqueeze(0)
            old_mask=F.interpolate(mask_t,size=(oh,ow),mode="bilinear",align_corners=False)[0,0].numpy()
        full[old[1]:old[3],old[0]:old[2]]=old_mask[:oh,:ow]
        cropped=full[new[1]:new[3],new[0]:new[2]]
        rebuilt.append(core.SEG(None,cropped,seg.confidence,new,seg.bbox,seg.label,seg.control_net_wrapper))
    return (segs[0],rebuilt)

class LAKISDetail:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),"face_segs":("SEGS",),"model":("MODEL",),"clip":("CLIP",),"vae":("VAE",),
            "positive":("CONDITIONING",),"negative":("CONDITIONING",),
            "seed":("INT",{"default":0,"min":0,"max":0xffffffffffffffff}),
            "steps":("INT",{"default":8,"min":1,"max":50}),"cfg":("FLOAT",{"default":5.,"min":0.,"max":30.,"step":.1}),
            "sampler_name":(comfy.samplers.KSampler.SAMPLERS,),"scheduler":(comfy.samplers.KSampler.SCHEDULERS,),
            "face_guide_size":("INT",{"default":768,"min":256,"max":2048,"step":64}),
            "face_max_size":("INT",{"default":1280,"min":256,"max":4096,"step":64}),
            "face_denoise":("FLOAT",{"default":.24,"min":0.,"max":1.,"step":.01}),
            "face_feather":("INT",{"default":8,"min":0,"max":100}),
            "eye_refine":("BOOLEAN",{"default":True}),"eye_strength":("FLOAT",{"default":.22,"min":0.,"max":1.5,"step":.01}),
            "eye_y":("FLOAT",{"default":.42,"min":.15,"max":.75,"step":.01}),
            "eye_spacing":("FLOAT",{"default":.34,"min":.1,"max":.7,"step":.01}),
            "eye_width":("FLOAT",{"default":.24,"min":.05,"max":.5,"step":.01}),
            "eye_height":("FLOAT",{"default":.14,"min":.03,"max":.35,"step":.01}),
            "eye_radius":("INT",{"default":2,"min":1,"max":8}),
            "eye_color_preservation":("FLOAT",{"default":.85,"min":0.,"max":1.,"step":.05}),
            "unload_after":("BOOLEAN",{"default":True}),
        },"optional":{
            "detailer_hook":("DETAILER_HOOK",),
            "multi_face_quality":("BOOLEAN",{"default":True}),
            "multi_face_crop_factor":("FLOAT",{"default":2.2,"min":1.2,"max":4.5,"step":.1}),
            "multi_face_guide_size":("INT",{"default":768,"min":256,"max":2048,"step":64}),
            "multi_face_steps":("INT",{"default":8,"min":1,"max":50}),
            "multi_face_denoise":("FLOAT",{"default":.25,"min":0.,"max":1.,"step":.01}),
            "multi_face_eye_strength":("FLOAT",{"default":.18,"min":0.,"max":1.5,"step":.01}),
        }}
    RETURN_TYPES=("IMAGE","MASK","IMAGE","STRING"); RETURN_NAMES=("image","eye_mask","debug_image","diagnostics")
    FUNCTION="run"; CATEGORY="LAKIS/Detailer"
    DESCRIPTION="One face diffusion pass plus eye-frequency refinement; no SAM3 or second eye sampler."

    def run(self,image,face_segs,model,clip,vae,positive,negative,seed,steps,cfg,sampler_name,scheduler,
            face_guide_size,face_max_size,face_denoise,face_feather,eye_refine,eye_strength,eye_y,
            eye_spacing,eye_width,eye_height,eye_radius,eye_color_preservation,unload_after,detailer_hook=None,
            multi_face_quality=True,multi_face_crop_factor=2.2,multi_face_guide_size=768,multi_face_steps=8,
            multi_face_denoise=.25,multi_face_eye_strength=.18):
        from impact import core
        from impact.impact_pack import DetailerForEach
        started=time.perf_counter(); segs=core.segs_scale_match(face_segs,image.shape); count=len(segs[1])
        if not count:
            empty=torch.zeros(image.shape[:3],device=image.device,dtype=image.dtype)
            return image,empty,image,json.dumps({"face_count":0,"status":"passthrough"})
        multi_profile=bool(multi_face_quality) and count > 1
        if multi_profile:
            segs=_recrop_multiface_segs(segs,image.shape,multi_face_crop_factor)
        effective_guide=max(int(face_guide_size),int(multi_face_guide_size)) if multi_profile else int(face_guide_size)
        effective_max=max(int(face_max_size),effective_guide*2) if multi_profile else int(face_max_size)
        effective_steps=max(int(steps),int(multi_face_steps)) if multi_profile else int(steps)
        effective_denoise=float(multi_face_denoise) if multi_profile else float(face_denoise)
        effective_eye_strength=float(multi_face_eye_strength) if multi_profile else float(eye_strength)
        face_start=time.perf_counter()
        result,*_=DetailerForEach.do_detail(image,segs,model,clip,vae,float(effective_guide),False,float(effective_max),
            int(seed),effective_steps,float(cfg),sampler_name,scheduler,positive,negative,max(.0001,effective_denoise),
            int(face_feather),True,True,"",detailer_hook,cycle=1,inpaint_model=False,
            noise_mask_feather=max(8,int(face_feather)),tiled_encode=False,tiled_decode=False)
        face_seconds=time.perf_counter()-face_start
        mask=_eye_mask(result,segs,eye_y,eye_spacing,eye_width,eye_height)
        final=_refine(result,mask if eye_refine else torch.zeros_like(mask),effective_eye_strength if eye_refine else 0,
                      eye_radius,eye_color_preservation)
        tint=torch.tensor([1.,.15,.65],device=final.device,dtype=final.dtype)
        debug=torch.lerp(final,tint,(mask*.45).unsqueeze(-1))
        # Never unload ComfyUI's global model registry from inside a node.
        # Doing so races the prompt worker's own lifecycle and can terminate
        # the worker after this prompt. Post-job cleanup belongs to the LAKIS
        # bridge (`/free`) once execution has fully completed.
        info={"face_count":count,"face_seconds":round(face_seconds,3),"total_seconds":round(time.perf_counter()-started,3),
              "guide_size":effective_guide,"max_size":effective_max,"steps":effective_steps,
              "face_denoise":effective_denoise,"eye_strength":effective_eye_strength,
              "multi_face_profile":multi_profile,"multi_face_crop_factor":float(multi_face_crop_factor),
              "eye_mode":"frequency" if eye_refine else "off","sam3_used":False}
        return final,mask,debug,json.dumps(info,ensure_ascii=False)

class LAKISVRAMGate:
    """Observe the VRAM boundary without mutating ComfyUI during execution."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "min_free_gb":("FLOAT",{"default":1.5,"min":0.25,"max":12.0,"step":0.25}),
            "empty_cache":("BOOLEAN",{"default":True}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","diagnostics")
    FUNCTION="run"
    CATEGORY="LAKIS/Memory"

    def run(self,image,min_free_gb,empty_cache):
        import comfy.model_management as mm
        free_before=int(mm.get_free_memory())
        threshold=int(float(min_free_gb)*1024**3)
        pressure=free_before < threshold
        free_after=int(mm.get_free_memory())
        info={"free_before_gb":round(free_before/1024**3,3),
              "free_after_gb":round(free_after/1024**3,3),
              "threshold_gb":float(min_free_gb),"pressure":pressure,
              "cleanup":"deferred_until_prompt_complete"}
        logging.info("LAKIS_VRAM_GATE %s",info)
        return image,json.dumps(info,ensure_ascii=False)

NODE_CLASS_MAPPINGS={"LAKIS_DETAIL":LAKISDetail,"LAKIS_FACE_SCOPE":LAKISDetail,"LAKIS_VRAM_GATE":LAKISVRAMGate}
NODE_DISPLAY_NAME_MAPPINGS={"LAKIS_DETAIL":"LAKIS_DETAIL (Single Pass)",
                            "LAKIS_FACE_SCOPE":"LAKIS_DETAIL (Legacy Alias)",
                            "LAKIS_VRAM_GATE":"LAKIS VRAM Gate (Adaptive)"}

# DEV benchmark bridge: load the independently maintained LAKIS_SCOPE upscaler
# from the release source tree without duplicating its implementation here.
try:
    import importlib.util
    from pathlib import Path
    _scope_path = Path(r"C:\AI Library\ComfyUI_windows_portable\release\LAKIS_v7_1_clean\src\custom_nodes\ComfyUI-LAKIS-Fast-Refiner\__init__.py")
    _scope_spec = importlib.util.spec_from_file_location("lakis_scope_benchmark", _scope_path)
    _scope_module = importlib.util.module_from_spec(_scope_spec)
    _scope_spec.loader.exec_module(_scope_module)
    NODE_CLASS_MAPPINGS.update(_scope_module.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_scope_module.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _scope_error:
    logging.warning("LAKIS_SCOPE benchmark bridge unavailable: %s", _scope_error)

__all__=["NODE_CLASS_MAPPINGS","NODE_DISPLAY_NAME_MAPPINGS"]
