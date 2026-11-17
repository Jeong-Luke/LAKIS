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

## Optional SnapRef references in the 8.1.2 candidate

The intended LAKIS delivery is a free standalone local application, not a
paid feature or paid generation service. No monetization is planned here.
Free delivery still preserves the publisher's model-use conditions.

SnapRef inference code and its model weights have separate terms:

- Code: `ArcAnima/SnapRef` revision
  `1f7e606621052c11486c7aa5ccf6c2c12c2c5a3a`, Apache-2.0.
- Adapter: `0ppxnhximxr/snapref-v2a` revision
  `e6d6a21e4d56faae4454a1cc9bfd065d87358bf2`,
  `snapref_v2a.safetensors`, SHA-256
  `8a22fc28d060447544eda283b36efe2dcdbad7422cbc0b8d42828d55a8a61ab4`.
  Its [exact license](https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2/LICENSE.md)
  is CircleStone Labs Non-Commercial License v1.2; its
  [original notice](https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2/NOTICE.txt)
  is preserved in `third_party_licenses/SnapRef-v2a-NOTICE.txt`.

The weight license is **not an unconditional redistribution ban**: sections
2 and 3 permit distribution subject to non-commercial-purpose restrictions,
the license text, attribution, direct rights from CircleStone, and the other
conditions. This does not authorize commercial or production model operation.
Section 2(c)'s individual sale-of-derivative-weights exception does not cover
a larger product, tool, or feature incorporating the model. Output permissions
are separate; applicable base-model and third-party terms still apply.

The 8.1.2 candidate package list includes the original LAKIS regional
integration code, `ComfyUI-LAKIS-Regional-Reference`, but excludes upstream
SnapRef and its adapter. The regular standalone launcher exposes the reference
panel; generation remains OFF until the user enables it, and unavailable
dependencies keep its controls disabled. Installers/updaters do not
automatically download the adapter. The manually invoked helper
`ComfyUI/LAKIS/install_snapref.py` (source:
`installer/install_snapref_experiment.py`) requires
`--acknowledge-snapref-terms` before any download or installation. It fetches
the pinned upstream code license, weight license and notice, verifies their
hashes, and preserves those files with the installed inference package.
Existing conflicting files are not overwritten.

Separate user installation, default-off gating and acknowledgement do not
change the model license or constitute release approval. The formal weight license's
non-commercial definition and the publisher's
[free-service clarification](https://huggingface.co/circlestone-labs/Anima/discussions/37)
must not be treated as a blanket exemption for every free application.
The free local integration must retain the license, attribution and limits
on model use. Any use outside those terms, including an ambiguous
third-party-end-user/production scenario, needs separate clarification.
The publisher lists `tdrussell@circlestone.ai` as its licensing contact.

The reference feature is approved for the 8.1.2 scope. This does not certify
license compliance for every deployment or authorize publication.
The regional extension's original LAKIS code remains subject to `LICENSE.md`;
interoperation with Apache-licensed SnapRef does not relicense either the
weights or LAKIS code. This change does not authorize a new public release,
change the pinned base model's v1.0 license, or change existing installations.

## Optional SnapRef download at 8.1.3 update time

The 8.1.3 candidate keeps the 8.1.2 package boundary: upstream SnapRef code
and the v2a adapter remain excluded from the bundled program set, with the
same pinned revisions, hashes, publisher URLs, and license/notice files
listed above and in `THIRD_PARTY_NOTICES.md`.

The standalone updater offers the download once, at update time, and only in
an interactive session: when finishing a stock 8.1.2 → 8.1.3 update, or
through an explicit `SnapRef 다운로드…` retry from the updater while 8.1.3
is current. Headless and repair runs never offer it, and checking the
version alone neither asks for terms nor starts a download.
Fresh-installation auto-download is not offered.

Skipping or failing the optional download leaves the completed LAKIS update
usable. The offer runs outside the core error/rollback path: a skip returns
without changes, and a failure reports that the LAKIS update finished while
only the optional SnapRef preparation did not, with a retry through the
updater.

The download choice is not stored as feature-use consent. First use of the
reference feature requires a separate acknowledgement keyed to the published
weight and its exact terms (adapter filename, weight SHA-256, and publisher
license-text hash). The helper's `--acknowledge-snapref-terms` likewise
confirms review and acceptance of the pinned publisher terms before any path
change or network access, and is not a commercial or production license
grant.

The helper fetches the pinned inference files and code license from GitHub
and checks their Git blob IDs. It fetches the weight, weight license and
notice from the pinned Hugging Face repository over HTTPS. The weight must
match its published size and SHA-256; both text files must match their
pinned SHA-256. The helper preserves the licenses and notice, refuses
conflicting existing files and publishes the verified weight and node
directory in separate same-volume rename operations.

The v1.2 weight license's conditional distribution terms (sections 2 and 3)
do not authorize commercial or production model operation; the section 2(c)
individual sale-of-derivative-weights exception does not cover a larger
product, tool, or feature incorporating the model. Output permissions are
separate from model-operation rights, and applicable base-model and
third-party terms still apply. This section states no blanket ban on output
sales and grants no commercial or production rights. Interoperation does not
relicense upstream code or weights, and this candidate is not a publication
approval. No Rust feature is included.

## Translation network disclosure

한국어 번역 기능을 사용하면 번역할 프롬프트 텍스트가 외부 Google 번역 서비스로 전송될 수 있습니다.

## MOSS model boundary in the 8.1.2 candidate

The 8.1.2 candidate's MOSS diffusion model, Qwen3.5 encoder and FLUX.2
autoencoder are pinned publisher downloads, not bundled runtime files.
Their filenames, hashes, licence sources and attributions are listed in
`THIRD_PARTY_NOTICES.md`. Existing ANIMA model restrictions still apply to
ANIMA; adding MOSS does not replace those terms.

The Qwen INT8 repack is licensed under Apache-2.0.

MOSS i2i is disabled. The experimental Moss-Image-Edit node and adapter are
excluded from the 8.1.2 dependency set.
