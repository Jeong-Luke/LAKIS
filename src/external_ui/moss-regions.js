(() => {
  "use strict";

  const root = document.querySelector("#mossRegionPanel");
  const imageWidthInput = document.querySelector("#imageWidth");
  const imageHeightInput = document.querySelector("#imageHeight");
  const MAX_REGIONS = 16;
  const MAX_TEXT_LENGTH = 2000;
  const LABELS = {
    object: "오브젝트",
    character: "인물",
    text: "텍스트",
  };
  const COLORS = {
    object: "#70c8ff",
    character: "#70d69a",
    text: "#e6bd72",
  };
  const KNOWN_REGION_FIELDS = new Set(["id", "label", "caption", "negative_prompt", "text", "bbox"]);
  const KNOWN_STATE_FIELDS = new Set(["enabled", "regions"]);

  let enabled = false;
  let regions = [];
  let unknownStateFields = {};
  let selectedId = null;
  let nextId = 0;
  let gesture = null;
  let tool = "select";
  let outputWidth = 1536;
  let outputHeight = 1024;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function cloneValue(value, seen = new WeakMap()) {
    if (value === null || typeof value !== "object") return value;
    if (seen.has(value)) return seen.get(value);

    const copy = Array.isArray(value)
      ? []
      : Object.create(Object.getPrototypeOf(value) === null ? null : Object.prototype);
    seen.set(value, copy);
    for (const key of Object.keys(value)) {
      Object.defineProperty(copy, key, {
        value: cloneValue(value[key], seen),
        enumerable: true,
        configurable: true,
        writable: true,
      });
    }
    return copy;
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function copyUnknownFields(source, knownFields) {
    const copy = {};
    if (!isRecord(source)) return copy;
    for (const key of Object.keys(source)) {
      if (knownFields.has(key)) continue;
      Object.defineProperty(copy, key, {
        value: cloneValue(source[key]),
        enumerable: true,
        configurable: true,
        writable: true,
      });
    }
    return copy;
  }

  function makeId() {
    let id;
    do {
      nextId += 1;
      id = `moss-region-${Date.now().toString(36)}-${nextId.toString(36)}`;
    } while (regions.some(region => region.id === id));
    return id;
  }

  function clampCoordinate(value) {
    return Math.max(0, Math.min(1000, Math.round(value)));
  }

  function positiveBox(x0, y0, x1, y1) {
    let left = Math.min(clampCoordinate(x0), clampCoordinate(x1));
    let top = Math.min(clampCoordinate(y0), clampCoordinate(y1));
    let right = Math.max(clampCoordinate(x0), clampCoordinate(x1));
    let bottom = Math.max(clampCoordinate(y0), clampCoordinate(y1));
    if (left === right) {
      if (right < 1000) right += 1;
      else left -= 1;
    }
    if (top === bottom) {
      if (bottom < 1000) bottom += 1;
      else top -= 1;
    }
    return [left, top, right, bottom];
  }

  function normalizeBbox(value) {
    if (!Array.isArray(value) || value.length < 4) return [200, 200, 800, 800];
    const coords = value.slice(0, 4).map(Number);
    if (!coords.every(Number.isFinite)) return [200, 200, 800, 800];
    return positiveBox(...coords);
  }

  function normalizeText(value) {
    if (typeof value === "string") return value.slice(0, MAX_TEXT_LENGTH);
    if (value === null || value === undefined) return "";
    return String(value).slice(0, MAX_TEXT_LENGTH);
  }

  function normalizeRegion(source, usedIds) {
    const extras = copyUnknownFields(source, KNOWN_REGION_FIELDS);
    const candidateId = typeof source?.id === "string" && source.id.length > 0
      ? source.id
      : makeId();
    const id = usedIds.has(candidateId) ? makeId() : candidateId;
    usedIds.add(id);
    const region = cloneValue(extras);
    region.id = id;
    region.label = Object.hasOwn(LABELS, source?.label) ? source.label : "object";
    region.caption = normalizeText(source?.caption);
    region.negative_prompt = normalizeText(source?.negative_prompt);
    region.text = normalizeText(source?.text);
    region.bbox = normalizeBbox(source?.bbox);
    return region;
  }

  function selectedRegion() {
    return regions.find(region => region.id === selectedId) || null;
  }

  function makeRegion(bbox) {
    return {
      id: makeId(),
      label: "object",
      caption: "",
      negative_prompt: "",
      text: "",
      bbox: bbox.slice(),
    };
  }

  const cardHeading = element("div", "panel-heading moss-region-card-heading");
  cardHeading.append(element("h2", "section-title-accent", "MOSS 영역 프롬프트"));
  const cardEnableLabel = element("div", "moss-region-enable");
  const cardEnableSwitch = element("button", "lora-switch");
  cardEnableSwitch.type = "button";
  cardEnableSwitch.setAttribute("role", "switch");
  cardEnableSwitch.setAttribute("aria-label", "MOSS 영역 프롬프트 사용");
  cardEnableLabel.append(cardEnableSwitch);
  cardHeading.append(cardEnableLabel);
  const overviewButton = element("button", "moss-region-overview-button");
  overviewButton.type = "button";
  overviewButton.setAttribute("aria-label", "영역 배치 미리보기 · 편집 창 열기");
  const overview = element("span", "moss-region-overview");
  overview.setAttribute("aria-hidden", "true");
  overviewButton.append(overview);
  const summary = element("span", "moss-region-summary");
  overviewButton.append(summary);
  const openButton = element("button", "mini-button moss-region-open", "편집");
  openButton.type = "button";
  openButton.setAttribute("aria-haspopup", "dialog");
  openButton.setAttribute("aria-controls", "mossRegionEditor");
  cardEnableLabel.append(openButton);
  root.replaceChildren(cardHeading, overviewButton);

  const dialog = element("dialog", "moss-region-panel moss-region-dialog");
  dialog.id = "mossRegionEditor";
  dialog.setAttribute("aria-labelledby", "mossRegionEditorTitle");
  const heading = element("header", "moss-region-heading");
  const headingText = element("div", "moss-region-heading-copy");
  const title = element("h2", "section-title-accent", "MOSS 영역 프롬프트");
  title.id = "mossRegionEditorTitle";
  headingText.append(
    title,
    element("p", "moss-region-hint", "인물·오브젝트·텍스트의 위치와 설명을 지정하세요. 정확한 위치를 보장하는 마스크가 아닌 배치 힌트입니다."),
  );
  const enableLabel = element("div", "moss-region-enable");
  const enableSwitch = element("button", "lora-switch");
  enableSwitch.type = "button";
  enableSwitch.setAttribute("role", "switch");
  enableSwitch.setAttribute("aria-label", "편집 창 영역 프롬프트 사용");
  const enableText = element("span", "", "영역 프롬프트 사용");
  enableLabel.append(enableText, enableSwitch);
  const closeButton = element("button", "moss-region-close", "×");
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "MOSS 영역 편집기 닫기");
  heading.append(headingText, enableLabel, closeButton);

  const toolbar = element("div", "moss-region-toolbar");
  const tools = element("div", "moss-region-tools");
  tools.setAttribute("role", "group");
  tools.setAttribute("aria-label", "영역 편집 도구");
  const selectTool = element("button", "moss-region-button", "선택·이동");
  const drawTool = element("button", "moss-region-button", "영역 그리기");
  selectTool.type = drawTool.type = "button";
  tools.append(selectTool, drawTool);
  const addButton = element("button", "moss-region-button moss-region-add", "+ 영역 추가");
  addButton.type = "button";
  const deleteButton = element("button", "moss-region-button");
  deleteButton.type = "button";
  deleteButton.textContent = "선택 삭제";
  const clearButton = element("button", "moss-region-button moss-region-clear");
  clearButton.type = "button";
  clearButton.textContent = "전체 지우기";
  const status = element("p", "moss-region-status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  toolbar.append(tools, addButton, deleteButton, clearButton, status);

  const workspace = element("div", "moss-region-workspace");
  const canvasColumn = element("div", "moss-region-canvas-column");
  const canvasFrame = element("div", "moss-region-canvas-frame");
  const outputFrame = element("div", "moss-region-output-frame");
  const outputLabel = element("span", "moss-region-output-label");
  outputLabel.id = "moss-region-output-label";
  const canvas = element("canvas", "moss-region-canvas");
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "출력 비율 영역 편집 캔버스");
  const canvasHelp = element("p", "moss-region-help", "출력 테두리 안에 영역을 배치하세요. ‘영역 그리기’로 추가 · ‘선택·이동’으로 배치 · 손잡이로 크기 조절");
  canvasHelp.id = "moss-region-canvas-help";
  canvas.setAttribute("aria-describedby", `${outputLabel.id} ${canvasHelp.id}`);
  outputFrame.append(canvas, outputLabel);
  canvasFrame.append(outputFrame);

  const listSection = element("div", "moss-region-list-section");
  listSection.append(element("h3", "moss-region-subheading", "등록된 영역"));
  const regionList = element("div", "moss-region-list");
  regionList.setAttribute("role", "group");
  regionList.setAttribute("aria-label", "MOSS 영역 선택");
  listSection.append(regionList);
  canvasColumn.append(canvasFrame, canvasHelp);

  const editor = element("div", "moss-region-editor");
  const editorTitle = element("h3", "moss-region-subheading", "영역 설정");
  editor.append(editorTitle);
  const emptyEditor = element("p", "moss-region-empty", "‘영역 그리기’ 또는 ‘영역 추가’로 시작하세요. 등록된 영역을 선택하면 프롬프트를 수정할 수 있습니다.");
  const editorFields = element("fieldset", "moss-region-fields");
  editorFields.disabled = true;
  editorFields.append(element("legend", "", "선택한 영역"));

  const typeLabel = element("label", "moss-region-field", "영역 종류");
  const typeSelect = element("select");
  for (const [value, label] of Object.entries(LABELS)) {
    const option = element("option", "", label);
    option.value = value;
    typeSelect.append(option);
  }
  typeLabel.append(typeSelect);

  const captionLabel = element("label", "moss-region-field", "영역 프롬프트");
  const captionInput = element("textarea");
  captionInput.id = "mossRegionCaptionInput";
  captionInput.rows = 4;
  captionInput.placeholder = "예: 창가에 앉아 있는 인물, 붉은 도자기 컵";
  captionInput.maxLength = MAX_TEXT_LENGTH;
  captionInput.setAttribute("aria-label", "선택한 영역의 프롬프트");
  const captionCount = element("span", "moss-region-char-count", `0 / ${MAX_TEXT_LENGTH}`);
  captionLabel.append(captionInput, captionCount);

  const exactTextLabel = element("label", "moss-region-field moss-region-exact-text");
  exactTextLabel.append(element("span", "", "이미지에 표시할 정확한 문구"));
  const exactTextInput = element("textarea");
  exactTextInput.rows = 3;
  exactTextInput.placeholder = "이미지에 표시할 문구를 그대로 입력하세요.";
  exactTextInput.maxLength = MAX_TEXT_LENGTH;
  exactTextInput.setAttribute("aria-label", "텍스트 영역에 표시할 정확한 문구");
  const exactTextCount = element("span", "moss-region-char-count", `0 / ${MAX_TEXT_LENGTH}`);
  exactTextLabel.append(exactTextInput, exactTextCount);

  const negativeLabel = element("label", "moss-region-field", "부정 프롬프트");
  const negativeInput = element("textarea");
  negativeInput.id = "mossRegionNegativeInput";
  negativeInput.rows = 4;
  negativeInput.placeholder = "이 영역에서 제외할 요소를 입력하세요.";
  negativeInput.maxLength = MAX_TEXT_LENGTH;
  negativeInput.setAttribute("aria-label", "선택한 영역의 부정 프롬프트");
  const negativeCount = element("span", "moss-region-char-count", `0 / ${MAX_TEXT_LENGTH}`);
  negativeLabel.append(negativeInput, negativeCount);

  const coordinates = element("fieldset", "moss-region-coordinates");
  coordinates.hidden = true;
  coordinates.append(element("legend", "", "정규화 좌표 (0–1000)"));
  const coordinateInputs = {};
  for (const [key, title, description] of [
    ["x0", "왼쪽 X", "왼쪽 X 좌표"],
    ["y0", "위쪽 Y", "위쪽 Y 좌표"],
    ["x1", "오른쪽 X", "오른쪽 X 좌표"],
    ["y1", "아래쪽 Y", "아래쪽 Y 좌표"],
  ]) {
    const label = element("label", "moss-region-coordinate");
    label.append(element("span", "", title));
    const input = element("input");
    input.type = "number";
    input.min = "0";
    input.max = "1000";
    input.step = "1";
    input.inputMode = "numeric";
    input.setAttribute("aria-label", description);
    coordinateInputs[key] = input;
    label.append(input);
    coordinates.append(label);
  }

  editorFields.append(typeLabel, captionLabel, exactTextLabel, negativeLabel, coordinates);
  editor.append(emptyEditor, editorFields);
  const sidebar = element("aside", "moss-region-sidebar");
  sidebar.append(listSection, editor);
  workspace.append(canvasColumn, sidebar);
  const footer = element("footer", "moss-region-footer");
  const doneButton = element("button", "moss-region-button moss-region-done", "완료");
  doneButton.type = "button";
  footer.append(element("p", "moss-region-help", "변경 내용은 생성 설정에 자동 반영됩니다. 닫아도 편집 내용은 유지됩니다."), doneButton);
  dialog.append(heading, toolbar, workspace, footer);
  document.body.append(dialog);

  const context = canvas.getContext("2d");

  function emitChange() {
    window.dispatchEvent(new CustomEvent("lakis:moss-regions-change"));
  }

  function setStatus() {
    const selected = selectedRegion();
    const selectedIndex = selected ? regions.indexOf(selected) + 1 : 0;
    status.textContent = selected
      ? `${regions.length} / ${MAX_REGIONS}개 영역 · ${selectedIndex}번 선택됨`
      : `${regions.length} / ${MAX_REGIONS}개 영역`;
    addButton.disabled = regions.length >= MAX_REGIONS;
    deleteButton.disabled = !selected;
    clearButton.disabled = regions.length === 0;
    selectTool.setAttribute("aria-pressed", String(tool === "select"));
    drawTool.setAttribute("aria-pressed", String(tool === "draw"));
    canvas.style.cursor = tool === "draw" ? "crosshair" : "default";
    editorTitle.textContent = selected ? `${selectedIndex}번 영역 · ${LABELS[selected.label]}` : "영역 설정";
    canvas.setAttribute(
      "aria-label",
      `출력 비율 영역 편집 캔버스. 영역 ${regions.length}개${selected ? `, ${selectedIndex}번 선택됨` : ""}. ${tool === "draw" ? "영역 그리기" : "선택·이동"} 도구.`,
    );
  }

  function renderOverview() {
    summary.textContent = `영역 ${regions.length}개 · ${outputWidth} × ${outputHeight}`;
    root.style.setProperty("--moss-output-ratio", String(outputWidth / outputHeight));
    overview.style.aspectRatio = `${outputWidth} / ${outputHeight}`;
    overview.style.width = `min(100%, ${150 * outputWidth / outputHeight}px)`;
    overview.replaceChildren();
    if (!regions.length) overview.append(element("span", "moss-region-overview-empty", "+ 영역 설정"));
    regions.forEach((region, index) => {
      const box = element("span", "moss-region-overview-box", String(index + 1));
      const [x0, y0, x1, y1] = region.bbox;
      Object.assign(box.style, {
        left: `${x0 / 10}%`, top: `${y0 / 10}%`,
        width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%`,
        color: COLORS[region.label],
      });
      overview.append(box);
    });
  }

  function renderRegionList() {
    regionList.replaceChildren();
    regions.forEach((region, index) => {
      const item = element("div", "moss-region-list-item");
      const button = element(
        "button",
        "moss-region-list-button",
        `${index + 1}. ${LABELS[region.label]}`,
      );
      button.type = "button";
      button.title = region.caption || LABELS[region.label];
      button.style.setProperty("--region-color", COLORS[region.label]);
      button.setAttribute("aria-pressed", String(region.id === selectedId));
      button.setAttribute("aria-label", `${index + 1}번 ${LABELS[region.label]} 영역 선택`);
      button.addEventListener("click", () => {
        selectedId = region.id;
        renderAll();
      });
      item.append(button);
      regionList.append(item);
    });
  }

  function syncEditor() {
    const region = selectedRegion();
    editorFields.disabled = !region;
    editorFields.hidden = !region;
    emptyEditor.hidden = Boolean(region);
    if (!region) return;
    typeSelect.value = region.label;
    captionInput.value = region.caption;
    negativeInput.value = region.negative_prompt;
    exactTextInput.value = region.text;
    for (const input of [captionInput, negativeInput]) input.dispatchEvent(new Event("change"));
    captionCount.textContent = `${region.caption.length} / ${MAX_TEXT_LENGTH}`;
    negativeCount.textContent = `${region.negative_prompt.length} / ${MAX_TEXT_LENGTH}`;
    exactTextCount.textContent = `${region.text.length} / ${MAX_TEXT_LENGTH}`;
    exactTextLabel.hidden = region.label !== "text";
    for (const key of ["x0", "y0", "x1", "y1"]) {
      coordinateInputs[key].value = String(region.bbox[["x0", "y0", "x1", "y1"].indexOf(key)]);
    }
  }

  function renderAll() {
    for (const toggle of [cardEnableSwitch, enableSwitch]) {
      toggle.classList.toggle("on", enabled);
      toggle.setAttribute("aria-checked", String(enabled));
    }
    root.classList.toggle("is-enabled", enabled);
    renderRegionList();
    syncEditor();
    setStatus();
    renderOverview();
    drawCanvas();
  }

  function fitCanvas() {
    if (!dialog.open) return;
    const gutter = 16;
    const scale = Math.min(
      (canvasFrame.clientWidth - gutter * 2) / outputWidth,
      (canvasFrame.clientHeight - gutter * 2) / outputHeight,
    );
    if (scale <= 0) return;
    canvas.style.width = `${outputWidth * scale}px`;
    canvas.style.height = `${outputHeight * scale}px`;
    drawCanvas();
  }

  function openEditor() {
    if (root.hidden || dialog.open) return;
    tool = regions.length ? "select" : "draw";
    updateAspectRatio();
    renderAll();
    dialog.showModal();
    requestAnimationFrame(() => {
      fitCanvas();
      canvas.focus({ preventScroll: true });
    });
  }

  function closeEditor() {
    if (dialog.open) dialog.close();
  }

  openButton.addEventListener("click", openEditor);
  overviewButton.addEventListener("click", openEditor);
  closeButton.addEventListener("click", closeEditor);
  doneButton.addEventListener("click", closeEditor);
  dialog.addEventListener("close", () => {
    if (gesture) {
      if (gesture.mode !== "draw") gesture.region.bbox = gesture.original.slice();
      if (canvas.hasPointerCapture(gesture.pointerId)) canvas.releasePointerCapture(gesture.pointerId);
      gesture = null;
    }
    renderAll();
    if (!root.hidden) openButton.focus();
  });
  selectTool.addEventListener("click", () => { tool = "select"; setStatus(); });
  drawTool.addEventListener("click", () => { tool = "draw"; setStatus(); });
  new ResizeObserver(fitCanvas).observe(canvasFrame);

  function getCanvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return {
      x: clampCoordinate((event.clientX - rect.left) / rect.width * 1000),
      y: clampCoordinate((event.clientY - rect.top) / rect.height * 1000),
      rect,
    };
  }

  function boxPoints(bbox) {
    const [x0, y0, x1, y1] = bbox;
    return [
      ["nw", x0, y0],
      ["n", (x0 + x1) / 2, y0],
      ["ne", x1, y0],
      ["e", x1, (y0 + y1) / 2],
      ["se", x1, y1],
      ["s", (x0 + x1) / 2, y1],
      ["sw", x0, y1],
      ["w", x0, (y0 + y1) / 2],
    ];
  }

  function hitHandle(point, region) {
    const toleranceX = 14 / point.rect.width * 1000;
    const toleranceY = 14 / point.rect.height * 1000;
    for (const [name, x, y] of boxPoints(region.bbox)) {
      if (Math.abs(point.x - x) <= toleranceX && Math.abs(point.y - y) <= toleranceY) {
        return name;
      }
    }
    return null;
  }

  function hitRegion(point) {
    for (let index = regions.length - 1; index >= 0; index -= 1) {
      const [x0, y0, x1, y1] = regions[index].bbox;
      if (point.x >= x0 && point.x <= x1 && point.y >= y0 && point.y <= y1) {
        return regions[index];
      }
    }
    return null;
  }

  function resizeBox(original, handle, point) {
    let [x0, y0, x1, y1] = original;
    if (handle.includes("w")) x0 = Math.min(point.x, x1 - 1);
    if (handle.includes("e")) x1 = Math.max(point.x, x0 + 1);
    if (handle.includes("n")) y0 = Math.min(point.y, y1 - 1);
    if (handle.includes("s")) y1 = Math.max(point.y, y0 + 1);
    return [x0, y0, x1, y1];
  }

  function updateGesture(point) {
    if (!gesture || !point) return;
    if (gesture.mode === "draw") {
      gesture.preview = positiveBox(gesture.start.x, gesture.start.y, point.x, point.y);
    } else if (gesture.mode === "move") {
      const width = gesture.original[2] - gesture.original[0];
      const height = gesture.original[3] - gesture.original[1];
      const dx = point.x - gesture.start.x;
      const dy = point.y - gesture.start.y;
      const x0 = Math.max(0, Math.min(1000 - width, Math.round(gesture.original[0] + dx)));
      const y0 = Math.max(0, Math.min(1000 - height, Math.round(gesture.original[1] + dy)));
      gesture.region.bbox = [x0, y0, x0 + width, y0 + height];
    } else if (gesture.mode === "resize") {
      gesture.region.bbox = resizeBox(gesture.original, gesture.handle, point);
    }
    drawCanvas();
  }

  function drawCanvas() {
    if (!context || canvas.width === 0 || canvas.height === 0) return;
    const width = canvas.width;
    const height = canvas.height;
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#11151b";
    context.fillRect(0, 0, width, height);

    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width > 0 ? width / rect.width : 1;
    const scaleY = rect.height > 0 ? height / rect.height : 1;
    const lineScale = Math.max(0.75, Math.min(scaleX, scaleY));
    const drawRegion = (region, index, selected, preview = false) => {
      const [x0, y0, x1, y1] = region.bbox;
      const left = x0 / 1000 * width;
      const top = y0 / 1000 * height;
      const boxWidth = (x1 - x0) / 1000 * width;
      const boxHeight = (y1 - y0) / 1000 * height;
      const color = COLORS[region.label] || COLORS.object;
      context.save();
      context.globalAlpha = preview ? 0.78 : 1;
      context.fillStyle = color;
      context.globalAlpha *= 0.12;
      context.fillRect(left, top, boxWidth, boxHeight);
      context.globalAlpha = preview ? 0.78 : 1;
      context.strokeStyle = color;
      context.lineWidth = Math.max(1.5, (selected ? 2.5 : 1.8) * lineScale);
      context.setLineDash(preview ? [7 * lineScale, 5 * lineScale] : []);
      context.strokeRect(left, top, boxWidth, boxHeight);
      context.setLineDash([]);

      const fontSize = Math.max(10, Math.min(24, 13 * scaleX));
      context.font = `600 ${fontSize}px sans-serif`;
      const label = `${index + 1} · ${LABELS[region.label] || LABELS.object}`;
      const tagHeight = fontSize * 1.55;
      const tagWidth = context.measureText(label).width + fontSize;
      context.fillStyle = color;
      context.fillRect(left, Math.max(0, top - tagHeight), tagWidth, tagHeight);
      context.fillStyle = "#10151a";
      context.textBaseline = "middle";
      context.fillText(label, left + fontSize / 2, Math.max(0, top - tagHeight / 2));

      if (selected) {
        const handleWidth = Math.max(8, 9 * scaleX);
        const handleHeight = Math.max(8, 9 * scaleY);
        context.fillStyle = "#f5f8fb";
        context.strokeStyle = color;
        context.lineWidth = Math.max(1, lineScale);
        for (const [, x, y] of boxPoints(region.bbox)) {
          const px = x / 1000 * width;
          const py = y / 1000 * height;
          context.fillRect(px - handleWidth / 2, py - handleHeight / 2, handleWidth, handleHeight);
          context.strokeRect(px - handleWidth / 2, py - handleHeight / 2, handleWidth, handleHeight);
        }
      }
      context.restore();
    };

    regions.forEach((region, index) => {
      drawRegion(region, index, region.id === selectedId);
    });
    if (gesture?.mode === "draw" && gesture.preview) {
      drawRegion({ label: "object", bbox: gesture.preview }, regions.length, false, true);
    }
  }

  function updateAspectRatio() {
    const width = Number(imageWidthInput.value);
    const height = Number(imageHeightInput.value);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return;
    outputWidth = width;
    outputHeight = height;
    outputLabel.textContent = `출력 범위 · ${outputWidth} × ${outputHeight}`;
    canvas.style.aspectRatio = `${outputWidth} / ${outputHeight}`;
    const longestSide = 1400;
    if (outputWidth >= outputHeight) {
      canvas.width = longestSide;
      canvas.height = Math.max(1, Math.round(longestSide * outputHeight / outputWidth));
    } else {
      canvas.height = longestSide;
      canvas.width = Math.max(1, Math.round(longestSide * outputWidth / outputHeight));
    }
    fitCanvas();
    renderOverview();
    drawCanvas();
  }

  function addRegion(bbox) {
    if (regions.length >= MAX_REGIONS) return;
    const index = regions.length;
    let initialBox = bbox;
    if (!initialBox) {
      if (index === 0) {
        initialBox = [200, 200, 800, 800];
      } else {
        const slot = index - 1;
        const left = 80 + (slot % 3) * 200;
        const top = 80 + (Math.floor(slot / 3) % 3) * 200;
        initialBox = [left, top, left + 360, top + 360];
      }
    }
    const region = makeRegion(initialBox);
    regions.push(region);
    selectedId = region.id;
    tool = "select";
    renderAll();
    emitChange();
  }

  function commitCoordinate(key, input) {
    const region = selectedRegion();
    if (!region) return;
    const parsed = input.value.trim() === "" ? NaN : Number(input.value);
    if (!Number.isFinite(parsed)) {
      syncEditor();
      return;
    }
    const value = clampCoordinate(parsed);
    const [x0, y0, x1, y1] = region.bbox;
    if (key === "x0") region.bbox = [Math.min(value, x1 - 1), y0, x1, y1];
    else if (key === "x1") region.bbox = [x0, y0, Math.max(value, x0 + 1), y1];
    else if (key === "y0") region.bbox = [x0, Math.min(value, y1 - 1), x1, y1];
    else region.bbox = [x0, y0, x1, Math.max(value, y0 + 1)];
    renderAll();
    emitChange();
  }

  for (const toggle of [enableSwitch, cardEnableSwitch]) {
    toggle.addEventListener("click", () => {
      enabled = !enabled;
      renderAll();
      emitChange();
    });
  }

  addButton.addEventListener("click", () => addRegion());
  deleteButton.addEventListener("click", () => {
    const index = regions.findIndex(region => region.id === selectedId);
    if (index < 0) return;
    regions.splice(index, 1);
    selectedId = regions[Math.min(index, regions.length - 1)]?.id || null;
    renderAll();
    emitChange();
  });
  clearButton.addEventListener("click", () => {
    if (regions.length === 0) return;
    regions = [];
    selectedId = null;
    renderAll();
    emitChange();
  });

  typeSelect.addEventListener("change", () => {
    const region = selectedRegion();
    if (!region) return;
    region.label = Object.hasOwn(LABELS, typeSelect.value) ? typeSelect.value : "object";
    renderAll();
    emitChange();
  });

  captionInput.addEventListener("input", () => {
    const region = selectedRegion();
    if (!region) return;
    region.caption = captionInput.value.slice(0, MAX_TEXT_LENGTH);
    captionInput.value = region.caption;
    captionCount.textContent = `${region.caption.length} / ${MAX_TEXT_LENGTH}`;
    renderRegionList();
    emitChange();
  });
  exactTextInput.addEventListener("input", () => {
    const region = selectedRegion();
    if (!region) return;
    region.text = exactTextInput.value.slice(0, MAX_TEXT_LENGTH);
    exactTextInput.value = region.text;
    exactTextCount.textContent = `${region.text.length} / ${MAX_TEXT_LENGTH}`;
    emitChange();
  });

  negativeInput.addEventListener("input", () => {
    const region = selectedRegion();
    if (!region) return;
    region.negative_prompt = negativeInput.value.slice(0, MAX_TEXT_LENGTH);
    negativeInput.value = region.negative_prompt;
    negativeCount.textContent = `${region.negative_prompt.length} / ${MAX_TEXT_LENGTH}`;
    emitChange();
  });

  for (const [key, input] of Object.entries(coordinateInputs)) {
    input.addEventListener("change", () => commitCoordinate(key, input));
  }

  canvas.addEventListener("pointerdown", event => {
    if (event.button !== 0 && event.pointerType !== "touch") return;
    const point = getCanvasPoint(event);
    if (!point) return;

    const current = selectedRegion();
    const handle = tool === "select" && current ? hitHandle(point, current) : null;
    if (handle) {
      gesture = {
        mode: "resize",
        pointerId: event.pointerId,
        region: current,
        handle,
        start: point,
        original: current.bbox.slice(),
      };
    } else {
      const hit = tool === "select" ? hitRegion(point) : null;
      if (hit) {
        if (hit.id !== selectedId) {
          selectedId = hit.id;
          renderAll();
        }
        gesture = {
          mode: "move",
          pointerId: event.pointerId,
          region: hit,
          start: point,
          original: hit.bbox.slice(),
        };
      } else {
        if (tool === "select") {
          selectedId = null;
          renderAll();
          return;
        }
        if (regions.length >= MAX_REGIONS) {
          status.textContent = `최대 ${MAX_REGIONS}개까지 추가할 수 있습니다.`;
          return;
        }
        gesture = {
          mode: "draw",
          pointerId: event.pointerId,
          start: point,
          startClientX: event.clientX,
          startClientY: event.clientY,
          preview: positiveBox(point.x, point.y, point.x, point.y),
        };
      }
    }
    canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
    drawCanvas();
  });

  canvas.addEventListener("pointermove", event => {
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    updateGesture(getCanvasPoint(event));
  });

  canvas.addEventListener("pointerup", event => {
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const currentGesture = gesture;
    updateGesture(getCanvasPoint(event));
    gesture = null;
    if (currentGesture.mode === "draw") {
      const distance = Math.hypot(
        event.clientX - currentGesture.startClientX,
        event.clientY - currentGesture.startClientY,
      );
      if (distance >= 3 && currentGesture.preview) {
        addRegion(currentGesture.preview);
        return;
      }
    } else {
      const changed = currentGesture.region.bbox.some(
        (coordinate, index) => coordinate !== currentGesture.original[index],
      );
      if (changed) {
        renderAll();
        emitChange();
        return;
      }
    }
    drawCanvas();
  });

  canvas.addEventListener("pointercancel", event => {
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    if (gesture.mode !== "draw") gesture.region.bbox = gesture.original.slice();
    gesture = null;
    drawCanvas();
  });

  for (const input of [imageWidthInput, imageHeightInput]) {
    input.addEventListener("input", updateAspectRatio);
    input.addEventListener("change", updateAspectRatio);
  }
  window.addEventListener("resize", fitCanvas, { passive: true });

  function restore(saved) {
    const source = isRecord(saved) ? saved : {};
    unknownStateFields = copyUnknownFields(source, KNOWN_STATE_FIELDS);
    enabled = source.enabled === true;
    const usedIds = new Set();
    regions = Array.isArray(source.regions)
      ? source.regions.slice(0, MAX_REGIONS).map(region => {
          const normalized = normalizeRegion(region, usedIds);
          usedIds.add(normalized.id);
          return normalized;
        })
      : [];
    selectedId = regions[0]?.id || null;
    gesture = null;
    updateAspectRatio();
    renderAll();
  }

  function snapshot() {
    const result = cloneValue(unknownStateFields);
    result.enabled = enabled;
    result.regions = regions.map(region => {
      const copy = cloneValue(region);
      copy.id = region.id;
      copy.label = region.label;
      copy.caption = region.caption;
      copy.text = region.text;
      copy.bbox = region.bbox.slice();
      return copy;
    });
    return result;
  }

  updateAspectRatio();
  renderAll();
  window.LAKISMossRegions = { restore, snapshot, close: closeEditor };
})();
