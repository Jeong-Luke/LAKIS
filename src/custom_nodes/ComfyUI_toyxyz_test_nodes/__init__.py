# SPDX-License-Identifier: GPL-3.0-only
# LAKIS 8.0 modification of Toyxyz 8291d9b65d56d65be55ee0f31df073d42b7d0eb6:
# register only the manual pose and region chain; no SAM loader, camera capture,
# external-service nodes, video tools or retired experimental registrations.
from .ComfyCouple.comfy_couple import ComfyCoupleBasePrompt, ComfyCoupleMask
from .nodes.couple_region_painter import ComfyCoupleRegionPainter
from .nodes.pose3d import Pose3DEditor


NODE_CLASS_MAPPINGS = {
    "ToyxyzPose3DEditor": Pose3DEditor,
    "ComfyCoupleBasePrompt": ComfyCoupleBasePrompt,
    "ComfyCoupleRegionPainter": ComfyCoupleRegionPainter,
    "ComfyCoupleMask": ComfyCoupleMask,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ToyxyzPose3DEditor": "3D Pose Editor",
    "ComfyCoupleBasePrompt": "ComfyCouple Base Prompt",
    "ComfyCoupleRegionPainter": "ComfyCouple Region painter",
    "ComfyCoupleMask": "ComfyCouple Mask",
}
WEB_DIRECTORY = "./web"
