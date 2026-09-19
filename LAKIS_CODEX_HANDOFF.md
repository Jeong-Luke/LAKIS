# LAKIS Codex Handoff

기준 시각: 2026-09-15 Asia/Seoul

## 현재 상태

- 공개 최신 버전: `v7.4.4`
- 로컬 브랜치: `main`
- 로컬/원격 HEAD: `54383bd6e7989e58573c33807cda2d6fec91c47a`
- 릴리즈 준비 커밋: `5d4c1f90b5d54de0d87dfd2e5e6d0ecfb5cc377f`
- 태그: `v7.4.4`
- GitHub Release: `https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.4.4`
- 공개 매니페스트: `7.4.4`, 파일 102개, 삭제 12개
- push/tag/release: 완료

## v7.4.4에 포함된 핵심 수정

1. 생성 오류 코드 정밀화
   - 요청 JSON, 빈 요청, 요청 크기, 연결, 비정상 응답, 필수 노드, GPU, 저장 및 Local Inpaint 단계를 구분했다.
   - 클라이언트가 서버 응답을 JSON으로 읽지 못해도 오류 원인과 정리된 설정 스냅샷을 보존한다.
2. Runtime node preflight
   - `/object_info`에서 최종 prompt graph에 필요한 node type을 확인한 뒤 제출한다.
   - LLLite, Local Inpaint, Final Saver 누락을 별도 코드로 보고한다.
3. Local Inpaint 배포 복구
   - 공개 업데이트에 `src/custom_nodes/ComfyUI-Anima-LLLite`의 실행 파일 5개를 포함했다.
   - 모델 가중치는 포함하지 않았다.
4. 업데이트 안전성
   - `STOP_AUTOMATION`을 업데이트 대상으로 복구했다.
   - 현행 UI 파일을 삭제 대상으로 잡던 오래된 목록을 실제 폐기 파일 12개로 축소했다.
   - 중복 경로와 설치·삭제 경로 충돌을 빌드 단계에서 차단한다.
5. 릴리즈 검사기
   - 실제 portable Python 후보 경로를 바로 찾도록 수정했다.

## 완료된 실제 생성 검증

메인 PC의 공식 LAKIS 실행 경로에서 다음을 실제 생성했고 모두 Final Saver 775까지 완료됐다.

- FAST
- DETAIL
- LAKIS DETAIL
- i2i DETAIL
- Local Inpaint V2 Regenerate
- Local Inpaint V2 Delete
- Composition + LoRA

각 계획된 실행은 `/prompt` 1회였다. 새 실패는 0건이었다. 계획된 테스트 출력 7개는 제품의 일괄 삭제 API로 삭제했다.

## 완료된 정적·회귀 검증

- 오류 코드 테스트: 12 PASS
- 릴리즈 회귀 게이트: PASS
- 설치 사용자 데이터 보호: PASS
- 복구 사용자 데이터 보호: PASS
- 설치별 UI 격리: PASS
- 공식 v7.4 workflow 3개: 구조 정상, Final Saver 775 존재
- 공개 매니페스트의 사설·폐기 기능 유출: 0
- 설치·삭제 경로 충돌: 0
- 공개 릴리즈 자산: 10개

## v7.4.4 실행 파일 SHA-256

- `LAKIS_Setup.exe`: `9E1B20B64A46F5D2A8DB9B88C5599CEB6A80D7575A1CA0A2A8B999E91898F61B`
- `LAKIS.exe`: `00621A5604CFDF6AF882DD7105955BC788EED95D6026F21F08BB11412FCB1D42`
- `LAKIS_Patcher.exe`: `A70FFC975354F575230B27296F8740D6C908C3000A7751CDF7FF0998413334C4`
- `LAKIS_Updater.exe`: `A70FFC975354F575230B27296F8740D6C908C3000A7751CDF7FF0998413334C4`
- `LAKIS_Desktop.exe`: `46B2E2DFA11E7A59ED4854ED3D2C774B1FA68752277ECD5C0AD3FD8CC7A9C76D`
- `LAKIS_Model_Importer.exe`: `F9AC3345A9A2898701E60FABA8456C82C7C35398F087D526DBF5781BB85A98F2`
- `Uninstall_LAKIS.exe`: `D43C629E69B2B1F44528F7D3EA75F34812569BE2E2EB4A79C9B3B3F90BD78A73`

자동화가 GitHub에서 다시 빌드한 공개 자산의 해시는 공개 매니페스트를 최종 기준으로 삼는다.

## 릴리즈 자료

- 로컬 후보 자료: `C:\AI Library\ComfyUI_windows_portable\release\v7.4.4`
- 공개 릴리즈 노트: `RELEASE_NOTES.md`
- 공개 오류 코드 문서: `ERROR_CODES.md`
- 공개 업데이트 매니페스트: `manifests/update-latest.json`

## 남은 작업

현재 확인된 v7.4.4 릴리즈 차단 문제는 없다.

새 사용자 오류가 접수되면 다음 순서로 조사한다.

1. 오류 보고의 버전, `error_code`, `failure_stage`, `error_detail`, `runtime_trace` 확인
2. 테스터 설치 경로와 업데이트 완료 여부 확인
3. 해당 설치의 실제 node inventory 및 `/object_info` 확인
4. `LAKIS_CODEX_START_HERE.md`의 시작 검사를 수행
5. 재현에 실제 생성이 필요하면 사용자 허가 범위를 확인하고 한 번만 실행

## 보존할 미추적 경로

다음은 현재 저장소에 존재하는 기존 미추적 작업물이다. 새 세션에서 임의 삭제·수정·커밋하지 않는다.

- `.rc-channel-7.3.7/`
- `dist/rc-patcher/`
- `tools/`

