# LAKIS v7.5.1

## 주요 변경 사항

- Library 저장 폴더 선택을 실제 Final Saver 출력에 연결하고, 설치별 사용자 설정으로 유지합니다.
- 저장 폴더 선택창이 현재 폴더에서 열리며 변경 사항은 다음 생성부터 적용됩니다.
- Library 단일·일괄 삭제를 기본 경로와 사용자 지정 경로 모두에서 Windows 휴지통으로 직접 처리합니다.
- 시작 직후 ComfyUI 모델 목록 준비를 기다려 정상 체크포인트가 누락으로 판정되는 문제를 수정했습니다.
- 실행 중 요청, 안전 잠금, 모델 초기화, 인페인트 원본·마스크 오류를 구체적인 코드로 안내합니다.
- Local Inpaint V2 요청 검증과 최종 결과 저장 경로를 안정화했습니다.
- 작은 수정 영역을 처리하고 그 밖의 원본 픽셀을 보존하는 Local Inpaint V2와 Inpaint Delete를 추가했습니다.
- LAKIS Link에서 모바일 생성 화면, 이미지 미리보기, 확대·축소, 인페인트 드로잉과 Library 사용을 지원합니다.
- LAKIS Library에 메타데이터 안정화, 다중 선택, 일괄 삭제와 화면 근처 이미지 지연 로드를 적용했습니다.
- 와일드카드 / 랜덤 선택과 연속 생성을 추가했습니다.
- 모바일과 PC의 프롬프트 및 Composition 설정 유지 동작을 개선했습니다.
- Local Inpaint V2와 Final Saver 775를 반영한 Editable, Runtime Visual, Runtime API workflow를 제공합니다.
- 모델 감지, 최근 이미지 전달, Link Library 검색, Final Saver 결과 검색과 패처 패키징 문제를 수정했습니다.
- 생성 오류를 요청 형식, 연결, 필수 노드, GPU, 저장 및 Local Inpaint 단계별 코드로 세분화했습니다.
- 서버 연결 또는 비정상 응답에서도 설정과 원인 정보가 오류 보고에서 사라지지 않도록 개선했습니다.
- 생성 요청 전에 필수 ComfyUI 노드를 확인하여 누락된 LLLite, Local Inpaint 및 Final Saver 노드를 즉시 안내합니다.
- 공개 업데이트에 Local Inpaint V2용 `ComfyUI-Anima-LLLite` 실행 노드를 포함하고 안전 마커를 항상 복구하도록 수정했습니다.
- 업데이트가 같은 파일을 설치한 뒤 삭제하지 못하도록 매니페스트 충돌 검사를 추가했습니다.
- 폐기된 Light/DSINE 경로와 비공개 연구 기능을 공개 배포에서 제외했습니다.
- Windows Defender가 일반 Setup을 차단하는 환경을 위한 공식 CMD Version 설치 경로를 추가했습니다.
- CMD 설치기도 다운로드 자산의 SHA-256, 설치 파일 목록과 크기를 검증하고 staging 완료 후에만 설치 위치로 승격합니다.
- 실행 전에 공개 `release-layout.json`으로 관리 파일의 누락과 크기를 확인하고, 확인된 손상은 한 번의 자동 Repair로 복구합니다.
- 자동 Repair와 업데이트가 사용자 workflow, 모델, LoRA, 입력·출력 이미지와 설치별 설정을 덮어쓰지 않도록 보호 범위를 강화했습니다.
- 신규 설치에 기본 입력 이미지와 Editable workflow를 포함하여 첫 생성과 LoRA Manager 초기화를 안정화했습니다.

## Local Inpaint 모델

`anima-lllite-inpainting-v2.safetensors`는 설치 프로그램이나 updater에 포함되지 않으며 자동으로 다운로드되지 않습니다. 공식 배포처에서 사용자가 직접 설치해야 합니다.

## 업데이트 안전성

기존 안정 버전 사용자는 v7.5.1 공개 후 자동 업데이트로 전환할 수 있습니다. 사용자 모델, LoRA, workflow, 입력·출력 이미지, Library, 사용자 와일드카드와 설치별 설정은 유지됩니다.

---

## English

- Connected the Library save-folder selection to Final Saver and persisted it in per-installation user state.
- Reopens the folder picker at the current folder and applies a successful change to the next generation.
- Moves Library single and batch deletions from default or custom roots directly to the Windows Recycle Bin.
- Waits for ComfyUI's model inventory during startup so valid checkpoints are not reported missing.
- Reports active-request, safety-lock, model-initialization, and Inpaint source/mask failures precisely.
- Hardened Local Inpaint V2 request validation and final output routing.
- Added Local Inpaint V2 and Inpaint Delete for focused edits that preserve source pixels outside the edited area.
- Added LAKIS Link mobile generation and Library access, image preview, pinch zoom, and mobile inpaint drawing.
- Added Library metadata fixes, multi-select, batch deletion, and viewport-based lazy image loading.
- Added wildcard/random prompt insertion and continuous generation.
- Improved prompt and Composition persistence across desktop and mobile.
- Updated the official Editable, Runtime Visual, and Runtime API workflows with Local Inpaint V2 and Final Saver 775.
- Fixed model detection, recent-image delivery, Link Library discovery, Final Saver result discovery, and patcher packaging.
- Split generation failures into precise request, transport, required-node, GPU, save, and Local Inpaint error codes.
- Preserved settings and diagnostic details when the UI receives a connection failure or a non-JSON server response.
- Added a preflight check for missing LLLite, Local Inpaint, and Final Saver nodes before submitting a generation request.
- Added the `ComfyUI-Anima-LLLite` runtime nodes to public updates and ensured the required safety marker is restored.
- Added manifest validation that rejects any path scheduled for both installation and deletion.
- Removed retired Light/DSINE paths and private research features from the public distribution.
- Added an official CMD Version installation path for systems where Windows Defender blocks the regular Setup.
- The CMD installer verifies downloaded assets, the managed-file inventory, and file sizes before promoting its staging tree.
- Added a public `release-layout.json` consistency check and a single automatic Repair cycle for confirmed managed-file damage.
- Strengthened update and Repair protection for user workflows, models, LoRAs, input/output images, and installation-specific state.
- Included the default input image and Editable workflow in fresh installations to stabilize first generation and LoRA Manager initialization.

The `anima-lllite-inpainting-v2.safetensors` weight is not bundled or downloaded automatically. Users install it manually from the official publisher.

Existing stable installations can move to v7.5.1 after the release is published. User models, LoRAs, workflows, input/output images, Library data, wildcards, and installation-specific settings are preserved.
