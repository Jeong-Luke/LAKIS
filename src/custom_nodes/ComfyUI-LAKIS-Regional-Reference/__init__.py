"""Standalone, opt-in regional reference nodes for ANIMA and SnapRef."""
from .nodes import RegionalReference, RegionalSnapRef, PoseReferenceMask

NODE_CLASS_MAPPINGS = {
    "LAKISRegionalReference": RegionalReference,
    "LAKISRegionalSnapRef": RegionalSnapRef,
    "LAKISPoseReferenceMask": PoseReferenceMask,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LAKISRegionalReference": "Regional SnapRef · Reference",
    "LAKISRegionalSnapRef": "Regional SnapRef · Apply (ANIMA)",
    "LAKISPoseReferenceMask": "Regional SnapRef · 3D Person Mask",
}
