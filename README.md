# LAKIS Studio

LAKIS Studio is an external user interface and curated workflow environment for ComfyUI.

## Download

**[Download LAKIS Studio v7.1.7 for Windows](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.1.7/LAKIS_Setup.exe)**

Run `LAKIS_Setup.exe` to install or repair LAKIS. You can also view the
[v7.1.7 release notes and individual files](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.1.7).

## Stable baseline

This repository contains the clean `v7.1` distribution line. The current prepared baseline is `v7.1.7`. Pre-v7.1 development packages and workflows are maintained separately and are not distributed to new users.

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
