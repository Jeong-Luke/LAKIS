// SPDX-License-Identifier: GPL-3.0-only
// Keep the upstream gizmo, IK, picking and history; simplify only visible markers.
import * as T from "./vendor/toyxyz/vendor/three/three.module.min.js";
import { validMHRShape } from "./vendor/toyxyz/util/pose_shape_control.js";
import { applyBodyModel } from "./pose-body-model.js";

const REST_ARMS = [0.16, -0.96, 0.02];
export const BASIC_POSE_PRESETS = [
  { id: "standing", label: "서기", arms: REST_ARMS },
  { id: "sitting", label: "의자에 앉기", height: 0.65, arms: [0.08, -0.9, 0.38],
    legs: [0.02, -0.54, 0.47], pole: [0, -0.1, 0.7] },
  { id: "lying", label: "눕기", tilt: -Math.PI / 2, arms: REST_ARMS, grounded: true },
  { id: "floor-sitting", label: "바닥에 앉기", height: 0.23, arms: [0.06, -0.86, 0.43],
    legs: [0.08, -0.12, 0.96], pole: [0, 0.5, 0.4], footTilt: -Math.PI / 2, grounded: true },
  { id: "kneeling", label: "무릎 꿇고 앉기", height: 0.28, arms: [0.05, -0.93, 0.27],
    legs: [0.02, -0.18, -0.06], pole: [0, -0.1, 0.65], footTilt: Math.PI, grounded: true },
];

const point = () => new T.Vector3();
const FINGERS = ["index", "middle", "pinky", "ring", "thumb"];
const hiddenJoint = name => FINGERS.some(finger => name.includes(finger)) ||
  name === "c_jaw" || name === "c_jaw_null" || name === "jaw";

export function distinctBodyColor(existing, preferred) {
  if (preferred) {
    const candidate = new T.Color(preferred);
    if (existing.every(color => color.getHex() !== candidate.getHex())) return preferred;
  }
  let best, separation = -1;
  for (let hue = 0; hue < 360; hue++) {
    const color = new T.Color().setHSL(hue / 360, 1, 0.5);
    const distance = Math.min(...existing.map(other =>
      (color.r - other.r) ** 2 + (color.g - other.g) ** 2 + (color.b - other.b) ** 2));
    if (distance > separation) { best = color; separation = distance; }
  }
  return `#${best.getHexString()}`;
}

export function filterPoseMarkers(editor) {
  for (const body of editor.bodies) {
    for (const marker of body.markers.children) {
      marker.visible = !hiddenJoint(marker.userData.object.name);
      if (!marker.visible && editor.selected === marker.userData.object) {
        editor.selectObject(body.rootControl);
      }
    }
  }
}

export class PrecisionPoseControls {
  constructor(editor) {
    this.editor = editor;
    this.abort = new AbortController();
    this.wheelAxes = new WeakMap();
    this.poleSensitivity = 0.5;
    this.controls = document.createElement("section");
    this.controls.className = "precision-pose-controls";
    this.controls.setAttribute("aria-label", "인물 추가·선택 및 포즈 조작");
    this.controls.innerHTML = `
      <h3>인물</h3>
      <div class="precision-pose-row">
        <button type="button" data-add-body>＋ 인물 추가</button>
        <button type="button" data-delete-body title="선택한 인물만 삭제합니다. 실행 취소로 복원할 수 있습니다.">인물 삭제</button>
        <label class="precision-pose-field">편집할 인물 <select data-select-body></select></label>
      </div>
      <h3>모델·기본 자세</h3>
      <div class="precision-pose-row">
        <button type="button" data-body-model="male" aria-pressed="false">남성</button>
        <button type="button" data-body-model="female" aria-pressed="false">여성</button>
      </div>
      <div class="precision-pose-row precision-pose-preset-row">
        <label class="precision-pose-field">기본 자세
          <select data-pose-preset>${BASIC_POSE_PRESETS.map(preset =>
            `<option value="${preset.id}">${preset.label}</option>`).join("")}</select>
        </label>
        <button type="button" data-apply-preset aria-label="기본 자세 적용">적용</button>
      </div>
      <h3>관절 조작</h3>
      <div class="precision-pose-row" data-transform-tools></div>
      <div class="precision-pose-row">
        <label class="precision-pose-field">초록·분홍 점 감도
          <input type="range" data-pole-sensitivity min="0.1" max="2" step="0.1" value="0.5">
          <output data-pole-sensitivity-value>0.5×</output>
        </label>
      </div>
      <div class="precision-pose-row">
      </div>
      <h3>화면·카메라</h3>
      <div class="precision-pose-row">
        <button type="button" data-view="front">정면 보기</button>
        <button type="button" data-view="side">측면 보기</button>
      </div>
      <div class="precision-pose-row" data-native-tools></div>
      <h3>광원 방향</h3>
      <div data-light-control></div>
      <div data-generation-controls hidden></div>
      <details data-body-parameters>
        <summary>상세 설정</summary>
        <div data-parameter-slot></div>
      </details>
      <p role="status"></p>`;
    editor.root.classList.add("precision-pose-editor");
    editor.bar.classList.add("precision-pose-toolbar");
    editor.workspace.classList.add("precision-pose-workspace");
    editor.note.classList.add("precision-pose-note");
    editor.modelTree.root.classList.add("precision-pose-models");
    editor.root.prepend(this.controls);
    this.bodyButtons = [...this.controls.querySelectorAll("button")];
    this.controls.querySelector("[data-native-tools]").append(editor.bar);
    this.controls.querySelector("[data-transform-tools]").append(editor.transformBar);
    editor.transformBar.classList.add("precision-pose-transform-tools");
    editor.transformBar.setAttribute("aria-orientation", "horizontal");
    this.localizeToolbar();
    this.controls.querySelector("[data-light-control]").append(editor.lightControl.root);
    editor.lightControl.root.classList.add("precision-pose-light");
    this.outputZoom = editor.camera.zoom;
    this.outputFrame = document.createElement("div");
    this.outputFrame.className = "precision-pose-output-frame";
    this.outputFrame.setAttribute("role", "img");
    this.outputLabel = document.createElement("span");
    this.outputLabel.className = "precision-pose-output-label";
    this.outputLabel.setAttribute("aria-hidden", "true");
    this.outputFrame.append(this.outputLabel);
    editor.view.append(this.outputFrame);
    this.help = document.createElement("div");
    this.help.className = "precision-pose-help";
    this.help.setAttribute("role", "note");
    this.help.setAttribute("aria-label", "3D 포즈 조작 안내");
    this.help.textContent = [
      "관절점 선택 → 축·고리 드래그",
      "관절 위 휠: 회전 · Shift/Alt: 회전축",
      "빈 공간 드래그: 시점 회전 · 휠: 확대/축소",
      "휠 누르고 드래그: 화면 이동",
      "흰 점: 관절 · 초록: 손발 · 분홍/보라: 굽힘 방향",
      "Ctrl+Z: 실행 취소 · Ctrl+Shift+Z: 다시 실행",
    ].join("\n");
    editor.view.append(this.help);
    this.originalResize = editor.resize;
    this.originalCapture = editor.capture;
    this.originalRegionCapture = editor.captureRegionPainter;
    editor.resize = () => this.resizePreview();
    editor.capture = () => this.withOutputAspect(() => this.originalCapture.call(editor));
    editor.captureRegionPainter = () => this.withOutputAspect(() => this.originalRegionCapture.call(editor));
    this.originalInfoHidden = editor.info.hidden;
    editor.info.hidden = true;
    this.parameters = this.controls.querySelector("[data-body-parameters]");
    this.parameterSlot = this.controls.querySelector("[data-parameter-slot]");
    this.parameters.ontoggle = () => this.syncParameters();
    this.status = this.controls.querySelector("[role=status]");
    this.bodySelect = this.controls.querySelector("[data-select-body]");
    this.bodySelect.onchange = () => this.selectBody(this.bodySelect.value);
    this.controls.querySelector("[data-add-body]").onclick = () => this.run(() => this.addBody());
    this.controls.querySelector("[data-delete-body]").onclick = () => this.run(() => editor.deleteBody());
    this.sensitivityInput = this.controls.querySelector("[data-pole-sensitivity]");
    this.sensitivityInput.oninput = () => {
      this.poleSensitivity = Number(this.sensitivityInput.value);
      this.controls.querySelector("[data-pole-sensitivity-value]").value = `${this.poleSensitivity}×`;
    };
    for (const button of this.controls.querySelectorAll("[data-body-model]")) {
      button.onclick = () => this.run(() => this.setBodyModel(button.dataset.bodyModel));
    }
    this.presetSelect = this.controls.querySelector("[data-pose-preset]");
    this.controls.querySelector("[data-apply-preset]").onclick = () =>
      this.run(() => this.applyPreset(this.presetSelect.value));
    for (const button of this.controls.querySelectorAll("[data-view]")) {
      button.onclick = () => this.setView(button.dataset.view);
    }
    this.originalVisibility = editor.updateControllerVisibility;
    editor.updateControllerVisibility = () => {
      this.originalVisibility.call(editor);
      this.wheelAxes = new WeakMap();
      this.refresh();
    };
    this.originalReadiness = editor.updateGetPoseButton;
    editor.updateGetPoseButton = () => {
      this.originalReadiness.call(editor);
      this.refresh();
    };
    this.originalTransform = editor.onTransformChange;
    editor.onTransformChange = () => {
      const drag = this.poleDrag;
      if (drag && editor.gizmo.dragging && editor.gizmo.mode === "translate" &&
          editor.gizmo.object === drag.object) {
        // TransformControls supplies a fresh start-relative position each move.
        // Scale that displacement once, not the previous adjusted result.
        drag.object.position.sub(drag.start).multiplyScalar(drag.gain).add(drag.start);
      }
      this.originalTransform.call(editor);
    };
    this.onDragStart = () => {
      this.finishWheel();
      const object = editor.gizmo.object;
      this.poleDrag = editor.gizmo.mode === "translate" && object?.userData.chain
        ? { object, start: object.position.clone(), gain: this.poleSensitivity } : null;
    };
    this.onDragEnd = () => { this.poleDrag = null; };
    editor.gizmo.addEventListener("mouseDown", this.onDragStart);
    editor.gizmo.addEventListener("mouseUp", this.onDragEnd);
    editor.renderer.domElement.addEventListener("wheel", event => this.turnWheel(event),
      { capture: true, passive: false, signal: this.abort.signal });
    editor.renderer.domElement.addEventListener("pointerdown", () => {
      this.finishWheel();
      this.wheelAxes = new WeakMap();
    }, { capture: true, signal: this.abort.signal });
    editor.root.addEventListener("keydown", event => this.historyKey(event),
      { capture: true, signal: this.abort.signal });
    editor.getPoseButton.hidden = true;
    this.refresh();
    editor.resize();
  }

  historyKey(event) {
    if (event.defaultPrevented || event.isComposing || event.altKey ||
        !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z" ||
        event.target?.isContentEditable || event.target?.closest?.("input, textarea, select")) return;
    event.preventDefault();
    event.stopPropagation();
    const editor = this.editor;
    if (this.busy || editor.loading || editor.root.inert || editor.gizmo.dragging) return;
    this.finishWheel();
    if (event.shiftKey) editor.redo();
    else editor.undo();
  }

  localizeToolbar() {
    const editor = this.editor;
    const labels = { "Reset pose": "포즈 초기화", "Reset view": "시점 초기화" };
    for (const button of editor.bar.querySelectorAll("button")) {
      const label = labels[button.textContent];
      if (label) button.textContent = button.title = label;
    }
    for (const [button, label, title = label] of [
      [editor.undoButton, "실행 취소"],
      [editor.redoButton, "다시 실행"],
      [editor.saveCameraButton, "시점 저장", "현재 카메라 위치와 화각을 저장합니다."],
      [editor.loadCameraButton, "시점 불러오기", "저장한 카메라 위치와 화각으로 돌아갑니다."],
      [editor.transformTools.get("rotate"), "회전", "회전 (E)"],
      [editor.transformTools.get("translate"), "이동", "이동 (W)"],
      [editor.transformTools.get("scale"), "크기 조절", "크기 조절 (R)"],
    ]) {
      button.setAttribute("aria-label", label);
      button.title = title;
    }
    this.originalDisplaySetters = new Map();
    for (const [method, button, label, title] of [
      ["setFloorVisible", editor.floorButton, "바닥", "미리보기의 바닥 격자를 표시하거나 숨깁니다."],
      ["setOutlineVisible", editor.outlineButton, "외곽선", "미리보기와 출력 이미지의 인물 외곽선을 표시하거나 숨깁니다."],
    ]) {
      const original = editor[method];
      this.originalDisplaySetters.set(method, original);
      const update = () => {
        button.textContent = `${label}: ${button.getAttribute("aria-pressed") === "true" ? "켜짐" : "꺼짐"}`;
      };
      button.title = title;
      editor[method] = (...args) => {
        const result = original.apply(editor, args);
        update();
        return result;
      };
      update();
    }
    editor.fovSlider.parentElement.firstChild.textContent = "화각";
    editor.fovSlider.parentElement.title = "카메라의 세로 시야각을 조절합니다.";
    editor.fovSlider.setAttribute("aria-label", "카메라 화각 조절");
    editor.fovInput.setAttribute("aria-label", "카메라 화각 (도)");
  }

  resizePreview() {
    const editor = this.editor;
    if (editor.disposed) return;
    const width = editor.view.clientWidth, height = editor.view.clientHeight;
    if (!width || !height) return;
    const outputWidth = editor.widget("width").value, outputHeight = editor.widget("height").value;
    const ratio = outputWidth / outputHeight;
    const zoom = Math.min(1, width / height / ratio);
    editor.camera.aspect = width / height;
    editor.camera.zoom = this.outputZoom * zoom;
    editor.camera.updateProjectionMatrix();
    editor.renderer.setSize(width, height);
    this.outputFrame.style.width = `${height * zoom * ratio}px`;
    this.outputFrame.style.height = `${height * zoom}px`;
    this.outputFrame.setAttribute("aria-label", `출력에 반영되는 포즈 범위 ${outputWidth} × ${outputHeight}`);
    this.outputLabel.textContent = `출력 범위 · ${outputWidth} × ${outputHeight}`;
  }

  withOutputAspect(action) {
    const editor = this.editor, aspect = editor.camera.aspect, zoom = editor.camera.zoom;
    editor.camera.aspect = editor.widget("width").value / editor.widget("height").value;
    editor.camera.zoom = this.outputZoom;
    editor.camera.updateProjectionMatrix();
    try { return action(); }
    finally {
      editor.camera.aspect = aspect;
      editor.camera.zoom = zoom;
      editor.camera.updateProjectionMatrix();
    }
  }

  refresh() {
    const editor = this.editor, locked = !!this.busy || editor.loading;
    filterPoseMarkers(editor);
    const options = [["", "장면 전체 (선택 해제)"], ...editor.bodies.map((body, index) =>
      [body.id, `인물 ${index + 1} · ${body.gender === "female" ? "여성" : "남성"}`])];
    const optionsKey = JSON.stringify(options);
    if (optionsKey !== this.bodyOptionsKey) {
      this.bodySelect.replaceChildren(...options.map(([id, label]) => {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = label;
        return option;
      }));
      this.bodyOptionsKey = optionsKey;
    }
    this.bodySelect.value = editor.selectedBody?.id ?? "";
    this.bodySelect.disabled = locked || !editor.bodies.length;
    this.presetSelect.disabled = locked || !editor.selectedBody;
    this.sensitivityInput.disabled = locked;
    for (const button of this.bodyButtons) {
      button.disabled = locked || (!("addBody" in button.dataset) && !editor.selectedBody);
      if (button.dataset.bodyModel) {
        button.setAttribute("aria-pressed",
          String(button.dataset.bodyModel === editor.selectedBody?.gender));
      }
    }
    this.syncParameters();
  }

  syncParameters() {
    const shape = this.editor.selectedBody?.shapeControl;
    if (this.parameterControl !== shape) {
      this.restoreParameters();
      this.parameterControl = shape;
      this.parameterExpanded = shape?.parametersExpanded;
      this.parameterSlot.replaceChildren();
      if (shape) this.parameterSlot.append(shape.inspector);
    }
    this.parameters.hidden = !shape;
    if (shape) shape.setExpanded(this.parameters.open);
  }

  restoreParameters() {
    const shape = this.parameterControl;
    if (!shape) return;
    shape.entry.append(shape.inspector);
    shape.setExpanded(this.parameterExpanded);
  }

  selectBody(id) {
    const editor = this.editor;
    if (this.busy || editor.loading || editor.gizmo.dragging) return;
    this.finishWheel();
    const body = editor.bodies.find(item => item.id === id);
    editor.record();
    if (body) {
      editor.activateBody(body);
      editor.selectObject(body.rootControl);
      editor.commit();
    } else {
      editor.selectScene();
    }
    editor.record();
  }

  async addBody() {
    const editor = this.editor;
    editor.record();
    const history = editor.history.slice();
    editor.ready = editor.addBody();
    if (!await editor.ready) return;
    editor.setBodyColor(distinctBodyColor(editor.bodies
      .filter(body => body !== editor.selectedBody).map(body => body.material.color)));
    this.setView("front");
    editor.history = history;
    editor.record();
  }

  turnWheel(event) {
    const editor = this.editor, body = editor.selectedBody;
    if (this.busy || editor.loading || editor.gizmo.dragging || !body) return;
    const hit = editor.pickObjectAt(event.clientX, event.clientY);
    const chain = hit?.userData.chain;
    const pole = chain && hit.userData.kind === "pole";
    const object = chain ? pole ? hit : body.bones[chain.ids[2]] : hit;
    if (!pole && !body.bones.includes(object)) return;
    const delta = event.deltaY || event.deltaX;
    if (!delta) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (this.wheelObject !== object) this.finishWheel();
    if (!this.wheelObject) { editor.record(); this.wheelObject = object; }
    const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE
      ? Number.parseFloat(getComputedStyle(event.currentTarget).lineHeight)
      : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? editor.renderer.domElement.clientHeight : 1;
    const angle = T.MathUtils.degToRad(delta * unit * 0.05);
    editor.selectObject(object);
    if (pole) {
      const [start, , end] = editor.chainFrame(chain).points;
      const axis = end.clone().sub(start).normalize();
      object.position.sub(start).applyAxisAngle(axis, angle).add(start);
    } else {
      const cached = !event.shiftKey && !event.altKey && this.wheelAxes.get(object);
      let axis;
      if (cached) {
        axis = cached.clone();
      } else {
        axis = new T.Vector3(event.shiftKey ? 1 : 0, event.shiftKey || event.altKey ? 0 : 1,
          event.shiftKey ? 0 : event.altKey ? 1 : 0)
          .applyQuaternion(body.rootControl.getWorldQuaternion(new T.Quaternion()));
        const limb = body.chains.find(item => item.ids.includes(body.bones.indexOf(object)));
        if (!event.shiftKey && !event.altKey) {
          if (limb && object === body.bones[limb.ids[1]]) {
            const [start, , end] = editor.chainFrame(limb).points;
            axis = limb.pole.position.clone().sub(start).cross(end.clone().sub(start)).normalize()
              .applyQuaternion(body.handles.getWorldQuaternion(new T.Quaternion()));
          } else if (limb?.name.endsWith("arm") && object === body.bones[limb.ids[2]]) {
            const prefix = body.source === "MHR"
              ? limb.name.startsWith("Left") ? "l_" : "r_"
              : limb.name.startsWith("Left") ? "left_" : "right_";
            axis = body.bones.find(bone => bone.name === prefix + "middle1")
              .getWorldPosition(point()).sub(object.getWorldPosition(point())).normalize();
          }
        }
        axis.applyQuaternion(object.parent.getWorldQuaternion(new T.Quaternion()).invert());
        if (!event.shiftKey && !event.altKey && limb && object === body.bones[limb.ids[1]]) {
          // Preserve the signed hinge axis across straight/folded poses. Native
          // dragging, body activation and loads invalidate this parent-space axis.
          this.wheelAxes.set(object, axis.clone());
        }
      }
      object.quaternion.premultiply(new T.Quaternion().setFromAxisAngle(axis, angle));
      editor.gizmo.setMode("rotate");
    }
    editor.onTransformChange();
    editor.updateMarkers();
    clearTimeout(this.wheelTimer);
    this.wheelTimer = setTimeout(() => this.finishWheel(), 200);
  }

  finishWheel() {
    clearTimeout(this.wheelTimer);
    if (!this.wheelObject) return;
    this.wheelObject = null;
    this.editor.record();
  }

  setView(view) {
    this.finishWheel();
    const editor = this.editor;
    if (!editor.bodies.length) return;
    editor.record();
    editor.updateAllMarkers();
    const bounds = new T.Box3().setFromPoints(
      editor.bodies.flatMap(body => body.bones.map(bone => bone.getWorldPosition(point()))));
    const center = bounds.getCenter(point()), size = bounds.getSize(point());
    const tangent = Math.tan(T.MathUtils.degToRad(editor.camera.fov / 2));
    const width = view === "side" ? size.z : size.x;
    const distance = Math.max(size.y / 2 / tangent, width / 2 / tangent / editor.camera.aspect)
      * 1.2 + (view === "side" ? size.x : size.z) / 2;
    editor.orbit.target.copy(center);
    editor.camera.position.copy(center).addScaledVector(
      view === "side" ? new T.Vector3(1, 0, 0) : new T.Vector3(0, 0, 1), distance);
    editor.orbit.update();
    editor.commit();
    editor.record();
  }

  async setBodyModel(gender) {
    let shape;
    if (gender === "female") {
      const response = await fetch(new URL("./pose-presets/female-shape-preset.json", import.meta.url));
      if (!response.ok) throw Error("여성 모델 체형을 불러오지 못했습니다.");
      shape = await response.json();
      if (!validMHRShape(shape)) throw Error("여성 모델 체형 형식이 올바르지 않습니다.");
    }
    const selected = this.editor.selectedBody;
    if (!selected) return;
    const others = this.editor.bodies.filter(body => body !== selected);
    const femaleColor = gender === "female" ? distinctBodyColor(
      others.map(body => body.material.color),
      others.some(body => body.gender === "female")
        ? `#${selected.material.color.getHexString()}` : "#f4b6c2",
    ) : undefined;
    await applyBodyModel(this.editor, gender, shape, femaleColor);
  }

  async applyPreset(preset) {
    const definition = BASIC_POSE_PRESETS.find(item => item.id === preset);
    if (!definition) throw Error("지원하지 않는 기본 자세입니다.");
    const editor = this.editor, original = editor.bodySnapshot(editor.selectedBody);
    editor.record();
    const history = editor.history.slice();
    editor.reset();
    await editor.ready;
    const body = editor.selectedBody;
    body.rootControl.position.fromArray(original.root_transform.position);
    body.rootControl.quaternion.fromArray(original.root_transform.quaternion);
    body.rootControl.scale.fromArray(original.root_transform.scale);
    editor.updateMarkers();
    const legs = body.chains.filter(chain => chain.name.endsWith("leg"));
    const rotation = new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), definition.tilt ?? 0);
    const endRotations = new Map(body.chains.map(chain =>
      [chain, editor.rigRotation(body.bones[chain.ids[2]])]));
    const handOffsets = new Map(body.chains.filter(chain => chain.name.endsWith("arm")).map(chain =>
      [chain, editor.rigRotation(body.bones[chain.ids[1]]).invert().multiply(endRotations.get(chain))]));
    if (definition.height !== undefined) {
      const pelvis = body.pelvisBone;
      const local = body.rootControl.worldToLocal(pelvis.getWorldPosition(point()));
      local.y = (legs[0].lengths[0] + legs[0].lengths[1]) * definition.height;
      pelvis.position.copy(pelvis.parent.worldToLocal(body.rootControl.localToWorld(local)));
    }
    const parentRotation = editor.rigRotation(body.pelvisBone.parent);
    body.pelvisBone.quaternion.premultiply(parentRotation.clone().invert().multiply(rotation).multiply(parentRotation));
    editor.updateMarkers();
    for (const chain of body.chains) {
      editor.syncFKChain(chain, true);
      const start = editor.chainFrame(chain).points[0];
      const length = chain.lengths[0] + chain.lengths[1];
      const arm = chain.name.endsWith("arm"), offset = arm ? definition.arms : definition.legs;
      if (offset) chain.target.position.copy(start).add(new T.Vector3(
        Math.sign(start.x) * offset[0], offset[1], offset[2]).multiplyScalar(length).applyQuaternion(rotation));
      if (!arm && definition.pole) {
        chain.pole.position.copy(start).add(new T.Vector3(...definition.pole).multiplyScalar(length));
      }
    }
    editor.refreshChainLengths();
    editor.solveIK();
    editor.updateMarkers();
    for (const chain of body.chains) {
      const end = body.bones[chain.ids[2]];
      const desired = chain.name.endsWith("arm")
        ? editor.rigRotation(body.bones[chain.ids[1]]).multiply(handOffsets.get(chain))
        : rotation.clone().multiply(new T.Quaternion().setFromAxisAngle(
          new T.Vector3(1, 0, 0), definition.footTilt ?? 0)).multiply(endRotations.get(chain));
      end.quaternion.copy(editor.rigRotation(end.parent).invert().multiply(desired));
    }
    editor.updateMarkers();
    if (definition.grounded) {
      // Measure the posed surface, not rest-pose bounds or controller markers.
      const inverseRoot = body.rootControl.matrixWorld.clone().invert();
      const vertex = point();
      let floor = Infinity;
      body.bodyRoot.traverse(mesh => {
        if (!mesh.isMesh) return;
        if (mesh.isSkinnedMesh) mesh.skeleton.update();
        const matrix = inverseRoot.clone().multiply(mesh.matrixWorld);
        for (let index = 0; index < mesh.geometry.attributes.position.count; index++) {
          floor = Math.min(floor, mesh.getVertexPosition(index, vertex).applyMatrix4(matrix).y);
        }
      });
      const pelvis = body.pelvisBone;
      const local = body.rootControl.worldToLocal(pelvis.getWorldPosition(point()));
      local.y -= floor;
      pelvis.position.copy(pelvis.parent.worldToLocal(body.rootControl.localToWorld(local)));
      editor.updateMarkers();
    }
    for (const chain of body.chains) editor.syncFKChain(chain, true);
    editor.history = history;
    editor.commit();
    editor.record();
  }

  async run(action) {
    if (this.busy || this.editor.loading) return;
    this.finishWheel();
    this.busy = true;
    this.editor.root.inert = true;
    this.refresh();
    try { await action(); }
    catch (error) { this.status.textContent = `포즈 편집 실패: ${error.message}`; }
    finally {
      this.editor.root.inert = false;
      this.busy = false;
      this.refresh();
    }
  }

  beforeCapture() {
    this.finishWheel();
    if (this.busy || this.editor.loading || this.editor.gizmo.dragging) {
      throw Object.assign(Error("편집을 마친 뒤 다시 시도해 주세요."), { code: "DEKIS_POSE_BUSY" });
    }
  }

  dispose() {
    this.finishWheel();
    this.abort.abort();
    this.editor.updateControllerVisibility = this.originalVisibility;
    this.editor.updateGetPoseButton = this.originalReadiness;
    this.editor.onTransformChange = this.originalTransform;
    for (const [method, original] of this.originalDisplaySetters) this.editor[method] = original;
    this.editor.gizmo.removeEventListener("mouseDown", this.onDragStart);
    this.editor.gizmo.removeEventListener("mouseUp", this.onDragEnd);
    this.editor.root.classList.remove("precision-pose-editor");
    this.editor.bar.classList.remove("precision-pose-toolbar");
    this.editor.workspace.classList.remove("precision-pose-workspace");
    this.editor.note.classList.remove("precision-pose-note");
    this.editor.modelTree.root.classList.remove("precision-pose-models");
    this.restoreParameters();
    this.controls.before(this.editor.bar);
    this.editor.view.prepend(this.editor.transformBar);
    this.editor.transformBar.classList.remove("precision-pose-transform-tools");
    this.editor.transformBar.setAttribute("aria-orientation", "vertical");
    this.editor.view.append(this.editor.lightControl.root);
    this.editor.lightControl.root.classList.remove("precision-pose-light");
    this.outputFrame.remove();
    this.outputLabel.remove();
    this.help.remove();
    this.editor.camera.zoom = this.outputZoom;
    this.editor.camera.updateProjectionMatrix();
    this.editor.resize = this.originalResize;
    this.editor.capture = this.originalCapture;
    this.editor.captureRegionPainter = this.originalRegionCapture;
    this.editor.info.hidden = this.originalInfoHidden;
    this.controls.remove();
  }
}
