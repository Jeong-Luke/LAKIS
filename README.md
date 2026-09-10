# LAKIS Studio

LAKIS Studio는 ComfyUI를 더 쉽게 사용할 수 있도록 제작된 외부 사용자 인터페이스이자, 검증된 워크플로 환경입니다.

Copyright © 2026 Luke Jeong. All rights reserved. LAKIS의 독자적인 자료와 제3자 구성 요소에는 각각 별도의 라이선스가 적용됩니다. 자세한 내용은 [LICENSE.md](LICENSE.md)와 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인해 주세요.

LAKIS 애플리케이션, 사용자 인터페이스, 설치기, 업데이터, 워크플로, 브랜드 및 문서 자료는 허가 없이 복사·수정·재배포할 수 없습니다. 별도로 표시된 LAKIS 커스텀 노드는 각자의 오픈 소스 라이선스로 공개됩니다. 독자적인 유틸리티 노드는 MIT 라이선스를 사용하며, AGPL 소프트웨어에서 파생된 구성 요소는 AGPL-3.0-or-later를 유지합니다.

## 다운로드

**[Windows용 LAKIS Studio v7.3.4.1 다운로드](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.3.4.1/LAKIS_Setup.exe)**

`LAKIS_Setup.exe`를 실행하면 LAKIS를 설치하거나 복구할 수 있습니다. [v7.3.4.1 릴리즈 설명과 개별 파일](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.3.4.1)도 확인할 수 있습니다.

## 안정 버전

이 저장소는 LAKIS의 안정 배포 버전을 관리합니다. 현재 안정 기준 버전은 `v7.3.4.1`입니다. 이전 개발 패키지와 개발용 워크플로는 별도로 관리하며 신규 사용자에게 배포하지 않습니다.

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

**[Download LAKIS Studio v7.3.4.1 for Windows](https://github.com/Jeong-Luke/LAKIS/releases/download/v7.3.4.1/LAKIS_Setup.exe)**

Run `LAKIS_Setup.exe` to install or repair LAKIS. You can also view the
[v7.3.4.1 release notes and individual files](https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.3.4.1).

### Stable baseline

This repository contains the stable LAKIS distribution line. The current prepared baseline is `v7.3.4.1`. Earlier development packages and workflows are maintained separately and are not distributed to new users.

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
