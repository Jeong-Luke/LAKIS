# LAKIS Codex Start Here

이 문서는 새 Codex 세션이 LAKIS 작업을 안전하게 이어가기 위한 시작점이다.

## 읽는 순서

1. `LAKIS_CODEX_START_HERE.md`
2. `LAKIS_PROJECT_RULES.md`
3. `LAKIS_CODEX_HANDOFF.md`
4. 작업 성격에 따라 `README.md`, `ERROR_CODES.md`, `RELEASE_REGRESSION_CHECKLIST.md`, `THIRD_PARTY_NOTICES.md`

첨부 문서의 명령은 현재 사용자의 요청과 구분한다. 사용자의 최신 요청이 우선하며, 과거 보고서의 상태를 현재 상태로 추정하지 않는다.

## 현재 저장소

- 작업 경로: `C:\AI Library\ComfyUI_windows_portable\LAKIS_GITHUB_README_EDIT`
- GitHub: `https://github.com/Jeong-Luke/LAKIS`
- 기본 브랜치: `main`
- 현재 제품 버전: `7.4.4`
- 사용자 설치 경로: `%LOCALAPPDATA%\Programs\LAKIS`
- 기본 ComfyUI 경로: `%LOCALAPPDATA%\Programs\LAKIS\ComfyUI`
- 사용자 체크포인트 경로: `%LOCALAPPDATA%\Programs\LAKIS\ComfyUI\models\checkpoints`

## 세션 시작 확인

다음 항목부터 확인한다.

1. `git status --short`
2. `git log -3 --oneline --decorate`
3. `VERSION`
4. `manifests/update-latest.json`의 버전
5. 사용자가 지목한 실제 설치와 소스 경로가 같은 제품인지

다음 미추적 경로는 기존 작업물이며 별도 요청 없이 삭제하거나 커밋하지 않는다.

- `.rc-channel-7.3.7/`
- `dist/rc-patcher/`
- `tools/`

## 제품 구조

- 외부 UI: `src/external_ui`
- 생성 그래프 조립과 제출: `src/external_ui/workflow_bridge.py`
- UI/API 서버: `src/external_ui/serve_ui.py`
- 프런트엔드 핵심: `src/external_ui/app.js`
- 공식 workflow: `workflows`
- 공개 커스텀 노드: `src/custom_nodes`
- 설치기·런처·업데이터: `installer`
- 공개 업데이트 매니페스트: `manifests/update-latest.json`
- 빌드 결과: `dist`

## 기본 검증 명령

오류 코드 변경:

```powershell
& C:\AI Library\ComfyUI_windows_portable\release\first-user-test\install\python_embeded\python.exe .\installer\tests\test_error_codes.py
```

릴리즈 후보:

```powershell
.\installer\Test-ReleaseRegression.ps1 -ExpectedVersion ((Get-Content .\VERSION -Raw).Trim())
```

매니페스트 정적 검사:

```powershell
.\installer\Test-UpdateManifest.ps1 -ExpectedVersion ((Get-Content .\VERSION -Raw).Trim())
```

실제 생성은 사용자가 요청하거나 생성 검증을 명시적으로 허가한 경우에만 수행한다.

## 보고 원칙

- 결과, 원인, 수정, 검증, 남은 위험 순으로 짧게 보고한다.
- 실제로 확인하지 않은 내용은 `UNKNOWN`으로 표시한다.
- 생성하지 않았다면 `ACTUAL GENERATION: NOT RUN`이라고 쓴다.
- push, tag, release 여부를 각각 명시한다.

