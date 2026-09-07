# Release notes

## v7.3.0

### Error diagnostics and LoRA workflow improvements

- Added structured LAKIS error codes and stage-specific diagnostics for generation, runtime, configuration, model, LoRA, i2i, translation, update and installation failures.
- Added an error-report copy action containing active models, LoRAs, generation settings, failing-node information, request identifiers and runtime trace when available.
- Added recovery reporting for interrupted generations and stale one-shot generation authorization files.
- Added automatic LoRA inventory refresh when returning to LAKIS after using LoRA Manager, without periodic background polling.
- Added searchable LoRA selectors that show all candidates on open, filter while typing, exclude LoRAs already in the active stack and use a larger upward-opening menu.
- Preserved existing checkpoints, diffusion models, LoRAs, workflows and saved application settings during update.

## v7.2.4

### External-component notices, upscaler choice, and UI reliability

- Added LAKIS copyright/licence information and consolidated third-party
  notices, available from System Information inside the application.
- Removed the former DSINE-based lighting implementation and its runtime
  dependency while the unfinished lighting feature remains disabled.
- Added the BSD-3-Clause RealESRGAN Anime 6B model as the commercial-use
  default. Existing installations download it from the official release only
  after selection, with pinned size and SHA-256 verification.
- Preserved AnimeSharp V4 Fast as an optional non-commercial choice requiring
  explicit acknowledgement; existing user model files are not deleted.
- Added a first-run upscaler choice with per-user persistence, including
  protected/read-only installation support and in-memory runtime application.
- Exposed the USDU upscale model immediately below its switch in advanced
  generation settings and highlighted its location.
- Rebuilt advanced settings from live ComfyUI schemas: sampler, scheduler,
  model and other combo values use selectable lists; Boolean and two-state
  On/Off-style values use switches; numeric inputs honor node bounds.
- Fixed prompt autocomplete appearing after restart, long pasted-prompt
  selection/overflow, prompt-panel resizing boundaries, LoRA order/state
  persistence, and multiple LAKIS desktop instances.
- Hardened i2i repeated generation, prompt/negative conditioning, original
  image-size controls, composition interaction and result metadata badges.
- Hardened update verification, cache-bypass retries and cross-volume clean
  installation while continuing to preserve user workflows and settings.
- Isolated each launch from stale UI bridge processes left by another LAKIS
  installation; the desktop now accepts only its own identity-verified backend.

## v7.2.3

### Open beta update reliability and UI state fixes

- Prompt autocomplete now remains hidden after startup, state restoration, and
  tab changes; suggestions appear only while the user is actively typing.
- Advanced node settings persist outside the application directory and survive
  a full LAKIS restart.
- Advanced-settings panels stay inside their assigned category without
  horizontal page overflow.
- Update downloads bypass stale caches and retry a failed or mismatched file up
  to three times before safely aborting.
- Clean installation now copies extracted components across drive boundaries,
  so custom locations such as `D:\AI\LAKIS` no longer fail with a
  source/destination root mismatch.
- The release workflow refuses to overwrite an existing version, verifies all
  published files byte-for-byte, and publishes the update manifest only after
  every SHA-256 check passes.

## v7.2.2

### Clean-install workflow launcher fix

- Report: on a clean installation, selecting the Comfy icon and then the
  LAKIS runtime workflow can show an error dialog.
- Cause found: the installer only copied `LAKIS_custom_v7.1.json` into the
  user workflow directory. It did not install the preferred runtime visual
  workflow or the editable user-facing workflow.
- Prepared fix:
  - install `LAKIS_runtime_visual_v7.1.json` under the application-owned
    `ComfyUI/LAKIS/workflows` directory;
  - install `LAKIS_custom_v7.1_editable.json` in the same application-owned
    directory;
  - resolve the computer and person workflow choices from that directory;
  - include both files in the automatic-update manifest without overwriting
    files in `ComfyUI/user/default/workflows`.
- Verification completed:
  - installer compilation succeeds;
  - runtime visual workflow parses with 110 nodes;
  - editable workflow parses with 110 nodes;
  - both workflow choices resolve when the user workflow directory is empty.
- Release verification:
  - application version bumped to v7.2.2;
  - binaries rebuilt and the 51-file update manifest regenerated;
  - both workflow choices pass the empty-user-workflow regression test;
  - the installer compiles with both application-owned workflows included.
