# LAKIS Feature Status Matrix

기준 버전: `v7.4.5`
기준 릴리즈: `https://github.com/Jeong-Luke/LAKIS/releases/tag/v7.4.5`
최종 갱신: 2026-09-21 Asia/Seoul

## 상태 정의

| 상태 | 의미 |
|---|---|
| RELEASED | v7.4.5 공개 릴리즈와 업데이트 매니페스트에 포함 |
| CANDIDATE | 현재 release-prep 후보에 포함됐지만 아직 공개되지 않음 |
| VERIFIED | 정적 검사 또는 실제 실행으로 확인 완료 |
| OWNER VERIFIED | 프로젝트 소유자가 실제 환경에서 확인 |
| CONDITIONAL | 외부 모델, 환경 또는 사용자 설정이 필요 |
| UNTESTED | 해당 환경에서 실제 검증하지 않음 |
| RETIRED | 공개 제품에서 제거 |
| PRIVATE | 공개 LAKIS에 포함하지 않는 기능 |

## Generation Modes

FAST, DETAIL, LAKIS DETAIL은 공식 생성 모드다. Composition, i2i, Inpaint는 모드에 결합되는 기능 상태다.

| 기능 | 제품 상태 | 실제 생성 | `/prompt` 계약 | 최종 출력 | 비고 |
|---|---|---|---|---|---|
| FAST | RELEASED | VERIFIED | 1회 | Final Saver 775 | 메인 PC 실제 생성 통과 |
| DETAIL | RELEASED | VERIFIED | 1회 | Final Saver 775 | Face/Eye 및 upscale 경로 실제 생성 통과 |
| LAKIS DETAIL | RELEASED | VERIFIED | 1회 | Final Saver 775 | LAKIS_SCOPE 경로 실제 생성 통과 |
| Continuous Generation | RELEASED | VERIFIED | 이미지당 1회 | Final Saver 775 | 동일 workflow를 순차 제출하며 병렬 branch를 만들지 않음 |

## Generation Feature States

| 기능 | 제품 상태 | 검증 | 상호작용 | 비고 |
|---|---|---|---|---|
| Composition | RELEASED | VERIFIED | Inpaint ON 동안 임시 비활성화 | 값과 UI 상태를 보존하며 Composition + LoRA 실제 생성 통과 |
| Image to Image | RELEASED | VERIFIED | Inpaint ON이면 비활성화 | DETAIL 결합 실제 생성 통과 |
| Local Inpaint V2 Regenerate | RELEASED | VERIFIED, CONDITIONAL | i2i 비활성화, Composition 임시 비활성화 | LLLite 모델 직접 설치 필요 |
| Local Inpaint V2 Delete | RELEASED | VERIFIED, CONDITIONAL | 일반/Inpaint prompt와 LoRA를 사용하지 않음 | LLLite 모델 직접 설치 필요 |
| Wildcard / Random Selection | RELEASED | OWNER VERIFIED | 일반 prompt 전처리 | 별도 ComfyUI node 없이 resolve된 prompt를 conditioning에 전달 |
| Prompt Translation | RELEASED | OWNER VERIFIED | 자동 번역 ON일 때 적용 | UI의 외부 전송 안내 문구는 제거됨 |
| Prompt Persistence | RELEASED | OWNER VERIFIED | PC와 Link 상태 유지 | Inpaint Delete 전환으로 Regenerate prompt를 삭제하지 않음 |
| Seed Random/Fixed | RELEASED | VERIFIED | 연속 생성과 결합 가능 | 기존 seed contract 유지 |
| LoRA Stack | RELEASED | VERIFIED | FAST/DETAIL/Composition과 결합 | 활성 LoRA 1개를 포함한 실제 생성 통과 |
| Camera/Composition Prompt | RELEASED | VERIFIED | Composition conditioning 생성 | 기존 카메라 값과 prompt contract 유지 |

## Local Inpaint V2 Pipeline

| 단계 | 상태 | 검증 | 계약 |
|---|---|---|---|
| User Mask Authority | RELEASED | VERIFIED | 사용자 mask가 edit region의 최우선 기준 |
| Mask Bounding Box | RELEASED | VERIFIED | 빈 mask는 제출 전에 중단 |
| Context Crop | RELEASED | VERIFIED | padding, alignment와 source boundary clamp 적용 |
| Local VAE Encode/Decode | RELEASED | VERIFIED | full image 대신 local crop 처리 |
| LLLite Inpaint | RELEASED, CONDITIONAL | VERIFIED | `AnimaLLLiteApply_sdscripts` 사용 |
| Local Color Match | RELEASED | VERIFIED | local crop 및 edit 범위로 제한 |
| Feathered Mask | RELEASED | VERIFIED | crop rectangle을 alpha로 사용하지 않음 |
| Local Composite | RELEASED | VERIFIED | 수정 영역 밖 원본 픽셀 보존 |
| Final Saver 775 | RELEASED | VERIFIED | composite 결과가 최종 saver로 연결 |
| Large Edit Warning | RELEASED | VERIFIED | 조정 가능한 mask ratio 기준 사용 |
| SAM3 Default | DISABLED IN V2 | VERIFIED | 일반 local edit에서는 실행하지 않음 |
| SAM3 Conditional Protection | RELEASED | VERIFIED | 필요한 semantic protection에서만 사용 |
| Mandatory LAKIS_DETAIL | DISABLED IN V2 | VERIFIED | V2 output upstream에서 제외 |
| Full-image HighRez | DISABLED IN V2 | VERIFIED | V2 output upstream에서 제외 |
| Face/Eye Detail | DISABLED IN V2 | VERIFIED | V2 output upstream에서 제외 |
| UltimateSDUpscale | DISABLED IN V2 | VERIFIED | V2 output upstream에서 제외 |

### Inpaint dependency

| 항목 | 상태 | 배포 정책 |
|---|---|---|
| `ComfyUI-Anima-LLLite` 실행 노드 | RELEASED | 공개 업데이트에 5개 파일 포함 |
| `ComfyUI-LAKIS-Local-Inpaint` | RELEASED | 공개 업데이트에 포함 |
| `anima-lllite-inpainting-v2.safetensors` | USER MANUAL INSTALL ONLY | 패키지 미포함, 자동 다운로드 없음 |
| LLLite 모델 감지와 안내 | RELEASED | filename, hash 및 runtime discoverability 확인 |

## Library

| 기능 | PC | LAKIS Link | 검증 | 비고 |
|---|---|---|---|---|
| 이미지 목록 | RELEASED | RELEASED | OWNER VERIFIED | 설치별 저장 경로 사용 |
| 날짜별 그룹 | RELEASED | RELEASED | VERIFIED | 기존 정렬 유지 |
| 상세 이미지 보기 | RELEASED | RELEASED | OWNER VERIFIED | 원본 이미지 사용 |
| Metadata 표시 | RELEASED | RELEASED | VERIFIED | Library metadata regression 통과 |
| Multi Select | RELEASED | RELEASED | OWNER VERIFIED | lazy image src와 selection state 분리 |
| Batch Delete | RELEASED | RELEASED | VERIFIED | 계획된 테스트 출력 7개 삭제 확인 |
| Library → Inpaint | RELEASED | RELEASED | OWNER VERIFIED | 원본 선택 및 전달 오류 수정 포함 |
| Library → i2i | RELEASED | RELEASED | OWNER VERIFIED | 기존 전달 계약 유지 |
| Viewport Lazy Load | RELEASED | RELEASED | OWNER VERIFIED | `loading=lazy`, `decoding=async`, IntersectionObserver |
| Custom Save Path | RELEASED | 미노출 | OWNER VERIFIED | Link Library에서는 폴더 열기와 저장 경로 변경을 숨김 |
| Pinch Zoom | RELEASED | RELEASED | OWNER VERIFIED | 미리보기 및 Library 상세 이미지에서만 허용 |
| 320px WebP Thumbnail Cache | CANDIDATE | CANDIDATE | VERIFIED | 카드/최근 생성에는 캐시 썸네일을 사용하고 메인 프리뷰·상세 이미지는 원본 유지 |
| Progressive Card Rendering | CANDIDATE | CANDIDATE | VERIFIED | 최초 20개 렌더 후 스크롤 시 20개씩 추가 |
| Preview Session History Cap | CANDIDATE | 해당 없음 | VERIFIED | 시작 시 과거 이미지 미리 로드 없음, 현재 세션 최근 20개 유지 |
| Library Inspector Layout | CANDIDATE | CANDIDATE | VERIFIED | 데스크톱 상세 패널 폭 확대 및 이미지 바로 아래 Inpaint/I2I 액션 배치 |

## LAKIS Link / Mobile

| 기능 | 상태 | iPhone | Android | 비고 |
|---|---|---|---|---|
| Link Generation UI | RELEASED | OWNER VERIFIED | UNTESTED | PC와 동일 생성 state 사용 |
| Link Library | RELEASED | OWNER VERIFIED | UNTESTED | 원격 이미지 URL과 Library discovery 수정 포함 |
| Mobile Wildcard | RELEASED | OWNER VERIFIED | UNTESTED | 터치 추가, 길게 눌러 제거 |
| Mobile Inpaint Drawing | RELEASED | OWNER VERIFIED | UNTESTED | 끊긴 점 대신 연속 stroke 처리 |
| Mobile Pinch Zoom | RELEASED | OWNER VERIFIED | UNTESTED | 이미지 영역 밖 페이지 확대 방지 |
| Text Selection Suppression | RELEASED | OWNER VERIFIED | UNTESTED | prompt 입력을 제외한 UI 선택 억제 |
| Mobile Sidebar | RELEASED | OWNER VERIFIED | UNTESTED | orientation 및 viewport 대응 |

## UI and Desktop Integration

| 기능 | 상태 | 검증 | 비고 |
|---|---|---|---|
| External UI | RELEASED | VERIFIED | LAKIS public runtime 경로 사용 |
| Desktop WebView2 Host | RELEASED | VERIFIED | v7.4.5 실행 파일 배포 |
| Prompt Panel Expand | CANDIDATE | VERIFIED | 데스크톱 전용, 긍정/네거티브 독립 확장, 모바일 레이아웃 유지 |
| Advanced Settings Gear Icon | CANDIDATE | VERIFIED | 세부설정 진입 아이콘을 돋보기에서 톱니바퀴로 변경 |
| LAKIS Sidebar Resources | CANDIDATE | VERIFIED | 데스크톱 전용 GitHub/Arcalive 링크 메뉴 및 LAKIS Link 순서 조정 |
| Inpaint Workspace Coverage | CANDIDATE | VERIFIED | Inpaint ON 동안 Wildcard·Composition·I2I 패널 제외 |
| Generation Monitor Button | RELEASED | OWNER VERIFIED | Runtime/API workflow visual 화면을 표시 |
| Runtime Visual Workflow | RELEASED | VERIFIED | 사람이 runtime 구조를 확인하는 counterpart |
| Editable Workflow | RELEASED | VERIFIED | ComfyUI에서 읽고 편집 가능 |
| Runtime API Workflow | RELEASED | VERIFIED | backend execution base contract |
| Folder Foreground Activation | RELEASED | OWNER VERIFIED | 폴더 열기 시 Explorer를 전면으로 표시 |
| Inpaint Progress Text | RELEASED | OWNER VERIFIED | Inpaint 요청은 `인페인트 진행중`으로 표시 |

## Official Workflow Pair

| Workflow | 파일 | 상태 | Final Saver 775 | Local Inpaint V2 | Private/Retired Nodes |
|---|---|---|---|---|---|
| Editable | `workflows/LAKIS_custom_v7.4_editable.json` | RELEASED, VERIFIED | PASS | PASS | 0 |
| Runtime Visual | `workflows/LAKIS_runtime_visual_v7.4.json` | RELEASED, VERIFIED | PASS | PASS | 0 |
| Runtime API | `workflows/LAKIS_runtime_api_v7.4.json` | RELEASED, VERIFIED | PASS | PASS | 0 |

Editable과 Runtime Visual은 현재 release convention에서 같은 시각적 graph를 두 역할로 제공한다. Runtime API는 API prompt 형식이며 node ID나 JSON 형태가 동일할 필요는 없지만 제품 기능 의미는 같아야 한다.

## Diagnostics and Error Reporting

| 영역 | 상태 | 검증 | 대표 코드 |
|---|---|---|---|
| Request JSON | RELEASED | 12-test suite PASS | `LKS-CFG-1001` |
| Empty Request | RELEASED | 실제 HTTP 응답 확인 | `LKS-CFG-1002` |
| Request Size | RELEASED | 정적 검증 | `LKS-CFG-1003` |
| Non-JSON Server Response | RELEASED | 테스트 포함 | `LKS-GEN-1011` |
| Browser/Server Transport | RELEASED | 테스트 포함 | `LKS-GEN-1012` |
| Missing Runtime Node | RELEASED | 테스트 포함 | `LKS-NODE-1201` |
| Missing LLLite Node | RELEASED | 테스트 포함 | `LKS-NODE-1202` |
| Missing Local Inpaint Node | RELEASED | 테스트 포함 | `LKS-NODE-1203` |
| Missing Final Saver | RELEASED | 테스트 포함 | `LKS-NODE-1204` |
| GPU Runtime | RELEASED | mapping 검증 | `LKS-GEN-1004` |
| Final Output Missing | RELEASED | mapping 검증 | `LKS-GEN-1702` |
| Save Permission/File Lock | RELEASED | mapping 검증 | `LKS-GEN-1703` |
| Disk Full | RELEASED | mapping 검증 | `LKS-GEN-1704` |
| Local Inpaint Stages | RELEASED | 테스트 포함 | `LKS-INP-1001`~`1006` |
| LLLite Weight | RELEASED | detection 검증 | `LKS-INP-1101` |

전체 코드와 의미는 `ERROR_CODES.md`를 기준으로 한다.

## Installer, Updater and Release

| 기능 | 상태 | 검증 | 비고 |
|---|---|---|---|
| Safe Installer | RELEASED | PASS | v7.4.5 신규 설치 및 복구 자산 공개 |
| Patcher/Updater | RELEASED | PASS | staging, SHA-256, rollback 및 cache bypass |
| Model Importer | RELEASED | PASS | 외부 모델을 사용자 선택으로 가져오기 |
| Uninstaller | RELEASED | PASS | 사용자 데이터 보호 계약 유지 |
| STOP_AUTOMATION Marker | RELEASED | PASS | manifest 설치 1, 삭제 0 |
| Manifest Duplicate Guard | RELEASED | PASS | 중복 path 발견 시 생성 중단 |
| Install/Delete Overlap Guard | RELEASED | PASS | 현재 overlap 0 |
| Remote Byte Verification | RELEASED | PASS | draft asset와 raw file을 3회 검증 |
| v7.4.5 Assets | RELEASED | PASS | GitHub Release 자산 10개 |
| Public Update Manifest | RELEASED | PASS | 파일 131개, 삭제 12개 |
| Current Candidate Local Manifest | CANDIDATE | PASS | provisional 135개, 삭제 12개; 최종 frozen binary build 후 manifest/hash 재생성 필요 |
| Public Product Boundary Guard | CANDIDATE | PASS | 8 tests + dist의 모든 EXE 검사; manifest/runtime/build/GitHub upload 경계 차단 |
| Startup Release Integrity | CANDIDATE | PASS | 정확한 release-owned 114개 집합 + managed-node inventory + Launcher 내장 manifest trust hash; manifest/runtime 변조 시 Python 시작 전 차단 |
| Runtime Capability Preflight | CANDIDATE | PASS | ComfyUI /object_info와 runtime workflow + 동적 필수 LAKIS 노드 대조, 실패 시 LKS-RUN-1003 |

## Data Safety and Compliance

| 항목 | 상태 | 결과 |
|---|---|---|
| User models/LoRA excluded | VERIFIED | PASS |
| Input/output/Library excluded | VERIFIED | PASS |
| User workflow/state excluded | VERIFIED | PASS |
| Logs, `.audit`, debug excluded | VERIFIED | PASS |
| Light/DSINE public nodes | RETIRED | 0 |
| Pose Control public nodes | PRIVATE | 0 |
| Health Monitor public nodes | PRIVATE | 0 |
| SamplerSPEED/ComfyUI-SPEED | PRIVATE | 0 |
| LUKIS-only files | PRIVATE | 0 |
| DEKIS/LUKIS public artifact leak | CANDIDATE VERIFIED | 0 · negative injection tests PASS |
| New executable/runtime dependency in v7.4.5 | NONE | 0 |
| Arcalive navigation logo | CANDIDATE | 단순 로고 public-domain 분류, 출처 THIRD_PARTY_NOTICES 기록 |
| LLLite weight redistribution | DISABLED | 사용자 직접 설치만 허용 |

## Environment Coverage

| 환경 | 상태 | 범위 |
|---|---|---|
| Main PC Windows | VERIFIED | 공식 launcher, UI server, ComfyUI 및 실제 생성 |
| Tester Windows PCs | OWNER/TEAM VERIFIED | v7.4 RC 및 후속 오류 보고 기반 수정 |
| iPhone Safari | OWNER VERIFIED | Link UI, Library, wildcard, zoom, Inpaint drawing |
| Android browser | UNTESTED | 다음 검증 대상 |
| Production LAKIS v7.4.5 update | RELEASED | GitHub 자동화와 공개 manifest 확인 |
| LUKIS | OUT OF SCOPE FOR THIS MATRIX | 별도 제품 handoff와 상태표 필요 |

## Current Release Decision

| 판정 | 상태 |
|---|---|
| Functional regression (v7.4.5 stable) | PASS |
| One Click / One Prompt (v7.4.5 stable) | PASS |
| Final Saver 775 (v7.4.5 stable) | PASS |
| User data safety | PASS |
| Private/retired leak | 0 |
| License blocker | NONE |
| Open v7.4.5 release blocker | 0 |
| v7.4.5 public release | COMPLETE |
| Current candidate version | v7.5.0 |
| Current candidate automated regression | PASS · RELEASE_REGRESSION_GATE_OK version=7.5.0 |
| Current candidate manifest safety | PASS |
| Current candidate LAKIS/DEKIS/LUKIS boundary | PASS · 8 runtime/source tests + manifest negative test + DEKIS/LUKIS artifact negative tests + 7 public EXE scan |
| Current candidate startup integrity | PASS · exact 114-file set + managed-node inventory + embedded normalized manifest trust hash + compiled Launcher manifest/runtime corruption rejection |
| Current candidate licence blocker | NONE |
| Independent DeepSeek Scout | COMPLETED · 32K re-audit finish_reason=stop, 8 findings; confirmed blockers fixed locally and full gate re-PASS; updater interruption remains Private RC risk |
| Current candidate desktop UI visual check | PENDING |
| Current candidate real-generation regression | REQUIRED · PENDING because launcher/runtime integrity and capability preflight changed |
| Current candidate Private RC | NOT STARTED |

새 오류나 기능 변경이 생기면 관련 행의 제품 상태, 검증 수준, 환경 범위와 마지막 갱신일을 함께 수정한다.
