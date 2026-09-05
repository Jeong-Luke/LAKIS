# LAKIS External UI Prototype

This dependency-free prototype establishes the external desktop interaction
contract without exposing ComfyUI node IDs.

- `GenerationSettings.mode`: `fast | detail`
- FAST: Face Detailer, Eye Detailer, USDU disabled
- DETAIL: Face Detailer, Eye Detailer, USDU enabled
- Both modes retain Initial Spectrum and Turbo HighRez
- Public-preview UI temporarily hides the unfinished Light Control.
- Composition Control exposes `CameraSettings {x, y, z, roll, frame_y}`.
- The 3D camera canvas is extracted from the real KR Camera Control v1.1.1
  interaction/math contract: left drag changes azimuth/elevation, right or Alt
  drag rotates the inspection view, wheel changes distance, Shift+wheel changes
  roll, double-click recenters, and numeric/range controls stay synchronized.

The Generate button now submits the application state to the local bridge. The
bridge derives an in-memory, Final-Saver-only API prompt from the validated
v7.1 runtime conversion contract; it never edits the saved workflow or custom nodes.

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
