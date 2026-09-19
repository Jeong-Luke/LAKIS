# LAKIS 오류 코드 규격

사용자 노출 오류 코드는 `LKS-영역-번호` 형식을 사용한다. 한 번 배포된 코드의
의미는 바꾸거나 재사용하지 않는다. 사용자 화면, API 응답, 상태 파일과 감사
로그에는 같은 코드를 기록한다.

| 영역 | 의미 |
| --- | --- |
| `INS` | 설치·복구 |
| `UPD` | 업데이트·패처 |
| `RUN` | 런처·프로세스·포트 |
| `UI` | 데스크톱 창·UI 브리지 |
| `CFG` | 설정 저장·검증 |
| `NET` | 네트워크·다운로드·번역 |
| `MOD` | 모델·LoRA·VAE·CLIP |
| `NODE` | ComfyUI 사용자 노드·실행 구성 |
| `GEN` | 생성 큐·실행·출력 |
| `I2I` | 입력 이미지·Image to Image |
| `INP` | Local Inpaint 입력·처리·합성 |
| `LGT` | 광원·깊이 추정·재조명 |

## 현재 확정 코드

| 코드 | 의미 | 사용자 조치 |
| --- | --- | --- |
| `LKS-RUN-1001` | ComfyUI 포트가 이미 사용 중 | LAKIS와 ComfyUI 종료 후 재실행 |
| `LKS-RUN-1002` | ComfyUI 백엔드 시작 실패 | 런처 로그 확인 후 복구 실행 |
| `LKS-UI-1001` | UI 브리지 신원 확인 실패 | 재실행, 반복 시 복구 실행 |
| `LKS-RUN-1099` | 분류되지 않은 실행 실패 | 코드와 로그를 함께 보고 |
| `LKS-GEN-1001` | 분류되지 않은 생성 실패 | 생성 로그 확인 후 코드 보고 |
| `LKS-GEN-1002` | ComfyUI 연결 끊김 | LAKIS 재실행 |
| `LKS-GEN-1003` | ComfyUI 큐 사용 중 | 기존 작업 완료 후 재시도 |
| `LKS-GEN-1004` | GPU 모델 메모리 상태 불안정 | LAKIS 재실행 후 재시도 |
| `LKS-GEN-1005` | GPU 메모리 부족 | 해상도·LoRA 수 감소 |
| `LKS-GEN-1006` | NaN/무한대 계산값 발생 | CFG·태그 가중치 감소 |
| `LKS-GEN-1007` | 생성 단계 응답 시간 초과 | 재실행 후 반복 여부 확인 |
| `LKS-GEN-1008` | 생성 중 프로세스 비정상 종료 | 재실행 후 복구된 오류 정보 전달 |
| `LKS-GEN-1009` | ComfyUI 작업 진행 멈춤 감지 | 오류 정보 복사 후 전달 |
| `LKS-GEN-1010` | 생성 요청 승인 파일 충돌 | 잠시 후 재시도, 반복 시 LAKIS 재실행 |
| `LKS-GEN-1011` | 생성 서버가 JSON이 아닌 응답 반환 | 오류 정보 복사 후 LAKIS 재실행 |
| `LKS-GEN-1012` | 브라우저와 생성 서버 연결 실패 | 오류 정보 복사 후 LAKIS 재실행 |
| `LKS-GEN-1101` | 시드 범위 오류 | 지원 범위의 시드 입력 |
| `LKS-GEN-1201` | 프롬프트 인코딩 실패 | CLIP과 프롬프트 설정 확인 |
| `LKS-GEN-1301` | Initial 샘플링 실패 | 모델·구도·CFG·샘플러 확인 |
| `LKS-GEN-1302` | Initial VAE 디코딩 실패 | VAE와 해상도 확인 |
| `LKS-GEN-1401` | HighRez VAE 인코딩 실패 | VAE·해상도 확인 |
| `LKS-GEN-1402` | HighRez 샘플링 실패 | 모델·VRAM·세부 설정 확인 |
| `LKS-GEN-1403` | HighRez VAE 디코딩 실패 | VAE·VRAM 확인 |
| `LKS-GEN-1501` | 얼굴 디테일 실패 | 디테일러 설정·검출 모델 확인 |
| `LKS-GEN-1502` | 눈 디테일 실패 | 디테일러 설정·검출 모델 확인 |
| `LKS-GEN-1601` | 업스케일 실패 | 업스케일러 파일·설정 확인 |
| `LKS-GEN-1701` | 최종 이미지 저장 실패 | 출력 폴더 권한·공간 확인 |
| `LKS-GEN-1702` | 저장 완료 후 생성 파일 탐색 실패 | 오류 정보와 출력 경로 확인 |
| `LKS-GEN-1703` | 출력 파일 권한·잠금 오류 | 파일을 사용하는 프로그램 종료 또는 저장 폴더 확인 |
| `LKS-GEN-1704` | 출력 저장 공간 부족 | 저장 장치 공간 확보 |
| `LKS-MOD-1001` | 체크포인트 로딩 실패 | 파일·VRAM·모델 형식 확인 |
| `LKS-MOD-1002` | VAE 로딩 실패 | VAE 파일 확인 |
| `LKS-MOD-1003` | CLIP 로딩 실패 | CLIP 파일 확인 |
| `LKS-MOD-1101` | 체크포인트 파일 없음 | 모델을 다시 선택·설치 |
| `LKS-MOD-1102` | 체크포인트 비호환 | Anima 호환 모델 선택 |
| `LKS-MOD-1103` | VAE 파일 없음 | VAE를 다시 선택·설치 |
| `LKS-MOD-1104` | CLIP 파일 없음 | CLIP을 다시 선택·설치 |
| `LKS-MOD-1201` | LoRA 파일을 찾을 수 없음 | LoRA 목록과 파일 확인 |
| `LKS-NODE-1201` | 최종 생성 그래프의 필수 노드 미로드 | LAKIS 업데이트·복구 후 재실행 |
| `LKS-NODE-1202` | Anima LLLite 인페인트 실행 노드 미로드 | LAKIS 업데이트·복구 후 재실행 |
| `LKS-NODE-1203` | LAKIS Local Inpaint 노드 미로드 | LAKIS 업데이트·복구 후 재실행 |
| `LKS-NODE-1204` | 최종 Image Saver 노드 미로드 | LAKIS 업데이트·복구 후 재실행 |
| `LKS-I2I-1001` | 입력 이미지 로딩 실패 | 지원 이미지로 다시 선택 |
| `LKS-I2I-1002` | 입력 이미지 크기 변환 실패 | 출력 해상도·입력 이미지 확인 |
| `LKS-I2I-1101` | i2i 입력 파일 만료·누락 | 입력 이미지 다시 선택 |
| `LKS-INP-1001` | 인페인트 마스크 로딩 실패 | 마스크를 다시 칠한 뒤 재시도 |
| `LKS-INP-1002` | Local Inpaint crop 준비 실패 | 원본·마스크를 다시 선택 |
| `LKS-INP-1003` | Local Inpaint VAE 인코딩 실패 | VAE·입력 이미지를 확인 |
| `LKS-INP-1004` | LLLite 적용 실패 | LLLite 노드·모델 파일 확인 |
| `LKS-INP-1005` | Local Inpaint 색상 보정 실패 | 오류 정보 복사 후 전달 |
| `LKS-INP-1006` | Local Inpaint 원본 합성 실패 | 원본·마스크 좌표 확인 |
| `LKS-INP-1101` | LLLite 인페인트 모델 파일 없음·불일치 | 공식 모델 파일 수동 설치 |
| `LKS-CFG-1101` | 지원하지 않는 샘플러 | 샘플러를 다시 선택 |
| `LKS-CFG-1001` | 생성 요청 JSON 형식 오류 | 오류 정보 복사 후 LAKIS 재실행 |
| `LKS-CFG-1002` | 생성 요청 본문 누락 | 오류 정보 복사 후 LAKIS 재실행 |
| `LKS-CFG-1003` | 생성 요청 본문 허용 크기 초과 | 입력 상태를 다시 선택 후 재시도 |
| `LKS-CFG-1102` | 지원하지 않는 스케줄러 | 스케줄러를 다시 선택 |
| `LKS-CFG-1103` | 세부 설정 검증 실패 | 해당 세부 설정 초기화 |
| `LKS-CFG-1104` | ComfyUI가 생성 요청 입력을 거부함 | 오류 정보의 노드·입력값 확인 |

새 코드는 이 문서에 먼저 등록한다. 내부 예외 전문은 화면에 직접 노출하지 않고
로그의 `error_detail`에만 남긴다.

## 생성 오류 기록 필드

생성 실패 시 `/api/generation-status`와 `external_ui_bridge_audit.jsonl`에
`error_code`, `request_id`, `prompt_id`, `error_stage`, `error_node_id`,
`error_node_type`, `error_exception_type`, `error_detail`, `finished_at`을 함께
남긴다. 화면에는 코드·단계·노드·축약 추적 ID만 표시한다.

오류창의 **오류 정보 복사하기**는 위 식별 정보와 재현용 생성 설정을 JSON으로
복사한다. 프롬프트 원문, 입력 이미지 데이터, 시드와 사용자 절대 경로는 포함하지
않는다.

`LKS-CFG-1103`에는 해당 노드가 ComfyUI에서 선언한 당시의 입력 규격만 기록한다.
`setting_node_id`, `setting_node_type`, `setting_name`, `received_value`,
`node_declaration`(min/max/step 또는 options), `internal_reason`이 포함된다. LAKIS가
별도의 임의 범위를 추가하지 않는다.


## Recovery candidate additions (not a published release)

| Code | Meaning | Retry policy |
|---|---|---|
| LKS-GEN-1011 | Submission or monitor result is unknown; backend may still be running. | Never automatically resubmit. Preserve request evidence and block another request in this bridge until explicitly recovered/restarted. |
| LKS-CFG-1104 | ComfyUI returned a definite 4xx validation rejection to /prompt. | Preserve HTTP status and node_errors; repair the request before a new user-approved generation. |
