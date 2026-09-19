# LAKIS RC Patcher — TESTER ONLY

This internal tool applies only a user-selected local ZIP using the `lakis-team-patch-v1` format. It has no public update channel, online update check, model downloader, or shared updater state.

Build the UI with `build_rc_patcher.ps1`. The resulting `LAKIS_RC_Patcher.exe` embeds its patch engine and can be shared as a single file. It uses the selected LAKIS installation's embedded Python runtime.

The builder compares an approved base inventory with an approved target inventory. It refuses stale target files, packages only modified/new files, writes removals to `delete[]`, and emits a ZIP SHA-256 sidecar.
