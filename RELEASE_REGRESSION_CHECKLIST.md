# LAKIS release regression checklist

Every release must pass this checklist before `manifests/update-latest.json` is
published. The public manifest is the final switch: do not move it while any
item is failing or unverified.

## Automated release gates

- [ ] `installer/Test-ReleaseRegression.ps1 -ExpectedVersion <version>` passes.
- [ ] GPT, DeepSeek, and Codex all PASS the exact same frozen source fingerprint before any Private RC artifact is built.
- [ ] `.github/workflows/prepare-private-rc.yml` builds the final artifact set exactly once from that audited candidate and uploads it as the `lakis-private-rc` Actions artifact with its fingerprint and file hashes.
- [ ] Private RC tests and explicit owner approval are recorded against that exact fingerprint and artifact-set SHA; `Test-ReleaseApprovalGate.ps1` passes before any public tag or release is created.
- [ ] `.github/workflows/publish-installer.yml` downloads the explicitly selected `rc_run_id`, never rebuilds the approved binaries, and publishes only those exact bytes.
- [ ] Every manifest URL and SHA-256 passes
  `Test-UpdateManifest.ps1 -VerifyRemote -Passes 3`.
- [ ] GitHub release remains a draft while assets are uploaded and checked;
  publish it only after all three verification passes complete.
- [ ] `ComfyUI/LAKIS/external_ui/app.js` passes all three independent
  downloads. Hashes must be calculated from GitHub's tagged bytes, never the
  Windows working-tree copy (LF/CRLF may differ).
- [ ] `Test-PublicProductBoundary.ps1` passes on the freshly built `dist`
  directory before any draft release asset upload and scans every public EXE:
  Launcher, Patcher, Updater, Desktop, Model Importer, Setup, and Uninstaller.
- [ ] The generated update manifest contains no `LAKIS_DEV`, `DEKIS`,
  `LUKIS`, `LAKIS_LUKE`, `DEV_VERSION`, `LUKE_VERSION`, or private/development asset paths.
- [ ] `New-ReleaseLayout.ps1` generates `release-layout.json` and `LAKIS_RepairPack.zip` from the same exact release payload; `test_release_layout.py` confirms every layout path/size matches the corresponding packed file.
- [ ] The layout covers only LAKIS-managed application/runtime files and explicitly excludes `ComfyUI/models`, `ComfyUI/user`, `ComfyUI/input`, `ComfyUI/output`, user workflows/state, logs and caches.
- [ ] Public Launcher fetches the matching GitHub Release `release-layout.json` before update/runtime startup and compares required-file existence, byte size, and retired-file absence.
- [ ] If GitHub comparison cannot be completed, the exact warning text is shown and LAKIS continues without the comparison; a confirmed mismatch instead schedules one automatic RepairPack replacement cycle.
- [ ] Automatic Repair validates the staged RepairPack against the same layout before replacing files, runs only after the Launcher exits, removes retired files, restarts LAKIS, and uses a marker to prevent repair loops.
- [ ] Fresh Setup and Repair both write `VERSION` from the candidate
  `ReleaseVersion`; no direct semantic-version string write is allowed.
- [ ] The live ComfyUI runtime-capability preflight confirms packaged workflow node
  types plus LAKIS_DETAIL, LAKIS_SCOPE, LAKIS_VRAM_GATE and Local Inpaint core nodes.
- [ ] The release asset set includes Launcher, Patcher, fallback Updater, Desktop host, Model
  Importer, Uninstaller, WebView2 libraries, and Setup.
- [ ] No path below `ComfyUI/models`, `ComfyUI/user`, `ComfyUI/input`, or
  `ComfyUI/output` appears in the updater manifest. Optional/default models are
  installed by the installer or the hash-verifying in-app importer.
- [ ] The public manifest is committed only after all tagged raw files and
  release assets are reachable and verified.

## Update and installation regressions

- [ ] Starting from the actual public v7.4.5 installation and its shipped
  Patcher/Updater, update to v7.5.0 through the production path. Confirm
  download/SHA validation, staging/replacement, updater self-update, VERSION
  transition, automatic restart, and the v7.5.0 GitHub size/layout consistency check all succeed.
- [ ] Restart v7.5.0 a second time without running Repair. It must not re-offer
  v7.5.0, must bind to `ComfyUI/LAKIS`, and must pass layout consistency and runtime
  capability checks again.
- [ ] Interrupt/fail the updater self-update helper in a controlled RC copy and
  verify the installation remains fail-closed/recoverable rather than silently
  starting a mixed runtime. Restore Stable before the next RC attempt.
- [ ] Update a copied 7.2.2 installation to the candidate. Confirm no checksum
  error, especially for `external_ui/app.js`, and confirm rollback data exists.
- [ ] Repeat the same update from a copied 7.2.3 installation.
- [ ] Run clean installation on the default drive and on a different drive.
  Confirm the previous cross-volume move error does not recur.
- [ ] Run **repair** on an existing installation. Confirm VERSION is v7.5.0
  and the repaired external UI, packaged workflows, managed public nodes, licence
  notices, desktop runtime, Model Importer, and RealESRGAN are present. Manual Repair
  must clear any automatic-repair retry marker; launch immediately and require the
  GitHub layout consistency check plus runtime-capability PASS.
- [ ] Confirm the candidate manifest, installer, external UI, and packaged
  workflows contain no retired Light Control or DSINE product dependency.
- [ ] Before and after Repair, hash representative files under
  `models/loras`, `models/checkpoints`, `models/diffusion_models`,
  `ComfyUI/user`, `ComfyUI/input`, and `ComfyUI/output`. Every hash and file
  count must remain unchanged. Only the pinned RealESRGAN file under
  `models/upscale_models` is an intentional model write.
- [ ] Preserve `%LOCALAPPDATA%\LAKIS Studio` across Repair, including prompts,
  advanced settings, LoRA order/weights, upscaler choice, migration consent,
  and all other saved state.
- [ ] Point **new install** at both an existing LAKIS installation and an
  unrelated non-empty folder. It must refuse, direct LAKIS users to Repair,
  and leave every sentinel/user file byte-for-byte unchanged.
- [ ] Launch from the LAKIS shortcut and from the ComfyUI workflow entry. Only
  one LAKIS instance may remain open.
- [ ] With two LAKIS/ComfyUI installations present, launch each separately and
  confirm its UI binds only to the backend belonging to that same install.
  A healthy but unrelated backend already using a familiar port must be
  rejected rather than silently reused.
- [ ] Alternate launches between two installations and confirm persisted UI,
  workflow, LoRA, advanced-setting, and upscaler state is never imported from
  or written into the other installation unintentionally.
- [ ] Leave another installation's legacy UI bridge listening on port 8766,
  then launch the candidate. The candidate must open its own version and
  installation state through a separately assigned, identity-verified port.
- [ ] Confirm generation errors identify the saved log location.

## UI and saved-state regressions

- [ ] Restart with saved prompts. Autocomplete must remain hidden until the
  user is actively editing text.
- [ ] Paste a long external prompt. Selection/caret scrolling must stay inside
  the editor without pushing the page sideways.
- [ ] Resize positive and negative prompt editors in every tab. Inner and outer
  boxes resize together, stay within their own half, and never overlap.
- [ ] Verify sampler, scheduler, upscaler, and every other enum in advanced
  settings is selectable. Boolean and On/Off pairs use switches and preserve
  the exact workflow value.
- [ ] Change representative advanced values, restart, and verify persistence
  without clipping or overlapping neighbouring UI.
- [ ] Add, remove, reorder, enable, and edit LoRAs; restart and verify the exact
  order and values are retained.
- [ ] Verify width/height wheel input, aspect lock, and i2i source-size option.
- [ ] Verify Page Up/Page Down never creates horizontal scrolling.
- [ ] Confirm the one-time upscaler licence screen stays dismissed after a
  choice. RealESRGAN selection must auto-download, SHA-256 verify, apply, and
  survive restart; AnimeSharp must require acknowledgement and an existing
  user-provided/installer-provided file.

## Generation regressions

- [ ] On the frozen v7.5.0 Private RC, confirm release-layout consistency and live
  runtime-capability preflight complete before the Desktop UI opens. Also verify a forced
  managed-file size mismatch triggers one automatic RepairPack cycle, while a blocked GitHub
  layout request shows the warning and continues without the comparison.
- [ ] FAST and DETAIL text-to-image each complete once with positive and
  negative prompts demonstrably applied.
- [ ] Run two ordinary generations consecutively from the same launched RC
  session. Each click must submit exactly one `/prompt`, each result must reach
  Final Saver node 775, save an actual output file, and return the same final
  image to the LAKIS UI/Library.
- [ ] Local Inpaint completes once through its v2 path with the edited region
  reflected in the saved Final Saver 775 output and returned UI image.
- [ ] i2i completes three consecutive runs using the same input. On every run,
  input influence, positive prompt, negative prompt, strength, dimensions, and
  i2i badge must be correct.
- [ ] Enabling i2i disables composition control and shows the explanatory
  message.
- [ ] Automatic translation works independently for positive and negative
  prompts.
- [ ] Prompt-inspector metadata matches the prompt and settings actually sent.

Record the date, tester, source commit, artifact hashes, and outcome in the
release notes or test report. A skipped manual item must be explicitly marked
with its reason; it is not a pass.
