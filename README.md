# LAKIS Studio

LAKIS Studio는 ComfyUI를 더 쉽게 사용할 수 있도록 제작된 외부 사용자 인터페이스이자, 검증된 워크플로 환경입니다.

Copyright © 2026 Luke Jeong. All rights reserved. LAKIS의 독자적인 자료와 제3자 구성 요소에는 각각 별도의 라이선스가 적용됩니다. 자세한 내용은 [LICENSE.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/LICENSE.md)와 [THIRD_PARTY_NOTICES.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/THIRD_PARTY_NOTICES.md)를 확인해 주세요.

LAKIS 애플리케이션, 사용자 인터페이스, 설치기, 업데이터, 워크플로, 브랜드 및 문서 자료는 허가 없이 복사·수정·재배포할 수 없습니다. 별도로 표시된 LAKIS 커스텀 노드는 각자의 오픈 소스 라이선스로 공개됩니다. 독자적인 유틸리티 노드는 MIT 라이선스를 사용하며, AGPL 소프트웨어에서 파생된 구성 요소는 AGPL-3.0-or-later를 유지합니다.

## 다운로드

**[최신 정식 버전: LAKIS Studio v8.1.0 릴리즈](https://github.com/Jeong-Luke/LAKIS/releases/tag/v8.1.0)**

### 기존 8.0.x 업데이트

평소처럼 LAKIS를 실행하고 업데이트 안내에서 진행하세요. 기존 업데이터가 필요한 업데이터 정비를 먼저 적용한 뒤 자동으로 8.1.0 업데이트를 이어갑니다. 별도 설치기나 CMD·ZIP을 실행할 필요가 없습니다.

없는 MOSS 모델 약 15.5GB는 공식 배포처에서 이어받기·SHA-256 검증 후 추가합니다. 기존 모델·LoRA·워크플로·설정·입력·생성 이미지는 보존합니다.

중간에 `8.0.3.1`이 표시될 수 있으며 최종 버전은 `8.1.0`입니다. 프로그램 런타임 다운로드는 약 3.1GB이고 모델 다운로드는 별도입니다.

### 신규 설치

신규 사용자는 아래 **8.1.0 설치기**를 사용하세요.

**[Windows용 설치기 (v8.1.0)](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/LAKIS_Setup.exe)**

**[Windows용 CMD 기본 설치기 (v8.0.0)](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/LAKIS_CMD_Installer_8.0.0.zip)**

일반적으로 `LAKIS_Setup.exe`를 사용하세요. Setup을 실행할 수 없다면 기존 8.0.0 CMD 기본 설치기의 압축을 완전히 푼 뒤 `LAKIS_CMD_Install.cmd`로 설치하고, LAKIS를 실행해 앱의 업데이트를 진행하세요. 관리자 권한이나 Defender 예외 설정을 요구하지 않습니다.

이번 배포는 **Windows·NVIDIA GPU 환경용**입니다.

### 검증·복구 파일

- [release-layout.json](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/release-layout.json) · [LAKIS_RepairPack.zip](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/LAKIS_RepairPack.zip): 앱의 무결성 확인·자동 복구에 사용합니다.
- [RUNTIME_SHA256SUMS.json](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/RUNTIME_SHA256SUMS.json): 런타임 파일별 크기·SHA-256입니다.
- [SHA256SUMS.txt](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/SHA256SUMS.txt) · [artifact-manifest.json](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/artifact-manifest.json): 배포물 해시와 기준 소스입니다.

## 안정 버전

이 저장소는 LAKIS의 안정 배포 버전을 관리합니다. 현재 안정 버전은 **`v8.1.0`**입니다. 이전 정식 릴리즈는 보존하며, 개발 패키지와 개발용 워크플로는 별도로 관리합니다.

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

8.0.3은 프로그램 파일 패치였으며 실행환경과 사용자 모델·설정·개인 워크플로·이미지를 교체하지 않았습니다. 현재 업데이트 대상은 위의 8.1.0입니다.

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

**8.1.0 출시 확인 범위:** 기존 앱 업데이터의 업데이트 완료·정상 실행·파일 무결성을 확인했습니다. 전체 생성 감사와 독립 최종 감사의 전체 통과를 의미하지 않습니다.

## v8.0.1 — 3D 생성 수정과 상세 오류 진단

- 다인 3D 생성 요청의 1MB 제한을 45MB로 확대하고, 3D를 끄면 저장된 장면을 생성 요청에서 제외합니다.
- 인물별·배경 와일드카드를 치환한 뒤 번역하며, 원문·마스크는 유지합니다.
- 제어 모델 안내 박스를 제거하고 실제 모델 검증과 배포 약관은 유지합니다.
- 오류 발생 단계를 세분화하고 요청 크기·통신 상태·접수 여부·추적 정보를 기록합니다.
- 한 번 복사하면 요약과 압축된 상세 진단이 함께 포함되며, 외부 서비스 없이 로컬에서 처리합니다.

v8.0.1 배포에서도 8.0.0 기본 설치기와 실행환경을 유지하고 변경된 프로그램 파일만 제공했습니다.

## v8.0.0 — 3D 포즈 편집과 실행 환경 업데이트

### 새로운 기능

- **3D 포즈 편집:** 인체의 자세와 구도를 직접 조절하고 이미지 생성에 적용할 수 있습니다.
- **인물별 프롬프트:** 인물마다 설명을 지정해 포즈와 함께 생성에 반영할 수 있습니다.
- **포즈 설정 복원:** 앱을 다시 실행해도 저장한 포즈 설정을 이어 사용할 수 있습니다.

### 설치·업데이트 개선

- ComfyUI **0.42.0** 기반으로 실행 환경을 업데이트했습니다.
- GUI·CMD 설치기를 새 설치 엔진으로 통합하고, CMD 실행 오류를 수정했습니다.
- 업데이트·복구 과정에서 기존 모델, LoRA, 설정, 워크플로, 생성 이미지를 보존하도록 개선했습니다.
- 필요한 포즈 모델은 공식 배포처에서 다운로드하고 파일 무결성을 확인합니다. 기존 사용자 모델은 덮어쓰지 않습니다.
- 업데이트 후 버전 표시 오류를 수정하고, 구성 요소의 라이선스·고지문을 보완했습니다.

## 이전 버전: v7.5.3 수정 사항

- 설치·복구 파일 검증 및 경로 처리 안정성 개선
- RvTools 압축 파일 이름 충돌로 인한 설치 실패 수정
- Library의 오래된 기록 추가 불러오기 개선
- 와일드카드 전체 해제 추가
- LAKIS SCOPE 메모리 사용 및 메모리 부족 처리 개선

## v7.5.2 수정 사항

- i2i를 끈 뒤에도 저장된 고급 설정이 입력 경로를 다시 켜 일반 생성 결과를 오염시키는 문제 수정
- Windows에 설치된 WebView2 Runtime을 공식 제품 키로 정확히 감지하도록 GUI 설치기 개선
- CMD 설치기의 압축 해제 임시 경로를 단축하여 Windows 260자 경로 제한으로 인한 설치 실패 수정
- Library에서 선택한 이미지 저장 폴더를 실제 Final Saver 출력에 연결
- 사용자별 저장 경로 유지와 현재 폴더에서 다시 열리는 선택창
- 기본·사용자 지정 경로의 Library 단일/일괄 삭제를 Windows 휴지통으로 직접 처리
- 시작 직후 ComfyUI 모델 목록 초기화를 기다려 정상 모델이 누락으로 판정되는 문제 수정
- 실행 중 요청, 안전 잠금, 모델 초기화, 인페인트 원본·마스크 오류를 구체적으로 안내
- Local Inpaint V2 요청 검증과 결과 저장 경로 안정화

## v7.5.0 주요 기능

- FAST, DETAIL, LAKIS DETAIL 생성 모드와 Composition, i2i
- 작은 영역을 수정하고 원본 영역을 보존하는 Local Inpaint V2와 Inpaint Delete
- 이미지 메타데이터, 다중 선택, 일괄 삭제 및 화면 근처 지연 로드를 지원하는 LAKIS Library
- 모바일에서 생성 화면과 Library를 사용하는 LAKIS Link
- 일반 프롬프트에 추가되는 와일드카드 / 랜덤 선택과 연속 생성
- 모바일·PC 프롬프트 및 Composition 설정 유지
- Editable, Runtime Visual, Runtime API로 구성된 공식 v7.4 workflow
- 단계별 생성 오류 코드, 필수 노드 사전 검사 및 진단 정보가 보존되는 오류 보고

Local Inpaint V2에 필요한 `anima-lllite-inpainting-v2.safetensors`는 LAKIS에 포함되거나 자동 다운로드되지 않습니다. 사용자가 공식 배포처에서 직접 설치해야 합니다.

## 배포 정책

- LAKIS가 소유한 UI, 워크플로, 런처, 설치기와 커스텀 노드는 이 저장소에서 관리합니다.
- 실행 환경은 검증된 고정 버전의 런타임 패키지로 배포합니다. 별도로 내려받는 모델과 구성 요소는 공식 배포처의 고정 버전을 사용합니다.
- 공식 원본을 사용할 수 없고 재배포가 허용된 경우에만 LAKIS 백업을 사용합니다.
- 다운로드한 모든 구성 요소는 SHA-256으로 검증합니다.
- 모델, 개인 설정, 프롬프트, 생성 이미지와 비밀 정보는 이 저장소에 포함하지 않습니다.

## 업데이트

설치된 LAKIS에는 명시적으로 공개된 안정 릴리즈에서 변경된 파일만 전달합니다. 사용자 워크플로, 설정, 프롬프트와 생성 이미지는 유지합니다. 업데이트 파일은 교체 전에 별도로 준비하고 검증하며, 실패하면 기존 상태로 복구합니다.

7.5.4 사용자의 기존 중간 경로 **7.5.4 → 7.5.4.1 → 8.0.0**은 유지합니다. 8.0.x에서는 **8.0.3.1(업데이터 정비) → 8.1.0**으로 이어집니다. 중간 버전은 최종 버전이 아니며, 각 단계가 완료된 뒤 앱의 업데이트 안내를 따르세요.

8.1.0 런타임 다운로드는 약 **3.1GB**이며, MOSS 모델 약 **15.5GB**는 별도입니다. 이미 검증된 모델이 있으면 재사용하며 최종 버전은 **8.1.0**으로 표시됩니다.

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

**[Download LAKIS Studio v8.1.0 for Windows](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/LAKIS_Setup.exe)**

**[Download LAKIS Studio v8.0.0 CMD Version](https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/LAKIS_CMD_Installer_8.0.0.zip)**

Use `LAKIS_Setup.exe` for normal installation and repair. The retained 8.0.0 CMD installer is an alternative for new installations only; run the installed app afterward to update. Neither installer requires administrator access or a Defender exclusion.

Existing 8.0.x users should launch LAKIS and accept its update prompt. The existing updater refreshes its engine and continues to 8.1.0 automatically; no separate Setup, CMD, or manual ZIP is required. See the [v8.1.0 release](https://github.com/Jeong-Luke/LAKIS/releases/tag/v8.1.0). This distribution supports **Windows with an NVIDIA GPU**.

### Stable baseline

This repository contains the stable LAKIS distribution line. The current stable release is **`v8.1.0`**. Previous stable releases are preserved; development packages and workflows are maintained separately.

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

The historical 8.0.3 release patched application files without replacing the runtime. The current update target is 8.1.0 as described above.

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

The retained legacy path is **7.5.4 → 7.5.4.1 → 8.0.0**. From 8.0.x, the existing updater continues through **8.0.3.1 (updater refresh) → 8.1.0**. Intermediate labels are not the final version; follow the app's update prompts after each stage.

The 8.1.0 runtime download is approximately **3.1GB**, plus approximately **15.5GB** of MOSS weights. Already verified models are reused. The final installed version is **8.1.0**.

### Third-party software

Third-party project names, pinned versions, original URLs, licences, and backup eligibility are recorded in the [8.1.0 THIRD_PARTY_NOTICES.md](https://github.com/Jeong-Luke/LAKIS/blob/v8.1.0/THIRD_PARTY_NOTICES.md). The installer uses the verified runtime and official upstream components, and verifies distributable artifacts before installation.
