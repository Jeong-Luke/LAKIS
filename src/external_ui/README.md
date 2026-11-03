# LAKIS External UI Prototype

This dependency-free prototype establishes the external desktop interaction
contract without exposing ComfyUI node IDs.

- `GenerationSettings.mode`: `fast | detail`
- FAST: Face Detailer, Eye Detailer, USDU disabled
- DETAIL: Face Detailer, Eye Detailer, USDU enabled
- Both modes retain Initial Spectrum and Turbo HighRez
- Retired Light Control is excluded from the public runtime and UI.
- Composition Control exposes `CameraSettings {x, y, z, roll, frame_y}`.
- The 3D camera canvas is extracted from the real KR Camera Control v1.1.1
  interaction/math contract: left drag changes azimuth/elevation, right or Alt
  drag rotates the inspection view, wheel changes distance, Shift+wheel changes
  roll, double-click recenters, and numeric/range controls stay synchronized.

The Generate button now submits the application state to the local bridge. The
bridge configures the controls in the same standalone v8.0 graph that ComfyUI
opens directly. Explicit legacy templates retain the earlier conversion path.
Neither path edits saved workflows or custom-node source.

The sidebar's ComfyUI workflow menu has two separate loaders:

- `사용자 편집용 워크플로` opens the packaged
  `LAKIS_custom_v8.0_editable.json` with ComfyUI's native graph loader.
- `API용 워크플로` opens the packaged `LAKIS_runtime_api_v8.0.json` with
  ComfyUI's API-prompt loader. The legacy `runtime` request kind is treated as
  `api`; an API request never substitutes an editable or visual graph.
- Existing personal v7.4 workflow files remain untouched and can still be
  loaded through ComfyUI's existing legacy workflow-loading path.

- Accepted S1R2 Initial Spectrum and validated Turbo HighRez are shared.
- FAST keeps Face/Eye/USDU off; DETAIL turns all three on.
- Prompt, fixed prompt, negative prompt, seed, image size, model settings, and
  CameraSettings are mapped without exposing node IDs to the browser.
- One user click creates one allowance which is atomically consumed immediately
  before exactly one `/prompt` request; retries remain zero.
- WebSocket execution events feed the button progress gauge.
- Final Saver 775's current-prompt output updates preview/history.
- A second click sends an explicit cancellation request for the active job.

The bridge attaches only to an already-running ComfyUI server. It does not
start, stop, or restart ComfyUI.

## Dedicated launcher

Run `C:\AI Library\ComfyUI_windows_portable\LAKIS.bat`. The batch starts the
windowless `launch_lakis.py` orchestrator. It attaches to an existing ComfyUI or
launches the exact portable backend once with `--disable-auto-launch`, waits for
ComfyUI and the local UI bridge, then opens only the LAKIS URL. It does not open
the ComfyUI frontend.
