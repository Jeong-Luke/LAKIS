// SPDX-License-Identifier: GPL-3.0-only
// Manual pose editing never submits a second prompt or downloads SAM weights.
class PoseEditorApi extends EventTarget {
  fetchApi() {
    throw new Error("이 편집기는 수동 포즈 편집 전용입니다. 자동 포즈 추출은 사용하지 않습니다.");
  }
}
export const api = new PoseEditorApi();
