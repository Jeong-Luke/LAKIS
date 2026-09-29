# LAKIS RC Patcher — TESTER ONLY

This internal tool applies only a user-selected local ZIP using the `lakis-team-patch-v1` format. It has no public update channel, online update check, model downloader, or shared updater state.

Build the UI with `build_rc_patcher.ps1`. The resulting `LAKIS_RC_Patcher.exe` embeds its patch engine and can be shared as a single file. It uses the selected LAKIS installation's embedded Python runtime.

The builder compares an approved base inventory with an approved target inventory. It refuses stale target files, packages only modified/new files, writes removals to `delete[]`, and emits a ZIP SHA-256 sidecar.

## Pre-public Private RC route

`serve_private_rc.py` is also tester-only. Point it at the downloaded, exact `lakis-private-rc` artifact directory containing `private-rc-build.json`, `release-layout.json`, and `LAKIS_RepairPack.zip`. It verifies the recorded hashes, verifies that the RepairPack exactly matches the layout, binds only to `127.0.0.1`, and serves:

- the original layout and RepairPack bytes for the production Launcher consistency/automatic-Repair path;
- an update manifest whose files are the exact bytes extracted from that RepairPack, with SHA-256 values consumed by the unchanged production Updater verification path.

Run `python serve_private_rc.py <artifact-directory> --launch <cloned-install-root>`. The READY line reports `LAKIS_RC_RELEASE_BASE_URL` and `LAKIS_RC_MANIFEST_URL`; `--launch` supplies them only to that process tree. With no variables, public binaries retain their normal public URLs.

For a cloned v7.4.5 installation, first use the existing RC patcher to stage the candidate `LAKIS.exe`, `LAKIS_Patcher.exe`, and `LAKIS_Updater.exe`. That bootstrap is tester-only: the originally shipped v7.4.5 Launcher/Updater cannot fetch a private manifest and is not claimed to do so. After bootstrap, update discovery, manifest download, per-file SHA verification, self-update, restart, release-layout comparison, and automatic Repair use the candidate production binaries and code paths. Keep the server running through the restart.

The helper is not included by Setup, release-layout, RepairPack, or the public update manifest and is never enabled automatically. Always use a disposable clone; the patcher protects the stable user-data trees but the test intentionally replaces LAKIS-managed application files.
