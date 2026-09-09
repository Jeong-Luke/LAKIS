# Release notes

## v7.3.4

- Added the user-selectable LAKIS optimization path: `LAKIS_DETAIL` performs
  one face diffusion pass with lightweight eye refinement, followed by the
  optimized `LAKIS_SCOPE` upscaler.
- Preserved legacy FAST and DETAIL behavior when LAKIS optimization is off.
- Added adaptive VRAM boundary diagnostics and moved cache cleanup outside the
  executing node to prevent worker termination and false generation stalls.
- Confirm the live ComfyUI queue and history before treating websocket silence
  during a long LAKIS_SCOPE pass as `LKS-GEN-1009`.
- Fixed startup warmup, LAKIS mode switching, composition controls, and prompt
  field switches after the external UI regression.
- Added v7.3 editable and runtime-visual workflows to the sidebar and package.
- Changed prompt-field ON switches to the standard LAKIS blue while retaining
  pink exclusively for the LAKIS optimization mode.
- Retained SAM3-based detection and excluded YOLO/Ultralytics materials.

## v7.3.3

- Fixed `LKS-RUN-1001` after cancelling startup by terminating the owned
  launcher process tree instead of leaving the ComfyUI child orphaned.
- Added strict same-installation stale-backend recovery using the recorded PID,
  executable path, command line, port, and ComfyUI API identity.
- Repeated and verified installed-process shutdown before updater relaunch.

## v7.3.2

- Fixed existing installations updated from v7.3.0 to v7.3.1 missing the
  `ComfyUI/LAKIS/STOP_AUTOMATION` safety marker after the production runtime
  directory migration. The marker is now part of the update manifest.

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
- Fixed the monitor workflow identity: AutoPatch now labels the runtime visual
  graph as `LAKIS_DETAIL_runtime_api_v7.3.json` instead of the old hard-coded
  `LAKIS_custom_v7.1.json` name.
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

- Completed a full direct-dependency licence pass: ship standard GPL, AGPL,
  Apache, Meta SAM, Microsoft WebView2, 7-Zip, Real-ESRGAN, CircleStone and
  NVIDIA texts/notices; retain component-level notices during clean install,
  Repair, and update. Keep the transitive Python/PyTorch/CUDA inventory and the
  re-audit transitive binaries if LAKIS begins hosting or embedding them rather
  than retrieving the official upstream distributions. Treat the
  Spectrum modulation-guidance projection weight as an Anima-derived artifact
  under the CircleStone non-commercial terms, not as MIT toolkit code.

- Package LAKIS_DETAIL as `GPL-3.0-only`, retaining Luke Jeong's copyright for
  the original LAKIS implementation and the dependency notice for ComfyUI
  Impact Pack. Ship the node's complete GPL v3 `LICENSE`, `NOTICE.md`, and
  dependency section in `README.md` together with its source.
- Keep YOLO/Ultralytics out of LAKIS. Do not package
  `ComfyUI-Impact-Subpack`, Ultralytics Python packages or executables, YOLO
  weights, provider nodes, caches, or benchmark scripts. LAKIS_DETAIL retains
  the SAM3-based detector path.
- Remove the dormant `window.LAKISDevTriggerError` hook from the production
  `external_ui/app.js` bundle. Keep the simulated-error UI and its trigger API
  exclusively in development builds; verify the production desktop binary and
  shipped JavaScript contain no `LAKISDevTriggerError`, `devtest-`, or simulated
  error-generator entry point.
- Include the complete Meta SAM License as
  `third_party_licenses/Meta-SAM-License.txt` in every installer, update
  package, and release archive that installs or retrieves SAM3 materials.
  Keep the existing SAM3 attribution and official source link in
  `THIRD_PARTY_NOTICES.md`; verify the packaged licence file is the exact
  official agreement applicable to the pinned SAM3 revision.

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
# Antivirus and Windows trust hardening

- The 7.3.3 installer was reported as being blocked by antivirus software.
- The previous artifact was an unsigned self-extracting executable containing
  multiple embedded EXEs and `7zr.exe`, which increases heuristic false-positive
  risk even when the payload is legitimate.
- All first-party EXEs now receive explicit company, product, copyright, and
  version metadata during compilation.
- Release builds must be Authenticode-signed and RFC 3161 timestamped. Developer
  builds may remain unsigned but print a warning.
- The release gate now validates signatures and metadata and can run a Defender
  custom scan before publishing.
- If a final signed build is still detected, submit that exact hash through the
  Microsoft Security Intelligence software-developer false-positive workflow.
