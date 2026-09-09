# LAKIS_DETAIL

Experimental LAKIS DEV detailer. It accepts external face `SEGS`, performs one
configurable face diffusion pass, and enhances adjustable eye regions with a
bounded frequency pass. It does not load SAM3 or run a second eye sampler.

All settings are ordinary serialized ComfyUI widgets. `debug_image` overlays
the effective eye regions; `diagnostics` reports actual timing and settings.
This prototype does not replace the legacy graph until comparison tests pass.

## Dependency and licence

LAKIS_DETAIL directly imports and calls ComfyUI Impact Pack components,
including `impact.core`, `impact.utils`, and `DetailerForEach`. It therefore
requires a compatible installation of ComfyUI Impact Pack and is distributed
under the GNU General Public License version 3 (`GPL-3.0-only`).

Copyright (c) 2026 Luke Jeong for the LAKIS_DETAIL implementation. ComfyUI
Impact Pack remains copyright of its respective authors and contributors and
is distributed under its own GPL-3.0 terms. See `NOTICE.md` and `LICENSE`.
