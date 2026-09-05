import { app } from "../../scripts/app.js";

const CAMERA_NODE_TYPE = "KR_CameraControl";
const STUDIO_NODE_TYPE = "EasyUseAnimaPromptStudioAdvanced";

const ENABLED_PROPERTY = "kr_camera_prompt_studio_bridge_enabled";
const TARGET_NODE_PROPERTY = "kr_camera_prompt_studio_bridge_target_node_id";
const TARGET_FIELD_PROPERTY = "kr_camera_prompt_studio_bridge_target_field_id";
const DISPLAY_LABEL_PROPERTY = "kr_camera_prompt_studio_bridge_display_label";
const DEFAULT_FIELD_ID = "positive_general_kr_camera_bridge";
const DEFAULT_DISPLAY_LABEL = "구도 설정";
const CAMERA_FIELD_HEIGHT = 64;
const MIN_STUDIO_FIELD_HEIGHT = 46;
const MAX_STUDIO_FIELD_HEIGHT = 360;
const ADVANCED_FIELDS_PROPERTY = "easyuse_anima_advanced_fields";

function nodeType(node) {
  return String(node?.type || node?.comfyClass || "");
}

function isNodeType(node, type) {
  return nodeType(node) === type;
}

function findWidget(node, name) {
  return node?.widgets?.find((widget) => widget?.name === name) || null;
}

function cameraRoot(node) {
  return findWidget(node, "camera_ui")?.element || null;
}

function cameraPrompt(node) {
  return String(cameraRoot(node)?.querySelector?.(".kr-camera-prompt")?.value || "");
}

function parseFields(node) {
  if (Array.isArray(node?.__easyuseAnimaAdvancedFields)) {
    return node.__easyuseAnimaAdvancedFields;
  }
  const widgetValue = findWidget(node, "advanced_fields")?.value;
  const propertyValue = node?.properties?.[ADVANCED_FIELDS_PROPERTY];
  for (const raw of [widgetValue, propertyValue]) {
    try {
      const fields = JSON.parse(String(raw || ""));
      if (Array.isArray(fields)) return fields;
    } catch {
      // Try the next storage surface.
    }
  }
  return [];
}

function fieldTextarea(node, fieldId) {
  const editor = node?.__easyuseAnimaAdvancedEditorEl;
  if (!editor || !fieldId) return null;
  return [...editor.querySelectorAll("textarea[data-easyuse-anima-advanced-field-id]")]
    .find((textarea) => textarea.dataset.easyuseAnimaAdvancedFieldId === fieldId) || null;
}

function persistFields(node, fields) {
  const value = JSON.stringify(fields);
  const widget = findWidget(node, "advanced_fields");
  if (widget) widget.value = value;
  node.properties ||= {};
  node.properties[ADVANCED_FIELDS_PROPERTY] = value;
  node.__easyuseAnimaAdvancedFields = fields;
}

function clampFieldHeight(value, fallback = 72) {
  const numeric = Number(value);
  const height = Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
  return Math.max(MIN_STUDIO_FIELD_HEIGHT, Math.min(MAX_STUDIO_FIELD_HEIGHT, Math.round(height)));
}

function stabilizeStudioFieldHeights(node, cameraFieldId) {
  const fields = parseFields(node);
  const editor = node?.__easyuseAnimaAdvancedEditorEl;
  let changed = false;

  for (const field of fields) {
    const fieldId = String(field?.id || "");
    const isCameraField = fieldId === cameraFieldId;
    const nextHeight = isCameraField
      ? CAMERA_FIELD_HEIGHT
      : clampFieldHeight(field?.height, field?.type === "general" ? 120 : 72);
    let fieldChanged = false;
    if (field.height !== nextHeight || field.heightMode !== "manual") {
      field.height = nextHeight;
      field.heightMode = "manual";
      changed = true;
      fieldChanged = true;
    }

    const textarea = editor
      ? [...editor.querySelectorAll("textarea[data-easyuse-anima-advanced-field-id]")]
        .find((candidate) => candidate.dataset.easyuseAnimaAdvancedFieldId === fieldId)
      : null;
    if (!textarea) continue;

    const visualHeight = Number.parseFloat(textarea.style.height || "");
    if (!Number.isFinite(visualHeight) || visualHeight > MAX_STUDIO_FIELD_HEIGHT || fieldChanged) {
      textarea.style.height = `${nextHeight}px`;
    }
    textarea.style.minHeight = `${MIN_STUDIO_FIELD_HEIGHT}px`;
    textarea.style.maxHeight = `${isCameraField ? CAMERA_FIELD_HEIGHT : MAX_STUDIO_FIELD_HEIGHT}px`;
    textarea.style.overflowY = "auto";
  }

  if (changed) persistFields(node, fields);
}

function studioFieldDisplayLabel(node, fieldId, label) {
  const positives = parseFields(node).filter((field) => field?.pane === "positive");
  const index = positives.findIndex((field) => String(field?.id || "") === fieldId);
  return `${Math.max(0, index) + 1}. ${label}`;
}

function decorateStudioField(node, fieldId, label) {
  const displayLabel = studioFieldDisplayLabel(node, fieldId, label);
  const fields = parseFields(node);
  const field = fields.find((candidate) => String(candidate?.id || "") === fieldId);
  let fieldChanged = false;
  if (field && (field.height !== CAMERA_FIELD_HEIGHT || field.heightMode !== "manual")) {
    field.height = CAMERA_FIELD_HEIGHT;
    field.heightMode = "manual";
    fieldChanged = true;
  }
  const textarea = fieldTextarea(node, fieldId);
  const block = textarea?.closest?.(".easyuse-anima-advanced-field");
  if (block) {
    block.classList.add("kr-ps-camera-field");
    textarea.classList.add("kr-ps-camera-textarea");
    textarea.style.height = `${CAMERA_FIELD_HEIGHT}px`;
    textarea.style.minHeight = `${CAMERA_FIELD_HEIGHT}px`;
    textarea.style.maxHeight = `${CAMERA_FIELD_HEIGHT}px`;
    textarea.style.overflowY = "auto";
    const fieldLabel = block.querySelector(".easyuse-anima-field-label");
    if (fieldLabel && fieldLabel.textContent !== displayLabel) fieldLabel.textContent = displayLabel;
  }

  const inputName = `field_${fieldId.replace(/[^A-Za-z0-9_]/g, "_")}`;
  const input = node?.inputs?.find((candidate) => candidate?.name === inputName);
  if (input && input.label !== displayLabel) input.label = displayLabel;
  if (fieldChanged) persistFields(node, fields);
}

function renameFieldInput(node, oldFieldId, newFieldId) {
  const oldName = `field_${oldFieldId.replace(/[^A-Za-z0-9_]/g, "_")}`;
  const newName = `field_${newFieldId.replace(/[^A-Za-z0-9_]/g, "_")}`;
  const input = node?.inputs?.find((candidate) => candidate?.name === oldName);
  if (!input) return;
  input.name = newName;
  input.__easyuseAnimaAdvancedFieldId = newFieldId;
}

function addCompositionField(studio, cameraNode, fieldId) {
  const beforeFields = parseFields(studio);
  if (beforeFields.some((field) => String(field?.id || "") === fieldId)) return true;

  const editor = studio?.__easyuseAnimaAdvancedEditorEl;
  const positivePane = editor?.querySelectorAll?.(".easyuse-anima-advanced-pane")?.[0];
  const actions = positivePane?.querySelector?.(".easyuse-anima-advanced-actions");
  const buttons = [...(actions?.querySelectorAll?.("button") || [])]
    .filter((button) => !button.classList.contains("kr-ps-add-composition"));
  const generalButton = buttons.find((button) => String(button.textContent || "").includes("일반"))
    || buttons.at(-2);
  if (!generalButton || generalButton.disabled) return false;

  const beforeIds = new Set(beforeFields.map((field) => String(field?.id || "")));
  generalButton.click();
  const nextFields = parseFields(studio);
  const created = nextFields.find((field) => (
    field?.pane === "positive"
    && field?.type === "general"
    && !beforeIds.has(String(field?.id || ""))
  ));
  if (!created) return false;

  const temporaryId = String(created.id || "");
  const temporaryTextarea = fieldTextarea(studio, temporaryId);
  created.id = fieldId;
  created.label = "General Tags";
  created.text = "";
  if (temporaryTextarea) temporaryTextarea.dataset.easyuseAnimaAdvancedFieldId = fieldId;
  renameFieldInput(studio, temporaryId, fieldId);
  persistFields(studio, nextFields);

  cameraNode.properties ||= {};
  cameraNode.properties[TARGET_NODE_PROPERTY] = studio.id;
  cameraNode.properties[TARGET_FIELD_PROPERTY] = fieldId;
  studio.graph?.setDirtyCanvas?.(true, true);
  return true;
}

function ensureCompositionButton(studio, cameraNode, fieldId) {
  const editor = studio?.__easyuseAnimaAdvancedEditorEl;
  const positivePane = editor?.querySelectorAll?.(".easyuse-anima-advanced-pane")?.[0];
  const actions = positivePane?.querySelector?.(".easyuse-anima-advanced-actions");
  if (!actions) return;

  let button = actions.querySelector(".kr-ps-add-composition");
  if (!button) {
    button = document.createElement("button");
    button.type = "button";
    button.className = "kr-ps-add-composition";
    button.textContent = "+ 구도";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!button.disabled) addCompositionField(studio, cameraNode, fieldId);
    });
    const naiaButton = [...actions.querySelectorAll("button")]
      .find((candidate) => String(candidate.textContent || "").toUpperCase().includes("NAIA"));
    if (naiaButton) actions.insertBefore(button, naiaButton);
    else actions.appendChild(button);
  }

  const exists = parseFields(studio).some((field) => String(field?.id || "") === fieldId);
  button.disabled = exists;
  button.title = exists
    ? "구도 설정 필드가 이미 있습니다."
    : "KR 카메라와 연동되는 구도 설정 필드를 추가합니다.";
}

function setStudioField(node, fieldId, value) {
  const fields = parseFields(node);
  const field = fields.find((candidate) => String(candidate?.id || "") === fieldId);
  if (!field) return false;

  const nextValue = String(value || "");
  const textarea = fieldTextarea(node, fieldId);
  if (textarea) {
    if (textarea.value !== nextValue) {
      textarea.value = nextValue;
      textarea.__easyuseAnimaHighlightRefresh?.(true);
    }
    field.text = nextValue;
  } else if (String(field.text || "") !== nextValue) {
    field.text = nextValue;
  }

  persistFields(node, fields);
  node.graph?.setDirtyCanvas?.(true, true);
  return true;
}

function distanceSquared(a, b) {
  const ax = Number(a?.pos?.[0]) || 0;
  const ay = Number(a?.pos?.[1]) || 0;
  const bx = Number(b?.pos?.[0]) || 0;
  const by = Number(b?.pos?.[1]) || 0;
  return ((ax - bx) ** 2) + ((ay - by) ** 2);
}

function findTargetStudio(cameraNode) {
  const graph = cameraNode?.graph || app.graph;
  const configuredId = cameraNode?.properties?.[TARGET_NODE_PROPERTY];
  if (configuredId != null && configuredId !== "") {
    const configured = graph?.getNodeById?.(configuredId)
      || graph?._nodes?.find((node) => String(node?.id) === String(configuredId));
    if (isNodeType(configured, STUDIO_NODE_TYPE)) return configured;
  }

  const candidates = (graph?._nodes || []).filter((node) => isNodeType(node, STUDIO_NODE_TYPE));
  candidates.sort((left, right) => distanceSquared(cameraNode, left) - distanceSquared(cameraNode, right));
  return candidates[0] || null;
}

function ensureStyle() {
  if (document.getElementById("kr-camera-prompt-studio-bridge-style")) return;
  const style = document.createElement("style");
  style.id = "kr-camera-prompt-studio-bridge-style";
  style.textContent = `
    .kr-ps-bridge-row {
      display: flex;
      align-items: center;
      gap: 9px;
      margin: 7px 0;
      padding: 8px 10px;
      color: #d8eaff;
      background: #202a35;
      border: 1px solid #41566b;
      border-radius: 6px;
      font-size: 12px;
      user-select: none;
    }
    .kr-ps-bridge-row input { accent-color: #5faeff; }
    .kr-ps-bridge-label { flex: 1; font-weight: 650; }
    .kr-ps-bridge-status { color: #8ea0b1; font-family: Consolas, monospace; }
    .kr-ps-bridge-row.is-on .kr-ps-bridge-status { color: #77d9a0; }
    .kr-ps-bridge-row.is-error .kr-ps-bridge-status { color: #ffad73; }
    .easyuse-anima-advanced-field textarea {
      min-height: ${MIN_STUDIO_FIELD_HEIGHT}px !important;
      max-height: ${MAX_STUDIO_FIELD_HEIGHT}px !important;
      overflow-y: auto !important;
    }
    .easyuse-anima-advanced-field textarea.kr-ps-camera-textarea {
      height: ${CAMERA_FIELD_HEIGHT}px !important;
      min-height: ${CAMERA_FIELD_HEIGHT}px !important;
      max-height: ${CAMERA_FIELD_HEIGHT}px !important;
      overflow-y: auto !important;
      resize: none !important;
    }
  `;
  document.head.appendChild(style);
}

function installBridge(cameraNode) {
  if (!cameraNode || cameraNode.__krPromptStudioBridgeInstalled) return;
  cameraNode.__krPromptStudioBridgeInstalled = true;
  cameraNode.properties ||= {};
  if (cameraNode.properties[ENABLED_PROPERTY] == null) {
    cameraNode.properties[ENABLED_PROPERTY] = false;
  }
  if (!cameraNode.properties[TARGET_FIELD_PROPERTY]) {
    cameraNode.properties[TARGET_FIELD_PROPERTY] = DEFAULT_FIELD_ID;
  }
  if (!cameraNode.properties[DISPLAY_LABEL_PROPERTY]) {
    cameraNode.properties[DISPLAY_LABEL_PROPERTY] = DEFAULT_DISPLAY_LABEL;
  }

  ensureStyle();
  let row = null;
  let checkbox = null;
  let status = null;
  let stopped = false;
  let animationFrame = 0;
  let lastApplied = Symbol("not-applied");
  let lastTargetId = null;

  function enabled() {
    return cameraNode.properties?.[ENABLED_PROPERTY] === true;
  }

  function ensureControls() {
    const root = cameraRoot(cameraNode);
    if (!root) return false;
    if (row?.isConnected) return true;

    row = document.createElement("label");
    row.className = "kr-ps-bridge-row";
    checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = enabled();
    const label = document.createElement("span");
    label.className = "kr-ps-bridge-label";
    label.textContent = "Prompt Studio 구도 자동 입력";
    status = document.createElement("span");
    status.className = "kr-ps-bridge-status";
    row.append(checkbox, label, status);

    const toolbar = root.querySelector(".kr-camera-toolbar");
    if (toolbar?.nextSibling) toolbar.parentNode.insertBefore(row, toolbar.nextSibling);
    else if (toolbar) toolbar.parentNode.appendChild(row);
    else root.prepend(row);

    checkbox.addEventListener("change", (event) => {
      event.stopPropagation();
      cameraNode.properties[ENABLED_PROPERTY] = checkbox.checked;
      lastApplied = Symbol("toggle-changed");
      sync(true);
      cameraNode.graph?.setDirtyCanvas?.(true, true);
    });
    return true;
  }

  function updateStatus(kind, text) {
    if (!row || !status) return;
    row.classList.toggle("is-on", kind === "on");
    row.classList.toggle("is-error", kind === "error");
    status.textContent = text;
    if (checkbox && checkbox.checked !== enabled()) checkbox.checked = enabled();
  }

  function sync(force = false) {
    if (!ensureControls()) return;
    const studio = findTargetStudio(cameraNode);
    const targetFieldId = String(cameraNode.properties?.[TARGET_FIELD_PROPERTY] || DEFAULT_FIELD_ID);
    const displayLabel = String(cameraNode.properties?.[DISPLAY_LABEL_PROPERTY] || DEFAULT_DISPLAY_LABEL);
    const desired = enabled() ? cameraPrompt(cameraNode) : "";
    const targetChanged = String(studio?.id ?? "") !== String(lastTargetId ?? "");

    if (!studio) {
      updateStatus("error", "대상 없음");
      return;
    }

    stabilizeStudioFieldHeights(studio, targetFieldId);
    ensureCompositionButton(studio, cameraNode, targetFieldId);

    const textarea = fieldTextarea(studio, targetFieldId);
    const currentField = parseFields(studio).find((field) => String(field?.id || "") === targetFieldId);
    if (!currentField) {
      updateStatus("error", "구도 칸 없음");
      return;
    }
    decorateStudioField(studio, targetFieldId, displayLabel);
    const current = textarea ? String(textarea.value || "") : String(currentField?.text || "");
    if (force || targetChanged || desired !== current || desired !== lastApplied) {
      if (!setStudioField(studio, targetFieldId, desired)) {
        updateStatus("error", "구도 칸 없음");
        return;
      }
      lastApplied = desired;
      lastTargetId = studio.id;
    }
    updateStatus(enabled() ? "on" : "off", enabled() ? "ON" : "OFF");
  }

  function tick() {
    if (stopped) return;
    sync(false);
    animationFrame = requestAnimationFrame(tick);
  }

  const originalRemoved = cameraNode.onRemoved;
  cameraNode.onRemoved = function () {
    stopped = true;
    cancelAnimationFrame(animationFrame);
    row?.remove();
    return originalRemoved?.apply(this, arguments);
  };

  requestAnimationFrame(tick);
}

app.registerExtension({
  name: "KR.CameraPromptStudioBridge",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== CAMERA_NODE_TYPE && nodeType.comfyClass !== CAMERA_NODE_TYPE) return;
    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = originalCreated?.apply(this, arguments);
      requestAnimationFrame(() => installBridge(this));
      return result;
    };
  },
});
