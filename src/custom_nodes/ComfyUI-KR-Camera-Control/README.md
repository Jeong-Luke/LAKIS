# ComfyUI-KR-Camera-Control

Current version: **1.1.1**

`frame_y` / **세로 프레이밍** is an independent serialized camera setting.
Positive values request the subject higher in the image with more visible
foreground; negative values request the subject lower. It does not change the
existing Y camera pitch/elevation control and is available to backend/API clients.

BSK UI가 제공하는 카메라 프롬프트 제어 기능을 ComfyUI 네이티브 노드 하나로 분리한 로컬 파생 노드입니다. BSK 패널, 학습, 갤러리, 영상 기능을 로드하지 않습니다.

## 사용법

1. ComfyUI를 재시작합니다.
2. `KR Tools/카메라 > KR 카메라 컨트롤` 노드를 추가합니다.
3. 캔버스 좌드래그로 카메라 방위와 높이, 우드래그로 3D 미리보기 시점, 휠로 거리, `Shift+휠`로 롤을 조절합니다. `Shift+더블클릭`하면 미리보기 시점만 초기화됩니다.
4. X·Y·Z·롤 숫자 칸의 화살표로 0.01씩 조절할 수 있으며, `Enter`로 적용, `Esc`로 취소, `Shift+↑/↓`로 0.10씩 조절할 수 있습니다.
5. `가중치 설정`에서 `방위 총 가중치`, `높이 총 가중치`, `거리 총 가중치`를 각각 조절합니다. 세 기본값은 모두 5입니다.
6. 초기 프리셋은 `0=(0,0,0)`, `1=(0.5,0,0)`, `2=(-0.5,0,0)`, `3=(1,0,0)`입니다. 기본 프리셋도 삭제할 수 있으며, 추가·삭제할 때 현재 목록이 0부터 자동으로 다시 번호 매겨집니다.
7. `preset_index`에 Random Int 범위 `0~(현재 프리셋 수-1)`을 연결하면 기본·사용자 프리셋을 포함한 전체 목록에서 실행마다 랜덤 선택합니다. 입력을 연결하지 않으면 UI의 X·Y·Z 값을 사용합니다.
8. 프롬프트 미리보기 아래의 `프리셋 사용자 프롬프트`에 `eye focus`, `back focus` 같은 태그를 입력합니다. 이 값은 선택한 프리셋에 저장되며, 새 프리셋을 저장할 때도 좌표와 함께 포함됩니다.
9. `preset_index` 입력이 연결되면 실행 좌표가 인덱스로 결정되므로 X·Y·Z 슬라이더와 숫자 칸이 비활성화됩니다. 롤은 계속 조절할 수 있습니다.
10. 상단 `랜덤` 버튼은 프리셋을 선택하지 않고 X·Y·Z를 각각 `-1.00~1.00` 범위의 무작위 값으로 설정합니다.
11. `카메라 프롬프트` STRING 출력을 프롬프트 병합 노드나 CLIP Text Encode에 연결합니다.

프리셋 목록은 각 카메라 노드의 설정에 개별 저장되며 워크플로에도 함께 포함됩니다. 다른 카메라 노드나 브라우저 `localStorage`의 프리셋을 자동으로 가져오지 않으며 외부 네트워크도 사용하지 않습니다.

## 저작권과 라이선스

Camera prompt algorithm and interaction design derived from `ComfyUI_bsk_UI`, Copyright © 2026 灰暗x. Modifications keep the original attribution and are licensed under `AGPL-3.0-or-later`. 재배포 전에 원본 BSK UI의 현재 배포 조건도 함께 확인하세요.
