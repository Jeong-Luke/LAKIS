# Release notes

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
