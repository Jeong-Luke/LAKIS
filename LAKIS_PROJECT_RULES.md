# LAKIS Project Rules

## 제품 경계

- LAKIS, DEKIS, LUKIS의 대상 경로와 배포 범위를 혼동하지 않는다.
- DEKIS 실험을 LAKIS에 승격할 때는 공개 이름, 의존성, workflow, 설치·업데이트 경로를 다시 검증한다.
- LUKIS 전용 기능과 비공개 연구 기능을 LAKIS 공개 배포에 포함하지 않는다.
- 기능 상태인 Composition, i2i, Inpaint를 FAST, DETAIL, LAKIS DETAIL과 같은 생성 모드로 취급하지 않는다.

## 생성 계약

- 사용자 제작 한 번은 ComfyUI `/prompt` 한 번이어야 한다.
- 최종 출력은 Final Saver node `775`로 연결한다.
- 공식 generation feature는 사람이 편집 가능한 workflow와 API/runtime workflow를 함께 유지한다.
- bridge가 요청별 변환을 하더라도 공식 workflow와 제품 의미가 같아야 한다.
- Inpaint ON 상태에서는 i2i를 비활성화하고 Composition을 임시 비활성화하되 기존 Composition 값은 보존한다.
- Prompt, Inpaint Prompt 및 모바일/PC 상태 유지 동작을 깨지 않는다.

## Local Inpaint V2

- 사용자 마스크가 수정 영역의 최우선 기준이다.
- 기본 경로는 Local Prepare → Local VAE → LLLite → Local Composite → Final Saver 775다.
- V2 최종 출력의 upstream에 full-image HighRez, Face/Eye detail, mandatory LAKIS_DETAIL 또는 USDU를 연결하지 않는다.
- 합성 alpha는 crop 사각형이 아니라 feathered effective edit mask를 사용한다.
- `ComfyUI-Anima-LLLite` 실행 노드는 공개 업데이트에 포함한다.
- `anima-lllite-inpainting-v2.safetensors` 가중치는 패키지에 포함하거나 자동 다운로드하지 않는다. 사용자가 공식 배포처에서 직접 설치한다.

## 사용자 데이터 보호

설치, 복구, 업데이트, 패치 및 제거 과정에서 다음을 덮어쓰거나 삭제하지 않는다.

- models 및 LoRA
- input/output과 Library 이미지
- 사용자 workflow
- 프롬프트와 UI 상태
- 사용자 wildcard
- 설치별 설정과 외부 사용자 상태

사용자 소유 경로를 대상으로 재귀 삭제·이동을 수행하지 않는다. 매니페스트에 `models`, `input`, `output`, `user`, 로그, `.audit` 또는 디버그 파일을 넣지 않는다.

## 공개 배포 제외 항목

활성 그래프와 배포 목록에서 다음을 0으로 유지한다.

- LAKIS Light Control 및 DSINE
- Pose Control 연구 기능
- Health Monitor
- SamplerSPEED 및 ComfyUI-SPEED
- LUKIS 전용 파일
- DEKIS 전용 이름과 경로

기본 wildcard의 `pose.txt`는 Pose Control 기능이 아니므로 문자열 검색 결과를 맥락 없이 유출로 판정하지 않는다.

## 업데이트 안전성

- `ComfyUI/LAKIS/STOP_AUTOMATION`을 설치·복구 대상에 포함하며 삭제 목록에 넣지 않는다.
- 하나의 매니페스트에서 같은 경로를 중복 설치하지 않는다.
- 설치 목록과 삭제 목록이 겹치면 릴리즈를 중단한다.
- 공개 매니페스트를 새 자산 검증보다 먼저 올리지 않는다.
- 릴리즈 자동화는 초안 자산 업로드 → 원격 바이트 해시 검증 3회 → 릴리즈 공개 → `main`의 최종 매니페스트 게시 순서를 유지한다.

## 오류 처리

- 모든 오류를 `LKS-GEN-1001`로 뭉치지 않는다.
- 잘못된 요청, 연결 실패, 비정상 서버 응답, 필수 노드 누락, GPU, 저장 및 Inpaint 단계를 가능한 범위에서 구분한다.
- 비밀 정보, 원본 이미지 데이터 및 민감한 전체 경로를 오류 보고에 넣지 않는다.
- ComfyUI `/prompt` 전 필수 node type을 확인한다.
- 오류 코드 변경 시 `ERROR_CODES.md`와 `installer/tests/test_error_codes.py`를 함께 갱신한다.

## 검사와 배포

- 사용자 요청 범위에 맞는 최소 검사를 먼저 수행한다.
- 이미 통과했고 새 변경과 무관한 실제 생성 회귀를 반복하지 않는다.
- 릴리즈 전 `Test-ReleaseRegression.ps1`과 매니페스트 검사를 통과시킨다.
- 배포 요청이 없으면 push, tag 또는 GitHub Release를 만들지 않는다.
- 배포 요청이 있으면 자동화 완료와 공개 매니페스트까지 확인한 뒤 성공으로 보고한다.
- README는 한글을 먼저, 영문을 뒤에 둔다. GitHub Release body는 `RELEASE_NOTES.md`, 저장소 소개는 `README.md`를 사용하며 서로 덮어쓰지 않는다.

## 작업 폴더 규칙

- 기존 미추적 파일을 임의로 삭제하거나 커밋하지 않는다.
- `.audit` 및 테스트 중 생성된 임시 로그만 생성 주체와 용도를 확인한 뒤 정리한다.
- 수정 전 실제 import path와 실행 중인 제품 경로를 확인한다.
- 사용자의 컴퓨터에서 재현되지 않는 테스터 오류를 로컬 상태만 보고 부정하지 않는다.

