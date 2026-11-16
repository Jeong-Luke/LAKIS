# Regional SnapRef for ComfyUI — experimental

Standalone ANIMA/SnapRef extension. LAKIS, its server, and its UI are **not**
dependencies. No upstream custom-node files, model files or workflows are
modified. This package is an unreleased prototype, not a quality-validated
public release.

## Installation and dependencies

Copy this directory into your ComfyUI `custom_nodes` directory and restart
ComfyUI once. Install [ArcAnima/SnapRef](https://github.com/ArcAnima/SnapRef)
and its adapter separately. ComfyUI already provides PyTorch.

The integration targets SnapRef source revision
`1f7e606621052c11486c7aa5ccf6c2c12c2c5a3a` and the ANIMA still-image model.
Other revisions/models are not verified. Missing or incompatible dependencies
produce an error; there is no silent global-reference fallback.

## Connect the nodes

1. Connect one `Load Image` IMAGE to **Regional SnapRef · Reference**.
2. Connect a MASK describing the **generated output frame**, not the reference
   image. White selects that reference's prediction; black excludes it.
   Soft masks blend with the global-only/background prediction.
3. Chain up to three Reference nodes through `previous`. Each reference has
   its own signed log strength (`0` is trained strength, not disabled).
4. Connect the final reference bundle, the pre-SnapRef MODEL, CLIP, VAE and
   adapter to **Regional SnapRef · Apply (ANIMA)**, then to KSampler.
   Do not also apply ordinary SnapRef to that model.
5. An all-white mask gives a global reference, including in a mixed bundle.
   Standard ComfyUI mask nodes can supply rectangles or arbitrary masks.

### Optional 3D persons

Connect the toyxyz **3D Pose Editor** `region painter` output
(`TOYXYZ_REGION_PAINTER`) to **Regional SnapRef · 3D Person Mask**, then connect
its MASK to a Reference node.

The source ID map already accounts for depth/occlusion. Select a stable
`body_id` to preserve identity across reordering. If empty, `body_number`
explicitly selects the current list position; the node also outputs the
selected stable ID. A missing saved ID raises an error instead of switching
to another person. Fully hidden people produce a black mask. The 3D package
is optional for ordinary MASK workflows.

## Scope and limitations

- One reference image per Reference node; one shared output-frame mask per
  reference. Image-batch references and videos are not supported.
- Each spatial reference gets a separate native full-frame model prediction.
  These predictions are mixed by their masks at the returned latent resolution.
  All-white/global references are present in every branch; uncovered pixels
  use a global-only/reference-free prediction. Ordinary overlapping masks
  share output weight proportionally. All blending weights sum to one.
- This can require up to **four model forwards per sampling call** for three
  spatial references plus background. Forwards run serially to avoid expanding
  the model batch/VRAM demand. One ComfyUI queue submission remains one request.
- Original target self-attention and SnapRef kernels remain unchanged.
  Masks resize with nearest-exact sampling on ANIMA's returned, unpadded latent
  frame. Initial and HighRez use the same source masks.
- Spatial branches pass only their active reference K/V tokens to those native
  kernels, instead of computing attention for excluded references at `-inf`
  bias. Contiguous selections are views; noncontiguous selections concatenate
  only the currently executing block, not a second full-model K/V cache.
- DiT Spectrum patch nodes are retained. When a mask plan needs multiple
  predictions, Spectrum's public cache-veto callback forces actual forwards:
  its feature forecast otherwise captures only the last branch and bypasses
  regional mixing on cached steps. Single-prediction global/empty-mask plans
  retain forecasting. Regional generation can therefore be substantially
  slower; experimental regional feature forecasting is not enabled by default.
- While multiple predictions prevent forecasting, the tested Spectrum
  pre-final capture is temporarily disarmed, including reference-free CFG
  calls. This avoids unused feature copies and history updates; its state is
  restored on success, failure and cancellation. Single-prediction plans keep
  the original capture behavior.
- `runtime.make_wrapper(..., forecast=...)` is an explicit Python integration
  point for a separate experimental per-branch forecaster. Normal nodes do not
  supply one. It must be reset for every generation request; no experimental
  cache is enabled in the default workflow.
  `experimental_forecast.RegionalForecast` accepts an explicit request token,
  step count, and injected Spectrum predictor/projection functions. Histories
  are separate per region, CFG branch, conditioning UUID, model and tensor
  signature. Warmup/tail calls stay native; unsupported contexts invalidate
  history and run natively. A completed or failed request requires explicit
  reset. This prototype has CPU contract checks, not image-quality, GPU or
  end-to-end speed validation.
- This is an experimental identity-separation method, not a quality-passed
  public release or a guarantee of pixel-perfect separation.
- Generated hair/clothing can differ from the 3D silhouette, and resizing/VAE
  processing can mix boundaries. SnapRef's trained target LoRA stays active
  as upstream does.
- ComfyCouple `cross_attention` is the initial compatibility target, not a
  claim of completed inference validation. Expanded batches such as
  `full_block` are rejected. Tiled diffusion and other attention patches
  are not verified.
- When upstream SnapRef splits a mixed conditional/unconditional batch, this
  package passes branch-local CFG flags and conditioning UUIDs downstream.
  The original caller metadata and native unsplit paths are unchanged.
  Split CFG with ControlNet, fps or padding masks is not supported and raises
  an error rather than forwarding misaligned batch data.
- Reference state is scoped to the separate predictions and restored even on
  errors/cancellation. This inherits SnapRef's normal, serial ComfyUI
  execution assumptions; concurrent forwards are not supported.
- The installed SnapRef provides its CPU/CUDA attention kernels and fallback
  behavior. Kernel errors propagate; no global-reference fallback is added.

## Upstream licenses

No model weights are bundled or downloaded. The installed SnapRef code is
Apache-2.0. Its v2a weights carry the **CircleStone Labs Non-Commercial License
v1.2**, including non-commercial/non-production restrictions and notices.
Installing weights separately does **not** remove those restrictions.
Read the original model license, notices and any applicable base-model terms
before use or redistribution; commercial generated-output permissions are
distinct from permissions to operate the model commercially.

Sections 2 and 3 of the weight license allow conditional non-commercial
distribution; this is not an unconditional redistribution ban or permission
for commercial/production product integration. The individual
sale-of-derivative-weights exception does not extend to a larger product,
tool or feature incorporating the model.

Original LAKIS extension code is governed by the repository's
[`LICENSE.md`](../../../LICENSE.md), unless otherwise noted; this does not
relicense upstream SnapRef code or weights. The exact pinned sources,
weight hash, original attribution and integration boundary are recorded in
[`THIRD_PARTY_NOTICES.md`](../../../THIRD_PARTY_NOTICES.md) and
[`COMPLIANCE.md`](../../../COMPLIANCE.md).

The original LAKIS extension is included in the 8.1.2 candidate package list;
upstream SnapRef and its weights remain optional, separately installed
dependencies. No commercial/production model-use authorization is established
by separate installation, default-off generation or an acknowledgement.
The packaged helper `ComfyUI/LAKIS/install_snapref.py` requires
`--acknowledge-snapref-terms` before fetching files and preserves the pinned
publisher license and notice. Publication remains subject to separate owner
approval and any necessary publisher clarification or permission.
