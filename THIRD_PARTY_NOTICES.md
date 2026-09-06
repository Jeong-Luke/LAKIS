# LAKIS third-party notices

Last reviewed: 2026-09-06

LAKIS includes, downloads, modifies, or interoperates with third-party software
and model files. Those materials remain subject to their own copyright notices
and licences. `LICENSE.md` applies only to original LAKIS material and does not
replace, narrow, or expand third-party terms.

The installer retrieves the components below from the linked publisher at a
pinned revision and verifies their bytes. Upstream archives are installed with
their licence files intact. Except where stated otherwise, LAKIS does not claim
authorship or ownership of these components.

## Core platform and extensions

| Component | Pinned source | Licence |
|---|---|---|
| ComfyUI | [v0.21.1](https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.21.1) | GPL-3.0 |
| ComfyUI-Lora-Manager | [df34efaf](https://github.com/willmiao/ComfyUI-Lora-Manager/tree/df34efafbc604fa81fbd58f09f723842a73dadfd) | GPL-3.0 |
| ComfyUI_UltimateSDUpscale | [a5547db9](https://github.com/ssitu/ComfyUI_UltimateSDUpscale/tree/a5547db9e1d07d3318bb21e9e9c474f4c1e9c8df) | GPL-3.0 |
| ComfyUI-Anima-DAVE | [83143e8d](https://github.com/sorryhyun/ComfyUI-Anima-DAVE/tree/83143e8d84768e25f72755ec00ea00ded07ee06e) | MIT |
| ComfyUI-Custom-Scripts | [609f3afa](https://github.com/pythongosssss/ComfyUI-Custom-Scripts/tree/609f3afaa74b2f88ef9ce8d939626065e3247469) | MIT |
| ComfyUI-DCW | [66aaf9dd](https://github.com/namemechan/ComfyUI-DCW/tree/66aaf9dddb03bad031c1e8443e255a811008e477) | GPL-3.0 |
| ComfyUI-Easy-Use | [b5e31ef1](https://github.com/yolain/ComfyUI-Easy-Use/tree/b5e31ef12ad9d0b187b545c2707735cc7d581c52) | GPL-3.0 |
| ComfyUI-EasyUseAnima | [c64236a5](https://github.com/n0va39/ComfyUI-EasyUseAnima/tree/c64236a5b64db3c1b5db4e333931ab7128a70200) | MIT; Copyright © 2026 n0va39 |
| ComfyUI-Image-Saver | [2ba0f2bc](https://github.com/alexopus/ComfyUI-Image-Saver/tree/2ba0f2bc4ee5235a0f9299f415fb2fb6be78f9e9) | MIT |
| ComfyUI-Impact-Pack | [429d0159](https://github.com/ltdrdata/ComfyUI-Impact-Pack/tree/429d0159ad429e64d2b3916e6e7be9c22d025c3c) | GPL-3.0 |
| ComfyUI-KJNodes | [e8e88f7c](https://github.com/kijai/ComfyUI-KJNodes/tree/e8e88f7c88e3f6205b122f5de87e69a09fbce5ac) | GPL-3.0 |
| ComfyUI-RvTools_v2 | [d3f7e8be](https://github.com/r-vage/ComfyUI-RvTools_v2/tree/d3f7e8beb477dff6c0fac44b298ab74ac433d93e) | Apache-2.0 |
| ComfyUI-Spectrum-KSampler | [b46a364a](https://github.com/sorryhyun/ComfyUI-Spectrum-KSampler/tree/b46a364aec3b161b889c9cc26cd976a49eb537ae) | MIT |
| rgthree-comfy | [13b4399c](https://github.com/rgthree/rgthree-comfy/tree/13b4399c00b5ef5a97b1b6800fc1185874740f5d) | MIT |
| WAS Node Suite | [44de7058](https://github.com/ltdrdata/was-node-suite-comfyui/tree/44de705818d4663fefefde57ffe0ea5a9ea39df4) | MIT |
| ultimate-upscale-for-automatic1111 | [2322caa4](https://github.com/Coyote-A/ultimate-upscale-for-automatic1111/tree/2322caa480535b1011a1f9c18126d85ea444f146) | GPL-3.0 |

GPL/AGPL-covered source, including LAKIS modifications to covered components, is
available in this repository and through the upstream links.

## Bundled and modified code

- `ComfyUI-KR-Camera-Control` is derived from `ComfyUI_bsk_UI`, Copyright
  © 2026 灰暗x, and is distributed under AGPL-3.0-or-later. The publisher's
  [Civitai page](https://civitai.red/models/2814655/bskanimacamera-control?modelVersionId=3174431)
  links to the original
  [ModelScope plugin](https://modelscope.cn/models/bskhuian/Anima_Camera_Position_Control/tree/master/Plugin).
  LAKIS modification notices are retained in the source headers.
- `ComfyUI-KR-Camera-PromptStudio-Bridge` is distributed under the MIT licence
  included in its directory.
- `ComfyUI-PreviewMonitor` is Copyright © 2026 Bedovyy and distributed under
  the MIT licence included in its directory.
- Modified Spectrum files retain the upstream MIT terms and identify the LAKIS
  modifications in source control.
- Original LAKIS nodes are covered by `LICENSE.md` unless their directory states
  a different licence.

## Models and weights

| Installed file | Source | Terms/status |
|---|---|---|
| `RealESRGAN_x4plus_anime_6B.pth` | [Real-ESRGAN v0.2.2.4](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.2.4) | BSD-3-Clause; Copyright © 2021 Xintao Wang. Default upscaler. Licence text is included in `third_party_licenses/Real-ESRGAN-BSD-3-Clause.txt`. |
| `2x-AnimeSharpV4_Fast_RCAN_PU.safetensors` | [Kim2091/2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4) | CC BY-NC-SA 4.0. Optional personal/non-commercial choice only; downloaded from the publisher after explicit acknowledgement and never mirrored by LAKIS. |
| `anima_baseV10.safetensors` (legacy local filename) | [official `anima-base-v1.0.safetensors` at `457fbf84`](https://huggingface.co/circlestone-labs/Anima/blob/457fbf842cb86e96af72c65bdd13e3f1c448de84/split_files/diffusion_models/anima-base-v1.0.safetensors) | CircleStone Labs Non-Commercial License v1.2 and applicable NVIDIA Open Model License Agreement terms. Copyright CircleStone Labs LLC. The official file and LAKIS pin have SHA-256 `bd43b7cffe1ed1153d9c41e7beb2f18cb1273eafbaa3af3edd6a173dc90a006e`. Model use is non-commercial and non-production; v1.2 separately permits individuals to sell derivatives under its conditions and permits commercial use of outputs subject to its terms. |
| `anima-turbo-lora-v0.2.safetensors` | [CircleStone Labs Civitai release](https://civitai.com/models/2560840/anima-turbo-lora) · [official Anima-Official-LoRAs](https://huggingface.co/circlestone-labs/Anima-Official-LoRAs/blob/main/anima-turbo-lora-v0.2.safetensors) | CircleStone Labs Non-Commercial License. Copyright CircleStone Labs LLC. The official file and LAKIS pin have SHA-256 `1b55e40bdb1d0e5a78cb498f245fccfdaae97823265db957d2aabdcf4cd3caf1`. Model/LoRA use is non-commercial and non-production; the licence separately permits commercial use of outputs subject to its terms. |
| `qwen_3_06b_base.safetensors` | [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) · [official Anima copy](https://huggingface.co/circlestone-labs/Anima/blob/main/split_files/text_encoders/qwen_3_06b_base.safetensors) | Apache-2.0; Alibaba Cloud Qwen Team. The official Anima copy and LAKIS pin have SHA-256 `cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba`. |
| `qwen_image_vae.safetensors` | [Comfy-Org/Qwen-Image_ComfyUI at `7beb7b64`](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/tree/7beb7b647f04469fbe64ba8adc2bb0d7e5e9f73f) | Apache-2.0 repository; underlying Qwen model terms also apply. |
| `sam3.1_multiplex_fp16.safetensors` | [Comfy-Org/sam3.1 at `f38cd62b`](https://huggingface.co/Comfy-Org/sam3.1/tree/f38cd62b71494b53ac2b56ca36e24f3c8d565581) | Meta SAM License; redistribution and use are subject to the [official agreement](https://github.com/facebookresearch/sam3/blob/main/LICENSE). |
| `pooled_text_proj-0611.safetensors` | [Spectrum release 0605](https://github.com/sorryhyun/ComfyUI-Spectrum-KSampler/releases/tag/0605) | Publisher release asset associated with the MIT project; no separate asset terms were stated. |

Availability through LAKIS is not a representation that every use is permitted.
Users must review the exact model terms before commercial use, redistribution,
fine-tuning, or publication.

Required CircleStone attribution notice for the Anima base and Turbo LoRA:

> The CircleStone Model is licensed by CircleStone Labs LLC under the CircleStone
> Non-Commercial License. Copyright CircleStone Labs LLC. IN NO EVENT SHALL
> CIRCLESTONE LABS LLC BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
> WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
> CONNECTION WITH USE OF THIS MODEL.

The complete CircleStone v1.2 text is included as
`third_party_licenses/CircleStone-Labs-Non-Commercial-License-v1.2.md` and is
also published in the
[official Anima repository](https://huggingface.co/circlestone-labs/Anima/blob/main/LICENSE.md).

Anima is a derivative of NVIDIA Cosmos. The NVIDIA agreement and its required
notice are included as `third_party_licenses/NVIDIA-Open-Model-License-2025-10-24.pdf`
and `third_party_licenses/NVIDIA-Cosmos-NOTICE.txt`. Built on NVIDIA Cosmos.

## Transitive source packages

- [facebookresearch/sam2 `2b90b9f5`](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4) — Apache-2.0.
- [ltdrdata/img2texture `d6159abe`](https://github.com/ltdrdata/img2texture/tree/d6159abea44a0b2cf77454d3d46962c8b21eb9d3) — MIT.
- [ltdrdata/cstr `0520c29a`](https://github.com/ltdrdata/cstr/tree/0520c29a18a7a869a6e5983861d6f7a4c86f8e9b) — MIT.
- [ltdrdata/ffmpy `f0007376`](https://github.com/ltdrdata/ffmpy/tree/f000737698b387ffaeab7cd871b0e9185811230d) — MIT.

## Installer and runtime prerequisites

- The installer uses the official unmodified `7zr.exe` from
  [7-Zip](https://www.7-zip.org/). Its publisher documents GNU LGPL, BSD
  3-Clause, and unRAR-notice portions.
- Microsoft Edge WebView2 runtime and SDK files remain subject to Microsoft's
  applicable terms.
- Python, PyTorch, CUDA libraries, and PyPI packages retain their respective
  upstream licences and notices.

## Removed component

DSINE source and weights are not downloaded, bundled, referenced, or required by
this release. Existing user cache files are not silently deleted.

## No endorsement

Third-party names and marks identify compatible components only. Their inclusion
does not imply endorsement of LAKIS by their authors or publishers.
