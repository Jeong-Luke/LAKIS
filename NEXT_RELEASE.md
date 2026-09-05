# Next release notes

## Planned for v7.2.2

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
- Before release:
  - review the tester's error dialog or
    `ComfyUI/LAKIS_DEV/process_audit.jsonl` if available;
  - bump the application version to v7.2.2;
  - rebuild binaries and regenerate the update manifest;
  - test both workflow choices in a fresh installation;
  - publish only after the clean-install test passes.
