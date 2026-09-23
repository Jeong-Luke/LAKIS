# LAKIS Studio

LAKIS Studio는 ComfyUI를 더 쉽게 사용할 수 있도록 제작된 외부 사용자 인터페이스이자, 검증된 워크플로 환경입니다.

Copyright © 2026 Luke Jeong. All rights reserved. LAKIS의 독자적인 자료와 제3자 구성 요소에는 각각 별도의 라이선스가 적용됩니다. 자세한 내용은 [LICENSE.md](LICENSE.md)와 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인해 주세요.

LAKIS 애플리케이션, 사용자 인터페이스, 설치기, 업데이터, 워크플로, 브랜드 및 문서 자료는 허가 없이 복사·수정·재배포할 수 없습니다. 별도로 표시된 LAKIS 커스텀 노드는 각자의 오픈 소스 라이선스로 공개됩니다. 독자적인 유틸리티 노드는 MIT 라이선스를 사용하며, AGPL 소프트웨어에서 파생된 구성 요소는 AGPL-3.0-or-later를 유지합니다.

## 다운로드

**[Windows용 LAKIS Studio v7.5.1 다운로드](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.1/LAKIS_Setup.exe)**

**[Windows용 LAKIS Studio v7.5.1 CMD Version 다운로드](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.1/LAKIS_CMD_Installer_7.5.1.zip)**

일반적으로 `LAKIS_Setup.exe`를 사용하세요. Windows Defender가 Setup을 차단하거나 설치 파일을 실행할 수 없다면 CMD Version ZIP의 압축을 완전히 푼 뒤 `LAKIS_CMD_Install.cmd`를 실행하세요. CMD Version은 관리자 권한이나 Defender 예외 설정을 요구하지 않는 공식 대체 설치 방법입니다.

[v7.5.1 릴리즈 설명과 개별 파일](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.5.1)도 확인할 수 있습니다.

## 안정 버전

이 저장소는 LAKIS의 안정 배포 버전을 관리합니다. 현재 릴리즈 후보는 `v7.5.1`입니다. 이전 개발 패키지와 개발용 워크플로는 별도로 관리하며 신규 사용자에게 배포하지 않습니다.

## v7.5.1 수정 사항

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

**[Download LAKIS Studio v7.5.1 for Windows](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.1/LAKIS_Setup.exe)**

**[Download LAKIS Studio v7.5.1 CMD Version](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.5.1/LAKIS_CMD_Installer_7.5.1.zip)**

Use `LAKIS_Setup.exe` for normal installation and repair. If Windows Defender blocks Setup or prevents it from running, fully extract the CMD Version ZIP and run `LAKIS_CMD_Install.cmd`. CMD Version is an official alternative installation method that does not require administrator access or a Defender exclusion.

You can also view the [v7.5.1 release notes and individual files](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.5.1).

### Stable baseline

This repository contains the stable LAKIS distribution line. The current release candidate is `v7.5.1`. Earlier development packages and workflows are maintained separately and are not distributed to new users.

### v7.5.1 fixes

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
- Third-party components are installed from their official upstream source at a pinned, tested version.
- A LAKIS backup is used only when the upstream source is unavailable and redistribution is permitted.
- Every downloaded component is verified using SHA-256.
- Models, personal settings, prompts, generated images, and secrets are not committed to this repository.

### Updates

Installed clients receive only files changed by an explicitly published stable release. User workflows, settings, prompts, and generated images are preserved. Updates are staged and verified before replacement, with rollback on failure.

### Third-party software

Third-party project names, pinned versions, original URLs, licenses, and backup eligibility are recorded in `THIRD_PARTY_NOTICES.md`. The installer downloads approved upstream versions and verifies distributable artifacts before installation.
