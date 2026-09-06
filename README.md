# LAKIS Studio

LAKIS Studio is an external user interface and curated workflow environment for ComfyUI.

Copyright © 2026 Luke Jeong. All rights reserved. Original LAKIS material and
third-party components are licensed separately; see [LICENSE.md](LICENSE.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

LAKIS application, user-interface, installer, updater, workflow, brand, and
documentation material may not be copied, modified, or redistributed without
permission. Separately marked LAKIS custom nodes are published under their own
open-source licences: original utility nodes use MIT, while components derived
from AGPL software remain AGPL-3.0-or-later.

## Download

**[Download LAKIS Studio v7.2.4 for Windows](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.2.4/LAKIS_Setup.exe)**

Run `LAKIS_Setup.exe` to install or repair LAKIS. You can also view the
[v7.2.4 release notes and individual files](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.2.4).

## Stable baseline

This repository contains the stable LAKIS distribution line. The current prepared baseline is `v7.2.4`. Earlier development packages and workflows are maintained separately and are not distributed to new users.

## Distribution policy

- LAKIS-owned UI, workflows, launcher, installer, and custom nodes are maintained in this repository.
- Third-party components are installed from their official upstream source at a pinned, tested version.
- A LAKIS backup is used only when the upstream source is unavailable and redistribution is permitted.
- Every downloaded component is verified using SHA-256.
- Models, personal settings, prompts, generated images, and secrets are not committed to this repository.

## Updates

Installed clients receive only files changed by an explicitly published stable release. User workflows, settings, prompts, and generated images are preserved. Updates are staged and verified before replacement, with rollback on failure.

## Third-party software

Third-party project names, pinned versions, original URLs, licenses, and backup eligibility are recorded in `THIRD_PARTY_NOTICES.md`. The installer downloads approved upstream versions and verifies distributable artifacts before installation.
