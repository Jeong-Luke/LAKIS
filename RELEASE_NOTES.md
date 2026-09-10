# LAKIS Studio v7.3.6

## 긴급 수정

- LAKIS 최적화를 켠 DETAIL 생성 결과가 이미지 배지에서 `FAST`로 잘못
  표시되던 문제를 수정했습니다. 생성 중, 생성 완료 후, 이력 이미지 재선택
  시 모두 `LAKIS DETAIL`로 표시됩니다.
- 구도 설정의 카메라 좌표와 ON/OFF 상태가 업데이트 또는 재시작 후 초기화되던
  문제를 수정했습니다.
- 캔버스 드래그, 휠 거리 조절, 키보드 이동, 슬라이더, 숫자 입력, 프리셋 및
  초기화 조작이 모두 구도 상태 저장에 반영되도록 보강했습니다.
- v7.3.3 계열에서 저장된 얼굴·눈 디테일러 수치가 문자열로 남아 있으면
  생성 큐에 들어가기 전에 `LKS-GEN-1001`이 발생하던 문제를 수정했습니다.
- 구버전 숫자·불리언·카메라 설정을 안전하게 변환하고, 잘못된 고급 설정은
  해당 항목만 제외하도록 변경했습니다. 오래된 모델 노드 설정이 현재 선택한
  체크포인트·VAE·CLIP을 다시 덮어쓰는 문제도 차단했습니다.
- 사이드바의 모니터 아이콘이 사용자 편집본을 열던 문제를 수정했습니다.
  이제 실제 `LAKIS_DETAIL_runtime_api_v7.3` 실행 그래프를 API 형식으로 열며,
  실행 파일이 없을 때 편집본으로 조용히 대체하지 않습니다.

사용자 모델, LoRA, 프롬프트, 워크플로 및 생성 이미지는 업데이트 시 보존됩니다.

## English

- Fixed LAKIS DETAIL results being mislabeled as FAST in the image badge.
- Persisted composition camera coordinates and the composition ON/OFF state
  across application restarts and updates.
- Migrated legacy numeric, boolean, camera, and advanced-node settings safely,
  preventing pre-queue generation failures and stale model overrides.
- Fixed the monitor shortcut to open the actual LAKIS DETAIL runtime API graph
  instead of falling back to the user-editable workflow.

---

## v7.3.4

## 주요 변경 사항

- 생성 모드에 `LAKIS 최적화` 전환 기능을 추가했습니다.
- LAKIS 최적화를 켜고 DETAIL을 선택하면 새 `LAKIS_DETAIL` 얼굴·눈 보정과
  `LAKIS_SCOPE` 업스케일 경로가 작동합니다.
- LAKIS 최적화를 끄면 기존 FAST 및 레거시 DETAIL 방식이 그대로 유지됩니다.
- 여러 인물이 등장하는 이미지도 인물별 영역이 겹치지 않도록
  LAKIS_DETAIL의 다인 처리 방식을 개선했습니다.
- 노드 실행 중 강제 메모리 해제를 제거하고 작업 완료 후 정리하도록 변경하여
  ComfyUI 작업 중단 및 잘못된 정체 감지를 줄였습니다.
- LAKIS_SCOPE처럼 중간 진행 이벤트가 없는 긴 연산을 웹소켓 정체로 오인하지
  않도록, 중단 전에 ComfyUI 큐와 작업 이력을 재확인합니다.

## 인터페이스 및 워크플로

- 사이드바에서 새 LAKIS DETAIL 실행 워크플로와 사용자 편집 워크플로를
  바로 열 수 있습니다.
- ComfyUI 메뉴의 모니터 버튼이 사용자 편집 워크플로 이름으로 잘못
  표시되던 문제를 수정했습니다. 이제 `LAKIS_DETAIL_runtime_api_v7.3`으로
  명확하게 연결되어 표시됩니다.
- 사용자가 ComfyUI에서 직접 확인하고 수정할 수 있도록
  `VRAM Gate → LAKIS_DETAIL → LAKIS_SCOPE` 경로를 시각적으로 구성했습니다.
- 프롬프트 입력칸의 ON/OFF 스위치를 다른 일반 스위치와 같은 파란색으로
  통일했습니다. LAKIS 최적화 스위치만 분홍색으로 구분됩니다.
- LAKIS 모드 스위치, 구도 설정 노브, 프롬프트 필드 토글이 작동하지 않던
  UI 회귀 문제를 수정했습니다.

## 안정성 및 배포 구성

- 시작 화면에서 실제 생성 경로를 안전하게 준비하도록 워밍업을 수정했습니다.
- LAKIS_DETAIL, LAKIS_SCOPE 및 VRAM 경계 진단을 오류 보고에 반영했습니다.
- LAKIS_DETAIL의 GPL 고지와 직접 의존성 라이선스 자료를 보강했습니다.
- YOLO, Ultralytics 및 ComfyUI-Impact-Subpack 자료는 배포본에 포함하지 않습니다.
- 사용자 모델, LoRA, 워크플로, 설정, 프롬프트 및 생성 이미지는 업데이트 시
  보존됩니다.

> 처리 시간과 메모리 사용량은 그래픽카드, 해상도, 모델, LoRA 구성 및 이미지
> 속 인물 수에 따라 달라질 수 있습니다.

기존 사용자는 LAKIS 실행 시 나타나는 업데이트 안내에서 `업데이트`를 선택하면
됩니다.

---

## English

- Added the optional LAKIS optimization path using `LAKIS_DETAIL` and
  `LAKIS_SCOPE`, while preserving legacy FAST and DETAIL behavior when off.
- Improved multi-person face-region handling and deferred memory cleanup until
  prompt completion to prevent worker interruption.
- Added v7.3 runtime and editable workflows to the sidebar.
- Fixed startup warmup, LAKIS mode switching, composition controls, and prompt
  field toggle regressions.
- Updated prompt switches to the standard blue active color and retained pink
  for LAKIS optimization only.
- Strengthened LAKIS_DETAIL licensing notices and kept YOLO/Ultralytics and
  ComfyUI-Impact-Subpack materials out of the distribution.
