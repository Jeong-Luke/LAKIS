"""Convex mixing weights on ANIMA's returned, unpadded latent frame."""
import torch
import torch.nn.functional as F


def mixing_plan(masks, height, width, device):
    """All-white references are global; other references own spatial branches.

    Overlapping spatial masks share their prediction weight proportionally.
    Uncovered/soft-mask pixels retain the global-only/background prediction.
    """
    global_refs = tuple(index for index, mask in enumerate(masks) if bool((mask == 1).all()))
    regions = []
    total = torch.zeros((1, 1, 1, height, width), device=device, dtype=torch.float32)
    for index, mask in enumerate(masks):
        if index in global_refs:
            continue
        weight = F.interpolate(mask.to(device=device, dtype=torch.float32)[None],
                               size=(height, width), mode="nearest-exact").unsqueeze(2)
        if bool((weight > 0).any()):
            regions.append((index, weight))
            total = total + weight
    denominator = total.clamp_min(1.)
    background = (1. - total).clamp_min(0.)
    plan = []
    if bool((background > 0).any()):
        plan.append((global_refs, background))
    plan.extend(((*global_refs, index), weight / denominator) for index, weight in regions)
    return tuple(plan)
