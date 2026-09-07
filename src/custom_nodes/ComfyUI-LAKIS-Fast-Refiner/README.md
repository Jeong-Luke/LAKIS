# LAKIS_SCOPE for ComfyUI

Copyright (c) 2026 Luke Jeong.

`LAKIS_SCOPE` is an independently designed LAKIS image-upscaling and refinement
node. It is not a wrapper, fork, modification, or redistributed copy of
Ultimate SD Upscale. Workflows may place the original Ultimate SD Upscale node
and LAKIS_SCOPE next to each other and select either output.

The LAKIS_SCOPE source code in this directory is distributed under the MIT
License. ComfyUI and any separately installed model files or third-party nodes
remain subject to their respective licenses.

The implementation performs learned pixel upscaling followed by an optional
globally consistent low-denoise refinement path. Its optimized two-step path
uses bounded multi-scale residual enhancement without invoking Ultimate SD
Upscale code.
