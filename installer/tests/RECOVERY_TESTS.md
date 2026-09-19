# Recovery candidate tests

Run `python installer/tests/run_recovery_tests.py --report-dir <new-results-directory>`.
Use Python with the runtime dependencies (aiohttp, Pillow, torch) and Node on PATH.
The runner does not install dependencies or download models. Real product audit output is redirected to the test report directory.
Each Python test module runs in its own process; socket connections outside loopback are rejected.

`--source <path>` executes the same NEW assertions against another source tree.
Existing regression tests are taken from the selected source tree. The baseline
is the user-provided 7.4.4 ZIP, not an assumed current GitHub/local checkout.

Test meanings:
- `test_recovery_patch.py`: full bridge module, actual state files and tiny real
  metadata images. Mock schema inventory, worker scheduling or backend where
  stated. No source-only AST rewrite substitutes for the patched implementation.
- `test_recovery_http.py`: actual aiohttp HTTP/WebSocket calls to an ephemeral
  loopback fake backend; the full product submission/observation code executes.
  A test-only 100-receive budget stops the OLD closed-socket busy loop, so the
  before/after run terminates. Responses are not fabricated by this guard.
  AutoPatch Python routes execute with PromptServer registration stubbed.
- `test_recovery_providers.py`: actual restored provider definitions and CPU
  tensor helpers with minimal ComfyUI import stubs. No model/Impact inference.
- `test_recovery_graphs.py`: real build_prompt and actual packaged workflows for
  8 feature paths. Inventory choices and source file presence are synthetic;
  the resulting graph SHA-256 must equal captured ORIGINAL 7.4.4 graph hashes.
  This does not assert the original node providers were installed or runnable.
- `test_recovery_autopatch.cjs`: actual JS + real API/Editable JSON in a Node VM.
  Only fetch/timers/app loader methods are mocked. A loader call is not browser
  rendering or successful GPU generation.
- `test_release_component_contract.py`: source text/file inventory guards only.
  These checks do not compile C# or execute PowerShell/Install/Update/Repair.

Existing tests are unchanged. The pinned RealESRGAN model download test requires
an exact 17,938,799-byte model fixture and is NOT silently counted as passed when
the fixture is unavailable. The runner reports it under `not_run`.

The eight baseline graph hashes were captured from ZIP comment
54383bd6e7989e58573c33807cda2d6fec91c47a. They preserve pipeline semantics for the
listed fixture inputs, not all possible user settings. A failing candidate is
not fixed by overwriting these expectations with new values.

Windows C# compilation, PowerShell gates, old-updater bootstrap, fresh install,
Repair, process ownership, current local patch reconciliation, actual Image
Saver metadata compatibility and real UI/GPU generation remain release gates.
