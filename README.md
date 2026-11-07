# LAKIS Studio

LAKIS Studio는 ComfyUI를 더 쉽게 사용할 수 있도록 제작된 외부 사용자 인터페이스이자, 검증된 워크플로 환경입니다.

Copyright © 2026 Luke Jeong. All rights reserved. LAKIS의 독자적인 자료와 제3자 구성 요소에는 각각 별도의 라이선스가 적용됩니다. 자세한 내용은 [LICENSE.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/LICENSE.md)와 [THIRD_PARTY_NOTICES.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/THIRD_PARTY_NOTICES.md)를 확인해 주세요.

LAKIS 애플리케이션, 사용자 인터페이스, 설치기, 업데이터, 워크플로, 브랜드 및 문서 자료는 허가 없이 복사·수정·재배포할 수 없습니다. 별도로 표시된 LAKIS 커스텀 노드는 각자의 오픈 소스 라이선스로 공개됩니다. 독자적인 유틸리티 노드는 MIT 라이선스를 사용하며, AGPL 소프트웨어에서 파생된 구성 요소는 AGPL-3.0-or-later를 유지합니다.




**[Windows용 설치기](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/LAKIS_Setup.exe)**

**[Windows용 CMD 설치기](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/LAKIS_CMD_Installer_8.0.0.zip)**

일반적으로 `LAKIS_Setup.exe`를 사용하세요. Setup을 실행할 수 없다면 기존 8.0.0 CMD 기본 설치기의 압축을 완전히 푼 뒤 `LAKIS_CMD_Install.cmd`로 설치하고, LAKIS를 실행해 앱의 업데이트를 진행하세요. 관리자 권한이나 Defender 예외 설정을 요구하지 않습니다.

이번 배포는 **Windows·NVIDIA GPU 환경용**입니다.

### 검증·복구 파일

- [LAKIS_Setup_SHA256SUMS.txt](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/LAKIS_Setup_SHA256SUMS.txt) · [LAKIS_Setup_manifest.json](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/LAKIS_Setup_manifest.json): 복구 지원 설치기의 해시와 기준 소스·기본 런타임입니다.
- [release-layout.json](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/release-layout.json) · [LAKIS_RepairPack.zip](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/LAKIS_RepairPack.zip): 앱의 무결성 확인·자동 복구에 사용합니다.
- [RUNTIME_SHA256SUMS.json](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/RUNTIME_SHA256SUMS.json): 런타임 파일별 크기·SHA-256입니다.
- [SHA256SUMS.txt](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/SHA256SUMS.txt) · [artifact-manifest.json](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/artifact-manifest.json): 배포물 해시와 기준 소스입니다.

## 안정 버전

이 저장소는 LAKIS의 안정 배포 버전을 관리합니다. 현재 안정 버전은 **`v8.1.1`**입니다. 이전 정식 릴리즈는 보존하며, 개발 패키지와 개발용 워크플로는 별도로 관리합니다.

## v8.1.1 — LoRA·프롬프트·화면 배치 수정

- ANIMA·MOSS LoRA Manager와 다운로드 폴더를 분리하고 새 LoRA 목록을 즉시 갱신합니다.
- ANIMA 3D 포즈의 정밀 프롬프트가 MOSS 화면·요청에 적용되지 않도록 수정합니다.
- MOSS 영역 프롬프트만으로 생성 요청을 진행할 수 있습니다.
- 화면 배율에 따라 연속생성 버튼이 화면 밖으로 밀려나는 문제를 수정합니다.
- 기존 실행환경과 사용자 모델·설정·이미지는 교체하지 않는 프로그램 파일 패치입니다.

## v8.1.0 — ANIMA/MOSS 통합

- ANIMA를 유지하면서 MOSS 엔진과 독립된 모델·생성 설정을 추가했습니다.
- MOSS 와일드카드와 영역 프롬프트의 자동완성·번역·크기 조절을 지원합니다.
- MOSS/ANIMA 라이브러리 메타데이터와 화면·입력 설정을 개선했습니다.
- MOSS i2i는 잠금 상태를 유지하며, 인페인트 평가 모델은 배포하지 않습니다.
- ComfyUI 0.42.0 기반을 유지합니다. 이번 출시 기준은 업데이트 정상 완료·정상 실행·무결성 확인이며, 생성 관련 추가 버그는 제보 후 8.1.1 형식의 패치로 수정합니다. 전체 생성 감사·WebView2 미설치 환경 검증을 완료했다고 주장하지 않습니다.

## v8.0.3 — DETAIL 생성 중단 수정

- 8.0.2에서 DETAIL·LAKIS DETAIL이 `SAM3_Detect`의 `TypeError`와 `LKS-GEN-1001`로 중단되던 모델 연결 오류를 수정했습니다.
- 얼굴·눈 감지에는 SAM3 전용 모델과 텍스트 인코더를 사용하고, 이미지 생성에는 기존 Anima 모델·LoRA 설정을 유지합니다.
- FAST 경로와 기존 노드 ID는 유지하며, 공식 워크플로 3종과 워크플로 생성 도구에 같은 수정을 적용했습니다.

8.0.3은 프로그램 파일 패치였으며 실행환경과 사용자 모델·설정·개인 워크플로·이미지를 교체하지 않았습니다. 현재 업데이트 대상은 위의 8.1.1입니다.

## v8.0.2 — 독립 워크플로와 Link 모바일 개선

- LAKIS UI 없이 사용할 수 있는 공식 v8.0 워크플로를 제공하고, 사용자 편집용·API용을 사이드바에 각각 연결합니다.
- 수정할 노드는 보기 편하게 정리하고, 모니터와 최종 이미지 표시를 보완합니다.
- 디테일 생성은 공통 Anima 모델·LoRA 설정을 사용하며, 얼굴·눈 감지는 별도 SAM3 모델을 사용합니다.
- 큰 3D 메타데이터의 저장 결과 탐색 오류, HTTP Link의 제작 버튼 오류, 초기 태그·설정 덮어쓰기, 연속 제작의 큐 정리 경합을 수정합니다.
- 결과 화면과 라이브러리에서 원본 이미지를 기기에 다운로드할 수 있습니다.
- 공식 템플릿은 앱 전용 리소스에 포함하며, 개인 워크플로와 기존 v7.4 편집본은 보존합니다.

ComfyUI 0.42.0·Python·PyTorch·CUDA·모델 실행환경은 교체하지 않습니다.

### 공식 워크플로 다운로드 (8.1.0 배포본)

- ANIMA: [사용자 편집용](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/LAKIS_custom_v8.0_editable.json) · [API용](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/LAKIS_runtime_api_v8.0.json)
- MOSS: [사용자 편집용](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/LAKIS_MOSS_custom_v8.1_editable.json) · [API용](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/LAKIS_MOSS_runtime_api_v8.1.json)

LAKIS에서는 사이드바의 **ComfyUI 워크플로 선택** 버튼에서 사용자 편집용·API용을 각각 열 수 있습니다. 별도 ComfyUI에서 JSON 파일만 사용하는 경우에는 LAKIS용 커스텀 노드도 필요합니다.

Local Inpaint V2에 필요한 `anima-lllite-inpainting-v2.safetensors`는 LAKIS에 포함되거나 자동 다운로드되지 않습니다. 사용자가 공식 배포처에서 직접 설치해야 합니다.

## 배포 정책

- LAKIS가 소유한 UI, 워크플로, 런처, 설치기와 커스텀 노드는 이 저장소에서 관리합니다.
- 실행 환경은 검증된 고정 버전의 런타임 패키지로 배포합니다. 별도로 내려받는 모델과 구성 요소는 공식 배포처의 고정 버전을 사용합니다.
- 공식 원본을 사용할 수 없고 재배포가 허용된 경우에만 LAKIS 백업을 사용합니다.
- 다운로드한 모든 구성 요소는 SHA-256으로 검증합니다.
- 모델, 개인 설정, 프롬프트, 생성 이미지와 비밀 정보는 이 저장소에 포함하지 않습니다.

## 업데이트

설치된 LAKIS에는 명시적으로 공개된 안정 릴리즈에서 변경된 파일만 전달합니다. 사용자 워크플로, 설정, 프롬프트와 생성 이미지는 유지합니다. 업데이트 파일은 교체 전에 별도로 준비하고 검증하며, 실패하면 기존 상태로 복구합니다.

7.5.4 사용자의 기존 중간 경로 **7.5.4 → 7.5.4.1 → 8.0.0**은 유지합니다. 8.0.x에서는 **8.0.3.1(업데이터 정비) → 8.1.0 → 8.1.1**로 이어집니다. 중간 버전은 최종 버전이 아니며, 각 단계가 완료된 뒤 앱의 업데이트 안내를 따르세요.

8.1.0 런타임 다운로드는 약 **3.1GB**이며, MOSS 모델 약 **15.5GB**는 별도입니다. 이미 검증된 모델이 있으면 재사용합니다. 8.1.1은 프로그램 파일 패치이며 최종 버전은 **8.1.1**로 표시됩니다.

## 제3자 소프트웨어

제3자 프로젝트의 이름, 고정 버전, 공식 주소, 라이선스와 백업 허용 여부는 [8.1.0 THIRD_PARTY_NOTICES.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/THIRD_PARTY_NOTICES.md)에 기록합니다. 설치기는 검증된 런타임과 공식 배포처의 구성 요소를 사용하며, 설치 전에 배포 파일을 검증합니다.

---

## English

LAKIS Studio is an external user interface and curated workflow environment for ComfyUI.

Copyright © 2026 Luke Jeong. All rights reserved. Original LAKIS material and
third-party components are licensed separately; see [LICENSE.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/LICENSE.md) and
[THIRD_PARTY_NOTICES.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/THIRD_PARTY_NOTICES.md).

LAKIS application, user-interface, installer, updater, workflow, brand, and
documentation material may not be copied, modified, or redistributed without
permission. Separately marked LAKIS custom nodes are published under their own
open-source licences: original utility nodes use MIT, while components derived
from AGPL software remain AGPL-3.0-or-later.

### Download

**[Latest stable release: LAKIS Studio v8.1.1](https://github.com/Jeong-Luke/LAKIS/releases/tag/v8.1.1)**

New users can install the pinned 8.1.0 runtime baseline with the installer below, then accept the app's update prompt for 8.1.1.

**[Windows installer — interrupted-update recovery supported](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.1/LAKIS_Setup.exe)**

If an interrupted update prevents LAKIS from starting, download this installer, enter the existing installation folder, and choose **기존 설치 복구 (Repair existing installation)**. This restores the previous installation so you can retry the update from LAKIS. Keep the installation folder and recovery backups.

**[Download LAKIS Studio v8.0.0 CMD Version](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/LAKIS_CMD_Installer_8.0.0.zip)**

Use `LAKIS_Setup.exe` for normal installation and interrupted-update recovery. The retained 8.0.0 CMD installer is an alternative for new installations only; run the installed app afterward to update. Neither installer requires administrator access or a Defender exclusion.

Existing users should launch LAKIS and accept its update prompt. The existing updater preserves the required intermediate runtime update for older installations and continues to 8.1.1. No separate Setup, CMD, or manual ZIP is required. This distribution supports **Windows with an NVIDIA GPU**.

### Stable baseline

This repository contains the stable LAKIS distribution line. The current stable release is **`v8.1.1`**. Previous stable releases are preserved; development packages and workflows are maintained separately.

### v8.1.1 — LoRA, prompt and layout fixes

- Separates ANIMA/MOSS LoRA Manager profiles and download folders, and refreshes newly downloaded LoRAs immediately.
- Keeps ANIMA 3D-pose precision prompts out of MOSS.
- Accepts MOSS region-only positive prompts with an empty main prompt.
- Keeps continuous-generation controls inside their column at scaled desktop resolutions.
- Patches application files without replacing the runtime or user models, settings or images.

### v8.1.0 — ANIMA/MOSS integration

- Adds MOSS with separate model and generation settings while retaining ANIMA.
- Adds MOSS wildcards and region prompts with autocomplete, translation, and resizing.
- Improves library metadata and screen/input controls.
- Downloads missing MOSS weights (approximately 15.5GB) from the official publisher with resume and SHA-256 verification.
- Release acceptance covers the existing native updater, normal app startup, and file integrity. It does not claim a complete generation audit or a fresh-WebView2 test.
- Publishes `release-layout.json`, `LAKIS_RepairPack.zip`, `RUNTIME_SHA256SUMS.json`, `SHA256SUMS.txt`, and `artifact-manifest.json` alongside the installers and runtime.

### v8.0.3 — DETAIL generation fix

- Fixes the incorrect model connection that caused `SAM3_Detect` to fail with `TypeError` / `LKS-GEN-1001` in DETAIL and LAKIS DETAIL after 8.0.2.
- Restores the dedicated SAM3 model and text encoder for detection, while preserving Anima/LoRA generation settings, FAST, and existing node IDs.
- Updates all three official workflow templates and the workflow generator. Existing models, settings, personal workflows, and images are preserved.

The historical 8.0.3 release patched application files without replacing the runtime. The current update target is 8.1.1 as described above.

Focused graph checks and Python syntax checks passed during implementation. Final image generation, mobile-device, Update/Repair validation, and an independent final audit have not been completed.

### v8.0.1 — 3D generation fixes and detailed diagnostics

- Raises the generation request limit from 1MB to 45MB and excludes saved scenes from requests when 3D is off.
- Resolves per-person/background wildcards before translation while preserving templates and masks.
- Removes the control-model notice panel while retaining model verification and distribution terms.
- Distinguishes failure stages and records request size, transport state, acceptance certainty, and correlation IDs.
- Copies a readable summary and compressed detailed diagnostics together, using local processing without an external service.

The 8.0.1 release changed application files only; ComfyUI, Python, PyTorch, CUDA, and models were unchanged.

### v8.0.0 — 3D pose editing and runtime update

#### New features

- **3D pose editing:** Adjust body poses and composition, then apply them to image generation.
- **Per-person prompts:** Describe each person and use those descriptions together with their poses.
- **Pose state restoration:** Continue using saved pose settings after restarting the app.

#### Installation and update improvements

- Updates the runtime to **ComfyUI 0.42.0**.
- Unifies GUI and CMD installation on the new installer engine and fixes CMD startup.
- Improves preservation of existing models, LoRAs, settings, workflows, and generated images during updates and repair.
- Downloads required pose models from the official publisher and verifies their integrity without overwriting existing user models.
- Fixes installed-version display after updating and supplements component licences and notices.

### Previous release: v7.5.3 fixes

- Improves installation and repair file validation and path handling
- Fixes the filename collision in the pinned RvTools archive
- Loads older Library history in additional pages
- Adds wildcard deselect-all
- Improves LAKIS SCOPE memory use and out-of-memory handling

### v7.5.2 fixes

- Prevents persisted advanced settings from re-enabling I2I after it is turned off and contaminating later text-to-image generations
- Detects an installed WebView2 Runtime through its official product registration key in the GUI installer
- Uses a short CMD extraction staging path to avoid Windows 260-character path failures
- Connects the Library save-folder selection to the actual Final Saver output
- Persists the selected folder per installation and reopens the picker at the current folder
- Moves Library single and batch deletions from default or custom roots directly to the Windows Recycle Bin
- Waits for ComfyUI's model inventory during startup so valid models are not reported missing
- Reports active-request, safety-lock, model-initialization, and Inpaint source/mask failures precisely
- Hardens Local Inpaint V2 request validation and final output routing

### v7.5.0 features

- FAST, DETAIL, and LAKIS DETAIL generation modes with Composition and i2i
- Local Inpaint V2 and Inpaint Delete for focused edits that preserve the source outside the edited area
- LAKIS Library with metadata, multi-select, batch deletion, and viewport-based lazy loading
- LAKIS Link for mobile generation and Library access
- Wildcard/random prompt insertion and continuous generation
- Prompt and Composition persistence across desktop and mobile
- Official v7.4 Editable, Runtime Visual, and Runtime API workflows
- Stage-specific generation errors, required-node preflight checks, and diagnostic reports that preserve failure context

The `anima-lllite-inpainting-v2.safetensors` weight required by Local Inpaint V2 is not bundled or downloaded automatically. Users install it manually from the official publisher.

### Distribution policy

- LAKIS-owned UI, workflows, launcher, installer, and custom nodes are maintained in this repository.
- The runtime is distributed as a pinned, verified package. Separately downloaded models and components use pinned versions from their official publishers.
- A LAKIS backup is used only when the upstream source is unavailable and redistribution is permitted.
- Every downloaded component is verified using SHA-256.
- Models, personal settings, prompts, generated images, and secrets are not committed to this repository.

### Updates

Installed clients receive only files changed by an explicitly published stable release. User workflows, settings, prompts, and generated images are preserved. Updates are staged and verified before replacement, with rollback on failure.

The retained legacy path is **7.5.4 → 7.5.4.1 → 8.0.0**. From 8.0.x, the existing updater continues through **8.0.3.1 (updater refresh) → 8.1.0 → 8.1.1**. Intermediate labels are not the final version; follow the app's update prompts after each stage.

The 8.1.0 runtime download is approximately **3.1GB**, plus approximately **15.5GB** of MOSS weights. Already verified models are reused. 8.1.1 is an application-file patch; the final installed version is **8.1.1**.

### Third-party software

Third-party project names, pinned versions, original URLs, licences, and backup eligibility are recorded in the [8.1.0 THIRD_PARTY_NOTICES.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/THIRD_PARTY_NOTICES.md). The installer uses the verified runtime and official upstream components, and verifies distributable artifacts before installation.
