# LAKIS release regression checklist

Every release must pass this checklist before `manifests/update-latest.json` is
published. The public manifest is the final switch: do not move it while any
item is failing or unverified.

## Automated release gates

- [ ] `installer/Test-ReleaseRegression.ps1 -ExpectedVersion <version>` passes.
- [ ] All installer executables are rebuilt from the tagged source.
- [ ] Every manifest URL and SHA-256 passes
  `Test-UpdateManifest.ps1 -VerifyRemote -Passes 3`.
- [ ] GitHub release remains a draft while assets are uploaded and checked;
  publish it only after all three verification passes complete.
- [ ] `ComfyUI/LAKIS_DEV/external_ui/app.js` passes all three independent
  downloads. Hashes must be calculated from GitHub's tagged bytes, never the
  Windows working-tree copy (LF/CRLF may differ).
- [ ] The release asset set includes Launcher, Patcher, fallback Updater, Desktop host, Model
  Importer, Uninstaller, WebView2 libraries, and Setup.
- [ ] No path below `ComfyUI/models`, `ComfyUI/user`, `ComfyUI/input`, or
  `ComfyUI/output` appears in the updater manifest. Optional/default models are
  installed by the installer or the hash-verifying in-app importer.
- [ ] The public manifest is committed only after all tagged raw files and
  release assets are reachable and verified.

## Update and installation regressions

- [ ] Update a copied 7.2.2 installation to the candidate. Confirm no checksum
  error, especially for `external_ui/app.js`, and confirm rollback data exists.
- [ ] Repeat the same update from a copied 7.2.3 installation.
- [ ] Run clean installation on the default drive and on a different drive.
  Confirm the previous cross-volume move error does not recur.
- [ ] Run **repair** on an existing installation. Confirm version, external UI,
  packaged workflows, Light Control stub, licence notices, desktop runtime,
  Model Importer, and RealESRGAN are present.
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

- [ ] FAST and DETAIL text-to-image each complete once with positive and
  negative prompts demonstrably applied.
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
