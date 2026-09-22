# Release notes

## v7.4.6 updater hardening backlog

- Add long-path-safe rollback storage for deeply nested installations.
- Preserve the primary ApplyUpdate exception when rollback also fails.

## v7.5.0 (unreleased)

### Public LAKIS / DEKIS boundary hardening

- Added a hard manifest guard that rejects any public update path containing `LAKIS_DEV`, `DEKIS`, `LUKIS`, `DEV_VERSION`, or development-only icon names.
- Public LAKIS now forces development/private environment flags off before launching and the Python runtime additionally requires the actual `ComfyUI/LAKIS_DEV` folder before development mode can activate.
- Migrated browser prompt persistence to the public `lakis.promptState.v3` key while retaining the former DEKIS key only as a read-only migration source for existing user data.
- Removed the visible `LAKIS DEV` badge and legacy DEV experiment title from public UI/runtime source.
- Added source/runtime product-boundary tests and a post-build binary/artifact scan; GitHub Actions now blocks draft upload if private/development output is detected.
- Corrected the release checklist to verify `ComfyUI/LAKIS/external_ui/app.js`, not the old `LAKIS_DEV` path.
- Added v7.5.0+ GitHub `release-layout.json` consistency checks for LAKIS-managed files. The layout records version, install-relative path, and byte size so the Launcher can detect missing files, mixed-version files, and retired leftovers without treating the check as a security signature system.
- Added `LAKIS_RepairPack.zip`, generated from the same payload as `release-layout.json`. A confirmed mismatch stages and validates the matching RepairPack, replaces only LAKIS-managed files after the Launcher exits, removes retired files, and restarts LAKIS. User-owned models, workflows/state, input/output and `%LOCALAPPDATA%\\LAKIS Studio` remain outside the layout and RepairPack.
- If GitHub consistency data cannot be reached, the Launcher warns that the comparison could not be completed and continues without blocking startup.
- Added a live ComfyUI runtime-capability preflight before the UI opens. Missing packaged workflow node types or critical dynamic LAKIS nodes now fail closed as `LKS-RUN-1003`.
- Public artifact scanning now checks every EXE in `dist`, including Launcher, Patcher, Updater, Desktop, Model Importer, Setup, and Uninstaller, for DEKIS/LUKIS/private-development markers.
- Fresh Setup and Repair now share the explicit v7.5.0 `ReleaseVersion` instead of hard-coding the previous release version; the release gate rejects direct semantic-version writes to `VERSION`.
- Removed DEKIS/LUKIS product labels from the public Setup safety message so public-facing recovery UI does not imply mixed-product ownership.

### Library and preview performance

- Added cached 320 px WebP thumbnails for recent-generation previews and Library cards while keeping original files for the main preview and Library inspector.
- Limited the desktop recent-generation strip to the latest 20 images from the current session without preloading older images at startup.
- Changed Library card rendering to progressive 20-item batches loaded as the user scrolls, reducing initial DOM and image work for large libraries.
- Moved Library Inpaint/I2I actions directly below the enlarged image and widened the desktop inspector for easier metadata review.

### Prompt workspace

- Added independent desktop-only expand/collapse controls for positive and negative prompt panels. Expanded panels cover the preview column without changing mobile layout.
- Moved the automatic-translation control beside the positive Prompt heading on desktop and kept the original mobile placement.
- Renamed the controls to `<< 확장` and `>> 축소`.

### Navigation and settings UI

- Replaced advanced-setting magnifier icons with small gear icons.
- Added a desktop LAKIS sidebar menu with direct links to the public LAKIS GitHub repository and the LAKIS Arcalive post.
- Moved LAKIS Link below the new LAKIS menu and renamed the Library folder tooltip to `LAKIS 라이브러리`.
- Added bundled LAKIS and Arcalive navigation icons; the Arcalive logo provenance is documented in `THIRD_PARTY_NOTICES.md`.

### Inpaint workspace

- Updated the exclusive Inpaint layout so the Wildcard panel is hidden together with Composition and I2I while Inpaint is active.

### Link Library mobile detail navigation

- Added a dedicated detail header above enlarged Library images in LAKIS, DEKIS, and LUKIS Link.
- Added a mobile-safe close button that returns to the existing Library list without overlapping the image.

### Inpaint removal runtime node

- Added and registered the missing `LAKIS_INPAINT_COLOR_MATCH` node used by removal-mode inpaint.
- Prevented `LKS-NODE-1201` from blocking an inpaint request before it reaches ComfyUI.

### Anima checkpoint compatibility detection

- Fixed `LKS-MOD-1102` incorrectly rejecting Anima checkpoints whose filenames do not contain `anima` and which have no Civitai sidecar metadata.
- Added safe Anima architecture detection from the small safetensors JSON header without loading the model weights into memory.
- Verified the fix directly against the official header of `screenChantvMerge_v11.safetensors` from Civitai model version `3327430`.
- Preserved rejection for non-Anima tensor layouts, malformed safetensors files, and unsupported checkpoint formats without reliable metadata.
- Added the model-compatibility cases to the release regression gate; all 15 error-code and compatibility tests pass.

## v7.4.0

### Local Inpaint V2, LAKIS Link, Library, and workflow updates

- Added Local Inpaint V2 for focused edits while preserving pixels outside the edited area. The required `anima-lllite-inpainting-v2.safetensors` weight remains a user-managed manual install and is not bundled or downloaded automatically.
- Added LAKIS Link mobile access with image preview, pinch zoom, mobile inpaint drawing, wildcard controls, and the shared Library view.
- Added Library multi-select and batch deletion, metadata reliability fixes, and viewport-based lazy image loading for lower browser memory use.
- Added wildcard/random prompt insertion and continuous generation while preserving the one-click/one-prompt execution contract.
- Improved prompt and Composition persistence across desktop and mobile feature-state changes.
- Updated the official editable, runtime visual, and runtime API workflows with Local Inpaint V2 and Final Saver 775.
- Removed retired Light/DSINE product paths and kept private research features out of the public package.
- Fixed release-candidate issues in model detection, recent-image delivery, Link Library discovery, Final Saver result discovery, and patcher packaging.

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
## Missing-node error report completeness

- Missing-node reports now place `error_detail` before the potentially large
  settings snapshot, so copied reports retain the exact missing node type.
- Long advanced-setting strings such as LoRA preset databases are represented
  by their character count instead of being copied in full. This keeps reports
  small without removing generation settings needed for diagnosis.
