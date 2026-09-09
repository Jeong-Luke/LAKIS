# LAKIS 실제 이미지 생성 검증 — 2026-09-09

## 검증 환경

- 대상: 설치되어 실행 중인 LAKIS 7.3 개발 런타임
- 해상도: 1056 × 1472
- 체크포인트: `fnMomentAnimaTurbo_v40NoTurbo.safetensors`
- VAE: `qwen_image_vae.safetensors`
- CLIP: `qwen_3_06b_base.safetensors`
- 샘플러 / 스케줄러: `euler_ancestral` / `normal`
- Steps / CFG: 30 / 5
- 단일 인물 비교 시드: `731904260911`
- LoRA, I2I, 사용자 구도 제어를 끈 동일 조건으로 세 모드를 비교했다.

## 결과

| 항목 | 결과 | 시간 | 출력 |
|---|---:|---:|---|
| 레거시 FAST | 통과 | 41.84초 | `01_legacy_fast_seed731904260911.webp` |
| 레거시 DETAIL | 통과 | 84.48초 | `02_legacy_detail_seed731904260911.webp` |
| LAKIS DETAIL | 통과 | 62.44초 | `03_lakis_detail_seed731904260911.webp` |
| LAKIS DETAIL 2인 비중첩 | 통과 | 61.80초 | `04_lakis_detail_two_adults_seed884206715309.webp` |
| I2I FAST, denoise 0.45 | 통과 | 53.22초 | `05_i2i_fast_seed509371824606.webp` |
| I2I FAST 연속 2회차 | 통과 | 51.41초 | `06_i2i_fast_seed509371824607.webp` |
| I2I FAST 연속 3회차 | 통과 | 51.47초 | `07_i2i_fast_seed509371824608.webp` |
| LoRA 단일 활성/단일 비활성 | 통과 | 37.35초 | `08_lora_bluearchive_fast_seed642180395711.webp` |
| 다중 LoRA A→B | 통과 | 37.21초 | `09_multi_lora_blue_then_masterpiece_seed772640931205.webp` |
| 다중 LoRA B→A | 통과 | 37.16초 | `10_multi_lora_masterpiece_then_blue_seed772640931205.webp` |

LAKIS DETAIL은 이 조건에서 레거시 DETAIL보다 22.04초, 약 26.1% 빨랐다. 최적화 그래프는 106개 노드, 레거시 DETAIL 그래프는 133개 노드로 확인됐다.

## 육안 판정

- 세 생성 모드 모두 저장까지 완료됐으며 검은 화면, 픽셀 파손, 부분 디코딩은 보이지 않았다.
- LAKIS DETAIL 단일 인물 출력은 레거시 DETAIL과 동일한 구도 계열을 유지했다.
- 2인 비중첩 출력은 두 얼굴과 두 신체가 분리됐고 얼굴/몸 융합은 보이지 않았다.
- 2인 출력은 `full body` 지시 대비 발끝 주변 여백이 좁아 구도 준수는 경계 수준이다.
- I2I 출력은 원본의 중앙 인물, 정면 전신, 비 오는 거리 배치를 유지하면서 새 프롬프트의 새벽·따뜻한 림라이트를 반영했다.
- I2I 사전검사에서 입력 강도 0.45, 양성/음성 프롬프트, 출력 해상도 연결을 확인했다.
- I2I는 서로 다른 고정 시드로 3회 연속 저장까지 완료했으며 중단, stall, decode 오류가 없었다.
- LoRA 검증은 목록의 2개 항목 중 `BlueArchiveStyleB1.safetensors` 하나만 0.7로 활성화했다. 사전검사는 전체 2개/활성 1개로 일치했고 출력에서 화풍 변화가 확인됐다.
- 다중 LoRA는 동일 시드와 동일 프롬프트에서 `BlueArchiveStyleB1`/`masterpiece` 순서만 뒤집어 각각 생성했다. 두 실행 모두 전체 2개/활성 2개로 통과했고, 픽셀 평균 절대 차이 2.40 및 RMS 6.95로 순서 변경이 실제 출력에 반영됐다.

## 발견 사항

- 최초 I2I API 시험에서 구도 문자열이 남았던 것은 제품 결함이 아니라 시험 payload가 UI 스키마와 달랐기 때문이다. UI와 동일한 최상위 `composition_enabled=false`, `lora_enabled=false`로 재검증했으며 사전검사와 실행 프롬프트 모두 비활성 상태로 일치했다.
- 마지막 생성 직후 시스템 전체 RAM 사용량은 약 20.1GB였으나 LAKIS 관련 프로세스 작업 세트 합계는 약 1.5GB였다. ComfyUI 주 프로세스의 private bytes는 약 5.41GB이므로 저메모리 환경 검증에서는 커밋/페이지 파일 압박도 별도로 관찰해야 한다.
- 유휴 상태 재측정에서 시스템 RAM 사용량은 약 18.78GB, VRAM 사용량은 약 1.40GB였다. LAKIS 관련 작업 세트는 약 1.50GB로 유지됐고 ComfyUI 주 프로세스 private bytes도 약 5.41GB로 유지됐다. 실제 물리 작업 세트는 낮지만 예약/페이지 메모리는 자동으로 완전히 반환되지 않는다.
- 이 문서는 실행 중인 개발 런타임 검증이다. 최종 배포 패키지를 다시 빌드한 뒤 같은 검증을 한 번 더 수행해야 릴리즈 게이트를 최종 통과한 것으로 본다.

## 자동 회귀검사

- 명령: 포터블 Python의 `unittest discover`로 `installer/tests/test_*.py` 실행
- 결과: UI 계약 검사를 추가한 뒤 30개 테스트 전체 통과, 실패 0, 오류 0
- 범위: 오류 코드, 설치 격리, stale backend 판별, 설치별 UI 상태, 업스케일러 선택·라이선스 상태
- 추가 UI 계약: I2I 활성 시 구도 해제와 안내, 완료 결과의 I2I 배지, 히스토리 프롬프트 메타데이터 복원, 번역 결과를 생성 payload에만 적용

## 프롬프트 번역 검증

- 실제 `/api/translate-prompt` 호출에 양성 한국어 문장과 음성 한국어 문장을 동시에 전달했다.
- 양성은 `Adult woman standing with umbrella on the street on a rainy night`, 음성은 `finger error, blurry face, letter`로 각각 번역됐다.
- 이미 영어였던 trigger, quality, fixed, negative-quality 필드는 변경되지 않았다.
- 화면 자동화 표면이 제공되지 않아 토글 클릭 자체는 최종 패키지 데스크톱 검증 항목으로 남겼다. 소스 계약과 실제 번역 API는 통과했다.

## 출력 위치

`C:\AI Library\ComfyUI_windows_portable\LAKIS_TEST_OUTPUT\release_validation`

## 7.3.3 릴리즈 전 전체 회귀 재검증 — 2026-09-09 20:02 KST

### 재검증 중 발견하고 수정한 결함

- 설치된 DEV 런타임에 `ComfyUI-LAKIS-Detail`이 누락되어 `LAKIS_DETAIL`을 로드할 수 없던 문제를 수정했다.
- LAKIS DETAIL 삽입이 `DEVELOPMENT` 조건에 묶여 배포 모드에서는 레거시 경로가 남던 문제를 수정했다. 이제 개발/배포 그래프 모두 `LAKIS_DETAIL -> LAKIS_SCOPE`를 사용한다.
- LAKIS 모드에서 출력 선택기와 타일 크기 측정 노드가 레거시 눈 디테일러를 계속 참조하던 연결을 제거했다. 최종 그래프에서 레거시 얼굴/눈 디테일러가 제외된다.
- 시작 워밍업 그래프에 ComfyUI 출력 노드가 없어 `prompt_no_outputs`로 항상 거절되던 문제를 수정했다. 256px, 1-step, VAE decode, `PreviewImage` 경로로 실제 워밍업한다.
- 제거된 `timeEstimate` 요소를 `render()`가 계속 갱신해 초기화 및 LAKIS 스위치 클릭 때 JavaScript 예외가 발생하던 문제를 수정했다.
- YOLO 금지 항목 검사기가 루트 Markdown 문서를 실행 코드로 오인하던 릴리즈 게이트 오탐을 수정했다.

### 실제 런타임 검증

동일 체크포인트, VAE, CLIP, 해상도 1056x1472, Steps 30, CFG 5로 실행했다.

| 검사 | 결과 | ComfyUI 실제 실행시간 | 증거 |
|---|---:|---:|---|
| 시작 워밍업 | 통과 | 4.735초 | 공식 DEV 런처 상태 `complete` |
| 레거시 FAST | 통과 | 32.90초 | Image Saver 완료, 출력 193631 |
| 레거시 DETAIL | 통과 | 78.24초 | SAM3 얼굴/눈, DetailerForEach 2회, Ultimate, Image Saver 완료 |
| LAKIS DETAIL | 통과 | 18.32초* | `LAKIS_VRAM_GATE -> LAKIS_DETAIL -> LAKIS_SCOPE -> Image Saver` |
| I2I FAST 0.45 | 통과 | 41.36초 | 입력 영향·양성/음성 프롬프트·정확한 1056x1472 연결 |
| 단일 LoRA 0.7 | 통과 | 27.75초 | 전체 1/활성 1, `BlueArchiveStyleB1.safetensors` |

`*` LAKIS DETAIL은 동일 시드의 직전 그래프 캐시를 재사용했으므로 이 수치는 연결 및 실행 검증용이며 냉간 성능 비교값으로 사용하지 않는다.

LAKIS DETAIL의 ComfyUI 히스토리는 109개 노드이며 `LAKIS_DETAIL`, `LAKIS_SCOPE`, `LAKIS_VRAM_GATE`, `SAM3_Detect`를 포함한다. 레거시 `1530:1826`과 `1836:2069`는 포함하지 않는다. 세 비교 이미지와 I2I/LoRA 출력 모두 검은 화면, 타일 경계, 픽셀 파손, 부분 디코딩이 없었다.

### UI 및 자동 회귀

- 실제 브라우저 UI에서 LAKIS 스위치 ON/OFF, 분홍 활성 상태, `LAKIS_DETAIL · LAKIS_SCOPE ON`, 제작 버튼의 `LAKIS DETAIL` 문구를 확인했다.
- 구도 캔버스가 321x200 이상으로 렌더링되고 노브/슬라이더가 존재하는 것을 확인했다.
- I2I ON 시 구도가 OFF되고 `is-disabled`가 적용되며, I2I OFF 후 구도를 다시 켤 수 있음을 확인했다.
- 양성/음성 전체 9개 프롬프트 스위치가 존재하고, OFF 상태가 재로드 후 유지되며 프롬프트 문자열은 삭제되지 않는 것을 확인했다.
- 사용자 상태는 검사 후 LAKIS OFF, I2I OFF, 구도 ON, 프롬프트 스위치 9개 ON으로 복원했다.
- Python 단위/계약 검사 37개 통과, JavaScript 문법 검사 통과, 릴리즈 회귀 게이트 통과.
- 공식 `LAKIS_DEV_Desktop.exe` 경로로 다시 시작하여 ComfyUI 8190, 설치별 임의 UI 포트, identity 상태 기록, 워밍업, 데스크톱 실행까지 `LAKIS_READY`를 확인했다.

### 판정

현재 소스 및 설치된 DEV 런타임의 생성 핵심 경로는 통과했다. 기존 `dist` 설치 파일은 이번 수정 이전 산출물이므로 릴리즈 승인 대상이 아니다. 최종 설치기 재빌드 후 clean install/repair/update와 동일 생성 묶음을 다시 통과해야 최종 릴리즈 가능으로 판정한다.

## 7.3.4 릴리즈 후보 준비 — 2026-09-09

- 제품·설치기·업데이터·런처·제거기 버전을 `7.3.4`로 통일했다.
- 한국어를 먼저 배치한 `RELEASE_NOTES.md`를 작성했다.
- `LAKIS_DETAIL_runtime_api_v7.3.json`을 런타임 빌더에서 재생성했다.
- `LAKIS_custom_v7.3_editable.json`과 `LAKIS_runtime_visual_v7.3.json`을
  생성하고 사이드바의 편집/실행 버튼에 각각 연결했다.
- 시각화 워크플로는 116개 노드와 163개 링크이며 끊어진 링크는 0개다.
- Python 단위·계약 검사 42개, 설치/복구 데이터 안전성 검사, 설치 격리
  검사, 릴리즈 회귀 게이트가 모두 통과했다.
- 서명 전 RC 설치기와 7개 LAKIS 실행 파일을 빌드했다. 모든 실행 파일의
  파일 버전은 `7.3.4.0`이며 필수 Windows 메타데이터가 존재한다.
- RC 설치기 SHA-256:
  `58B6A91621865536E830386467229ED4251D121744773F423BD8BF0208C703B2`
- 검토용 업데이트 매니페스트는 100개 파일, 중복·비 HTTPS·잘못된 해시·
  안전하지 않은 설치 경로 0개로 구조 검사를 통과했다.

### 공개 전 남은 게이트

- 격리된 새 경로에서 RC clean install 후 실제 FAST, 레거시 DETAIL,
  LAKIS DETAIL 생성 검증
- 같은 설치에서 Repair와 7.3.3 → 7.3.4 업데이트 데이터 보존 검증
- 최종 공개 방침에 따른 Authenticode 서명 또는 명시적인 무서명 승인
- Git 태그와 draft release 생성 뒤 게시 바이트 기준 매니페스트 3회 검증
- 위 검증 완료 전에는 `manifests/update-latest.json`을 7.3.4로 변경하지 않음
