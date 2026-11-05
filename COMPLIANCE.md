# LAKIS compliance notes

## Built-in wildcards

The seven built-in wildcard files are an original AI-assisted curated dataset created specifically for LAKIS. No third-party wildcard pack, external wildcard collection, or specific external dataset was copied. User-added wildcards are separate user-provided material, and LAKIS does not represent that it owns or has cleared user-supplied content.

## Autocomplete dataset

`autocomplete.csv` is LAKIS-owned original, AI-assisted data created specifically for LAKIS. No external third-party dataset was copied. It requires no third-party permission evidence, `THIRD_PARTY_NOTICES` entry, or separate public user-facing notice.

## External LLLite inpainting weight

`anima-lllite-inpainting-v2.safetensors` is not included, mirrored, or automatically downloaded by LAKIS. Users obtain it directly from the official publisher at `https://huggingface.co/kohya-ss/Anima-LLLite` and install it manually.

The weight is governed by the CircleStone Labs Non-Commercial License v1.0. Its non-commercial and non-production restrictions remain applicable. Known SHA-256: `5242e677d2be34ee70ca7c97c3b14ff5ee49838c03fc1e60ac4852a180db6ef5`.

The `ComfyUI-Anima-LLLite` node code is a separate Apache-2.0 component.

## External 3D pose and region weights

`anima_3dpose_6200.safetensors` and `anima_regional_4335.safetensors` are not
bundled or mirrored. The installer/updater downloads them directly from the
official fixed revision and verifies their sizes and SHA-256 values. Repair
adds missing files; a conflicting existing file is preserved and reported.
Program rollback retains downloaded models as user data. The official model card at
`toyxyz/Anima_ControlNet-LLLite`, revision
`37f3a4b6574f1dce3dfe3b5440285a39b11b3d8d`, identifies
`upstream-anima-and-source-data-terms`. The Anima non-commercial/non-production
restrictions and source-data conditions remain applicable to official downloads.
The GPL Toyxyz editor, MIT Three.js, Apache MHR meshes, SAM-licensed sparse
mapping, and Apache LLLite node code are separate components with separate terms.

## Translation network disclosure

한국어 번역 기능을 사용하면 번역할 프롬프트 텍스트가 외부 Google 번역 서비스로 전송될 수 있습니다.

## MOSS preview model boundary

The 8.1.0 preview's MOSS diffusion model, Qwen3.5 encoder and FLUX.2
autoencoder are pinned publisher downloads, not bundled runtime files.
Their filenames, hashes, licence sources and attributions are listed in
`THIRD_PARTY_NOTICES.md`. Existing ANIMA model restrictions still apply to
ANIMA; adding MOSS does not replace those terms.

The exact upstream revision and conversion provenance of the Qwen INT8
repack remain unverified. The publisher's Apache-2.0 declaration and the
official Qwen licence are recorded separately from that unresolved lineage.
This candidate is not licence-audit-passed.

MOSS i2i is disabled. The experimental Moss-Image-Edit node and adapter are
excluded from the preview dependency set.
