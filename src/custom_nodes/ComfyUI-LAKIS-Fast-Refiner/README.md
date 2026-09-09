# LAKIS_SCOPE for ComfyUI

Copyright (c) 2026 Luke Jeong.

An experimental tiled upscaling and low-denoise refinement node for ComfyUI.
The project is being published early so users and node developers can test it,
report edge cases, and suggest improvements.

## Installation

Clone or download this repository into `ComfyUI/custom_nodes/ComfyUI-LAKIS-SCOPE`,
then restart ComfyUI. Search for `LAKIS_SCOPE` under `LAKIS/Upscale`.

The node uses PyTorch and public ComfyUI interfaces. It does not ship checkpoint,
VAE, LoRA, or pixel-upscaler model files. Select compatible models already
installed in your own ComfyUI environment.

## What it does

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

Important controls include tile size, overlap, tile batch size, sampling
settings, denoise strength, and an optional quality mode. VRAM requirements
depend on the selected diffusion model, pixel upscaler, resolution, and tile
settings.

## Feedback and contributions

Bug reports and optimization proposals are welcome. When reporting a problem,
please include your ComfyUI version, GPU and VRAM capacity, input/output size,
tile settings, sampler settings, and the complete error log. Do not upload
copyrighted model weights or private prompts with an issue.

Pull requests should keep the node usable as a standalone ComfyUI custom-node
package and must not add model weights or code with an incompatible license.

## License

The LAKIS_SCOPE source code in this repository is licensed under the MIT
License. See `LICENSE` and `NOTICE.md`.
