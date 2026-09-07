# Release notes

## v7.3.1

### Diagnostics, LoRA workflow, autocomplete, and LAKIS_SCOPE

- Expanded generation error reports with failure-stage, node, model, LoRA,
  output, i2i, composition, advanced-setting, and runtime-trace diagnostics.
- Fixed Nova Anime and other metadata-confirmed Anima-derived checkpoints
  being rejected solely because their filenames did not contain `Anima`.
- Refresh the LoRA catalogue when returning from LoRA Manager; added keyboard
  search, live filtering, registered-LoRA exclusion, and a larger upward list.
- Updated autocomplete to the 2026-09-07 Korean Danbooru dataset and fixed
  duplicate suggestions, space/underscore matching, Korean lookup, and escaped
  compound tags such as character names containing parentheses.
- Added the independent MIT-licensed `LAKIS_SCOPE` refinement node and exposed
  Ultimate/SCOPE processing as separate workflow paths; Ultimate remains the
  default and SCOPE is user-selectable.
- Updated both packaged workflows: the monitor icon opens the expanded runtime
  workflow and the person icon opens the validated clean editable workflow.
- Moved the production external UI from the legacy `LAKIS_DEV` directory to
  `LAKIS`, and removed the development-only simulated-error hook from shipped
  production JavaScript.
- Kept the unfinished lighting feature disabled and DSINE-free.

## v7.3-dev4

### Nova Anime compatibility and complete validation diagnostics

- Fixed Nova Anime and other Anima-derived checkpoints being rejected as
  incompatible merely because their filenames did not contain the exact word
  `Anima`.
- Anima compatibility now also uses the downloaded checkpoint metadata
  (`base_model` / `baseModel`) instead of relying only on the filename.
- Fixed request-validation error reports omitting the submitted model,
  generation, output, LoRA, composition, i2i, and advanced-setting context as
  `settings: null`.
- Include these changes in the next production release build and regression
  test both a metadata-confirmed Anima derivative and an unrelated model.

## Next patch — required cleanup

- Remove the dormant `window.LAKISDevTriggerError` hook from the production
  `external_ui/app.js` bundle. Keep the simulated-error UI and its trigger API
  exclusively in development builds; verify the production desktop binary and
  shipped JavaScript contain no `LAKISDevTriggerError`, `devtest-`, or simulated
  error-generator entry point.

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
