# LAKIS Studio

LAKIS Studio는 ComfyUI를 더 쉽게 사용할 수 있도록 제작된 외부 사용자 인터페이스이자, 검증된 워크플로 환경입니다.

Copyright © 2026 Luke Jeong. All rights reserved. LAKIS의 독자적인 자료와 제3자 구성 요소에는 각각 별도의 라이선스가 적용됩니다. 자세한 내용은 [LICENSE.md](LICENSE.md)와 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인해 주세요.

LAKIS 애플리케이션, 사용자 인터페이스, 설치기, 업데이터, 워크플로, 브랜드 및 문서 자료는 허가 없이 복사·수정·재배포할 수 없습니다. 별도로 표시된 LAKIS 커스텀 노드는 각자의 오픈 소스 라이선스로 공개됩니다. 독자적인 유틸리티 노드는 MIT 라이선스를 사용하며, AGPL 소프트웨어에서 파생된 구성 요소는 AGPL-3.0-or-later를 유지합니다.

## 다운로드

**[Windows용 LAKIS Studio v7.5.0 다운로드](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.0/LAKIS_Setup.exe)**

**[Windows용 LAKIS Studio v7.5.0 CMD Version 다운로드](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.0/LAKIS_CMD_Installer_7.5.0.zip)**

`LAKIS_Setup.exe`로 설치하거나 복구할 수 있습니다. Windows Defender가 일반 Setup을 차단하면 CMD Version ZIP을 완전히 압축 해제한 뒤 `LAKIS_CMD_Install.cmd`를 실행하세요. 보안 기능을 끄거나 Defender 예외를 추가할 필요가 없습니다. [v7.5.0 전체 변경사항과 검증 범위](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.5.0)

## v7.5.0 주요 개선사항

- 시작할 때 LAKIS 관리 파일의 누락·버전 혼합을 확인해 필요하면 자동 복구합니다. 사용자 모델, 개인 설정, 워크플로, 생성물과 LoRA Manager 데이터는 보호합니다.
- 긴 Windows 경로와 복구 실행 문제를 수정하고, 첫 생성에 필요한 기본 워크플로와 입력 파일을 설치 패키지에 포함했습니다.
- CMD 설치기에 한글 안내, 현재 파일·압축 해제 진행 표시, 회전 표시와 바탕화면 바로가기를 추가했습니다.
- 실행 전 필수 ComfyUI 기능을 확인하고, Anima 체크포인트 감지 및 제거 모드 인페인트 호환성을 개선했습니다.
- 이미지 라이브러리의 미리보기와 점진적 목록 로딩을 개선하고, 프롬프트 확장·축소, LAKIS 메뉴와 모바일 이미지 상세 화면을 추가했습니다.
- 공개 업데이트에서 개발용·비공개 파일이 섞이지 않도록 빌드 검사와 배포 차단을 강화했습니다.

## 안정 버전

현재 안정 버전은 `v7.5.0`입니다. 이전 개발 패키지와 개발용 워크플로는 별도로 관리하며 신규 사용자에게 배포하지 않습니다.

## v7.4.5 주요 기능

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
- 제3자 구성 요소는 검증된 고정 버전을 공식 원본에서 설치합니다.
- 공식 원본을 사용할 수 없고 재배포가 허용된 경우에만 LAKIS 백업을 사용합니다.
- 다운로드한 모든 구성 요소는 SHA-256으로 검증합니다.
- 모델, 개인 설정, 프롬프트, 생성 이미지와 비밀 정보는 이 저장소에 포함하지 않습니다.

## 업데이트

설치된 LAKIS에는 명시적으로 공개된 안정 릴리즈에서 변경된 파일만 전달합니다. 사용자 워크플로, 설정, 프롬프트와 생성 이미지는 유지합니다. 업데이트 파일은 교체 전에 별도로 준비하고 검증하며, 실패하면 기존 상태로 복구합니다.

## 제3자 소프트웨어

제3자 프로젝트의 이름, 고정 버전, 공식 주소, 라이선스와 백업 허용 여부는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 기록합니다. 설치기는 승인된 공식 버전을 내려받으며, 설치 전에 배포 파일을 검증합니다.

---

## English

LAKIS Studio is an external user interface and curated workflow environment for ComfyUI.

Copyright © 2026 Luke Jeong. All rights reserved. Original LAKIS material and
third-party components are licensed separately; see [LICENSE.md](LICENSE.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

LAKIS application, user-interface, installer, updater, workflow, brand, and
documentation material may not be copied, modified, or redistributed without
permission. Separately marked LAKIS custom nodes are published under their own
open-source licences: original utility nodes use MIT, while components derived
from AGPL software remain AGPL-3.0-or-later.

### Download

**[Download LAKIS Studio v7.5.0 for Windows](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.0/LAKIS_Setup.exe)**

**[Download LAKIS Studio v7.5.0 CMD Version](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.0/LAKIS_CMD_Installer_7.5.0.zip)**

Run `LAKIS_Setup.exe` to install or repair LAKIS. If Windows Defender blocks the regular Setup, fully extract the CMD Version ZIP and run `LAKIS_CMD_Install.cmd`. You do not need to disable security features or add a Defender exclusion. See the [full v7.5.0 changes and validation scope](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.5.0).

### v7.5.0 highlights

- Detects missing or mixed-version LAKIS-managed files at startup and automatically repairs them when needed, while protecting user models, settings, workflows, generated files, and LoRA Manager data.
- Fixes long Windows paths and repair launch handling; includes the default workflow and input files needed for the first generation.
- Adds Korean guidance, current-file and extraction progress, a spinner, and a desktop shortcut to the CMD installer.
- Checks required ComfyUI capabilities before launch and improves Anima checkpoint detection and removal-mode inpaint compatibility.
- Improves Library thumbnails and progressive loading, and adds prompt expand/collapse controls, a LAKIS menu, and mobile image details.
- Strengthens build and release checks to prevent development or private-product files from entering public updates.

### Stable baseline

The current stable release is `v7.5.0`. Earlier development packages and workflows are maintained separately and are not distributed to new users.

### v7.4.5 features

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
- Third-party components are installed from their official upstream source at a pinned, tested version.
- A LAKIS backup is used only when the upstream source is unavailable and redistribution is permitted.
- Every downloaded component is verified using SHA-256.
- Models, personal settings, prompts, generated images, and secrets are not committed to this repository.

### Updates

Installed clients receive only files changed by an explicitly published stable release. User workflows, settings, prompts, and generated images are preserved. Updates are staged and verified before replacement, with rollback on failure.

### Third-party software

Third-party project names, pinned versions, original URLs, licenses, and backup eligibility are recorded in `THIRD_PARTY_NOTICES.md`. The installer downloads approved upstream versions and verifies distributable artifacts before installation.
