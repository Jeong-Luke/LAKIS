# LAKIS 8.1.1 — LoRA·프롬프트·화면 배치 수정

## 주요 수정
- ANIMA와 MOSS의 LoRA Manager·다운로드 폴더를 분리하고, 다운로드 후 LoRA 목록을 바로 갱신합니다.
- ANIMA의 3D 포즈를 켠 상태에서 MOSS로 전환해도 정밀 프롬프트가 적용되지 않도록 수정했습니다.
- MOSS 영역 프롬프트에 내용이 있으면 메인 프롬프트가 비어 있어도 생성 요청을 진행할 수 있습니다.
- 1920×1080 화면의 배율 설정에 따라 연속생성 버튼이 화면 밖으로 밀려나던 배치를 수정했습니다.

ComfyUI·Python·PyTorch·CUDA와 기존 모델 실행환경은 교체하지 않습니다.

## 검증·복구 파일
- `release-layout.json` · `LAKIS_RepairPack.zip`
- `RUNTIME_SHA256SUMS.json` · `SHA256SUMS.txt` · `artifact-manifest.json`
