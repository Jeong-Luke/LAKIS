# LAKIS third-party notices

Runtime inventory reviewed: 2026-10-27 (8.0.0 candidate; final artifact verification pending)

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
| ComfyUI | [0.42.0, commit `355cd6b1`](https://github.com/Comfy-Org/ComfyUI/tree/355cd6b14c92c19ac3188fe528e47a3f21ef5178) | GPL-3.0 |
| ComfyUI-Lora-Manager | [df34efaf](https://github.com/willmiao/ComfyUI-Lora-Manager/tree/df34efafbc604fa81fbd58f09f723842a73dadfd) | GPL-3.0 |
| ComfyUI_UltimateSDUpscale | [a5547db9](https://github.com/ssitu/ComfyUI_UltimateSDUpscale/tree/a5547db9e1d07d3318bb21e9e9c474f4c1e9c8df) | GPL-3.0 |
| ComfyUI-Anima-DAVE | [83143e8d](https://github.com/sorryhyun/ComfyUI-Anima-DAVE/tree/83143e8d84768e25f72755ec00ea00ded07ee06e) | MIT |
| ComfyUI-Anima-LLLite | [b7495bd8](https://github.com/kohya-ss/ComfyUI-Anima-LLLite/tree/b7495bd8eb876e334509976896702484ed19cdbb) | Apache-2.0; model weights are separate components with separate terms |
| Toyxyz manual 3D pose and region nodes | [8291d9b6](https://github.com/toyxyz/ComfyUI_toyxyz_test_nodes/tree/8291d9b65d56d65be55ee0f31df073d42b7d0eb6) | GPL-3.0; selected source files and the upstream `LICENSE` are supplied in `ComfyUI/custom_nodes/ComfyUI_toyxyz_test_nodes`. |
| Three.js | `three@0.170.0`, vendored by the pinned Toyxyz revision | MIT; Copyright three.js authors; the licence and vendoring notice are supplied in the node's `web/vendor/three`. |
| MHR editor meshes and sparse SAM 3D Body face mapping | Assets frozen by Toyxyz `8291d9b6`; see its `web/vendor/pose3d/README.md` | MHR: Apache-2.0; sparse face mapping: SAM License. Copyright Meta Platforms, Inc. and affiliates. Separate full texts and `NOTICE-MHR.txt` accompany the assets. No SAM inference checkpoint is included. |
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

- The Toyxyz integration registers only `ToyxyzPose3DEditor`,
  `ComfyCoupleBasePrompt`, `ComfyCoupleRegionPainter`, and `ComfyCoupleMask`.
  LAKIS's selective registration is marked in `__init__.py`; the remaining
  selected Python and browser modules retain their upstream source.
  `LAKIS_POSE_SOURCE.json` records the frozen source archive, file hashes,
  and modifications. The standalone `toyxyz-editor.js`, `precision-pose-controls`,
  `pose-body-model.js`, `toyxyz-prompt-validation.js`, `precision-prompts`, and
  `external_ui/scripts` adapters retain their file-level GPL-3.0-only notices.
  Their source is provided with LAKIS; original-LAKIS restrictions do not replace
  these terms. Automatic image-to-pose extraction is not enabled.
- The Toyxyz MHR assets are modified, baked adult presets, not official
  sex-specific Meta models. Their modification notice and the distinction
  between Apache-licensed meshes and SAM-licensed face mapping are retained.
  The corrupted SAM text is replaced with the full
  [SAM 3D Body licence at `b5c765a0`](https://github.com/facebookresearch/sam-3d-body/blob/b5c765a0d89d789985e186d396315e7590887b94/LICENSE),
  also supplied as `third_party_licenses/Meta-SAM-3D-Body-License.txt`.
  This licence revision is not a claim about the checkpoint revision used
  upstream to bake the meshes or mapping.
- `ComfyUI-KR-Camera-Control` is derived from `ComfyUI_bsk_UI`, Copyright
  © 2026 灰暗x, and is distributed under AGPL-3.0-or-later. The publisher's
  [Civitai page](https://civitai.red/models/2814655/bskanimacamera-control?modelVersionId=3174431)
  links to the original
  [ModelScope plugin](https://modelscope.cn/models/bskhuian/Anima_Camera_Position_Control/tree/master/Plugin).
  LAKIS modification notices are retained in the source headers.
  The complete AGPLv3 text is included in this node's `LICENSE` file.
- `ComfyUI-KR-Camera-PromptStudio-Bridge` is distributed under the MIT licence
  included in its directory.
- `ComfyUI-PreviewMonitor` is Copyright © 2026 Bedovyy and distributed under
  the MIT licence included in its directory.
- Modified Spectrum files retain the upstream MIT terms and identify the LAKIS
  modifications in source control.
- Original LAKIS nodes are covered by `LICENSE.md` unless their directory states
  a different licence.
- The bundled `src/external_ui/assets/arcalive-logo.svg` is the Arcalive logo
  by umanle S.R.L., sourced from
  `https://commons.wikimedia.org/wiki/File:Arcalive_logo.svg` from the
  publisher's `https://arca.live/` artwork. Wikimedia Commons classifies this
  simple logo as public domain; it is used only to identify the external
  Arcalive link.

## Runtime Python packages with separate terms

The portable runtime also retains the licences supplied inside installed
Python packages. These entries identify packages whose wheel metadata does not
populate a licence field; that field is not a replacement for the actual terms.
The 8.0.0 candidate uses the versions below. The installed-distribution inventory
and retained licence-file hashes are recorded in
`third_party_licenses/runtime-packages.json`; supplemental licence texts and
their fixed sources are recorded in `third_party_licenses/package-license-sources.json`.
The final release package must be checked against these inventories.

| Package | Installed version / corresponding source | Licence and supplied text |
|---|---|---|
| comfy-aimdo | 0.5.6; [publisher source](https://github.com/Comfy-Org/comfy-aimdo) | GPL-3.0; its wheel includes `licenses/LICENSE`; a full copy is also supplied as `third_party_licenses/ComfyUI-runtime-GPL-3.0.txt`. |
| comfyui-frontend-package | 1.55.18; [v1.55.18 source](https://github.com/Comfy-Org/ComfyUI_frontend/tree/v1.55.18) | GPL-3.0; the full text is supplied as `third_party_licenses/ComfyUI-runtime-GPL-3.0.txt`. |
| cstr | 0.1.0; [pinned publisher source](https://github.com/ltdrdata/cstr/tree/0520c29a18a7a869a6e5983861d6f7a4c86f8e9b) | MIT; copyright and licence are retained in its wheel's `licenses/LICENSE`. |
| segment-anything | 1.0; [publisher source](https://github.com/facebookresearch/segment-anything) | Apache-2.0; copyright and full licence are retained in its wheel's `LICENSE`. These terms describe the Python library, separately from SAM model weights. |
| sentencepiece | 0.2.2; [v0.2.2 source](https://github.com/google/sentencepiece/tree/v0.2.2) | Apache-2.0; Copyright Google Inc.; the full text is supplied as `third_party_licenses/packages/sentencepiece-0.2.2/LICENSE`. |

## Models and weights

### Publisher-downloaded 3D pose controls

These adapters are not bundled or mirrored by LAKIS. Its installer/updater
downloads them directly from the
[official fixed revision](https://huggingface.co/toyxyz/Anima_ControlNet-LLLite/tree/37f3a4b6574f1dce3dfe3b5440285a39b11b3d8d)
and verifies their sizes and SHA-256 values before installing them in the
selected installation's `ComfyUI/models/controlnet`. Repair adds missing
files without replacing conflicting existing models. Program rollback leaves
downloaded models intact.

| File | SHA-256 |
|---|---|
| `anima_3dpose_6200.safetensors` | `97542346a658d23ca65368b568aa9aaf2486ccda8942612983aaffdc986cd495` |
| `anima_regional_4335.safetensors` | `e907ea9259b324a11c94e5767420a6a46c6a9d86597df5ccf9b1ad5eeb817618` |

Their model card specifies `upstream-anima-and-source-data-terms`, not the
Apache licence of the LLLite node. The upstream Anima non-commercial and
non-production restrictions and any applicable source-data terms remain in
force. A local hash match verifies file identity only; it does not grant
permission for use, production deployment, or redistribution.

### Other models and weights

| Installed file | Source | Terms/status |
|---|---|---|
| `RealESRGAN_x4plus_anime_6B.pth` | [Real-ESRGAN v0.2.2.4](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.2.4) | BSD-3-Clause; Copyright © 2021 Xintao Wang. Default upscaler. Licence text is included in `third_party_licenses/Real-ESRGAN-BSD-3-Clause.txt`. |
| `2x-AnimeSharpV4_Fast_RCAN_PU.safetensors` | [Kim2091/2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4) | CC BY-NC-SA 4.0. Optional personal/non-commercial choice only; downloaded from the publisher after explicit acknowledgement and never mirrored by LAKIS. |
| `anima_baseV10.safetensors` (legacy local filename) | [official `anima-base-v1.0.safetensors` at `457fbf84`](https://huggingface.co/circlestone-labs/Anima/blob/457fbf842cb86e96af72c65bdd13e3f1c448de84/split_files/diffusion_models/anima-base-v1.0.safetensors) | CircleStone Labs Non-Commercial License v1.0 at the pinned revision, and applicable NVIDIA Open Model License Agreement terms. Copyright CircleStone Labs LLC. The official file and LAKIS pin have SHA-256 `bd43b7cffe1ed1153d9c41e7beb2f18cb1273eafbaa3af3edd6a173dc90a006e`. Model use is non-commercial and non-production. Permissions stated in a different licence revision must not be assumed for this pin. |
| `anima-turbo-lora-v0.2.safetensors` | [CircleStone Labs Civitai release](https://civitai.com/models/2560840/anima-turbo-lora) · [official Anima-Official-LoRAs at `218b5466`](https://huggingface.co/circlestone-labs/Anima-Official-LoRAs/blob/218b5466a07e8a79328dd8b73ff810706d73cb86/anima-turbo-lora-v0.2.safetensors) | CircleStone Labs Non-Commercial License v1.0 at the pinned revision. Copyright CircleStone Labs LLC. The official file and LAKIS pin have SHA-256 `1b55e40bdb1d0e5a78cb498f245fccfdaae97823265db957d2aabdcf4cd3caf1`. Model/LoRA use is non-commercial and non-production; output permissions are governed separately by that licence. |
| `qwen_3_06b_base.safetensors` | [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) · [official Anima copy](https://huggingface.co/circlestone-labs/Anima/blob/main/split_files/text_encoders/qwen_3_06b_base.safetensors) | Apache-2.0; Alibaba Cloud Qwen Team. The official Anima copy and LAKIS pin have SHA-256 `cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba`. |
| `qwen_image_vae.safetensors` | [Comfy-Org/Qwen-Image_ComfyUI at `7beb7b64`](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/tree/7beb7b647f04469fbe64ba8adc2bb0d7e5e9f73f) | Apache-2.0 repository; underlying Qwen model terms also apply. |
| `sam3.1_multiplex_fp16.safetensors` | [Comfy-Org/sam3.1 at `f38cd62b`](https://huggingface.co/Comfy-Org/sam3.1/tree/f38cd62b71494b53ac2b56ca36e24f3c8d565581) | Meta SAM License; SHA-256 `9BA99C92703C2E8B4F47DE2D34A539BB8E18923049E238B780D70DBE6368EB03`. The pinned [official license](https://huggingface.co/Comfy-Org/sam3.1/blob/f38cd62b71494b53ac2b56ca36e24f3c8d565581/LICENSE) is bundled as `third_party_licenses/Meta-SAM-License.txt`. |
| `anima-lllite-inpainting-v2.safetensors` | [kohya-ss/Anima-LLLite](https://huggingface.co/kohya-ss/Anima-LLLite) | CircleStone Labs Non-Commercial License v1.0; SHA-256 `5242e677d2be34ee70ca7c97c3b14ff5ee49838c03fc1e60ac4852a180db6ef5`. Not bundled, mirrored, or automatically downloaded by LAKIS. The user installs it manually from the official publisher. Non-commercial and non-production restrictions remain applicable. |
| `pooled_text_proj-0611.safetensors` | [Spectrum release 0605](https://github.com/sorryhyun/ComfyUI-Spectrum-KSampler/releases/tag/0605) | Publisher release asset associated with the MIT project; no separate asset terms were stated. |

Availability through LAKIS is not a representation that every use is permitted.
Users must review the exact model terms before commercial use, redistribution,
fine-tuning, or publication.

Required CircleStone attribution notice for the Anima base, Turbo LoRA, and external LLLite inpainting weight:

> The CircleStone Model is licensed by CircleStone Labs LLC under the CircleStone
> Non-Commercial License. Copyright CircleStone Labs LLC. IN NO EVENT SHALL
> CIRCLESTONE LABS LLC BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
> WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
> CONNECTION WITH USE OF THIS MODEL.

The pinned [Anima base licence at `457fbf84`](https://huggingface.co/circlestone-labs/Anima/blob/457fbf842cb86e96af72c65bdd13e3f1c448de84/LICENSE.md)
and [Turbo LoRA licence at `218b5466`](https://huggingface.co/circlestone-labs/Anima-Official-LoRAs/blob/218b5466a07e8a79328dd8b73ff810706d73cb86/LICENSE.md)
both identify CircleStone v1.0. The complete text is included as
`third_party_licenses/CircleStone-Labs-Non-Commercial-License-v1.0.txt`;
the separate LLLite inpainting weight also uses v1.0.

The 3D pose adapter's training record instead identifies
[Anima revision `f973fc41`, whose licence is v1.2](https://huggingface.co/circlestone-labs/Anima/blob/f973fc41ec7545364ac9776c2440285f43ff2a30/LICENSE.md).
That text is supplied separately as
`third_party_licenses/CircleStone-Labs-Non-Commercial-License-v1.2.md`.
It does not establish a licence-version upgrade for the pinned base or Turbo
LoRA. The adapter-specific upstream and source-data conditions still apply.

Anima is a derivative of NVIDIA Cosmos. The NVIDIA agreement and its required
notice are included as `third_party_licenses/NVIDIA-Open-Model-License-2025-10-24.pdf`
and `third_party_licenses/NVIDIA-Cosmos-NOTICE.txt`. Built on NVIDIA Cosmos.

## Transitive source packages

- [facebookresearch/sam2 `2b90b9f5`](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4) — Apache-2.0.
- [ltdrdata/img2texture `d6159abe`](https://github.com/ltdrdata/img2texture/tree/d6159abea44a0b2cf77454d3d46962c8b21eb9d3) — MIT.
- [ltdrdata/cstr `0520c29a`](https://github.com/ltdrdata/cstr/tree/0520c29a18a7a869a6e5983861d6f7a4c86f8e9b) — MIT.
- [ltdrdata/ffmpy `f0007376`](https://github.com/ltdrdata/ffmpy/tree/f000737698b387ffaeab7cd871b0e9185811230d) — MIT.
- [googletrans-py 4.0.0](https://github.com/StarkBotsIndustries/googletrans) — MIT. The license copy is included as `third_party_licenses/googletrans-py-MIT.txt`.

## Installer and runtime prerequisites

- The installer uses the official unmodified `7zr.exe` from
  [7-Zip](https://www.7-zip.org/). Its publisher documents GNU LGPL, BSD
  3-Clause, and unRAR-notice portions.
- Microsoft WebView2 SDK 1.0.4191.47 supplies
  `Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll`, and
  `WebView2Loader.dll`. Its copyright notice, redistribution conditions and
  disclaimer are reproduced in
  `third_party_licenses/Microsoft-WebView2-SDK-1.0.4191.47-LICENSE.txt` from the
  [version-specific publisher licence](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4191.47/License).
  Microsoft Edge WebView2 Evergreen Runtime and its bootstrapper are separate
  components subject to their own Microsoft terms; the SDK licence does not
  replace those terms.
- The CUDA 13.0 licence, redistribution list (Attachment A), and third-party
  notices (Attachment B) are reproduced in
  `third_party_licenses/NVIDIA-CUDA-13.0.0-EULA.md` from the
  [official archived EULA](https://docs.nvidia.com/cuda/archive/13.0.0/eula/index.html).
  This copy does not broaden NVIDIA's redistribution grant or replace
  component-specific terms.
- PyTorch's bundled NVIDIA cuDNN 9.24.0 runtime is separately governed by the
  [version-specific cuDNN agreement and supplement](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.24.0/reference/eula.html),
  reproduced in `third_party_licenses/NVIDIA-cuDNN-9.24.0-EULA.md`.
  The supplement identifies runtime `.so` and `.dll` files as distributable
  subject to the agreement's application-distribution conditions, and limits
  the SDK to applications for systems with NVIDIA GPUs. The CUDA Toolkit
  agreement and the cuDNN Frontend source licence do not replace these terms.
- Python, PyTorch, and PyPI packages retain their respective
  upstream licences and notices.

## Removed components

The retired Light Control implementation and its former DSINE source and weights
are not downloaded, bundled, referenced, or required by this release. Existing
user cache files are not silently deleted.

## No endorsement

Third-party names and marks identify compatible components only. Their inclusion
does not imply endorsement of LAKIS by their authors or publishers.


## Restored LAKIS runtime providers (recovery candidate)

`ComfyUI-LAKIS-Detail` is restored from the supplied 7.3.6 source snapshot
`571238fe535b8981b14c980d78713dc9592ae9d2`, with its GPL-3.0-only `LICENSE` and
`NOTICE.md` retained. The machine-specific development loader is removed.
`ComfyUI-LAKIS-Fast-Refiner` is restored from that same source snapshot with
its MIT `LICENSE` and `NOTICE.md` retained. Its duplicate mask registration
is omitted; `ComfyUI-LAKIS-Local-Inpaint` remains the owner of that type.
This candidate does not include model weights or a new licence approval.
