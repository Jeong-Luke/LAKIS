const state = {
  generation: { engine: "anima", profiles: {}, mode: "detail", lakis_mode: false, upscale_engine: "ultimate" },
  translation_enabled: true,
  lora_enabled: true,
  composition_enabled: true,
  wildcard_enabled: true,
  wildcard_exclusions: {},
  continuous: { enabled: false, count: 1 },
  i2i: { enabled: false, denoise: 0.5, image_name: "", auto_size: false, image_width: 0, image_height: 0 },
  // Inpaint source/processing dimensions are request-local. They must never be
  // copied into output.width/output.height, which exclusively belong to normal generation.
  inpaint: { enabled: false, operation: "regenerate", image_name: "", image_width: 0, image_height: 0, processing_width: 0, processing_height: 0, mask_name: "", brush_size: 64, grow_mask_by: 8, strength: 1.0, denoise: 0.65, prompt: "", negative_prompt: "" },
  loras: [],
  camera: { x: 0, y: .35, z: -.45, roll: 0, frame_y: 0 },
  output: { width: 1536, height: 1024, seed: 579441119814924, seed_mode: "random", aspect_locked: false },
  prompt: {
    negative: "", fixed: "", general: "", quality: "", artist: "", trigger: "",
    negative_fixed: "", negative_quality: "", negative_artist: ""
  },
  model: {
    checkpoint: "anima_baseV10.safetensors",
    vae: "qwen_image_vae.safetensors",
    clip: "qwen_3_06b_base.safetensors",
    sampler: "euler_ancestral",
    scheduler: "normal",
    steps: 30,
    cfg: 5.0
  },
  node_overrides: {}
};
state.moss_regions = { enabled: false, regions: [] };
state.moss_detail = { enabled: false, scope: "none", steps: 20, denoise: 0.25 };
state.moss_node_overrides = {};

let engineConfiguration = null;
let runtimeCapabilities = {};
let loraInventoryRefreshTask = null;
let engineSwitchBusy = true;
let engineTransitionActive = false;
let engineSwitchError = "";

function currentGenerationEngine() {
  return state.generation.engine === "moss" ? "moss" : "anima";
}

function enforceMossGenerationMode() {
  if (currentGenerationEngine() !== "moss") return;
  state.generation.mode = "fast";
  state.generation.lakis_mode = false;
}

function syncPromptHeadings() {
  const global = currentGenerationEngine() === "moss" && state.moss_regions.enabled === true;
  document.querySelector("#positivePromptHeading").textContent = global ? "전역 프롬프트" : "프롬프트";
  document.querySelector("#negativePromptHeading").textContent = global ? "전역 부정 프롬프트" : "네거티브 프롬프트";
}

function syncMossI2iAvailability() {
  const unavailable = currentGenerationEngine() === "moss" && state.i2i.enabled;
  const panel = document.querySelector("#mossRegionPanel");
  panel.inert = unavailable;
  panel.setAttribute("aria-disabled", String(unavailable));
  panel.title = unavailable ? "i2i 사용 중에는 영역 프롬프트를 사용할 수 없습니다." : "";
  if (unavailable) {
    const regions = window.LAKISMossRegions?.snapshot() || state.moss_regions;
    if (regions.enabled) {
      state.moss_regions = { ...regions, enabled: false };
      window.LAKISMossRegions?.restore(state.moss_regions);
    }
    window.LAKISMossRegions?.close();
  }
}

function captureGenerationEngineProfile() {
  enforceMossGenerationMode();
  if (!isStateRecord(state.generation.profiles)) state.generation.profiles = {};
  state.generation.profiles[currentGenerationEngine()] = {
    ...state.generation.profiles[currentGenerationEngine()],
    model: structuredClone(state.model), output: structuredClone(state.output),
    loras: structuredClone(state.loras), lora_enabled: state.lora_enabled,
    camera: structuredClone(state.camera), composition_enabled: state.composition_enabled,
    i2i: structuredClone(state.i2i),
    generation: { mode: state.generation.mode, lakis_mode: state.generation.lakis_mode,
      upscale_engine: state.generation.upscale_engine },
  };
}

function syncGenerationEngineUI() {
  const moss = currentGenerationEngine() === "moss";
  const status = engineConfiguration?.[currentGenerationEngine()];
  const unavailable = status?.ready === false;
  document.body.classList.toggle("moss-mode", moss);
  const toggle = document.querySelector("#generationEngineToggle");
  const name = moss ? "MOSS" : "ANIMA";
  const nextName = moss ? "ANIMA" : "MOSS";
  document.querySelector("#generationEngineName").textContent = name;
  toggle.setAttribute("aria-label", `현재 ${name} 모드 · ${nextName} 모드로 전환`);
  toggle.title = `${nextName} 모드로 전환`;
  toggle.disabled = engineTransitionActive || engineSwitchBusy || !generationStateHydrated;
  const capabilities = status?.capabilities || {};
  const i2iLocked = moss && capabilities.i2i !== true;
  if (i2iLocked && state.i2i.enabled) setI2iEnabled(false);
  const i2iPanel = document.querySelector(".i2i-panel");
  i2iPanel.title = i2iLocked ? "MOSS i2i는 품질 검증 전까지 임시 잠금 상태입니다. 기존 입력 이미지와 설정은 보존됩니다." : "";
  const panels = [
    [document.querySelector(".lora-panel"), moss && capabilities.lora !== true],
    [document.querySelector(".compact-mode-panel"), moss],
    [document.querySelector(".composition-panel"), moss && capabilities.composition !== true],
    [document.querySelector(".i2i-panel"), moss && capabilities.i2i !== true],
    ...[
    document.querySelector("#sceneControls"), document.querySelector("#inpaintToggle")?.closest(".panel"),
    ].map(panel => [panel, moss]),
  ];
  for (const [panel, locked] of panels) {
    if (panel) {
      panel.inert = locked;
      panel.classList.toggle("engine-unavailable", locked);
      panel.setAttribute("aria-disabled", String(locked));
    }
  }
  for (const [id, key] of [["checkpointSelect", "checkpoint"], ["vaeSelect", "vae"],
    ["clipSelect", "clip"], ["samplerSelect", "sampler"], ["schedulerSelect", "scheduler"]]) {
    const select = document.querySelector(`#${id}`);
    select.disabled = moss && capabilities[key] !== true;
    if (moss && ["sampler", "scheduler"].includes(key)) {
      const options = status?.inventory?.[key] || [];
      select.replaceChildren(...options.map(value => new Option(value, value)));
    }
    if (moss && state.model[key] && ![...select.options].some(option => option.value === state.model[key])) {
      select.add(new Option(state.model[key], state.model[key]));
    }
    if (moss) select.value = state.model[key];
  }
  const notice = document.querySelector("#generationEngineStatus");
  notice.textContent = engineSwitchError || (engineConfiguration?.preview_only
    ? "화면 프로토타입 · 실제 생성·다운로드·사용자 설정 저장은 실행하지 않습니다."
    : moss
      ? status?.ready
        ? ""
        : `MOSS 준비 필요 · ${(status?.missing || ["ComfyUI 연결을 확인해 주세요."]).join(" / ")}`
      : unavailable
        ? `ANIMA 준비 필요 · ${(status.missing || [status.message || "이 실행 환경에서는 ANIMA 생성 경로를 제공하지 않습니다."]).join(" / ")}`
        : "");
  notice.dataset.ready = String(!unavailable && (!moss || status?.ready === true));
  notice.hidden = !notice.textContent;
  const generate = document.querySelector("#generateButton");
  generate.disabled = engineTransitionActive
    || (!engineSwitchBusy && (engineConfiguration?.preview_only === true || unavailable || (moss && !status?.ready)));
  const translationUnavailable = runtimeCapabilities.translation === false;
  const translationToggle = document.querySelector("#promptTranslationToggle");
  translationToggle.disabled = translationUnavailable;
  if (translationUnavailable) translationToggle.checked = false;
  document.querySelector(".prompt-translation-toggle").title = translationUnavailable
    ? "이 MOSS 프로토타입은 자동 번역을 제공하지 않습니다. 입력한 원문을 사용합니다."
    : "한글 프롬프트를 제작 직전에 영어로 번역합니다";
  const wildcardUnavailable = runtimeCapabilities.wildcards === false;
  for (const id of ["wildcardOpen", "wildcardToggle"]) {
    const control = document.querySelector(`#${id}`);
    control.disabled = wildcardUnavailable;
    if (wildcardUnavailable) control.title = "이 MOSS 프로토타입에서는 와일드카드를 지원하지 않습니다.";
  }
  const continuousUnavailable = runtimeCapabilities.continuous === false;
  const continuousRow = document.querySelector(".continuous-generation-row");
  continuousRow.inert = continuousUnavailable;
  continuousRow.classList.toggle("engine-unavailable", continuousUnavailable);
  continuousRow.title = continuousUnavailable ? "이 MOSS 프로토타입은 한 번에 한 장씩 생성합니다." : "";
  document.querySelector("#mossRegionPanel").hidden = !moss || capabilities.regions !== true;
  if (document.querySelector("#mossRegionPanel").hidden) window.LAKISMossRegions?.close();
  document.querySelector("#mossDetailControls").hidden = !moss || capabilities.detail !== true;
  if (state.moss_detail.scope === "face_eyes") state.moss_detail.scope = "none";
  document.querySelector("#mossDetailScope").value = state.moss_detail.scope;
  document.querySelector("#mossDetailSteps").value = state.moss_detail.steps;
  document.querySelector("#mossDetailDenoise").value = state.moss_detail.denoise;
  document.querySelector("#mossDetailSteps").disabled = state.moss_detail.scope === "none";
  document.querySelector("#mossDetailDenoise").disabled = state.moss_detail.scope === "none";
  renderCompositionAvailability();
  syncMossI2iAvailability();
  syncPromptHeadings();
  window.LAKISAdvancedSettings?.syncGenerationEngine();
  modeButtons.forEach(button => { button.disabled = moss; });
  lakisModeButton.disabled = moss;
  const manager = document.querySelector('a[aria-label="LoRA Manager"]');
  if (status?.lora_manager_url) {
    manager.href = status.lora_manager_url;
    manager.title = `${name} 전용 LoRA Manager`;
  }
}

function applyGenerationEngineProfile(engine, profile) {
  state.generation.engine = engine;
  state.model = structuredClone(profile.model);
  state.output = structuredClone(profile.output);
  state.loras = Array.isArray(profile.loras) ? structuredClone(profile.loras) : [];
  state.lora_enabled = profile.lora_enabled !== false;
  state.i2i = {
    enabled: false, denoise: 0.5, image_name: "", auto_size: false,
    image_width: 0, image_height: 0, ...structuredClone(profile.i2i || {}),
  };
  Object.assign(state.camera, profile.camera || engineConfiguration?.[engine]?.defaults?.camera || {});
  state.composition_enabled = typeof profile.composition_enabled === "boolean"
    ? profile.composition_enabled : engine === "moss" ? false : state.composition_enabled;
  Object.assign(state.generation, profile.generation || {
    mode: engine === "moss" ? "fast" : "detail", lakis_mode: false, upscale_engine: "ultimate",
  });
  const edits = new Map(["model", "output"].flatMap(root => Object.keys(state[root]).map(
    key => [JSON.stringify([root, key]), {present: true, value: state[root][key]}],
  )));
  for (const key of ["loras", "lora_enabled", "composition_enabled", "i2i"]) {
    edits.set(JSON.stringify([key]), { present: true, value: structuredClone(state[key]) });
  }
  syncEditedGenerationControls(edits);
  render();
}

const waitForEngineTransition = milliseconds => new Promise(resolve => window.setTimeout(resolve, milliseconds));

async function animateGenerationEngineSwitch(next, prepare) {
  const shell = document.querySelector(".app-shell");
  const layer = document.querySelector("#generationEngineTransition");
  const wasInert = shell.inert;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  layer.dataset.easterEgg = String(Math.random() < 0.05);
  const fade = reduced ? 80 : 220;
  shell.inert = true;
  shell.classList.add("engine-transition-shell");
  void shell.offsetWidth;
  shell.classList.add("is-engine-leaving");
  await waitForEngineTransition(fade);

  layer.dataset.engine = next;
  document.querySelector("#generationEngineTransitionStatus").textContent =
    `${next === "moss" ? "MOSS" : "ANIMA"} 화면과 모델 목록을 준비하는 중입니다.`;
  layer.hidden = false;
  void layer.offsetWidth;
  layer.classList.add("is-active");
  try {
    await Promise.all([prepare(), waitForEngineTransition(reduced ? 200 : 1800)]);
  } finally {
    layer.classList.add("is-exiting");
    await waitForEngineTransition(reduced ? 80 : 320);
    layer.classList.remove("is-active");
    shell.classList.remove("is-engine-leaving");
    await waitForEngineTransition(fade);
    layer.hidden = true;
    delete layer.dataset.easterEgg;
    layer.classList.remove("is-exiting");
    shell.classList.remove("engine-transition-shell");
    shell.inert = wasInert;
  }
}

async function switchGenerationEngine(next) {
  if (engineTransitionActive || engineSwitchBusy || generationActive || generationPreparationPending || generationSubmissionPending
      || !generationStateHydrated || next === currentGenerationEngine()) return;
  if (!["anima", "moss"].includes(next)) return;
  const defaults = engineConfiguration?.[next]?.defaults;
  if (!defaults && !state.generation.profiles[next]) return;
  const previousEngine = currentGenerationEngine();
  engineTransitionActive = true;
  engineSwitchError = "";
  syncGenerationEngineUI();
  try {
    await animateGenerationEngineSwitch(next, async () => {
      if (modelInventoryRefreshPromise) await modelInventoryRefreshPromise;
      if (loraInventoryRefreshTask) await loraInventoryRefreshTask;
      syncOutputStateFromInputs();
      captureGenerationEngineProfile();
      const previousProfile = state.generation.profiles[previousEngine];
      const profile = state.generation.profiles[next]
        || { model: defaults.model, output: { ...state.output, ...defaults.output } };
      try {
        applyGenerationEngineProfile(next, profile);
        modelInventorySignature = "";
        if (!await refreshModelInventory()) throw new Error("Could not prepare the target model inventory");
        loraOptions = [];
        loraInventorySignature = "";
        await refreshLoraInventory();
        scheduleGenerationStateSave();
      } catch (error) {
        applyGenerationEngineProfile(previousEngine, previousProfile);
        modelInventorySignature = "";
        engineSwitchError = `모델 목록을 확인하지 못해 기존 ${previousEngine.toUpperCase()} 모드를 유지했습니다. 다시 전환해 주세요.`;
        throw error;
      }
    });
  } catch (error) {
    console.error("Could not switch generation engine", error);
  } finally {
    engineTransitionActive = false;
    syncGenerationEngineUI();
    document.querySelector("#generationEngineToggle").focus({ preventScroll: true });
  }
}

document.querySelector("#generationEngineToggle").addEventListener("click", () => {
  switchGenerationEngine(currentGenerationEngine() === "moss" ? "anima" : "moss");
});

// DEV must reflect frontend edits without requiring users to repeatedly
// close and reopen LAKIS. The server revision covers every local HTML/JS/CSS
// file and is intentionally disabled in release builds.
let lakisDevRevision = null;
async function pollLakisDevRevision() {
  try {
    const response = await fetch(`/api/dev-revision?t=${Date.now()}`, { cache: "no-store" });
    const payload = await response.json();
    if (!payload.development) return;
    if (lakisDevRevision === null) lakisDevRevision = payload.revision;
    else if (payload.revision !== lakisDevRevision) window.location.reload();
  } catch (_) { /* A transient bridge restart is expected during DEV edits. */ }
}
pollLakisDevRevision();
setInterval(pollLakisDevRevision, 1500);

// The packaged application owns a dedicated ComfyUI port so it never opens a
// different portable installation that happens to be running on port 8188.
const loraManagerLink = document.querySelector('a[aria-label="LoRA Manager"]');

const COMFYUI_SEED_MAX = 1125899906842624;
const PROMPT_STORAGE_KEY = "lakis.promptState.v3";
const LEGACY_DEKIS_PROMPT_STORAGE_KEY = "lakis.dekis.promptState.v1";
const LEGACY_PROMPT_STORAGE_KEY = "lakis.prompt-state.v2";
const TRANSLATION_STORAGE_KEY = "lakis.prompt-translation-enabled.v1";
let promptStateHydrated = false;
let promptStateDirty = false;
let promptStateRevision = 0;
let loraOptions = [];
let loraInventorySignature = "";
let loraInventoryRefreshActive = false;
let modelInventorySignature = "";
let modelInventoryRefreshPromise = null;
let generationStateSaveTimer = null;
let generationStateHydrated = false;
let lastSavedGenerationState = null;

function persistedGenerationState() {
  captureGenerationEngineProfile();
  return {
    model: state.model,
    output: state.output,
    loras: state.loras,
    lora_enabled: state.lora_enabled,
    node_overrides: state.node_overrides,
    moss_node_overrides: state.moss_node_overrides,
    generation: state.generation,
    camera: state.camera,
    composition_enabled: state.composition_enabled,
    wildcard_enabled: state.wildcard_enabled,
    wildcard_exclusions: state.wildcard_exclusions,
    continuous: state.continuous,
    i2i: state.i2i,
    moss_regions: window.LAKISMossRegions?.snapshot() || state.moss_regions,
    moss_detail: state.moss_detail,
  };
}

const isStateRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
function recordStateEdits(previous, current, edits, path = []) {
  if (isStateRecord(previous) && isStateRecord(current)) {
    for (const key of new Set([...Object.keys(previous), ...Object.keys(current)])) {
      const hadPrevious = Object.prototype.hasOwnProperty.call(previous, key);
      const hasCurrent = Object.prototype.hasOwnProperty.call(current, key);
      const nextPath = [...path, key];
      if (!hasCurrent) edits.set(JSON.stringify(nextPath), { present: false });
      else if (!hadPrevious) edits.set(JSON.stringify(nextPath), { present: true, value: structuredClone(current[key]) });
      else recordStateEdits(previous[key], current[key], edits, nextPath);
    }
    return;
  }
  if (JSON.stringify(previous) !== JSON.stringify(current)) {
    edits.set(JSON.stringify(path), { present: current !== undefined, value: structuredClone(current) });
  }
}

function applyStateEdits(target, edits) {
  for (const [encodedPath, edit] of edits) {
    const path = JSON.parse(encodedPath);
    let parent = target;
    for (const key of path.slice(0, -1)) {
      if (!isStateRecord(parent[key])) parent[key] = {};
      parent = parent[key];
    }
    if (edit.present) parent[path.at(-1)] = structuredClone(edit.value);
    else delete parent[path.at(-1)];
  }
}

function applyPersistedGenerationState(saved) {
  Object.assign(state.model, saved.model || {});
  Object.assign(state.output, saved.output || {});
  state.loras = Array.isArray(saved.loras) ? structuredClone(saved.loras) : [];
  state.lora_enabled = saved.lora_enabled !== false;
  state.node_overrides = isStateRecord(saved.node_overrides) ? structuredClone(saved.node_overrides) : {};
  state.moss_node_overrides = isStateRecord(saved.moss_node_overrides) ? structuredClone(saved.moss_node_overrides) : {};
  Object.assign(state.generation, saved.generation || {});
  Object.assign(state.camera, saved.camera || {});
  state.composition_enabled = saved.composition_enabled !== false;
  state.wildcard_enabled = saved.wildcard_enabled === true;
  state.wildcard_exclusions = isStateRecord(saved.wildcard_exclusions)
    ? structuredClone(saved.wildcard_exclusions) : {};
  Object.assign(state.continuous, saved.continuous || {});
  Object.assign(state.i2i, saved.i2i || {});
  state.moss_regions = isStateRecord(saved.moss_regions) ? structuredClone(saved.moss_regions) : state.moss_regions;
  Object.assign(state.moss_detail, saved.moss_detail || {});
  window.LAKISMossRegions?.restore(state.moss_regions);
}

function syncEditedGenerationControls(edits) {
  const paths = [...edits.keys()].map(encoded => JSON.parse(encoded));
  const roots = new Set(paths.map(path => path[0]));
  if (roots.has("model")) {
    const controls = {
      checkpoint: "checkpointSelect", vae: "vaeSelect", clip: "clipSelect",
      sampler: "samplerSelect", scheduler: "schedulerSelect", steps: "stepsInput", cfg: "cfgInput",
    };
    for (const key of new Set(paths.filter(path => path[0] === "model").map(path => path[1]))) {
      const id = controls[key];
      if (id) document.querySelector(`#${id}`).value = state.model[key];
    }
  }
  if (roots.has("output")) {
    const controls = { width: "imageWidth", height: "imageHeight", seed: "seedInput" };
    for (const key of new Set(paths.filter(path => path[0] === "output").map(path => path[1]))) {
      const id = controls[key];
      if (id) document.querySelector(`#${id}`).value = state.output[key];
    }
    document.querySelector("#aspectRatioLock").checked = state.output.aspect_locked === true;
    lockedAspectRatio = clampImageDimension(state.output.width) / clampImageDimension(state.output.height);
    document.querySelectorAll("[data-seed-mode]").forEach(button => {
      button.classList.toggle("active", button.dataset.seedMode === state.output.seed_mode);
    });
    document.querySelector("#seedInput").classList.toggle("seed-locked", state.output.seed_mode === "current");
  }
  if (roots.has("loras")) renderLoras();
  if (roots.has("lora_enabled")) {
    const toggle = document.querySelector("#allLorasToggle");
    toggle.classList.toggle("on", state.lora_enabled);
    toggle.setAttribute("aria-pressed", String(state.lora_enabled));
    document.querySelector("#loraList").classList.toggle("all-disabled", !state.lora_enabled);
  }
  if (roots.has("composition_enabled")) renderCompositionAvailability();
  if (roots.has("wildcard_enabled")) window.lakisApplyWildcardState?.(state.wildcard_enabled);
  if (roots.has("wildcard_exclusions")) window.lakisApplyWildcardExclusions?.(state.wildcard_exclusions);
  if (roots.has("continuous")) syncContinuousControls();
  if (roots.has("i2i")) syncI2iControls();
}

let generationStateObserved = structuredClone(persistedGenerationState());
const pendingGenerationStateEdits = new Map();
const pendingPromptStateEdits = new Map();
let promptStateObserved = null;
let applyingWorkflowConfiguration = false;
let workflowConfigurationReady = Promise.resolve();

function capturePendingGenerationStateEdits() {
  if (generationStateHydrated || applyingWorkflowConfiguration) return;
  const current = structuredClone(persistedGenerationState());
  recordStateEdits(generationStateObserved, current, pendingGenerationStateEdits);
  generationStateObserved = current;
}

function scheduleGenerationStateSave() {
  if (!generationStateHydrated) {
    capturePendingGenerationStateEdits();
    return;
  }
  if (applyingWorkflowConfiguration) return;
  clearTimeout(generationStateSaveTimer);
  generationStateSaveTimer = setTimeout(async () => {
    try {
      const body = JSON.stringify(persistedGenerationState());
      if (body === lastSavedGenerationState) return;
      const response = await fetch("/api/generation-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      lastSavedGenerationState = body;
    } catch (error) {
      console.error("Could not persist LAKIS model configuration", error);
    }
  }, 250);
}

function flushGenerationState() {
  if (!generationStateHydrated || lastSavedGenerationState === null) return;
  clearTimeout(generationStateSaveTimer);
  const body = JSON.stringify(persistedGenerationState());
  if (body === lastSavedGenerationState) return;
  const payload = new Blob([body], { type: "application/json" });
  if (navigator.sendBeacon?.("/api/generation-state", payload)) lastSavedGenerationState = body;
}

window.addEventListener("pagehide", () => {
  flushGenerationState();
  flushPromptState({ beacon: true });
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    flushGenerationState();
    flushPromptState({ beacon: true });
  }
});

const previewStage = document.querySelector(".preview-stage");
const previewImage = document.querySelector("#previewImage");
const previewEmptyState = document.querySelector("#previewEmptyState");
const previewBadge = document.querySelector(".preview-badge");
const previewPromptButton = document.querySelector("#previewPromptButton");
const promptInspector = document.querySelector("#promptInspector");
const promptInspectorClose = document.querySelector("#promptInspectorClose");
const usedPositivePrompt = document.querySelector("#usedPositivePrompt");
const usedNegativePrompt = document.querySelector("#usedNegativePrompt");
const previewZoomValue = document.querySelector("#previewZoomValue");
const PREVIEW_ZOOM_MIN = 25;
const PREVIEW_ZOOM_MAX = 400;
const PREVIEW_ZOOM_STEP = 10;
let previewZoom = 100;
let previewPanX = 0;
let previewPanY = 0;
let currentPreviewPrompt = null;

function syncPreviewPromptButton() {
  previewPromptButton.hidden = previewImage.hidden || !currentPreviewPrompt;
}

function setCurrentPreviewPrompt(promptSnapshot) {
  currentPreviewPrompt = promptSnapshot && typeof promptSnapshot === "object"
    ? structuredClone(promptSnapshot)
    : null;
  syncPreviewPromptButton();
}

function joinPromptParts(promptSnapshot, keys) {
  return keys
    .map(key => String(promptSnapshot?.[key] || "").trim())
    .filter(Boolean)
    .join(", ");
}

function closePromptInspector() {
  promptInspector.hidden = true;
}

previewPromptButton.addEventListener("click", () => {
  if (!currentPreviewPrompt) return;
  usedPositivePrompt.value = joinPromptParts(currentPreviewPrompt, ["trigger", "artist", "quality", "fixed", "general", "composition"]);
  usedNegativePrompt.value = joinPromptParts(currentPreviewPrompt, ["negative_artist", "negative_quality", "negative_fixed", "negative"]);
  promptInspector.hidden = false;
  promptInspectorClose.focus();
});

promptInspectorClose.addEventListener("click", closePromptInspector);
promptInspector.addEventListener("click", event => {
  if (event.target === promptInspector) closePromptInspector();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !promptInspector.hidden) closePromptInspector();
});

function setPreviewAvailability(hasImage) {
  previewImage.hidden = !hasImage;
  previewEmptyState.hidden = hasImage;
  previewBadge.hidden = !hasImage;
  syncPreviewPromptButton();
}

previewImage.addEventListener("load", () => setPreviewAvailability(true));
previewImage.addEventListener("error", () => {
  previewImage.removeAttribute("src");
  setPreviewAvailability(false);
});
setPreviewAvailability(false);

function clampPreviewPan(scale) {
  if (scale <= 1) {
    previewPanX = 0;
    previewPanY = 0;
    return;
  }
  const maxX = previewStage.clientWidth * (scale - 1) / 2;
  const maxY = previewStage.clientHeight * (scale - 1) / 2;
  previewPanX = Math.max(-maxX, Math.min(maxX, previewPanX));
  previewPanY = Math.max(-maxY, Math.min(maxY, previewPanY));
}

function applyPreviewTransform() {
  const scale = previewZoom / 100;
  clampPreviewPan(scale);
  previewImage.style.setProperty("--preview-zoom", String(scale));
  previewImage.style.setProperty("--preview-pan-x", `${previewPanX}px`);
  previewImage.style.setProperty("--preview-pan-y", `${previewPanY}px`);
}

function setPreviewZoom(nextZoom, anchor = null) {
  const previousScale = previewZoom / 100;
  const next = Math.max(PREVIEW_ZOOM_MIN, Math.min(PREVIEW_ZOOM_MAX, Math.round(nextZoom)));
  const nextScale = next / 100;
  if (anchor && next !== previewZoom) {
    const centerX = previewStage.clientWidth / 2;
    const centerY = previewStage.clientHeight / 2;
    const offsetX = anchor.x - centerX;
    const offsetY = anchor.y - centerY;
    previewPanX = offsetX - ((offsetX - previewPanX) / previousScale) * nextScale;
    previewPanY = offsetY - ((offsetY - previewPanY) / previousScale) * nextScale;
  }
  previewZoom = next;
  applyPreviewTransform();
  previewZoomValue.textContent = `${previewZoom}%`;
  document.querySelector("#previewZoomOut").disabled = previewZoom <= PREVIEW_ZOOM_MIN;
  document.querySelector("#previewZoomIn").disabled = previewZoom >= PREVIEW_ZOOM_MAX;
}

document.querySelector("#previewZoomOut").addEventListener("click", () => setPreviewZoom(previewZoom - PREVIEW_ZOOM_STEP));
document.querySelector("#previewZoomIn").addEventListener("click", () => setPreviewZoom(previewZoom + PREVIEW_ZOOM_STEP));
previewStage.addEventListener("wheel", event => {
  event.preventDefault();
  const rect = previewStage.getBoundingClientRect();
  setPreviewZoom(previewZoom + (event.deltaY < 0 ? PREVIEW_ZOOM_STEP : -PREVIEW_ZOOM_STEP), {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  });
}, { passive: false });
previewStage.addEventListener("dblclick", () => {
  previewPanX = 0;
  previewPanY = 0;
  setPreviewZoom(100);
});
window.addEventListener("resize", applyPreviewTransform);
setPreviewZoom(100);

const loraSearchMenu = document.createElement("div");
loraSearchMenu.className = "lora-search-menu";
loraSearchMenu.hidden = true;
document.body.append(loraSearchMenu);
let activeLoraSearchInput = null;

function closeLoraSearchMenu() {
  loraSearchMenu.hidden = true;
  loraSearchMenu.replaceChildren();
  activeLoraSearchInput = null;
}

function updateLoraSearchMenu(input, onSelect, availableOptions = loraOptions) {
  const query = input.value.trim().toLocaleLowerCase();
  const matches = availableOptions.filter(name => name.toLocaleLowerCase().includes(query));
  loraSearchMenu.replaceChildren();
  for (const name of matches) {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "lora-search-option";
    option.textContent = name;
    option.title = name;
    option.addEventListener("mousedown", event => event.preventDefault());
    option.addEventListener("click", () => onSelect(name));
    loraSearchMenu.append(option);
  }
  if (!matches.length) {
    const empty = document.createElement("div");
    empty.className = "lora-search-empty";
    empty.textContent = "일치하는 LoRA가 없습니다.";
    loraSearchMenu.append(empty);
  }
  const rect = input.getBoundingClientRect();
  const availableAbove = rect.top - 8;
  const menuHeight = Math.max(80, availableAbove);
  const menuWidth = Math.min(window.innerWidth - 16, Math.max(400, rect.width * 1.65));
  loraSearchMenu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - menuWidth - 8))}px`;
  loraSearchMenu.style.width = `${menuWidth}px`;
  loraSearchMenu.style.maxHeight = `${menuHeight}px`;
  loraSearchMenu.style.top = "auto";
  loraSearchMenu.style.bottom = `${window.innerHeight - rect.top + 3}px`;
  loraSearchMenu.hidden = false;
  activeLoraSearchInput = input;
}

document.addEventListener("mousedown", event => {
  if (!loraSearchMenu.hidden && event.target !== activeLoraSearchInput && !loraSearchMenu.contains(event.target)) {
    closeLoraSearchMenu();
  }
});
window.addEventListener("resize", closeLoraSearchMenu);

function renderLoras() {
  const list = document.querySelector("#loraList");
  const count = document.querySelector("#loraCount");
  list.replaceChildren();
  state.loras.forEach((lora, index) => {
    const row = document.createElement("div");
    row.className = "lora-row";

    const select = document.createElement("input");
    select.type = "search";
    select.className = "lora-select";
    select.placeholder = "로라 검색 또는 선택";
    select.autocomplete = "off";
    select.spellcheck = false;
    select.value = lora.name;
    select.title = loraOptions.includes(lora.name) ? lora.name : `${lora.name} (파일 없음)`;
    const unregisteredLoraOptions = () => {
      const registered = new Set(state.loras.map(item => String(item.name || "")).filter(Boolean));
      return loraOptions.filter(name => !registered.has(name));
    };
    select.addEventListener("focus", () => {
      select.dataset.searching = "true";
      select.value = "";
      select.placeholder = lora.name || "로라 검색 또는 선택";
      updateLoraSearchMenu(select, name => {
        select.value = name;
        commitLoraSelection();
        closeLoraSearchMenu();
      }, unregisteredLoraOptions());
    });
    select.addEventListener("input", () => {
      updateLoraSearchMenu(select, name => {
        select.value = name;
        commitLoraSelection();
        closeLoraSearchMenu();
      }, unregisteredLoraOptions());
    });
    const commitLoraSelection = () => {
      const selectedName = select.value.trim();
      if (!loraOptions.includes(selectedName)) {
        select.value = state.loras[index].name;
        return false;
      }
      if (selectedName === state.loras[index].name) return true;
      state.loras[index].name = selectedName;
      state.loras[index].enabled = true;
      select.title = selectedName;
      scheduleGenerationStateSave();
      renderLoras();
      return true;
    };
    select.addEventListener("change", commitLoraSelection);
    select.addEventListener("blur", () => {
      // Restore the existing value only when no valid option was committed.
      setTimeout(() => {
        if (document.body.contains(select) && !loraOptions.includes(select.value.trim())) {
          select.value = state.loras[index]?.name || "";
        }
        if (activeLoraSearchInput === select) closeLoraSearchMenu();
        delete select.dataset.searching;
      }, 0);
    });
    select.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        commitLoraSelection();
      } else if (event.key === "Escape") {
        select.value = state.loras[index].name;
        closeLoraSearchMenu();
        select.blur();
      }
    });

    const strength = document.createElement("input");
    strength.type = "number";
    strength.min = "-20";
    strength.max = "20";
    strength.step = "0.05";
    strength.value = Number(lora.strength).toFixed(2);
    strength.title = "로라 강도";
    strength.addEventListener("change", event => {
      const value = Number(event.target.value);
      state.loras[index].strength = Number.isFinite(value) ? value : 1;
      event.target.value = state.loras[index].strength.toFixed(2);
      scheduleGenerationStateSave();
    });

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = `lora-switch${lora.enabled ? " on" : ""}`;
    toggle.setAttribute("aria-label", `${lora.name} ${lora.enabled ? "끄기" : "켜기"}`);
    toggle.setAttribute("aria-pressed", String(lora.enabled));
    toggle.addEventListener("click", () => {
      state.loras[index].enabled = !state.loras[index].enabled;
      scheduleGenerationStateSave();
      renderLoras();
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "lora-remove";
    remove.textContent = "×";
    remove.title = "로라 제거";
    remove.addEventListener("click", () => {
      state.loras.splice(index, 1);
      scheduleGenerationStateSave();
      renderLoras();
    });

    const orderControls = document.createElement("div");
    orderControls.className = "lora-order-controls";
    const moveUp = document.createElement("button");
    moveUp.type = "button";
    moveUp.className = "lora-order-button";
    moveUp.textContent = "▲";
    moveUp.title = "위 로라와 순서 바꾸기";
    moveUp.setAttribute("aria-label", `${lora.name || `로라 ${index + 1}`} 위로 이동`);
    moveUp.disabled = index === 0;
    moveUp.addEventListener("click", () => {
      if (index === 0) return;
      [state.loras[index - 1], state.loras[index]] = [state.loras[index], state.loras[index - 1]];
      scheduleGenerationStateSave();
      renderLoras();
    });
    const moveDown = document.createElement("button");
    moveDown.type = "button";
    moveDown.className = "lora-order-button";
    moveDown.textContent = "▼";
    moveDown.title = "아래 로라와 순서 바꾸기";
    moveDown.setAttribute("aria-label", `${lora.name || `로라 ${index + 1}`} 아래로 이동`);
    moveDown.disabled = index === state.loras.length - 1;
    moveDown.addEventListener("click", () => {
      if (index >= state.loras.length - 1) return;
      [state.loras[index], state.loras[index + 1]] = [state.loras[index + 1], state.loras[index]];
      scheduleGenerationStateSave();
      renderLoras();
    });
    orderControls.append(moveUp, moveDown);

    const rowActions = document.createElement("div");
    rowActions.className = "lora-row-actions";
    rowActions.append(remove, orderControls);

    row.append(rowActions, select, strength, toggle);
    list.append(row);
  });
  count.textContent = `(${state.loras.length})`;
}

document.querySelector("#addLoraButton").addEventListener("click", () => {
  state.loras.push({ name: "", enabled: false, strength: 1 });
  scheduleGenerationStateSave();
  renderLoras();
  document.querySelector("#loraList").lastElementChild?.scrollIntoView({ block: "nearest" });
});

document.querySelector("#allLorasToggle").addEventListener("click", event => {
  state.lora_enabled = !state.lora_enabled;
  event.currentTarget.classList.toggle("on", state.lora_enabled);
  event.currentTarget.setAttribute("aria-pressed", String(state.lora_enabled));
  event.currentTarget.setAttribute("aria-label", `전체 로라 ${state.lora_enabled ? "끄기" : "켜기"}`);
  document.querySelector("#loraList").classList.toggle("all-disabled", !state.lora_enabled);
  scheduleGenerationStateSave();
});

const modeButtons = [...document.querySelectorAll(".mode-option")];
const lakisModeButton = document.querySelector("#lakisModeButton");
const cameraCanvas = document.querySelector("#cameraCanvas");
const cameraStatus = document.querySelector("#cameraStatus");
const clamp = value => Math.max(-1, Math.min(1, Number(value)));
const WIDTH = 560;
const HEIGHT = 360;
const dpr = Math.min(window.devicePixelRatio || 1, 2);
cameraCanvas.width = WIDTH * dpr;
cameraCanvas.height = HEIGHT * dpr;
const cameraContext = cameraCanvas.getContext("2d");
cameraContext.scale(dpr, dpr);
let viewYaw = 0;
let viewPitch = .42;

function project3d(x, y, z) {
  const cosine = Math.cos(viewYaw);
  const sine = Math.sin(viewYaw);
  const horizontal = x * cosine + z * sine;
  const depth = -x * sine + z * cosine;
  const scale = 78;
  return {
    x: WIDTH / 2 + horizontal * scale,
    y: HEIGHT / 2 - (y - .7) * scale * Math.cos(viewPitch) + depth * scale * Math.sin(viewPitch)
  };
}

function drawOrbit(radius, elevation, color, dashed = true) {
  cameraContext.beginPath();
  for (let index = 0; index <= 80; index++) {
    const angle = index / 80 * Math.PI * 2;
    const point = project3d(radius * Math.sin(angle), elevation, radius * Math.cos(angle));
    index ? cameraContext.lineTo(point.x, point.y) : cameraContext.moveTo(point.x, point.y);
  }
  cameraContext.strokeStyle = color;
  cameraContext.lineWidth = 1.8;
  cameraContext.setLineDash(dashed ? [5,7] : []);
  cameraContext.stroke();
  cameraContext.setLineDash([]);
}

function drawVerticalOrbit(radius, azimuth, color) {
  cameraContext.beginPath();
  for (let index = 0; index <= 80; index++) {
    const angle = index / 80 * Math.PI * 2;
    const horizontal = radius * Math.cos(angle);
    const point = project3d(horizontal * Math.sin(azimuth), .7 + radius * Math.sin(angle), horizontal * Math.cos(azimuth));
    index ? cameraContext.lineTo(point.x, point.y) : cameraContext.moveTo(point.x, point.y);
  }
  cameraContext.strokeStyle = color;
  cameraContext.lineWidth = 1.8;
  cameraContext.setLineDash([5,7]);
  cameraContext.stroke();
  cameraContext.setLineDash([]);
}

function drawElevationOrbit(radius, elevation, color) {
  const horizontal = radius * Math.cos(elevation);
  const height = .7 + radius * Math.sin(elevation);
  cameraContext.beginPath();
  for (let index = 0; index <= 80; index++) {
    const angle = index / 80 * Math.PI * 2;
    const point = project3d(horizontal * Math.sin(angle), height, horizontal * Math.cos(angle));
    index ? cameraContext.lineTo(point.x, point.y) : cameraContext.moveTo(point.x, point.y);
  }
  cameraContext.strokeStyle = color;
  cameraContext.lineWidth = 1.4;
  cameraContext.setLineDash([3,7]);
  cameraContext.stroke();
  cameraContext.setLineDash([]);
}

function drawMarker(x, y, z, label) {
  const point = project3d(x,y,z);
  cameraContext.fillStyle = "#75d9e9";
  cameraContext.beginPath();
  cameraContext.arc(point.x,point.y,5,0,Math.PI*2);
  cameraContext.fill();
  cameraContext.fillStyle = "#eef8ff";
  cameraContext.font = "700 13px Consolas";
  cameraContext.textAlign = "center";
  cameraContext.fillText(label,point.x,point.y-10);
}

function drawCamera3d() {
  const ctx = cameraContext;
  ctx.clearRect(0,0,WIDTH,HEIGHT);
  const background = ctx.createLinearGradient(0,0,0,HEIGHT);
  background.addColorStop(0,"#151a20");
  background.addColorStop(1,"#222932");
  ctx.fillStyle = background;
  ctx.fillRect(0,0,WIDTH,HEIGHT);
  const radius = 1.7 - .7 * state.camera.z;
  const angle = state.camera.x * Math.PI;
  const elevation = state.camera.y * Math.PI / 2;
  drawOrbit(radius,.7,"rgba(74,201,217,.34)");
  drawVerticalOrbit(radius,angle,"rgba(255,137,75,.38)");
  drawElevationOrbit(radius,elevation,"rgba(111,215,235,.25)");
  const horizontal = radius * Math.cos(elevation);
  const camera = {x:horizontal*Math.sin(angle),y:.7+radius*Math.sin(elevation),z:horizontal*Math.cos(angle)};
  drawMarker(0,.7,radius,"F"); drawMarker(0,.7,-radius,"B"); drawMarker(radius,.7,0,"L"); drawMarker(-radius,.7,0,"R");
  const center = project3d(0,.7,0);
  const cameraPoint = project3d(camera.x,camera.y,camera.z);
  ctx.strokeStyle = "rgba(255,210,103,.7)";
  ctx.setLineDash([5,6]); ctx.beginPath(); ctx.moveTo(center.x,center.y); ctx.lineTo(cameraPoint.x,cameraPoint.y); ctx.stroke(); ctx.setLineDash([]);
  ctx.save();
  ctx.translate(center.x, center.y);
  ctx.scale(1.7, 1.7);
  ctx.shadowColor = "rgba(83,211,226,.72)";
  ctx.shadowBlur = 12;
  const personGradient = ctx.createLinearGradient(-8,-16,9,17);
  personGradient.addColorStop(0,"#e8ffff");
  personGradient.addColorStop(.45,"#73d9e5");
  personGradient.addColorStop(1,"#2d7885");
  ctx.fillStyle = personGradient;
  ctx.strokeStyle = "rgba(221,255,255,.72)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(0,-11,5,0,Math.PI*2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(-7,-4);
  ctx.quadraticCurveTo(0,-8,7,-4);
  ctx.lineTo(5,7);
  ctx.lineTo(3,7);
  ctx.lineTo(3,16);
  ctx.lineTo(0,16);
  ctx.lineTo(0,8);
  ctx.lineTo(-3,16);
  ctx.lineTo(-6,16);
  ctx.lineTo(-4,7);
  ctx.lineTo(-6,7);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
  ctx.save(); ctx.translate(cameraPoint.x,cameraPoint.y); ctx.rotate(Math.atan2(center.y-cameraPoint.y,center.x-cameraPoint.x)+state.camera.roll*Math.PI/4);
  ctx.fillStyle="#ff9555"; ctx.fillRect(-13,-8,26,16); ctx.fillStyle="#10151b"; ctx.beginPath(); ctx.arc(6,0,5,0,Math.PI*2); ctx.fill(); ctx.restore();
  const degrees = Math.round(state.camera.x*180);
  cameraStatus.textContent = Math.abs(state.camera.x)>.85 ? "뒤" : state.camera.x<-.05 ? `왼쪽 ${Math.abs(degrees)}°` : state.camera.x>.05 ? `오른쪽 ${degrees}°` : "정면 0°";
}

function renderCamera() {
  const { x, y, z, roll, frame_y } = state.camera;
  for (const [id, value] of [["cameraX",x],["cameraY",y],["cameraZ",z],["cameraRoll",roll]]) {
    document.querySelector(`#${id}`).value = value.toFixed(2);
  }
  document.querySelector("#cameraXSlider").value = x;
  document.querySelector("#cameraYSlider").value = y;
  document.querySelector("#cameraZSlider").value = z;
  document.querySelector("#frameYSlider").value = frame_y;
  document.querySelector("#cameraRollSlider").value = roll;
  document.querySelector("#frameYInput").value = frame_y.toFixed(2);
  drawCamera3d();
  if (generationStateHydrated) scheduleGenerationStateSave();
}

function render() {
  enforceMossGenerationMode();
  modeButtons.forEach(button => button.classList.toggle("active", button.dataset.mode === state.generation.mode));
  const detail = state.generation.mode === "detail";
  const lakisDetail = detail && state.generation.lakis_mode === true;
  const generationActionRow = document.querySelector(".generation-action-row");
  generationActionRow.classList.toggle("mode-fast", !detail);
  generationActionRow.classList.toggle("mode-detail", detail);
  generationActionRow.classList.toggle("mode-lakis-detail", lakisDetail);
  lakisModeButton.classList.toggle("active", state.generation.lakis_mode === true);
  lakisModeButton.setAttribute("aria-checked", String(state.generation.lakis_mode === true));
  document.querySelector("#detailContract").innerHTML = lakisDetail
    ? `<span class="contract-dot on"></span>LAKIS_DETAIL · LAKIS_SCOPE ON`
    : `<span class="contract-dot ${detail ? "on" : ""}"></span>Face · Eye · USDU ${detail ? "ON" : "OFF"}`;
  document.querySelector("#generateHint").textContent = `${generationModeLabel()} · COMPOSITION READY`;
  if (currentGenerationEngine() === "moss") {
    document.querySelector("#detailContract").textContent = "MOSS FAST · 기본 생성 (고정)";
    document.querySelector("#generateHint").textContent = "MOSS · 기본 이미지 생성";
  }
  renderCamera();
  syncGenerationEngineUI();
}

function generationModeLabel(mode = state.generation.mode, lakisMode = state.generation.lakis_mode) {
  if (currentGenerationEngine() === "moss") return mode === "detail"
    ? (lakisMode ? "MOSS LAKIS DETAIL" : "MOSS DETAIL") : "MOSS";
  if (mode === "lakis_detail" || (mode === "detail" && lakisMode === true)) return "LAKIS DETAIL";
  return mode === "detail" ? "DETAIL" : "FAST";
}

function setPreviewModeLabel(mode) {
  const badge = document.querySelector("#previewMode");
  const label = String(mode || "").toUpperCase();
  badge.textContent = label;
  badge.classList.toggle("lakis-detail", label === "LAKIS DETAIL" || label === "MOSS LAKIS DETAIL");
}

modeButtons.forEach(button => button.addEventListener("click", () => {
  if (currentGenerationEngine() === "moss") return;
  state.generation.mode = button.dataset.mode;
  render();
  scheduleGenerationStateSave();
}));

lakisModeButton.addEventListener("click", () => {
  if (currentGenerationEngine() === "moss") return;
  state.generation.lakis_mode = state.generation.lakis_mode !== true;
  state.generation.upscale_engine = state.generation.lakis_mode ? "lakis_scope" : "ultimate";
  render();
  scheduleGenerationStateSave();
});

function canvasPoint(event) {
  const rect = cameraCanvas.getBoundingClientRect();
  return {x:(event.clientX-rect.left)*WIDTH/rect.width,y:(event.clientY-rect.top)*HEIGHT/rect.height};
}
let cameraDrag = null;
cameraCanvas.addEventListener("pointerdown", event => {
  event.preventDefault();
  cameraCanvas.setPointerCapture(event.pointerId);
  const point=canvasPoint(event);
  cameraDrag={mode:event.button===2||event.altKey?"view":"camera",pointerId:event.pointerId,x:point.x,y:point.y,posX:state.camera.x,posY:state.camera.y,viewYaw,viewPitch};
  cameraCanvas.style.cursor=cameraDrag.mode==="view"?"move":"grabbing";
});
cameraCanvas.addEventListener("pointermove", event => {
  if(!cameraDrag||cameraDrag.pointerId!==event.pointerId)return;
  const point=canvasPoint(event);
  if(cameraDrag.mode==="view"){
    viewYaw=cameraDrag.viewYaw-(point.x-cameraDrag.x)/WIDTH*Math.PI*2;
    viewPitch=Math.max(.12,Math.min(1.15,cameraDrag.viewPitch+(point.y-cameraDrag.y)/HEIGHT*1.5));
  }else{
    let value=cameraDrag.posX+(point.x-cameraDrag.x)/(WIDTH/2);
    while(value>1)value-=2; while(value<-1)value+=2;
    state.camera.x=value;
    state.camera.y=clamp(cameraDrag.posY-(point.y-cameraDrag.y)/(HEIGHT/2));
  }
  renderCamera();
});
function stopCameraDrag(event){if(!cameraDrag||cameraDrag.pointerId!==event.pointerId)return;cameraDrag=null;cameraCanvas.style.cursor="crosshair";}
cameraCanvas.addEventListener("pointerup",stopCameraDrag);
cameraCanvas.addEventListener("pointercancel",stopCameraDrag);
cameraCanvas.addEventListener("contextmenu",event=>event.preventDefault());
cameraCanvas.addEventListener("wheel", event => {
  event.preventDefault();
  const amount=event.deltaY*.0003;
  if(event.shiftKey)state.camera.roll=clamp(state.camera.roll-amount*3);
  else state.camera.z=clamp(state.camera.z-amount);
  renderCamera();
}, { passive:false });
cameraCanvas.addEventListener("dblclick",event=>{if(event.shiftKey){viewYaw=0;viewPitch=.42;}else{state.camera.x=0;state.camera.y=0;}renderCamera();});
cameraCanvas.addEventListener("keydown", event => {
  const delta = event.shiftKey ? .1 : .02;
  if (["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(event.key)) event.preventDefault();
  if (event.key === "ArrowLeft") state.camera.x = clamp(state.camera.x - delta);
  if (event.key === "ArrowRight") state.camera.x = clamp(state.camera.x + delta);
  if (event.key === "ArrowUp") state.camera.y = clamp(state.camera.y + delta);
  if (event.key === "ArrowDown") state.camera.y = clamp(state.camera.y - delta);
  renderCamera();
});

for (const [id,key] of [["cameraX","x"],["cameraY","y"],["cameraZ","z"],["cameraRoll","roll"]]) {
  document.querySelector(`#${id}`).addEventListener("change", event => {
    state.camera[key] = clamp(event.target.value);
    renderCamera();
  });
}
document.querySelector("#frameYInput").addEventListener("change", event => {
  state.camera.frame_y = clamp(event.target.value);
  renderCamera();
});
for (const [id,key] of [["cameraXSlider","x"],["cameraYSlider","y"],["cameraZSlider","z"],["frameYSlider","frame_y"],["cameraRollSlider","roll"]]) {
  document.querySelector(`#${id}`).addEventListener("input", event => {
    state.camera[key] = clamp(event.target.value);
    renderCamera();
  });
}

const cameraPresets = {
  front:{x:0,y:0,z:0,roll:0,frame_y:0},
  left:{x:.5,y:0,z:0,roll:0,frame_y:0},
  center:{x:0,y:.35,z:-.45,roll:0,frame_y:0},
  right:{x:-.5,y:0,z:0,roll:0,frame_y:0},
  rear:{x:1,y:0,z:0,roll:0,frame_y:0}
};
document.querySelectorAll("[data-camera-preset]").forEach(button => button.addEventListener("click", () => {
  state.camera = {...cameraPresets[button.dataset.cameraPreset]};
  document.querySelectorAll("[data-camera-preset]").forEach(item => item.classList.toggle("active", item === button));
  renderCamera();
}));
document.querySelector("#cameraReset").addEventListener("click", () => {
  state.camera = {...cameraPresets.center};
  document.querySelectorAll("[data-camera-preset]").forEach(item => item.classList.toggle("active", item.dataset.cameraPreset === "center"));
  renderCamera();
});

function isToyxyzEnabled() {
  return currentGenerationEngine() !== "moss"
    && Boolean(state.scene_controls?.enabled && state.scene_controls.toyxyz_enabled);
}

function syncPoseModeAvailability() {
  const locked = isToyxyzEnabled();
  if (locked) {
    setI2iEnabled(false, false);
    setInpaintEnabled(false, false);
    setCompositionEnabled(false);
  }
  for (const toggle of [i2iToggle, inpaintToggle]) {
    toggle.disabled = locked;
    toggle.setAttribute("aria-disabled", String(locked));
  }
  renderCompositionAvailability();
}

function setCompositionEnabled(enabled) {
  state.composition_enabled = Boolean(enabled) && !isToyxyzEnabled();
  renderCompositionAvailability();
}

function renderCompositionAvailability() {
  const unavailable = state.i2i.enabled || (currentGenerationEngine() === "moss"
    ? engineConfiguration?.moss?.capabilities?.composition !== true
    : state.inpaint.enabled || isToyxyzEnabled());
  const toggle = document.querySelector("#compositionToggle");
  toggle.classList.toggle("on", state.composition_enabled);
  toggle.setAttribute("aria-pressed", String(state.composition_enabled));
  toggle.setAttribute("aria-label", `구도 설정 ${state.composition_enabled ? "끄기" : "켜기"}`);
  toggle.disabled = unavailable;
  toggle.setAttribute("aria-disabled", String(unavailable));
  document.querySelector("#compositionControls").classList.toggle("is-disabled", !state.composition_enabled || unavailable);
}

async function refreshLoraInventory() {
  if (loraInventoryRefreshTask) return loraInventoryRefreshTask;
  loraInventoryRefreshActive = true;
  const engine = currentGenerationEngine();
  loraInventoryRefreshTask = (async () => {
  try {
    const response = await fetch(`/api/lora-options?engine=${engine}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const inventory = await response.json();
    if (engine !== currentGenerationEngine()) return false;
    const options = Array.isArray(inventory.options) ? inventory.options.map(String) : [];
    const signature = String(inventory.signature || JSON.stringify(options));
    if (signature === loraInventorySignature) return false;
    loraInventorySignature = signature;
    loraOptions = options;
    renderLoras();
    return true;
  } catch (error) {
    console.error("Could not refresh LoRA inventory", error);
    return false;
  } finally {
    loraInventoryRefreshActive = false;
    loraInventoryRefreshTask = null;
  }
  })();
  return loraInventoryRefreshTask;
}

function replaceModelOptions(id, configKey, options) {
  const select = document.querySelector(`#${id}`);
  const current = String(select.value || state.model[configKey] || "");
  select.replaceChildren(...options.map(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    return option;
  }));
  if (options.includes(current)) {
    select.value = current;
  } else if (options.length) {
    select.value = options[0];
    state.model[configKey] = options[0];
    scheduleGenerationStateSave();
  }
}

async function refreshModelInventory() {
  if (modelInventoryRefreshPromise) return modelInventoryRefreshPromise;
  const engine = currentGenerationEngine();
  modelInventoryRefreshPromise = (async () => {
    try {
      const response = await fetch("/api/model-options", {
        cache: "no-store", signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const inventory = await response.json();
      if (engine !== currentGenerationEngine()) return false;
      if (inventory.moss) engineConfiguration = { ...engineConfiguration, moss: inventory.moss };
      if (inventory.anima) engineConfiguration = { ...engineConfiguration, anima: inventory.anima };
      const options = engine === "moss" ? inventory.moss?.inventory || {} : inventory.anima?.inventory || inventory;
      const signature = `${engine}:${String(inventory.signature || "")}`;
      if (signature && signature === modelInventorySignature) return false;
      modelInventorySignature = signature;
      replaceModelOptions("checkpointSelect", "checkpoint", Array.isArray(options.checkpoint) ? options.checkpoint.map(String) : []);
      replaceModelOptions("vaeSelect", "vae", Array.isArray(options.vae) ? options.vae.map(String) : []);
      replaceModelOptions("clipSelect", "clip", Array.isArray(options.clip) ? options.clip.map(String) : []);
      syncGenerationEngineUI();
      return true;
    } catch (error) {
      console.error("Could not refresh model inventory", error);
      return false;
    } finally {
      modelInventoryRefreshPromise = null;
    }
  })();
  return modelInventoryRefreshPromise;
}

function refreshExternalModelInventories() {
  refreshLoraInventory();
  refreshModelInventory();
}

window.addEventListener("focus", refreshExternalModelInventories);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshExternalModelInventories();
});

document.querySelector("#compositionToggle").addEventListener("click", () => {
  setCompositionEnabled(!state.composition_enabled);
  scheduleGenerationStateSave();
});

document.querySelector("#outputFolderButton").addEventListener("click", () => {
  window.dispatchEvent(new CustomEvent("lakis:open-image-history"));
});

const workflowButton = document.querySelector("#workflowButton");
const workflowMenu = document.querySelector("#workflowMenu");
const sidebarResourceButton = document.querySelector("#sidebarResourceButton");
const sidebarResourceMenu = document.querySelector("#sidebarResourceMenu");
function closeWorkflowMenu() {
  workflowMenu.hidden = true;
  workflowButton.setAttribute("aria-expanded", "false");
}
function closeSidebarResourceMenu() {
  if (!sidebarResourceMenu || !sidebarResourceButton) return;
  sidebarResourceMenu.hidden = true;
  sidebarResourceButton.setAttribute("aria-expanded", "false");
}
workflowButton.addEventListener("click", event => {
  event.stopPropagation();
  closeSidebarResourceMenu();
  workflowMenu.hidden = !workflowMenu.hidden;
  workflowButton.setAttribute("aria-expanded", String(!workflowMenu.hidden));
});
sidebarResourceButton?.addEventListener("click", event => {
  event.stopPropagation();
  closeWorkflowMenu();
  sidebarResourceMenu.hidden = !sidebarResourceMenu.hidden;
  sidebarResourceButton.setAttribute("aria-expanded", String(!sidebarResourceMenu.hidden));
});
sidebarResourceMenu?.addEventListener("click", event => {
  const option = event.target.closest("[data-resource-url]");
  if (!option) return;
  const url = String(option.dataset.resourceUrl || "");
  closeSidebarResourceMenu();
  if (url) window.open(url, "_blank", "noopener,noreferrer");
});
workflowMenu.addEventListener("click", async event => {
  const option = event.target.closest("[data-workflow-kind]");
  if (!option) return;
  const kind = option.dataset.workflowKind;
  closeWorkflowMenu();
  const workflowWindow = window.open("about:blank", "_blank");
  try {
    const response = await fetch("/api/open-workflow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, engine: currentGenerationEngine() }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw Object.assign(new Error(result.error || `HTTP ${response.status}`), { code: result.code || "" });
    if (workflowWindow) workflowWindow.location.replace(result.comfy_url || "http://127.0.0.1:8189/");
    else window.open(result.comfy_url || "http://127.0.0.1:8189/", "_blank", "noopener");
  } catch (error) {
    workflowWindow?.close();
    showGenerationError(error.message || "LAKIS 워크플로를 열지 못했어요.", error.code || "");
  }
});

let latestSystemStatus = null;
const gib = bytes => bytes ? bytes / (1024 ** 3) : 0;
function setMeter(id, used, total) {
  document.querySelector(`#${id}`).style.width = `${total ? Math.min(100, used / total * 100) : 0}%`;
}
async function refreshSystemStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const status = await response.json();
    latestSystemStatus = status;
    if (status.engine_configuration) {
      engineConfiguration = { ...engineConfiguration, ...status.engine_configuration };
      syncGenerationEngineUI();
    }
    document.querySelector("#workflowVersion").textContent = status.lakis_version || status.workflow_version
      ? `v${status.lakis_version || status.workflow_version}` : status.model || "프로토타입";
    const backendRunning = status.comfyui_running ?? status.backend_ready;
    document.querySelector("#comfyStatusText").textContent = backendRunning ? "실행 중" : "연결 안 됨";
    document.querySelector("#comfyStatusDot").className = `footer-dot ${backendRunning ? "online" : "offline"}`;
    const vramUsed = Math.max(0, status.vram_total - status.vram_free);
    const ramUsed = Math.max(0, status.ram_total - status.ram_free);
    document.querySelector("#vramText").textContent = status.vram_total ? `${gib(vramUsed).toFixed(1)} / ${gib(status.vram_total).toFixed(0)} GB` : "-- / -- GB";
    document.querySelector("#ramText").textContent = status.ram_total ? `${gib(ramUsed).toFixed(1)} / ${gib(status.ram_total).toFixed(0)} GB` : "-- / -- GB";
    document.querySelector("#cpuText").textContent = status.cpu_percent == null ? "--%" : `${status.cpu_percent.toFixed(0)}%`;
    setMeter("vramMeter", vramUsed, status.vram_total);
    setMeter("ramMeter", ramUsed, status.ram_total);
  } catch (_) {
    document.querySelector("#comfyStatusText").textContent = "브리지 연결 안 됨";
    document.querySelector("#comfyStatusDot").className = "footer-dot offline";
  }
}
refreshSystemStatus();
setInterval(refreshSystemStatus, 3000);

document.querySelectorAll("[data-prompt-panel]").forEach(button => {
  button.addEventListener("click", () => {
    const panel = document.querySelector(`#${button.dataset.promptPanel}`);
    if (!panel.hidden) return;
    const group = button.closest("[data-prompt-group]");
    group.querySelectorAll("[data-prompt-panel]").forEach(item => {
      item.classList.remove("active");
      item.setAttribute("aria-expanded", "false");
      document.querySelector(`#${item.dataset.promptPanel}`).hidden = true;
    });
    panel.hidden = false;
    button.classList.add("active");
    button.setAttribute("aria-expanded", "true");
    panel.querySelector("textarea")?.focus();
    markPromptStateDirty();
  });
});

const promptMaximizeMedia = window.matchMedia("(min-width: 1181px)");
const promptColumn = document.querySelector(".prompt-column");
const previewColumn = document.querySelector(".preview-column");
const positivePromptPanel = promptColumn?.querySelector(".prompt-panel:not(.negative-prompt-panel)");
const negativePromptPanel = promptColumn?.querySelector(".negative-prompt-panel");
const positivePromptMaximizeButton = document.querySelector("#positivePromptMaximizeButton");
const negativePromptMaximizeButton = document.querySelector("#negativePromptMaximizeButton");
const promptTranslationControl = document.querySelector(".prompt-translation-toggle");
const positivePromptHeadingRow = positivePromptPanel?.querySelector(".prompt-heading-row");
const positivePromptTools = positivePromptPanel?.querySelector(".prompt-tools");

function syncPromptDesktopControls() {
  if (!promptTranslationControl || !positivePromptHeadingRow || !positivePromptTools) return;
  if (promptMaximizeMedia.matches) positivePromptHeadingRow.append(promptTranslationControl);
  else positivePromptTools.insertBefore(promptTranslationControl, positivePromptMaximizeButton);
}

function activePromptTextarea(panel) {
  const activePanel = panel?.querySelector(".fixed-prompt-panel:not([hidden])");
  return activePanel?.querySelector("textarea") || panel?.querySelector("textarea");
}

function updatePromptMaximizeButton(button, maximized, label) {
  if (!button) return;
  button.classList.toggle("active", maximized);
  button.setAttribute("aria-expanded", String(maximized));
  const icon = button.querySelector("span");
  if (icon) icon.textContent = maximized ? ">>" : "<<";
  const text = button.querySelector("strong");
  if (text) text.textContent = maximized ? "축소" : "확장";
}

function restorePromptPanel(panel, button, label) {
  if (!panel) return;
  panel.classList.remove("prompt-panel-maximized");
  panel.style.removeProperty("--prompt-max-offset-left");
  panel.style.removeProperty("--prompt-max-width");
  updatePromptMaximizeButton(button, false, label);
}

function setPromptPanelMaximized(panel, button, label, enabled) {
  if (!panel || !promptColumn) return;
  const maximized = Boolean(enabled && promptMaximizeMedia.matches && previewColumn);
  const otherPanel = panel === positivePromptPanel ? negativePromptPanel : positivePromptPanel;
  const otherButton = panel === positivePromptPanel ? negativePromptMaximizeButton : positivePromptMaximizeButton;
  const otherLabel = panel === positivePromptPanel ? "네거티브 프롬프트" : "긍정 프롬프트";
  restorePromptPanel(otherPanel, otherButton, otherLabel);

  if (!maximized) {
    restorePromptPanel(panel, button, label);
    promptColumn.classList.remove("prompt-panel-maximize-active");
    document.body.classList.remove("prompt-maximize-active");
    return;
  }

  const panelRect = panel.getBoundingClientRect();
  const previewRect = previewColumn.getBoundingClientRect();
  const promptRect = promptColumn.getBoundingClientRect();
  panel.style.setProperty("--prompt-max-offset-left", (previewRect.left - panelRect.left) + "px");
  panel.style.setProperty("--prompt-max-width", (promptRect.right - previewRect.left) + "px");
  panel.classList.add("prompt-panel-maximized");
  promptColumn.classList.add("prompt-panel-maximize-active");
  document.body.classList.add("prompt-maximize-active");
  updatePromptMaximizeButton(button, true, label);
  requestAnimationFrame(() => activePromptTextarea(panel)?.focus({ preventScroll: true }));
}

positivePromptMaximizeButton?.addEventListener("click", () => {
  setPromptPanelMaximized(
    positivePromptPanel,
    positivePromptMaximizeButton,
    "긍정 프롬프트",
    !positivePromptPanel?.classList.contains("prompt-panel-maximized"),
  );
});
negativePromptMaximizeButton?.addEventListener("click", () => {
  setPromptPanelMaximized(
    negativePromptPanel,
    negativePromptMaximizeButton,
    "네거티브 프롬프트",
    !negativePromptPanel?.classList.contains("prompt-panel-maximized"),
  );
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if (positivePromptPanel?.classList.contains("prompt-panel-maximized")) {
    setPromptPanelMaximized(positivePromptPanel, positivePromptMaximizeButton, "긍정 프롬프트", false);
  } else if (negativePromptPanel?.classList.contains("prompt-panel-maximized")) {
    setPromptPanelMaximized(negativePromptPanel, negativePromptMaximizeButton, "네거티브 프롬프트", false);
  }
});
const handlePromptMaximizeMediaChange = event => {
  syncPromptDesktopControls();
  if (event.matches) return;
  restorePromptPanel(positivePromptPanel, positivePromptMaximizeButton, "긍정 프롬프트");
  restorePromptPanel(negativePromptPanel, negativePromptMaximizeButton, "네거티브 프롬프트");
  promptColumn?.classList.remove("prompt-panel-maximize-active");
  document.body.classList.remove("prompt-maximize-active");
};
syncPromptDesktopControls();
if (promptMaximizeMedia.addEventListener) promptMaximizeMedia.addEventListener("change", handlePromptMaximizeMediaChange);
else promptMaximizeMedia.addListener(handlePromptMaximizeMediaChange);

const promptInputBindings = [
  ["fixedPromptInput", "fixed"], ["generalPromptInput", "general"],
  ["qualityPromptInput", "quality"], ["artistPromptInput", "artist"],
  ["triggerPromptInput", "trigger"],
  ["negativeFixedPromptInput", "negative_fixed"],
  ["negativeQualityPromptInput", "negative_quality"],
  ["negativeArtistPromptInput", "negative_artist"],
  ["negativePrompt", "negative"],
];
const promptStateInputIds = {
  general: "generalPromptInput", quality: "qualityPromptInput",
  artist: "artistPromptInput", trigger: "triggerPromptInput",
  fixed: "fixedPromptInput", negative: "negativePrompt",
  negative_quality: "negativeQualityPromptInput",
  negative_artist: "negativeArtistPromptInput",
  negative_fixed: "negativeFixedPromptInput",
};

const promptTranslationToggle = document.querySelector("#promptTranslationToggle");
try {
  const savedTranslation = localStorage.getItem(TRANSLATION_STORAGE_KEY);
  state.translation_enabled = savedTranslation === null ? true : savedTranslation === "true";
} catch (_) {
  state.translation_enabled = true;
}
promptTranslationToggle.checked = state.translation_enabled;
promptTranslationToggle.addEventListener("change", event => {
  state.translation_enabled = Boolean(event.target.checked);
  try {
    localStorage.setItem(TRANSLATION_STORAGE_KEY, String(state.translation_enabled));
  } catch (_) {}
  markPromptStateDirty();
});

const containsKoreanPrompt = value => /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/u.test(String(value || ""));

async function translatedPromptForGeneration(prompt, forceTranslation = false) {
  const original = structuredClone(prompt);
  if (runtimeCapabilities.translation === false) return original;
  if ((!state.translation_enabled && !forceTranslation) || !Object.values(original).some(containsKoreanPrompt)) return original;
  const response = await fetch("/api/translate-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: original }),
  });
  const result = await response.json();
  if (!response.ok || !result.ok || !result.prompt) {
    throw new Error(result.error || "프롬프트 자동 번역에 실패했어요.");
  }
  return result.prompt;
}

async function translatedMossRegionsForGeneration(mossRegions) {
  const translatedRegions = structuredClone(mossRegions);
  if (!translatedRegions.enabled) return translatedRegions;
  // Translate each region separately to stay within the prompt API's limit.
  // Keep exact image text, coordinates and the saved editor source untouched.
  for (const region of translatedRegions.regions) {
    const translated = await translatedPromptForGeneration({
      caption: region.caption || "",
      negative_prompt: region.negative_prompt || "",
    });
    region.caption = translated.caption;
    region.negative_prompt = translated.negative_prompt;
  }
  return translatedRegions;
}

async function translatedInpaintForGeneration(inpaint) {
  const translatedInpaint = structuredClone(inpaint);
  if (!translatedInpaint.enabled) return translatedInpaint;
  if (translatedInpaint.operation === "remove") {
    translatedInpaint.prompt = "";
    translatedInpaint.negative_prompt = "";
    return translatedInpaint;
  }
  const translated = await translatedPromptForGeneration({
    inpaint_positive: translatedInpaint.prompt || "",
    inpaint_negative: translatedInpaint.negative_prompt || "",
  }, true);
  translatedInpaint.prompt = translated.inpaint_positive || "";
  translatedInpaint.negative_prompt = translated.inpaint_negative || "";
  return translatedInpaint;
}

function syncPromptStateFromInputs() {
  for (const [id, key] of promptInputBindings) {
    state.prompt[key] = document.querySelector(`#${id}`).value;
  }
}

function loadLocalPromptState() {
  try {
    const raw = localStorage.getItem(PROMPT_STORAGE_KEY);
    if (raw) {
      const value = JSON.parse(raw);
      return value && typeof value === "object" ? value : {};
    }
    const legacyDekisRaw = localStorage.getItem(LEGACY_DEKIS_PROMPT_STORAGE_KEY);
    if (legacyDekisRaw) {
      const legacyDekis = JSON.parse(legacyDekisRaw);
      if (legacyDekis && typeof legacyDekis === "object") {
        localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(legacyDekis));
        return legacyDekis;
      }
    }
    const legacy = JSON.parse(localStorage.getItem(LEGACY_PROMPT_STORAGE_KEY) || "null");
    if (legacy && typeof legacy === "object") {
      const migrated = { schema: 1, prompt: legacy, dirty: true, revision: 0, updated_at: Date.now() / 1000 };
      localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(migrated));
      return migrated;
    }
    return {};
  } catch (_) {
    return {};
  }
}

function currentPromptUiState() {
  const active = group => group?.querySelector("[data-prompt-panel].active")?.dataset.promptPanel || "";
  const groups = [...document.querySelectorAll("[data-prompt-group]")];
  return { positive_tab: active(groups[0]), negative_tab: active(groups[1]) };
}

function restorePromptUiState(promptUi) {
  if (!promptUi || typeof promptUi !== "object") return;
  const requested = new Set([promptUi.positive_tab, promptUi.negative_tab].filter(Boolean));
  for (const group of document.querySelectorAll("[data-prompt-group]")) {
    const buttons = [...group.querySelectorAll("[data-prompt-panel]")];
    const selected = buttons.find(button => requested.has(button.dataset.promptPanel));
    if (!selected) continue;
    for (const button of buttons) {
      const active = button === selected;
      button.classList.toggle("active", active);
      button.setAttribute("aria-expanded", String(active));
      document.querySelector(`#${button.dataset.promptPanel}`).hidden = !active;
    }
  }
}

function promptPersistencePayload() {
  syncPromptStateFromInputs();
  return {
    prompt: structuredClone(state.prompt),
    prompt_enabled: structuredClone(state.prompt_enabled || {}),
    inpaint_prompt: {
      prompt: String(state.inpaint.prompt || ""),
      negative_prompt: String(state.inpaint.negative_prompt || ""),
    },
    translation_enabled: state.translation_enabled !== false,
    prompt_ui: currentPromptUiState(),
  };
}

promptStateObserved = structuredClone(promptPersistencePayload());
function capturePendingPromptStateEdits() {
  if (promptStateHydrated || applyingWorkflowConfiguration) return;
  const current = structuredClone(promptPersistencePayload());
  recordStateEdits(promptStateObserved, current, pendingPromptStateEdits);
  promptStateObserved = current;
}

for (const eventName of ["click", "input", "change", "pointermove", "wheel", "keydown", "dblclick"]) {
  document.addEventListener(eventName, () => {
    if (applyingWorkflowConfiguration || (generationStateHydrated && promptStateHydrated)) return;
    queueMicrotask(() => {
      capturePendingGenerationStateEdits();
      capturePendingPromptStateEdits();
    });
  }, true);
}

function applyPromptStateSnapshot(snapshot) {
  state.prompt = structuredClone(snapshot.prompt || {});
  for (const [key, id] of Object.entries(promptStateInputIds)) {
    const value = Object.prototype.hasOwnProperty.call(state.prompt, key) ? String(state.prompt[key] || "") : "";
    state.prompt[key] = value;
    document.querySelector(`#${id}`).value = value;
  }
  state.prompt_enabled = structuredClone(snapshot.prompt_enabled || {});
  const inpaintPrompt = snapshot.inpaint_prompt || {};
  state.inpaint.prompt = String(inpaintPrompt.prompt || "").slice(0, 4000);
  state.inpaint.negative_prompt = String(inpaintPrompt.negative_prompt || "").slice(0, 4000);
  inpaintPromptInput.value = state.inpaint.prompt;
  inpaintNegativePromptInput.value = state.inpaint.negative_prompt;
  inpaintPromptCount.textContent = `${state.inpaint.prompt.length} / 4000`;
  inpaintNegativePromptCount.textContent = `${state.inpaint.negative_prompt.length} / 4000`;
  state.translation_enabled = snapshot.translation_enabled !== false;
  promptTranslationToggle.checked = state.translation_enabled;
  restorePromptUiState(snapshot.prompt_ui || {});
}

function saveLocalPromptState(dirty = promptStateDirty) {
  try {
    localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify({
      schema: 1, ...promptPersistencePayload(), dirty,
      revision: promptStateRevision, updated_at: Date.now() / 1000,
    }));
  } catch (error) {
    console.error("Could not persist browser-local prompt state", error);
  }
}

let promptSaveTimer = null;
function markPromptStateDirty() {
  if (applyingWorkflowConfiguration) return;
  if (!promptStateHydrated) {
    capturePendingPromptStateEdits();
    return;
  }
  promptStateDirty = true;
  saveLocalPromptState(true);
  schedulePromptStateSave();
}

async function flushPromptState({ beacon = false } = {}) {
  clearTimeout(promptSaveTimer);
  if (!promptStateHydrated || !promptStateDirty) return;
  const payload = promptPersistencePayload();
  saveLocalPromptState(true);
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon("/api/prompt-state", new Blob([JSON.stringify(payload)], { type: "application/json" }));
    return;
  }
  try {
    const response = await fetch("/api/prompt-state", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), keepalive: true,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const saved = await response.json();
    promptStateRevision = Number(saved.revision || promptStateRevision);
    promptStateDirty = false;
    saveLocalPromptState(false);
  } catch (error) {
    promptStateDirty = true;
    saveLocalPromptState(true);
    console.error("Could not persist LAKIS prompt state", error);
  }
}

function schedulePromptStateSave() {
  clearTimeout(promptSaveTimer);
  promptSaveTimer = setTimeout(() => flushPromptState(), 500);
}

for (const [id, key] of promptInputBindings) {
  document.querySelector(`#${id}`).addEventListener("input", event => {
    state.prompt[key] = event.target.value;
    markPromptStateDirty();
  });
  document.querySelector(`#${id}`).addEventListener("blur", () => flushPromptState());
}

for (const [id,key] of [["checkpointSelect","checkpoint"],["vaeSelect","vae"],
  ["clipSelect","clip"],["samplerSelect","sampler"],["schedulerSelect","scheduler"],
  ["stepsInput","steps"],["cfgInput","cfg"]]) {
  document.querySelector(`#${id}`).addEventListener("change", event => {
    state.model[key] = ["steps", "cfg"].includes(key) ? Number(event.target.value) : event.target.value;
    scheduleGenerationStateSave();
  });
}

function populateWorkflowSelect(id, configKey, config) {
  const select = document.querySelector(`#${id}`);
  select.replaceChildren(...config.options.map(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    return option;
  }));
  select.value = config.current;
  state.model[configKey] = config.current;
  select.title = `${config.loader_class} · ${config.options.length} options`;
}

async function refreshWorkflowConfiguration() {
  try {
    const response = await fetch("/api/workflow-config", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    engineConfiguration = config.engine_configuration || null;
    runtimeCapabilities = config.capabilities || {};
    applyingWorkflowConfiguration = true;
    if (loraManagerLink && Number(config.comfy_port)) {
      loraManagerLink.href = `http://127.0.0.1:${Number(config.comfy_port)}/loras`;
    }
    populateWorkflowSelect("checkpointSelect", "checkpoint", config.checkpoint);
    populateWorkflowSelect("vaeSelect", "vae", config.vae);
    populateWorkflowSelect("clipSelect", "clip", config.clip);
    modelInventorySignature = "";
    populateWorkflowSelect("samplerSelect", "sampler", config.sampler);
    populateWorkflowSelect("schedulerSelect", "scheduler", config.scheduler);
    const savedGeneration = config.generation_state || {};
    Object.assign(state.camera, savedGeneration.camera || {});
    setCompositionEnabled(savedGeneration.composition_enabled !== false);
    state.wildcard_enabled = savedGeneration.wildcard_enabled === true;
    window.lakisApplyWildcardState?.(state.wildcard_enabled);
    state.wildcard_exclusions = savedGeneration.wildcard_exclusions && typeof savedGeneration.wildcard_exclusions === "object"
      ? structuredClone(savedGeneration.wildcard_exclusions) : {};
    window.lakisApplyWildcardExclusions?.(state.wildcard_exclusions);
    Object.assign(state.continuous, savedGeneration.continuous || {});
    state.continuous.count = Math.max(1, Math.min(20, Number(state.continuous.count) || 1));
    syncContinuousControls();
    renderCamera();
    Object.assign(state.generation, savedGeneration.generation || {});
    Object.assign(state.i2i, savedGeneration.i2i || {});
    syncI2iControls();
    if (currentGenerationEngine() === "moss" && !["fast", "detail"].includes(state.generation.mode)) {
      state.generation.mode = "fast";
    }
    state.moss_regions = structuredClone(savedGeneration.moss_regions || { enabled: false, regions: [] });
    Object.assign(state.moss_detail, savedGeneration.moss_detail || {});
    window.LAKISMossRegions?.restore(state.moss_regions);
    Object.assign(state.model, savedGeneration.model || {});
    if (currentGenerationEngine() === "moss") {
      Object.assign(state.model, engineConfiguration?.moss?.defaults?.model || {}, savedGeneration.model || {});
      for (const key of ["clip", "vae"]) {
        state.model[key] = engineConfiguration?.moss?.defaults?.model[key] || state.model[key];
      }
    }
    Object.assign(state.output, savedGeneration.output || {});
    state.node_overrides = savedGeneration.node_overrides && typeof savedGeneration.node_overrides === "object"
      ? structuredClone(savedGeneration.node_overrides)
      : {};
    state.moss_node_overrides = isStateRecord(savedGeneration.moss_node_overrides)
      ? structuredClone(savedGeneration.moss_node_overrides) : {};
    for (const [id, key] of [["checkpointSelect", "checkpoint"], ["samplerSelect", "sampler"], ["schedulerSelect", "scheduler"],
      ["stepsInput", "steps"], ["cfgInput", "cfg"]]) {
      document.querySelector(`#${id}`).value = state.model[key];
    }
    for (const [id, key] of [["imageWidth", "width"], ["imageHeight", "height"], ["seedInput", "seed"]]) {
      document.querySelector(`#${id}`).value = state.output[key];
    }
    document.querySelector("#aspectRatioLock").checked = state.output.aspect_locked === true;
    lockedAspectRatio = clampImageDimension(state.output.width) / clampImageDimension(state.output.height);
    document.querySelectorAll("[data-seed-mode]").forEach(button => {
      button.classList.toggle("active", button.dataset.seedMode === state.output.seed_mode);
    });
    loraOptions = Array.isArray(config.lora?.options) ? config.lora.options : [];
    loraInventorySignature = "";
    state.lora_enabled = config.lora?.enabled !== false;
    const allLorasToggle = document.querySelector("#allLorasToggle");
    allLorasToggle.classList.toggle("on", state.lora_enabled);
    allLorasToggle.setAttribute("aria-pressed", String(state.lora_enabled));
    document.querySelector("#loraList").classList.toggle("all-disabled", !state.lora_enabled);
    state.loras = Array.isArray(config.lora?.current)
      ? config.lora.current.map(item => ({
          name: String(item.name || ""),
          enabled: Boolean(item.enabled),
          strength: Number(item.strength ?? 1),
        }))
      : [];
    const generationStateBase = structuredClone(persistedGenerationState());
    lastSavedGenerationState = JSON.stringify(generationStateBase);
    const mergedGenerationState = structuredClone(generationStateBase);
    applyStateEdits(mergedGenerationState, pendingGenerationStateEdits);
    applyPersistedGenerationState(mergedGenerationState);
    syncEditedGenerationControls(pendingGenerationStateEdits);
    renderLoras();
    refreshLoraInventory();
    const localPrompt = loadLocalPromptState();
    const serverPromptState = config.prompt_state && typeof config.prompt_state === "object"
      ? config.prompt_state : {};
    // A dirty cache is a recovery source only while the server is still at the
    // revision from which that edit started.  If another PC/mobile session has
    // already advanced the server revision, that newer canonical state wins.
    const recoverLocal = localPrompt.dirty === true
      && localPrompt.prompt && typeof localPrompt.prompt === "object"
      && Number(localPrompt.revision || 0) >= Number(serverPromptState.revision || 0);
    const selectedPrompt = recoverLocal ? localPrompt.prompt : (serverPromptState.prompt || config.prompt || {});
    for (const [key, id] of Object.entries(promptStateInputIds)) {
      const source = Object.prototype.hasOwnProperty.call(selectedPrompt, key) ? selectedPrompt[key] : "";
      const value = String(source || "");
      state.prompt[key] = value;
      document.querySelector(`#${id}`).value = value;
    }
    state.prompt_enabled = structuredClone(
      (recoverLocal ? localPrompt.prompt_enabled : serverPromptState.prompt_enabled)
      || config.prompt_enabled || {}
    );
    const inpaintPrompt = (recoverLocal ? localPrompt.inpaint_prompt : serverPromptState.inpaint_prompt) || {};
    state.inpaint.prompt = String(inpaintPrompt.prompt || "").slice(0, 4000);
    state.inpaint.negative_prompt = String(inpaintPrompt.negative_prompt || "").slice(0, 4000);
    inpaintPromptInput.value = state.inpaint.prompt;
    inpaintNegativePromptInput.value = state.inpaint.negative_prompt;
    inpaintPromptCount.textContent = `${state.inpaint.prompt.length} / 4000`;
    inpaintNegativePromptCount.textContent = `${state.inpaint.negative_prompt.length} / 4000`;
    const translationSource = recoverLocal ? localPrompt.translation_enabled : serverPromptState.translation_enabled;
    if (typeof translationSource === "boolean") {
      state.translation_enabled = translationSource;
      promptTranslationToggle.checked = translationSource;
    }
    restorePromptUiState((recoverLocal ? localPrompt.prompt_ui : serverPromptState.prompt_ui) || {});
    const hydratedPromptState = structuredClone(promptPersistencePayload());
    const hadPendingPromptEdits = pendingPromptStateEdits.size > 0;
    applyStateEdits(hydratedPromptState, pendingPromptStateEdits);
    applyPromptStateSnapshot(hydratedPromptState);
    promptStateRevision = Number(serverPromptState.revision || 0);
    promptStateDirty = recoverLocal || hadPendingPromptEdits;
    promptStateHydrated = true;
    saveLocalPromptState(promptStateDirty);
    if (promptStateDirty) schedulePromptStateSave();
    window.dispatchEvent(new CustomEvent("lakis-prompt-state-loaded"));
    // The initial render happens before this asynchronous configuration is
    // available. Refresh engine-dependent labels once the saved DEV engine
    // has been restored (USDU for Ultimate, SCOPE for LAKIS_SCOPE).
    render();
    generationStateObserved = structuredClone(persistedGenerationState());
    promptStateObserved = structuredClone(promptPersistencePayload());
    const hadPendingGenerationEdits = pendingGenerationStateEdits.size > 0;
    pendingGenerationStateEdits.clear();
    pendingPromptStateEdits.clear();
    generationStateHydrated = true;
    syncGenerationEngineUI();
    applyingWorkflowConfiguration = false;
    if (hadPendingGenerationEdits) scheduleGenerationStateSave();
  } catch (error) {
    applyingWorkflowConfiguration = false;
    console.error("Could not load ComfyUI workflow model configuration", error);
  }
}
workflowConfigurationReady = refreshWorkflowConfiguration();

function syncOutputStateFromInputs() {
  for (const [id, key] of [["imageWidth", "width"], ["imageHeight", "height"]]) {
    const input = document.querySelector(`#${id}`);
    const value = clampImageDimension(input.value);
    input.value = String(value);
    state.output[key] = value;
  }
  const seed = Number(document.querySelector("#seedInput").value);
  if (Number.isFinite(seed)) state.output.seed = seed;
}

const aspectRatioLock = document.querySelector("#aspectRatioLock");
const sizeInputs = {
  width: document.querySelector("#imageWidth"),
  height: document.querySelector("#imageHeight"),
};
let lockedAspectRatio = state.output.width / state.output.height;
let syncingAspectRatio = false;

function clampImageDimension(value) {
  const bounded = Math.max(64, Math.min(8192, Math.round(Number(value) || 64)));
  return Math.round(bounded / 16) * 16;
}

function syncLockedImageDimension(changedKey) {
  if (!aspectRatioLock.checked || syncingAspectRatio || !Number.isFinite(lockedAspectRatio) || lockedAspectRatio <= 0) return;
  const otherKey = changedKey === "width" ? "height" : "width";
  const changedValue = clampImageDimension(sizeInputs[changedKey].value);
  const calculated = changedKey === "width" ? changedValue / lockedAspectRatio : changedValue * lockedAspectRatio;
  // Anima/Spectrum requires an even latent width/height, so keep dimensions
  // on a 16-pixel boundary. Preserve the
  // locked ratio as closely as possible while keeping the paired value valid.
  const pairedValue = clampImageDimension(Math.round(calculated / 16) * 16);
  syncingAspectRatio = true;
  sizeInputs[otherKey].value = String(pairedValue);
  state.output[otherKey] = pairedValue;
  syncingAspectRatio = false;
}

for (const [key, input] of Object.entries(sizeInputs)) {
  input.addEventListener("input", event => {
    const value = Number(event.target.value);
    if (!Number.isFinite(value)) return;
    state.output[key] = clampImageDimension(value);
    syncLockedImageDimension(key);
    scheduleGenerationStateSave();
  });
  input.addEventListener("change", event => {
    event.target.value = String(clampImageDimension(event.target.value));
    event.target.dispatchEvent(new Event("input", { bubbles: true }));
  });
  input.addEventListener("wheel", event => {
    event.preventDefault();
    const step = Number(input.step) || 64;
    input.value = String(clampImageDimension(Number(input.value) + (event.deltaY < 0 ? step : -step)));
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, { passive: false });
}

aspectRatioLock.addEventListener("change", () => {
  state.output.aspect_locked = aspectRatioLock.checked;
  if (aspectRatioLock.checked) {
    const width = clampImageDimension(sizeInputs.width.value);
    const height = clampImageDimension(sizeInputs.height.value);
    lockedAspectRatio = width / height;
  }
  scheduleGenerationStateSave();
});

document.querySelector("#seedInput").addEventListener("input", event => {
  const value = Number(event.target.value);
  if (!Number.isFinite(value)) return;
  state.output.seed = value;
  scheduleGenerationStateSave();
});
document.querySelectorAll("[data-seed-mode]").forEach(button => button.addEventListener("click", () => {
  state.output.seed_mode = button.dataset.seedMode;
  document.querySelectorAll("[data-seed-mode]").forEach(item => item.classList.toggle("active", item === button));
  document.querySelector("#seedInput").classList.toggle("seed-locked", state.output.seed_mode === "current");
  scheduleGenerationStateSave();
}));

const previewHistoryStrip = document.querySelector(".history-strip");
const previewThumbnailObserver = "IntersectionObserver" in window
  ? new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const image = entry.target;
        if (image.dataset.src && !image.src) image.src = image.dataset.src;
        delete image.dataset.src;
        previewThumbnailObserver.unobserve(image);
      }
    }, { root: previewHistoryStrip, rootMargin: "0px 150%", threshold: 0.01 })
  : null;
const previewHistoryMutationObserver = previewThumbnailObserver
  ? new MutationObserver(records => {
      for (const record of records) for (const node of record.removedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.matches("img")) previewThumbnailObserver.unobserve(node);
        node.querySelectorAll?.("img").forEach(image => previewThumbnailObserver.unobserve(image));
      }
    })
  : null;
previewHistoryMutationObserver?.observe(previewHistoryStrip, { childList: true, subtree: true });
window.addEventListener("beforeunload", () => {
  previewThumbnailObserver?.disconnect();
  previewHistoryMutationObserver?.disconnect();
}, { once: true });

function observePreviewThumbnail(image, source) {
  image.loading = "lazy";
  image.decoding = "async";
  if (!previewThumbnailObserver) {
    image.src = source;
    return;
  }
  image.dataset.src = source;
  previewThumbnailObserver.observe(image);
}

previewHistoryStrip.addEventListener("click", event => {
  const button = event.target.closest(".history-thumb");
  if (!button) return;
  document.querySelectorAll(".history-thumb").forEach(item => item.classList.remove("selected"));
  button.classList.add("selected");
  document.querySelector("#previewImage").src = button.dataset.sourceUrl || button.querySelector("img").src;
  setCurrentPreviewPrompt(button._lakisPrompt || null);
  if (button.dataset.mode) {
    setPreviewModeLabel(button.dataset.mode);
  }
  document.querySelector("#previewI2i").hidden = button.dataset.i2i !== "true";
  if (button.dataset.seed) {
    document.querySelector("#previewSeed").textContent = `SEED ${button.dataset.seed}`;
  }
  const durationBadge = document.querySelector("#previewDuration");
  if (button.dataset.duration) {
    durationBadge.textContent = `${Number(button.dataset.duration).toFixed(1)}초`;
    durationBadge.hidden = false;
  } else {
    durationBadge.hidden = true;
  }
  if (state.output.seed_mode === "current" && button.dataset.seed) {
    state.output.seed = Number(button.dataset.seed);
    document.querySelector("#seedInput").value = state.output.seed;
  }
});

const i2iToggle = document.querySelector("#i2iToggle");
const i2iFileInput = document.querySelector("#i2iFileInput");
const i2iDropZone = document.querySelector("#i2iDropZone");
const i2iPreview = document.querySelector("#i2iPreview");
const i2iPlaceholder = document.querySelector("#i2iPlaceholder");
const i2iDenoise = document.querySelector("#i2iDenoise");
const i2iDenoiseNumber = document.querySelector("#i2iDenoiseNumber");
const i2iRemove = document.querySelector("#i2iRemove");
const i2iStatus = document.querySelector("#i2iStatus");
const i2iAutoSize = document.querySelector("#i2iAutoSize");
const i2iPreviewUrls = new Map();
const inpaintToggle = document.querySelector("#inpaintToggle");
const inpaintCanvas = document.querySelector("#inpaintCanvas");
const inpaintControls = document.querySelector("#inpaintControls");
const inpaintBrushSize = document.querySelector("#inpaintBrushSize");
const inpaintGrowMask = document.querySelector("#inpaintGrowMask");
const inpaintDenoise = document.querySelector("#inpaintDenoise");
const inpaintStrength = document.querySelector("#inpaintStrength");
const inpaintStatus = document.querySelector("#inpaintStatus");
const inpaintErase = document.querySelector("#inpaintErase");
const inpaintGeneratedGallery = document.querySelector("#inpaintGeneratedGallery");
const inpaintFileInput = document.querySelector("#inpaintFileInput");
const inpaintEditor = document.querySelector("#inpaintEditor");
const inpaintPreview = document.querySelector("#inpaintPreview");
const inpaintPlaceholder = document.querySelector("#inpaintPlaceholder");
const inpaintRemove = document.querySelector("#inpaintRemove");
const inpaintPromptPanel = document.querySelector("#inpaintPromptPanel");
const inpaintPromptInput = document.querySelector("#inpaintPromptInput");
const inpaintPromptCount = document.querySelector("#inpaintPromptCount");
const inpaintNegativePromptInput = document.querySelector("#inpaintNegativePromptInput");
const inpaintNegativePromptCount = document.querySelector("#inpaintNegativePromptCount");
const inpaintOperationButtons = [...document.querySelectorAll("[data-inpaint-operation]")];
let inpaintDrawing = false;
let inpaintErasing = false;
let inpaintLastPoint = null;
let inpaintDirty = false;

function sameOriginMediaUrl(sourceUrl) {
  const parsed = new URL(sourceUrl, window.location.href);
  return parsed.pathname === "/view"
    ? `/api/comfy-view?${parsed.searchParams.toString()}`
    : sourceUrl;
}

function thumbnailMediaUrl(sourceUrl) {
  const original = sameOriginMediaUrl(sourceUrl);
  const parsed = new URL(original, window.location.href);
  const query = new URLSearchParams();
  if (parsed.pathname === "/api/history-image") {
    query.set("id", parsed.searchParams.get("id") || "");
  } else if (parsed.pathname === "/api/comfy-view") {
    query.set("filename", parsed.searchParams.get("filename") || "");
    query.set("subfolder", parsed.searchParams.get("subfolder") || "");
    query.set("type", parsed.searchParams.get("type") || "output");
  } else {
    return original;
  }
  return `/api/thumbnail?${query.toString()}`;
}

const PREVIEW_HISTORY_MAX_ITEMS = 20;

function trimPreviewHistory() {
  if (!previewHistoryStrip) return;
  while (previewHistoryStrip.children.length > PREVIEW_HISTORY_MAX_ITEMS) {
    previewHistoryStrip.lastElementChild?.remove();
  }
}

function syncInpaintGeneratedGallery() {
  const history = [...document.querySelectorAll(".history-strip .history-thumb")];
  inpaintGeneratedGallery.replaceChildren();
  if (!history.length) {
    const empty = document.createElement("span");
    empty.className = "inpaint-gallery-empty";
    empty.textContent = "아직 생성된 이미지가 없습니다.";
    inpaintGeneratedGallery.append(empty);
    return;
  }
  history.slice(0, 12).forEach((historyButton, index) => {
    const sourceImage = historyButton.querySelector("img");
    const originalSource = historyButton.dataset.sourceUrl;
    if (!sourceImage?.src || !originalSource) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inpaint-generated-thumb";
    button.dataset.sourceUrl = originalSource;
    button.title = `최근 생성 이미지 ${index + 1}을 LLLite 원본으로 사용`;
    const image = document.createElement("img");
    image.src = sourceImage.src;
    image.loading = "lazy";
    image.decoding = "async";
    image.alt = `최근 생성 이미지 ${index + 1}`;
    button.append(image);
    inpaintGeneratedGallery.append(button);
  });
}

async function useGeneratedImageForInpaint(button) {
  const sourceUrl = button?.dataset.sourceUrl;
  if (!sourceUrl) return;
  inpaintStatus.textContent = "생성 이미지를 LLLite 원본으로 준비 중…";
  try {
    const response = await fetch(sameOriginMediaUrl(sourceUrl), {credentials:"same-origin"});
    if (!response.ok) throw new Error("생성 이미지를 불러오지 못했어요.");
    const blob = await response.blob();
    const mime = ["image/png", "image/jpeg", "image/webp"].includes(blob.type) ? blob.type : "image/png";
    const extension = mime === "image/jpeg" ? "jpg" : mime.split("/")[1];
    await uploadInpaintFile(new File([blob], `LAKIS_generated.${extension}`, { type: mime }));
    setInpaintEnabled(true);
    inpaintGeneratedGallery.querySelectorAll(".inpaint-generated-thumb").forEach(item => item.classList.toggle("selected", item === button));
    inpaintStatus.textContent = "선택한 생성 이미지에서 수정할 영역을 칠하세요.";
  } catch (error) {
    inpaintStatus.textContent = error.message || "생성 이미지를 준비하지 못했어요.";
  }
}

function resetInpaintCanvas() {
  const width = Math.max(1, state.inpaint.image_width || 1);
  const height = Math.max(1, state.inpaint.image_height || 1);
  inpaintCanvas.width = width;
  inpaintCanvas.height = height;
  inpaintCanvas.getContext("2d").clearRect(0, 0, width, height);
  inpaintDirty = false;
  state.inpaint.mask_name = "";
  requestAnimationFrame(syncInpaintCanvasLayout);
}

function syncInpaintCanvasLayout() {
  if (!state.inpaint.image_width || !state.inpaint.image_height) return;
  const editorWidth = inpaintEditor.clientWidth;
  const editorHeight = inpaintEditor.clientHeight;
  if (!editorWidth || !editorHeight) return;
  const scale = Math.min(
    editorWidth / state.inpaint.image_width,
    editorHeight / state.inpaint.image_height,
  );
  const shownWidth = state.inpaint.image_width * scale;
  const shownHeight = state.inpaint.image_height * scale;
  const left = (editorWidth - shownWidth) / 2;
  const top = (editorHeight - shownHeight) / 2;
  // Position both layers explicitly instead of relying on object-fit. This
  // guarantees that landscape, portrait and square sources are shown whole
  // and that the mask canvas covers exactly the same pixels.
  for (const layer of [inpaintPreview, inpaintCanvas]) {
    layer.style.width = `${shownWidth}px`;
    layer.style.height = `${shownHeight}px`;
    layer.style.left = `${left}px`;
    layer.style.top = `${top}px`;
    layer.style.right = "auto";
    layer.style.bottom = "auto";
  }
}

function setInpaintEnabled(enabled, enforceExclusive = true) {
  state.inpaint.enabled = Boolean(enabled) && !isToyxyzEnabled();
  if (state.inpaint.enabled) {
    if (state.i2i.enabled) setI2iEnabled(false, false);
  }
  inpaintToggle.classList.toggle("on", state.inpaint.enabled);
  inpaintToggle.setAttribute("aria-pressed", String(state.inpaint.enabled));
  inpaintToggle.setAttribute("aria-label", state.inpaint.enabled ? "인페인트 끄기" : "인페인트 켜기");
  inpaintControls.hidden = !state.inpaint.enabled;
  inpaintPromptPanel.hidden = !state.inpaint.enabled;
  inpaintCanvas.hidden = !state.inpaint.enabled || !state.inpaint.image_name;
  renderCompositionAvailability();
  const controlColumn = document.querySelector(".control-column");
  controlColumn?.classList.toggle("inpaint-layout-active", state.inpaint.enabled);
  if (state.inpaint.enabled && state.inpaint.image_name) {
    requestAnimationFrame(syncInpaintCanvasLayout);
  }
}

function setInpaintOperation(operation) {
  state.inpaint.operation = operation === "remove" ? "remove" : "regenerate";
  const removing = state.inpaint.operation === "remove";
  inpaintOperationButtons.forEach(button => {
    const active = button.dataset.inpaintOperation === state.inpaint.operation;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  inpaintPromptPanel.classList.toggle("is-disabled", removing);
  inpaintPromptInput.disabled = removing;
  inpaintNegativePromptInput.disabled = removing;
  inpaintPromptPanel.setAttribute("aria-disabled", String(removing));
  inpaintStatus.textContent = removing
    ? "칠한 영역의 대상을 삭제하고 주변 배경으로 복원합니다."
    : "칠한 영역을 인페인트 프롬프트의 내용으로 다시 생성합니다.";
}

async function uploadInpaintFile(file) {
  if (!file || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("PNG, JPEG 또는 WebP 이미지를 선택해 주세요.");
  if (file.size > 32 * 1024 * 1024) throw new Error("입력 이미지는 32MB 이하여야 합니다.");
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("이미지를 읽지 못했어요."));
    reader.readAsDataURL(file);
  });
  const dimensions = await readImageDimensions(dataUrl);
  const response = await fetch("/api/inpaint-image", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({data_url:dataUrl}) });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "LLLite 원본 이미지 업로드 실패");
  state.inpaint.image_name = result.image_name;
  state.inpaint.image_width = dimensions.width;
  state.inpaint.image_height = dimensions.height;
  inpaintPreview.src = dataUrl;
  inpaintPreview.hidden = false;
  inpaintPlaceholder.hidden = true;
  inpaintRemove.disabled = false;
  resetInpaintCanvas();
  setInpaintEnabled(true);
}

function inpaintPoint(event) {
  const rect = inpaintCanvas.getBoundingClientRect();
  const scaleX = rect.width / inpaintCanvas.width;
  const scaleY = rect.height / inpaintCanvas.height;
  const x = (event.clientX - rect.left) / scaleX;
  const y = (event.clientY - rect.top) / scaleY;
  // Keep painting for one brush radius beyond the displayed image. Canvas
  // clipping discards the outside half of the circle while the inside half
  // reaches the exact image edge, avoiding an unpaintable border strip.
  const radius = state.inpaint.brush_size / 2;
  if (x < -radius || y < -radius || x > inpaintCanvas.width + radius || y > inpaintCanvas.height + radius) return null;
  return { x, y };
}

function paintInpaintMask(event) {
  const point = inpaintPoint(event);
  if (!point) { inpaintLastPoint = null; return; }
  const ctx = inpaintCanvas.getContext("2d");
  ctx.globalCompositeOperation = inpaintErasing ? "destination-out" : "source-over";
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = state.inpaint.brush_size;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  // Store a binary-strength mask. Its translucent appearance belongs to CSS;
  // baking display opacity into the pixels produces a gray composite mask and
  // can leave a pale patch in the generated image.
  if (inpaintLastPoint) {
    ctx.moveTo(inpaintLastPoint.x, inpaintLastPoint.y);
    ctx.lineTo(point.x, point.y);
    ctx.stroke();
  } else {
    ctx.arc(point.x, point.y, state.inpaint.brush_size / 2, 0, Math.PI * 2);
    ctx.fill();
  }
  inpaintLastPoint = point;
  inpaintDirty = true;
  state.inpaint.mask_name = "";
}

async function uploadInpaintMask() {
  if (!state.inpaint.enabled) return;
  if (!inpaintDirty) throw new Error("수정할 영역을 먼저 칠해 주세요.");
  const exportCanvas = document.createElement("canvas");
  exportCanvas.width = inpaintCanvas.width; exportCanvas.height = inpaintCanvas.height;
  const ctx = exportCanvas.getContext("2d");
  ctx.fillStyle = "black"; ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
  ctx.drawImage(inpaintCanvas, 0, 0);
  const response = await fetch("/api/inpaint-mask", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({data_url:exportCanvas.toDataURL("image/png")}) });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "마스크를 준비하지 못했어요.");
  state.inpaint.mask_name = result.image_name;
  state.inpaint.mask_bbox = result.mask_bbox || null;
  state.inpaint.mask_ratio = Number.isFinite(Number(result.mask_ratio)) ? Number(result.mask_ratio) : null;
  state.inpaint.large_edit_warning = Boolean(result.large_edit);
}
const imageWidthInput = document.querySelector("#imageWidth");
const imageHeightInput = document.querySelector("#imageHeight");
let manualI2iSize = { width: Number(imageWidthInput.value), height: Number(imageHeightInput.value) };

function setModelImageSize(width, height) {
  const safeWidth = clampImageDimension(width);
  const safeHeight = clampImageDimension(height);
  if (aspectRatioLock.checked && safeWidth > 0 && safeHeight > 0) {
    lockedAspectRatio = safeWidth / safeHeight;
  }
  syncingAspectRatio = true;
  imageWidthInput.value = String(safeWidth);
  imageHeightInput.value = String(safeHeight);
  imageWidthInput.dispatchEvent(new Event("input", { bubbles: true }));
  imageHeightInput.dispatchEvent(new Event("input", { bubbles: true }));
  syncingAspectRatio = false;
}

function applyI2iAutoSize() {
  if (!state.i2i.auto_size || !state.i2i.image_width || !state.i2i.image_height) return;
  let width = state.i2i.image_width, height = state.i2i.image_height;
  if (currentGenerationEngine() === "moss") {
    const limits = engineConfiguration.moss.limits;
    const scale = Math.min(1, limits.max_dimension / width, limits.max_dimension / height,
      Math.sqrt(limits.max_pixels / (width * height)));
    width = Math.max(limits.min_dimension, Math.floor(width * scale / 16) * 16);
    height = Math.max(limits.min_dimension, Math.floor(height * scale / 16) * 16);
  }
  setModelImageSize(width, height);
}

function syncI2iControls() {
  setI2iEnabled(state.i2i.enabled, false);
  i2iDenoise.value = String(state.i2i.denoise);
  i2iDenoiseNumber.value = Number(state.i2i.denoise).toFixed(2);
  i2iAutoSize.checked = state.i2i.auto_size === true;
  const engine = currentGenerationEngine();
  const cached = i2iPreviewUrls.get(engine);
  const preview = state.i2i.image_name && (cached?.name === state.i2i.image_name ? cached.url
    : engine === "moss" ? `/api/i2i-image?image_name=${encodeURIComponent(state.i2i.image_name)}` : "");
  if (preview) i2iPreview.src = preview;
  else i2iPreview.removeAttribute("src");
  i2iPreview.hidden = !preview;
  i2iPlaceholder.hidden = Boolean(preview);
  i2iRemove.disabled = !state.i2i.image_name;
}

function readImageDimensions(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => reject(new Error("이미지 크기를 확인하지 못했어요."));
    image.src = dataUrl;
  });
}

function setI2iEnabled(enabled, enforceExclusive = true) {
  const wasEnabled = state.i2i.enabled;
  const available = currentGenerationEngine() !== "moss" || engineConfiguration?.moss?.capabilities?.i2i === true;
  state.i2i.enabled = Boolean(enabled) && available && !isToyxyzEnabled();
  if (state.i2i.enabled && enforceExclusive && state.inpaint.enabled && currentGenerationEngine() !== "moss") setInpaintEnabled(false, false);
  if (state.i2i.enabled) {
    if (currentGenerationEngine() === "moss" && enforceExclusive) setCompositionEnabled(false);
    if (!wasEnabled) showI2iCompositionNotice();
  }
  i2iToggle.classList.toggle("on", state.i2i.enabled);
  i2iToggle.setAttribute("aria-pressed", String(state.i2i.enabled));
  i2iToggle.setAttribute("aria-label", state.i2i.enabled ? "Image to Image 끄기" : "Image to Image 켜기");
  document.querySelector(".i2i-panel").classList.toggle("is-disabled", !state.i2i.enabled);
  renderCompositionAvailability();
  syncMossI2iAvailability();
  syncPromptHeadings();
}

let i2iNoticeTimer = null;
function showI2iCompositionNotice() {
  const notice = document.querySelector("#i2iCompositionNotice");
  clearTimeout(i2iNoticeTimer);
  notice.hidden = false;
  requestAnimationFrame(() => notice.classList.add("visible"));
  i2iNoticeTimer = setTimeout(() => {
    notice.classList.remove("visible");
    setTimeout(() => { notice.hidden = true; }, 180);
  }, 3200);
}

async function uploadI2iFile(file) {
  const engine = currentGenerationEngine();
  if (!file || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    i2iStatus.textContent = "PNG, JPEG 또는 WebP 이미지를 선택해 주세요.";
    return;
  }
  if (file.size > 32 * 1024 * 1024) {
    i2iStatus.textContent = "입력 이미지는 32MB 이하여야 합니다.";
    return;
  }
  i2iStatus.textContent = "입력 이미지 준비 중…";
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("이미지를 읽지 못했어요."));
    reader.readAsDataURL(file);
  });
  try {
    const dimensions = await readImageDimensions(dataUrl);
    if (currentGenerationEngine() !== engine) return;
    const response = await fetch("/api/i2i-image", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data_url: dataUrl }),
    });
    const result = await response.json();
    if (currentGenerationEngine() !== engine) return;
    if (!response.ok || !result.ok) throw new Error(result.error || "이미지 업로드 실패");
    state.i2i.image_name = result.image_name;
    state.i2i.image_width = result.width || dimensions.width;
    state.i2i.image_height = result.height || dimensions.height;
    i2iPreviewUrls.set(engine, { name: result.image_name, url: dataUrl });
    i2iPreview.src = dataUrl;
    i2iPreview.hidden = false;
    i2iPlaceholder.hidden = true;
    i2iRemove.disabled = false;
    if (engine !== "moss") {
      resetInpaintCanvas();
      setInpaintEnabled(state.inpaint.enabled);
    }
    setI2iEnabled(state.i2i.enabled);
    applyI2iAutoSize();
    scheduleGenerationStateSave();
    i2iStatus.textContent = "원본 이미지 크기 자동 입력하기";
  } catch (error) {
    if (currentGenerationEngine() !== engine) return;
    setI2iEnabled(false);
    i2iStatus.textContent = error.message || "입력 이미지를 준비하지 못했어요.";
  }
}

i2iToggle.addEventListener("click", () => {
  setI2iEnabled(!state.i2i.enabled);
  scheduleGenerationStateSave();
  i2iStatus.textContent = "원본 이미지 크기 자동 입력하기";
});
i2iAutoSize.addEventListener("change", () => {
  state.i2i.auto_size = i2iAutoSize.checked;
  if (state.i2i.auto_size) {
    manualI2iSize = { width: Number(imageWidthInput.value), height: Number(imageHeightInput.value) };
    applyI2iAutoSize();
  } else {
    setModelImageSize(manualI2iSize.width, manualI2iSize.height);
  }
  scheduleGenerationStateSave();
});
i2iDropZone.addEventListener("click", event => {
  if (!event.target.closest("#i2iRemove")) i2iFileInput.click();
});
i2iDropZone.addEventListener("keydown", event => {
  if ((event.key === "Enter" || event.key === " ") && !event.target.closest("#i2iRemove")) {
    event.preventDefault();
    i2iFileInput.click();
  }
});
i2iFileInput.addEventListener("change", () => uploadI2iFile(i2iFileInput.files?.[0]));
for (const eventName of ["dragenter", "dragover"]) i2iDropZone.addEventListener(eventName, event => {
  event.preventDefault(); i2iDropZone.classList.add("is-dragging");
});
for (const eventName of ["dragleave", "drop"]) i2iDropZone.addEventListener(eventName, event => {
  event.preventDefault(); i2iDropZone.classList.remove("is-dragging");
});
i2iDropZone.addEventListener("drop", event => uploadI2iFile(event.dataTransfer?.files?.[0]));
i2iDenoise.addEventListener("input", () => {
  state.i2i.denoise = Number(i2iDenoise.value);
  i2iDenoiseNumber.value = state.i2i.denoise.toFixed(2);
  scheduleGenerationStateSave();
});
i2iDenoiseNumber.addEventListener("input", () => {
  const value = Math.min(1, Math.max(0, Number(i2iDenoiseNumber.value)));
  if (!Number.isFinite(value)) return;
  state.i2i.denoise = value;
  i2iDenoise.value = String(value);
  scheduleGenerationStateSave();
});
i2iDenoiseNumber.addEventListener("change", () => {
  const value = Math.min(1, Math.max(0, Number(i2iDenoiseNumber.value) || 0));
  state.i2i.denoise = value;
  i2iDenoise.value = String(value);
  i2iDenoiseNumber.value = value.toFixed(2);
  scheduleGenerationStateSave();
});
i2iRemove.addEventListener("click", event => {
  event.stopPropagation();
  state.i2i.image_name = ""; setI2iEnabled(false);
  i2iPreviewUrls.delete(currentGenerationEngine());
  state.i2i.image_width = 0; state.i2i.image_height = 0;
  if (state.i2i.auto_size) setModelImageSize(manualI2iSize.width, manualI2iSize.height);
  state.i2i.auto_size = false; i2iAutoSize.checked = false;
  i2iPreview.removeAttribute("src"); i2iPreview.hidden = true; i2iPlaceholder.hidden = false;
  i2iRemove.disabled = true; i2iFileInput.value = "";
  if (currentGenerationEngine() !== "moss") {
    resetInpaintCanvas(); setInpaintEnabled(false);
  }
  i2iStatus.textContent = "원본 이미지 크기 자동 입력하기";
  scheduleGenerationStateSave();
});
setI2iEnabled(false);
setInpaintEnabled(false);
setInpaintOperation(state.inpaint.operation);

inpaintToggle.addEventListener("click", async () => {
  const enabling = !state.inpaint.enabled;
  if (enabling && !await requireLLLiteInpaintWeight()) return;
  setInpaintEnabled(enabling);
  if (enabling && !state.inpaint.image_name) {
    inpaintStatus.textContent = "인페인트가 켜졌습니다. 먼저 원본 이미지를 선택해 주세요.";
  }
});
inpaintOperationButtons.forEach(button => button.addEventListener("click", () => {
  setInpaintOperation(button.dataset.inpaintOperation);
}));
inpaintGeneratedGallery.addEventListener("click", event => {
  const button = event.target.closest(".inpaint-generated-thumb");
  if (button) useGeneratedImageForInpaint(button);
});
inpaintPromptInput.addEventListener("input", () => {
  state.inpaint.prompt = inpaintPromptInput.value.slice(0, 4000);
  inpaintPromptCount.textContent = `${state.inpaint.prompt.length} / 4000`;
  markPromptStateDirty();
});
inpaintNegativePromptInput.addEventListener("input", () => {
  state.inpaint.negative_prompt = inpaintNegativePromptInput.value.slice(0, 4000);
  inpaintNegativePromptCount.textContent = `${state.inpaint.negative_prompt.length} / 4000`;
  markPromptStateDirty();
});
inpaintPromptInput.addEventListener("blur", () => flushPromptState());
inpaintNegativePromptInput.addEventListener("blur", () => flushPromptState());
inpaintEditor.addEventListener("click", event => {
  if (!event.target.closest("#inpaintRemove") && !state.inpaint.image_name) inpaintFileInput.click();
});
inpaintEditor.addEventListener("keydown", event => {
  if ((event.key === "Enter" || event.key === " ") && !state.inpaint.image_name) { event.preventDefault(); inpaintFileInput.click(); }
});
inpaintFileInput.addEventListener("change", async () => {
  try { await uploadInpaintFile(inpaintFileInput.files?.[0]); inpaintStatus.textContent="수정할 영역을 칠하세요."; }
  catch(error) { inpaintStatus.textContent=error.message; }
});
for (const eventName of ["dragenter", "dragover"]) inpaintEditor.addEventListener(eventName, event => { event.preventDefault(); inpaintEditor.classList.add("is-dragging"); });
for (const eventName of ["dragleave", "drop"]) inpaintEditor.addEventListener(eventName, event => { event.preventDefault(); inpaintEditor.classList.remove("is-dragging"); });
inpaintEditor.addEventListener("drop", async event => {
  try { await uploadInpaintFile(event.dataTransfer?.files?.[0]); inpaintStatus.textContent="수정할 영역을 칠하세요."; }
  catch(error) { inpaintStatus.textContent=error.message; }
});
inpaintRemove.addEventListener("click", event => {
  event.stopPropagation();
  Object.assign(state.inpaint, {image_name:"", image_width:0, image_height:0, mask_name:""});
  inpaintPreview.removeAttribute("src"); inpaintPreview.hidden=true; inpaintPlaceholder.hidden=false; inpaintRemove.disabled=true;
  resetInpaintCanvas(); inpaintCanvas.hidden=true; inpaintStatus.textContent="원본 이미지를 선택해 주세요.";
});
inpaintCanvas.addEventListener("pointerdown", event => { event.preventDefault(); inpaintDrawing=true; inpaintLastPoint=null; inpaintCanvas.setPointerCapture(event.pointerId); paintInpaintMask(event); });
inpaintCanvas.addEventListener("pointermove", event => {
  if (!inpaintDrawing) return;
  event.preventDefault();
  const samples = typeof event.getCoalescedEvents === "function" ? event.getCoalescedEvents() : [];
  if (samples.length) samples.forEach(paintInpaintMask); else paintInpaintMask(event);
});
inpaintCanvas.addEventListener("pointerup", () => { inpaintDrawing=false; inpaintLastPoint=null; });
inpaintCanvas.addEventListener("pointercancel", () => { inpaintDrawing=false; inpaintLastPoint=null; });
window.addEventListener("resize", syncInpaintCanvasLayout);
inpaintBrushSize.addEventListener("input", () => { state.inpaint.brush_size=Number(inpaintBrushSize.value); document.querySelector("#inpaintBrushValue").textContent=inpaintBrushSize.value; });
inpaintGrowMask.addEventListener("input", () => { state.inpaint.grow_mask_by=Number(inpaintGrowMask.value); document.querySelector("#inpaintGrowValue").textContent=inpaintGrowMask.value; });
inpaintDenoise.addEventListener("input", () => { state.inpaint.denoise=Number(inpaintDenoise.value); document.querySelector("#inpaintDenoiseValue").textContent=state.inpaint.denoise.toFixed(2); });
inpaintStrength.addEventListener("input", () => { state.inpaint.strength=Number(inpaintStrength.value); document.querySelector("#inpaintStrengthValue").textContent=state.inpaint.strength.toFixed(2); });
async function historyDataUrlFile(detail) {
  const response = await fetch(detail.dataUrl);
  const blob = await response.blob();
  return new File([blob], detail.name || "LAKIS_history.png", {type: blob.type || "image/png"});
}
window.addEventListener("lakis:history-to-inpaint", async event => {
  try {
    if (!state.inpaint.enabled && !await requireLLLiteInpaintWeight()) return;
    await uploadInpaintFile(await historyDataUrlFile(event.detail)); setInpaintEnabled(true);
  }
  catch (error) { inpaintStatus.textContent = error.message || "라이브러리 이미지를 불러오지 못했어요."; }
});
window.addEventListener("lakis:history-to-i2i", async event => {
  try { await uploadI2iFile(await historyDataUrlFile(event.detail)); setI2iEnabled(true); }
  catch (error) { i2iStatus.textContent = error.message || "라이브러리 이미지를 불러오지 못했어요."; }
});
inpaintErase.addEventListener("click", () => { inpaintErasing=!inpaintErasing; inpaintErase.classList.toggle("is-active", inpaintErasing); inpaintErase.textContent=inpaintErasing?"브러시":"지우개"; });
document.querySelector("#inpaintClear").addEventListener("click", () => { resetInpaintCanvas(); inpaintStatus.textContent="마스크를 지웠어요."; });

const CONTINUOUS_DEFAULT_COUNT = 1;
const continuousToggle = document.querySelector("#continuousToggle");
const continuousCount = document.querySelector("#continuousCount");
const continuousProgress = document.querySelector("#continuousProgress");
const continuousProgressCount = document.querySelector("#continuousProgressCount");
const continuousProgressLabel = document.querySelector("#continuousProgressLabel");
function setContinuousProgress(count = "", label = "") {
  continuousProgressCount.textContent = count;
  continuousProgressLabel.textContent = label;
}
function syncContinuousControls() {
  const count = Math.max(1, Math.min(20, Math.trunc(Number(state.continuous?.count)) || CONTINUOUS_DEFAULT_COUNT));
  state.continuous.count = count;
  continuousCount.textContent = String(count);
  continuousToggle.classList.toggle("on", state.continuous.enabled === true);
  continuousToggle.setAttribute("aria-pressed", String(state.continuous.enabled === true));
  continuousToggle.setAttribute("aria-label", `연속 생성 ${state.continuous.enabled ? "끄기" : "켜기"}`);
  document.querySelector(".continuous-generation-row").classList.toggle("is-enabled", state.continuous.enabled === true);
}
continuousToggle.addEventListener("click", () => {
  state.continuous.enabled = !state.continuous.enabled;
  if (!state.continuous.enabled && continuousRun) continuousRun.stop = true;
  syncContinuousControls();
  scheduleGenerationStateSave();
});
document.querySelector("#continuousCountDown").addEventListener("click", () => { state.continuous.count = Math.max(1, state.continuous.count - 1); syncContinuousControls(); scheduleGenerationStateSave(); });
document.querySelector("#continuousCountUp").addEventListener("click", () => { state.continuous.count = Math.min(20, state.continuous.count + 1); syncContinuousControls(); scheduleGenerationStateSave(); });
syncContinuousControls();

const generateButton = document.querySelector("#generateButton");
const generateButtonLabel = generateButton.querySelector("span");
const generateButtonHint = document.querySelector("#generateHint");
const errorDialog = document.querySelector("#errorDialog");
const errorDialogTitle = document.querySelector("#errorDialogTitle");
const errorDialogMessage = document.querySelector("#errorDialogMessage");
const errorDialogIcon = document.querySelector("#errorDialogIcon");
const errorDialogContextActions = document.querySelector("#errorDialogContextActions");
const errorDialogDevLabel = document.querySelector("#errorDialogDevLabel");
const errorDialogCopy = document.querySelector("#errorDialogCopy");
const errorDialogCancel = document.querySelector("#errorDialogCancel");
const errorDialogClose = document.querySelector("#errorDialogClose");
let generationActive = false;
let generationCancelRequested = false;
let lastPreviewRevision = 0;
let previewObjectUrl = null;
let generationResetTimer = null;
let generationSubmissionPending = false;
let generationPreparationPending = false;
let continuousRun = null;
let continuousAdvance = false;

async function refreshGenerationPreview(revision) {
  if (!revision || revision === lastPreviewRevision) return;
  const response = await fetch(`/api/generation-preview?r=${revision}`, { cache: "no-store" });
  lastPreviewRevision = revision;
  if (response.status === 204 || !response.ok) return;
  const blob = await response.blob();
  const nextUrl = URL.createObjectURL(blob);
  document.querySelector("#previewImage").src = nextUrl;
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = nextUrl;
}

function setGenerationProgress(percent, stage = "최종 이미지 생성 중") {
  if (generationResetTimer) {
    clearTimeout(generationResetTimer);
    generationResetTimer = null;
  }
  const knownProgress = percent != null && Number.isFinite(Number(percent));
  const progress = knownProgress ? Math.max(0, Math.min(100, Number(percent))) : 0;
  const phase = String(stage || "")
    .replace(/^생성 중\s*·\s*/, "")
    .replace(/^생성 중$/, "준비")
    .trim() || "처리";
  generationActive = progress < 100;
  engineSwitchBusy = generationActive || generationPreparationPending || generationSubmissionPending;
  syncGenerationEngineUI();
  generateButton.style.setProperty("--generation-progress", `${progress}%`);
  generateButton.classList.toggle("is-generating", progress < 100);
  generateButton.classList.toggle("is-complete", progress >= 100);
  generateButtonLabel.textContent = progress >= 100 ? "완료" : currentGenerationEngine() === "moss"
    ? "MOSS 제작 중" : (state.inpaint.enabled ? "인페인트 진행 중" : "제작 중");
  generateButtonHint.textContent = progress >= 100 ? "100%" : `${phase}${knownProgress ? ` · ${Math.round(progress)}%` : ""}`;
}

function resetGenerationButton() {
  if (generationResetTimer) {
    clearTimeout(generationResetTimer);
    generationResetTimer = null;
  }
  generationActive = false;
  generationCancelRequested = false;
  generateButton.style.setProperty("--generation-progress", "0%");
  generateButton.classList.remove("is-generating", "is-complete", "is-cancelling");
  generateButtonLabel.textContent = "제작하기";
  generateButtonHint.textContent = currentGenerationEngine() === "moss"
    ? "MOSS · 기본 이미지 생성" : `${generationModeLabel()} · COMPOSITION READY`;
  engineSwitchBusy = generationPreparationPending || generationSubmissionPending;
  syncGenerationEngineUI();
}

let lastErrorReport = null;
let devModalSession = null;

function closeDevModal(result = "cancel") {
  if (errorDialog.hidden) return;
  const session = devModalSession;
  devModalSession = null;
  errorDialog.hidden = true;
  errorDialogContextActions.replaceChildren();
  session?.resolve(result);
  session?.focusTarget?.focus?.();
}

function showDevModal({type="INFO", title, message, actions=[], confirmLabel="확인", cancelLabel="", copyError=false, focusTarget=null}) {
  if (devModalSession) closeDevModal("cancel");
  errorDialog.dataset.type = type.toLowerCase();
  errorDialog.setAttribute("role", type === "ERROR" ? "alertdialog" : "dialog");
  errorDialogTitle.textContent = title;
  errorDialogMessage.textContent = message;
  errorDialogIcon.textContent = type === "ERROR" ? "!" : type === "WARNING" ? "!" : "i";
  errorDialogCopy.hidden = !copyError;
  errorDialogCancel.hidden = !cancelLabel;
  errorDialogCancel.textContent = cancelLabel || "취소";
  errorDialogClose.textContent = confirmLabel;
  errorDialogDevLabel.hidden = !["LICENSE_NOTICE", "WARNING", "INFO"].includes(type);
  errorDialogContextActions.replaceChildren();
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const result = await action.run();
        if (result !== false && result !== undefined) closeDevModal(result);
      } finally {
        button.disabled = false;
      }
    });
    errorDialogContextActions.append(button);
  }
  errorDialogContextActions.hidden = actions.length === 0;
  errorDialog.hidden = false;
  return new Promise(resolve => {
    devModalSession = {resolve, focusTarget};
    (cancelLabel ? errorDialogCancel : errorDialogClose).focus();
  });
}

function showGenerationError(message, errorCode = "", context = {}) {
  continuousRun = null;
  continuousAdvance = false;
  setContinuousProgress();
  resetGenerationButton();
  const code = String(errorCode || "").trim();
  const details = [];
  if (code) details.push(`오류 코드: ${code}`);
  if (context.stage) details.push(`실패 단계: ${context.stage}`);
  if (context.nodeType || context.nodeId) details.push(`실패 노드: ${context.nodeType || "알 수 없음"}${context.nodeId ? ` (${context.nodeId})` : ""}`);
  if (context.failureStep) details.push(`발생 위치: ${context.failureStep}`);
  if (context.requestId || context.clientRequestId) details.push(`추적 ID: ${String(context.requestId || context.clientRequestId).slice(0, 12)}`);
  const displayMessage = `${message || "생성 중 오류가 발생했어요."}${details.length ? `\n\n${details.join("\n")}` : ""}`;
  lastErrorReport = {
    report_schema: 1,
    error_code: code || "LKS-GEN-1001",
    message: context.reportMessage || message || "생성 중 오류가 발생했어요.",
    failure_stage: context.stage || null,
    failure_component: context.failureComponent || null,
    failure_step: context.failureStep || null,
    node_id: context.nodeId || null,
    node_type: context.nodeType || null,
    exception_type: context.exceptionType || null,
    request_id: context.requestId || null,
    client_request_id: context.clientRequestId || null,
    prompt_id: context.promptId || null,
    occurred_at: new Date().toISOString(),
    error_detail: context.failureComponent === "frontend" ? context.errorDetail || null : null,
    settings: context.diagnostics ? clientGenerationDiagnostics(context.diagnostics) : null,
    setting_diagnostic: context.settingDiagnostic || null,
    runtime_trace: context.runtimeTrace || null,
    submission: context.submissionDiagnostic || null,
  };
  showDevModal({type:"ERROR", title:"생성 오류", message:displayMessage, copyError:true, focusTarget:generateButton});
}

function compactDiagnosticValue(value, depth = 0) {
  if (typeof value === "string") {
    return { type: "string", chars: value.length };
  }
  if (depth >= 6) return "<omitted nested value>";
  if (Array.isArray(value)) return value.slice(0, 64).map((item) => compactDiagnosticValue(item, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).slice(0, 128).map(
      ([key, item]) => [key, compactDiagnosticValue(item, depth + 1)],
    ));
  }
  return value;
}

function clientGenerationDiagnostics(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  const inpaint = source.inpaint && typeof source.inpaint === "object" ? source.inpaint : {};
  const i2i = source.i2i && typeof source.i2i === "object" ? source.i2i : {};
  const pick = (value, keys) => Object.fromEntries(keys
    .filter(key => value && value[key] !== undefined)
    .map(key => [key, value[key]]));
  const model = pick(source.model, ["checkpoint", "vae", "clip", "sampler", "scheduler", "steps", "cfg"]);
  const fileName = value => typeof value === "string" ? value.replaceAll("\\", "/").split("/").pop() : value;
  for (const key of ["checkpoint", "vae", "clip"]) {
    if (key in model) model[key] = fileName(model[key]);
  }
  return {
    generation: pick(source.generation, ["engine", "mode", "lakis_mode", "upscale_engine"]),
    model,
    output: pick(source.output, ["width", "height", "seed_mode", "aspect_locked"]),
    loras_enabled: Boolean(source.lora_enabled ?? source.loras_enabled ?? true),
    loras: Array.isArray(source.loras) ? source.loras.map(item => ({
      name: fileName(item.name), enabled: Boolean(item.enabled), strength: item.strength,
    })) : [],
    camera: pick(source.camera, ["x", "y", "z", "roll", "frame_y"]),
    i2i: {
      enabled: Boolean(i2i.enabled),
      has_source: Boolean(i2i.has_source || i2i.image || i2i.source || i2i.filename),
      denoise: i2i.denoise ?? null,
      source_size_enabled: Boolean(i2i.source_size_enabled),
    },
    inpaint: {
      enabled: Boolean(inpaint.enabled),
      has_source: Boolean(inpaint.has_source || inpaint.source_image || inpaint.source || inpaint.source_filename),
      has_mask: Boolean(inpaint.has_mask || inpaint.mask_image || inpaint.mask || inpaint.mask_filename),
      has_prompt: Boolean(inpaint.has_prompt || String(inpaint.prompt || "").trim()),
      has_negative_prompt: Boolean(inpaint.has_negative_prompt || String(inpaint.negative_prompt || "").trim()),
      operation: inpaint.operation || null,
      denoise: inpaint.denoise ?? null,
      strength: inpaint.strength ?? null,
      grow_mask_by: inpaint.grow_mask_by ?? null,
    },
    advanced_node_settings: compactDiagnosticValue(source.advanced_node_settings || {}),
  };
}

function compactErrorReport(value) {
  if (Array.isArray(value)) return value.map(compactErrorReport);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value)
      .filter(([, item]) => item !== null && item !== undefined)
      .map(([key, item]) => [key, compactErrorReport(item)]));
  }
  return value;
}

async function formatGenerationErrorReport(report, version) {
  const detail = compactErrorReport({
    ...report, report_schema: 1, version,
  });
  const submission = detail.submission || {};
  const acceptance = {
    not_submitted: "전송 전 실패", rejected: "거절 응답 확인",
    accepted: "서버 접수 확인", unknown: "서버 접수 여부 미확인",
  }[submission.acceptance] || "서버 접수 여부 미확인";
  const summary = [
    `LAKIS ${version} | ${detail.error_code} | ${detail.failure_stage || "단계 미확인"}`,
    detail.failure_step ? `위치: ${detail.failure_step}` : "",
    `통신: ${submission.http_status === undefined ? "HTTP 응답 미확인" : `HTTP ${submission.http_status}`} | ${acceptance}${submission.request_bytes === undefined ? "" : ` | 요청 ${submission.request_bytes} B`}`,
    detail.request_id || detail.client_request_id
      ? `추적: ${detail.request_id || detail.client_request_id}` : "",
  ].filter(Boolean).join("\n");
  try {
    return `${summary}\n진단: ${await window.LAKISDiagnosticPacket.encode(detail)}`;
  } catch (error) {
    detail.packet_error = { error_code: "LKS-UI-1020", exception_type: error.name || "Error" };
    return `${summary}\n진단(압축 실패·전체 원문): ${JSON.stringify(detail)}`;
  }
}

function closeGenerationError() {
  closeDevModal("close");
}

errorDialogClose.addEventListener("click", () => closeDevModal("confirm"));
errorDialogCancel.addEventListener("click", () => closeDevModal("cancel"));
errorDialogCopy.addEventListener("click", async event => {
  if (!lastErrorReport) return;
  const snapshot = structuredClone(lastErrorReport);
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "복사 중...";
  let version = "unknown";
  try {
    const response = await fetch("/api/launcher-identity", { cache: "no-store", signal: AbortSignal.timeout(1500) });
    if (response.ok) version = String((await response.json()).version || version);
  } catch (_) {}
  const report = await formatGenerationErrorReport(snapshot, version);
  let copied = false;
  try {
    await navigator.clipboard.writeText(report);
    copied = true;
  } catch (_) {
    try {
      const field = document.createElement("textarea");
      field.value = report; field.style.position = "fixed"; field.style.opacity = "0";
      document.body.append(field); field.select(); copied = document.execCommand("copy"); field.remove();
    } catch (_) {}
  }
  button.textContent = copied ? "복사 완료" : "복사 실패";
  setTimeout(() => {
    button.textContent = "오류 정보 복사하기";
    button.disabled = false;
  }, 1800);
});
errorDialog.addEventListener("click", event => {
  if (event.target === errorDialog) closeGenerationError();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !errorDialog.hidden) closeGenerationError();
});

window.addEventListener("lakis:generation-progress", event => {
  setGenerationProgress(event.detail?.percent, event.detail?.stage);
});
function handleGenerationComplete() {
  setGenerationProgress(100, "완료");
  if (continuousRun && !continuousRun.stop && continuousRun.index < continuousRun.total) {
    const run = continuousRun;
    setContinuousProgress(`${continuousRun.index} / ${continuousRun.total}`, "완료");
    generationResetTimer = setTimeout(() => {
      generationResetTimer = null;
      if (continuousRun !== run) return;
      if (run.stop || generationCancelRequested) {
        setContinuousProgress(`${run.index} / ${run.total}`, "중지됨");
        continuousRun = null;
        continuousAdvance = false;
        resetGenerationButton();
        return;
      }
      resetGenerationButton();
      continuousAdvance = true;
      generateButton.click();
    }, 350);
    return;
  }
  continuousRun ? setContinuousProgress(`${continuousRun.index} / ${continuousRun.total}`, continuousRun.stop ? "중지됨" : "완료") : setContinuousProgress();
  continuousRun = null;
  generationResetTimer = setTimeout(() => {
    generationResetTimer = null;
    resetGenerationButton();
  }, 1400);
}
window.addEventListener("lakis:generation-complete", handleGenerationComplete);
window.addEventListener("lakis:generation-error", () => { continuousRun=null; setContinuousProgress(); resetGenerationButton(); });
window.addEventListener("lakis:generation-cancelled", () => { continuousRun=null; setContinuousProgress(); resetGenerationButton(); });
window.LAKISGenerationProgress = setGenerationProgress;

let lastGenerationState = "idle";
let lastGenerationSubmission = null;
async function pollGenerationStatus() {
  try {
    const response = await fetch("/api/generation-status", { cache: "no-store" });
    if (!response.ok) return;
    const status = await response.json();
    // While /api/generate is being accepted, the bridge may still report the
    // previous job's terminal state for one poll. Ignore only that stale
    // terminal snapshot so it cannot unlock the button mid-submission.
    if ((generationPreparationPending || generationSubmissionPending) && ["idle", "complete", "cancelled", "error"].includes(status.state)) return;
    if (["preparing", "running", "unknown"].includes(status.state)) {
      setGenerationProgress(status.percent, status.state === "unknown" ? "서버 접수 상태 확인 중" : status.stage || "생성 중");
      refreshGenerationPreview(status.preview_revision).catch(() => {});
    } else if (status.state === "cancelling") {
      generationActive = true;
      generationCancelRequested = true;
      generateButton.classList.add("is-generating", "is-cancelling");
      generateButtonLabel.textContent = "중지 중";
      generateButtonHint.textContent = "현재 작업 종료 요청됨";
    } else if (status.state === "complete" && lastGenerationState !== "complete") {
      if (status.output_url) {
        const outputUrl = new URL(sameOriginMediaUrl(status.output_url), window.location.href);
        outputUrl.searchParams.set("lakis", String(Date.now()));
        const imageUrl = `${outputUrl.pathname}${outputUrl.search}`;
        document.querySelector("#previewImage").src = imageUrl;
        if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
        previewObjectUrl = null;
        const thumb = document.createElement("button");
        thumb.className = "history-thumb selected";
        thumb.dataset.seed = String(status.seed ?? state.output.seed);
        thumb.dataset.mode = status.mode === "moss_lakis_detail" ? "MOSS LAKIS DETAIL" : status.mode === "moss_detail" ? "MOSS DETAIL" : status.mode === "moss" ? "MOSS" : status.mode === "lakis_detail" ? "LAKIS DETAIL" : (status.mode === "detail" ? "DETAIL" : "FAST");
        thumb.dataset.i2i = String(status.i2i_enabled === true);
        thumb.dataset.sourceUrl = imageUrl;
        thumb._lakisPrompt = status.prompt_used && typeof status.prompt_used === "object"
          ? structuredClone(status.prompt_used)
          : null;
        const durationSeconds = Math.max(0, Number(status.finished_at || 0) - Number(status.started_at || 0));
        thumb.dataset.duration = durationSeconds.toFixed(3);
        const thumbnail = document.createElement("img");
        thumbnail.alt = "LAKIS generated image";
        observePreviewThumbnail(thumbnail, thumbnailMediaUrl(imageUrl));
        thumb.append(thumbnail);
        document.querySelectorAll(".history-thumb").forEach(item => item.classList.remove("selected"));
        const historyStrip = document.querySelector(".history-strip");
        historyStrip.prepend(thumb);
        trimPreviewHistory();
        historyStrip.scrollLeft = 0;
        syncInpaintGeneratedGallery();
        setPreviewModeLabel(thumb.dataset.mode);
        document.querySelector("#previewI2i").hidden = thumb.dataset.i2i !== "true";
        document.querySelector("#previewSeed").textContent = `SEED ${thumb.dataset.seed}`;
        document.querySelector("#previewDuration").textContent = `${durationSeconds.toFixed(1)}초`;
        document.querySelector("#previewDuration").hidden = false;
        setCurrentPreviewPrompt(thumb._lakisPrompt);
      }
      window.dispatchEvent(new CustomEvent("lakis:generation-complete"));
    } else if (status.state === "cancelled" && lastGenerationState !== "cancelled") {
      window.dispatchEvent(new CustomEvent("lakis:generation-cancelled"));
    } else if (status.state === "error" && lastGenerationState !== "error") {
      showGenerationError(status.error, status.error_code, {
        stage: status.error_stage, nodeId: status.error_node_id,
        nodeType: status.error_node_type, exceptionType: status.error_exception_type,
        requestId: status.request_id, promptId: status.prompt_id,
        diagnostics: status.diagnostic_context,
        settingDiagnostic: status.setting_diagnostic,
        errorDetail: status.error_detail,
        failureComponent: "generation_backend",
        failureStep: status.error_stage || "backend_execution",
        clientRequestId: lastGenerationSubmission?.bridge_request_id === status.request_id
          ? lastGenerationSubmission.client_request_id : null,
        submissionDiagnostic: lastGenerationSubmission?.bridge_request_id === status.request_id
          ? lastGenerationSubmission : null,
        runtimeTrace: {
          last_node_id: status.last_node_id || null,
          last_node_type: status.last_node_type || null,
          last_activity_at: status.last_activity_at || null,
          last_node_started_at: status.last_node_started_at || null,
        },
      });
    }
    lastGenerationState = status.state;
    engineSwitchBusy = generationPreparationPending || generationSubmissionPending
      || ["preparing", "running", "cancelling", "unknown"].includes(status.state);
    syncGenerationEngineUI();
  } catch (_) {
    // Main status polling already displays bridge connectivity.
  }
}
setInterval(pollGenerationStatus, 500);

async function requireLLLiteInpaintWeight() {
  const noticeResponse = await fetch(`/api/inpaint-model-notice?t=${Date.now()}`, {cache:"no-store"});
  const notice = await noticeResponse.json();
  if (!noticeResponse.ok) throw new Error(notice.error || "인페인트 안내 상태를 확인하지 못했습니다.");

  let statusResponse = await fetch(`/api/lllite-weight-status?t=${Date.now()}`, {cache:"no-store"});
  let status = await statusResponse.json();
  if (!notice.inpaint_model_notice_ack) {
    const decision = await showDevModal({
      type:"LICENSE_NOTICE",
      title:"인페인트 사용을 위한 추가 모델 안내",
      message:`인페인트에는 ${status.model || "anima-lllite-inpainting-v2.safetensors"} 모델이 필요합니다.\n\n제공자: CircleStone Labs (kohya-ss / Anima-LLLite)\n적용 라이선스: ${status.license_name || "CircleStone Labs Non-Commercial License"}\n비상업·비프로덕션 사용 조건이 별도로 적용됩니다.\n\n이 모델은 LAKIS에 포함되지 않으며 자동으로 다운로드되지 않습니다.`,
      actions:[
        {label:"라이선스 보기", run:async()=>{ await fetch("/api/open-legal-document", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({document:"lllite-inpaint"})}); return false; }},
        {label:"공식 배포 페이지 열기", run:()=>{ window.open(status.official_source || "https://huggingface.co/kohya-ss/Anima-LLLite", "_blank", "noopener,noreferrer"); return false; }},
        {label:"모델 폴더 열기", run:async()=>{ await fetch("/api/open-lllite-model-folder", {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}); return false; }},
      ],
      confirmLabel:"확인하고 계속", cancelLabel:"취소", focusTarget:inpaintToggle,
    });
    if (decision !== "confirm") return false;
    const savedResponse = await fetch("/api/inpaint-model-notice", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({inpaint_model_notice_ack:true})});
    if (!savedResponse.ok) throw new Error("인페인트 안내 확인 상태를 저장하지 못했습니다.");
  }

  if (statusResponse.ok && status.valid) return true;
  const missingResult = await showDevModal({
    type:"WARNING", title:"인페인트 모델을 확인해 주세요",
    message:`${status.model || "anima-lllite-inpainting-v2.safetensors"} 모델을 현재 LAKIS 실행 환경에서 찾지 못했거나 공식 파일과 일치하지 않습니다.\n공식 배포 페이지에서 직접 설치한 뒤 다시 확인해 주세요.`,
    actions:[
      {label:"공식 배포 페이지 열기", run:()=>{ window.open(status.official_source || "https://huggingface.co/kohya-ss/Anima-LLLite", "_blank", "noopener,noreferrer"); return false; }},
      {label:"모델 폴더 열기", run:async()=>{ await fetch("/api/open-lllite-model-folder", {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}); return false; }},
      {label:"다시 확인", run:async()=>{
        statusResponse = await fetch(`/api/lllite-weight-status?t=${Date.now()}`, {cache:"no-store"});
        status = await statusResponse.json();
        if (statusResponse.ok && status.valid) { inpaintStatus.textContent="Anima LLLite Inpainting 모델을 확인했습니다."; return "found"; }
        inpaintStatus.textContent = status.installed ? "모델 파일이 공식 파일과 일치하지 않습니다." : "모델 파일이 아직 설치되지 않았습니다.";
        return false;
      }},
    ],
    confirmLabel:"닫기", focusTarget:inpaintToggle,
  });
  return missingResult === "found";
}

generateButton.addEventListener("click", async () => {
  if (engineTransitionActive || generationPreparationPending) return;
  if (generationActive) {
    if (generationCancelRequested) return;
    generationCancelRequested = true;
    if (continuousRun) continuousRun.stop = true;
    generateButton.classList.add("is-cancelling");
    generateButtonLabel.textContent = "중지 중";
    generateButtonHint.textContent = "현재 작업 종료 요청됨";
    window.dispatchEvent(new CustomEvent("lakis:generation-cancel-request"));
    return;
  }

  generationPreparationPending = true;
  engineSwitchBusy = true;
  syncGenerationEngineUI();
  try {
  await workflowConfigurationReady;
  const mossMode = currentGenerationEngine() === "moss";
  if (engineConfiguration?.preview_only) throw new Error("화면 프로토타입에서는 실제 생성을 실행하지 않습니다.");
  if (!mossMode && engineConfiguration?.anima?.ready === false) throw new Error("이 MOSS 전용 실행 환경에서는 ANIMA 생성을 지원하지 않습니다.");
  if (mossMode && !engineConfiguration?.moss?.ready) throw new Error("MOSS 필수 모델과 ComfyUI 노드의 준비 상태를 확인해 주세요.");
  if (continuousAdvance) {
    continuousAdvance = false;
    continuousRun.index += 1;
  } else {
    continuousRun = { index: 1, total: state.continuous.enabled ? state.continuous.count : 1, stop: false };
  }
  continuousRun.total > 1 ? setContinuousProgress(`${continuousRun.index} / ${continuousRun.total}`, "생성 중") : setContinuousProgress();

  if (state.i2i.enabled && !state.i2i.image_name) {
    continuousRun = null; setContinuousProgress();
    i2iStatus.textContent = "i2i 입력 이미지를 먼저 선택해 주세요.";
    i2iDropZone.focus();
    return;
  }
  if (!mossMode && state.inpaint.enabled) {
    try {
      if (!await requireLLLiteInpaintWeight()) { continuousRun = null; setContinuousProgress(); return; }
    } catch (error) {
      continuousRun = null; setContinuousProgress();
      inpaintStatus.textContent = "Inpainting 모델 설치 상태를 확인하지 못했습니다.";
      return;
    }
    try { await uploadInpaintMask(); }
    catch (error) { continuousRun = null; setContinuousProgress(); inpaintStatus.textContent=error.message; inpaintCanvas.focus(); return; }
  }

  // Number inputs do not always dispatch `change` before a nearby button is
  // activated (notably with spinner/IME interaction). Read the visible size
  // again so every generation uses the ratio currently shown in the UI.
  syncOutputStateFromInputs();
  if (state.output.seed_mode === "random") {
    state.output.seed = Math.floor(Math.random() * (COMFYUI_SEED_MAX + 1));
    document.querySelector("#seedInput").value = state.output.seed;
  }
  // Read the visible controls again at submission time. This prevents a stale
  // startup/default state from replacing text the user has just entered.
  syncPromptStateFromInputs();
  saveLocalPromptState();
  setPreviewModeLabel(generationModeLabel());
  document.querySelector("#previewI2i").hidden = !state.i2i.enabled;
  document.querySelector("#previewSeed").textContent = `SEED ${state.output.seed}`;
  document.querySelector("#previewDuration").hidden = true;
  // A zoom chosen for the previous aspect ratio must not make the next image
  // appear cropped or locked to that ratio.
  setPreviewZoom(100);
  const generationTrace = window.LAKISGenerationDiagnostics.createContext();
  let generationPayload;
  try {
    generationPayload = structuredClone(state);
    delete generationPayload.generation.profiles;
    if (mossMode) {
      generationPayload.generation.mode = "moss";
      generationPayload.generation.lakis_mode = false;
      generationPayload.moss_regions = window.LAKISMossRegions.snapshot();
      if (generationPayload.i2i.enabled) generationPayload.moss_regions.enabled = false;
      generationPayload.moss_detail = { ...state.moss_detail, enabled: false };
      generationPayload.node_overrides = {};
      generationPayload.inpaint.enabled = false;
      generationPayload.scene_controls = { enabled: false, toyxyz_enabled: false };
    }
    generationPayload.composition_enabled = state.composition_enabled
      && !generationPayload.i2i.enabled && !generationPayload.inpaint.enabled;
    window.LAKISGenerationDiagnostics.bind(generationPayload, generationTrace);
    window.LAKISGenerationDiagnostics.mark(generationTrace, "prompt_prepare");
    const promptTemplate = mossMode
      ? Object.fromEntries(Object.entries(state.prompt).map(([key, value]) => [
          key, state.prompt_enabled?.[key] === false ? "" : value,
        ]))
      : await window.lakisPromptForGeneration(state.prompt);
    const inpaintTemplate = structuredClone(generationPayload.inpaint);
    window.LAKISGenerationDiagnostics.mark(generationTrace, "wildcard_resolve");
    const wildcardResult = await window.lakisResolveWildcardsForGeneration({
      prompt: promptTemplate, inpaint: inpaintTemplate, seed: state.output.seed,
    });
    generationPayload.prompt = wildcardResult.prompt;
    generationPayload.inpaint = wildcardResult.inpaint;
    generationPayload.wildcard = {
      enabled: state.wildcard_enabled,
      prompt_template: promptTemplate,
      inpaint_template: inpaintTemplate.operation === "remove" ? null : {
        prompt: inpaintTemplate.prompt, negative_prompt: inpaintTemplate.negative_prompt,
      },
      selections: wildcardResult.selections,
    };
    const inpaintNeedsTranslation = state.inpaint.enabled && [state.inpaint.prompt, state.inpaint.negative_prompt].some(containsKoreanPrompt);
    const regionsNeedTranslation = mossMode && generationPayload.moss_regions.enabled
      && generationPayload.moss_regions.regions.some(region => [region.caption, region.negative_prompt].some(containsKoreanPrompt));
    if ((state.translation_enabled && (Object.values(generationPayload.prompt).some(containsKoreanPrompt) || regionsNeedTranslation)) || inpaintNeedsTranslation) {
      setGenerationProgress(0, "프롬프트 번역 중");
    }
    window.LAKISGenerationDiagnostics.mark(generationTrace, "prompt_translate");
    generationPayload.prompt = await translatedPromptForGeneration(generationPayload.prompt);
    window.LAKISGenerationDiagnostics.mark(generationTrace, "inpaint_translate");
    generationPayload.inpaint = await translatedInpaintForGeneration(generationPayload.inpaint);
    if (mossMode) {
      window.LAKISGenerationDiagnostics.mark(generationTrace, "region_translate");
      generationPayload.moss_regions = await translatedMossRegionsForGeneration(generationPayload.moss_regions);
    }
    window.LAKISGenerationDiagnostics.mark(generationTrace, "scene_prepare");
    if (!mossMode) await window.lakisPrepareScene(generationPayload);
    lastPreviewRevision = 0;
    lastGenerationState = "preparing";
    setGenerationProgress(0, "생성 중");
    generationSubmissionPending = true;
    window.dispatchEvent(new CustomEvent("lakis:generate", { detail: generationPayload }));
  } catch (error) {
    const failure = window.LAKISGenerationDiagnostics.preparationFailure(error, generationTrace).lakis;
    showGenerationError(error.message || failure.error, failure.error_code, {
      stage: failure.error_stage, failureComponent: failure.failure_component,
      failureStep: failure.failure_step, exceptionType: failure.error_exception_type,
      reportMessage: failure.error,
      clientRequestId: failure.client_request_id,
      submissionDiagnostic: failure.submission_diagnostic,
      diagnostics: clientGenerationDiagnostics(generationPayload || state),
      errorDetail: failure.error_detail,
    });
  }
  } finally {
    generationPreparationPending = false;
    engineSwitchBusy = generationActive || generationSubmissionPending;
    syncGenerationEngineUI();
  }
});
window.addEventListener("lakis:wildcard-enabled", event => {
  state.wildcard_enabled = Boolean(event.detail);
  scheduleGenerationStateSave();
});
window.addEventListener("lakis:moss-regions-change", () => {
  state.moss_regions = window.LAKISMossRegions.snapshot();
  syncMossI2iAvailability();
  syncPromptHeadings();
  scheduleGenerationStateSave();
});
for (const [id, key, convert] of [
  ["mossDetailScope", "scope", String],
  ["mossDetailSteps", "steps", Number],
  ["mossDetailDenoise", "denoise", Number],
]) {
  document.querySelector(`#${id}`).addEventListener("change", event => {
    state.moss_detail[key] = convert(event.target.value);
    render();
    scheduleGenerationStateSave();
  });
}
window.addEventListener("lakis:wildcard-exclusions", event => {
  state.wildcard_exclusions = event.detail && typeof event.detail === "object" ? structuredClone(event.detail) : {};
  scheduleGenerationStateSave();
});
document.addEventListener("click", event => {
  if (!event.target.closest(".workflow-launcher")) closeWorkflowMenu();
  if (!event.target.closest(".sidebar-resource-launcher")) closeSidebarResourceMenu();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    closeWorkflowMenu();
    closeSidebarResourceMenu();
  }
});

window.addEventListener("lakis:generate", async event => {
  try {
    const result = await window.LAKISGenerationDiagnostics.submit(event.detail);
    lastGenerationSubmission = result.submission_diagnostic;
    lastGenerationState = "preparing";
  } catch (error) {
    const transportFailure = !error.lakis;
    showGenerationError(error.message, error.lakis?.error_code || (transportFailure ? "LKS-GEN-1012" : ""), {
      stage: error.lakis?.error_stage || (transportFailure ? "생성 서버 연결" : "요청 검증"),
      nodeId: error.lakis?.error_node_id, nodeType: error.lakis?.error_node_type,
      requestId: error.lakis?.request_id,
      promptId: error.lakis?.prompt_id,
      exceptionType: error.lakis?.error_exception_type || error.name,
      failureComponent: error.lakis?.failure_component || "frontend",
      failureStep: error.lakis?.failure_step || "request_send",
      clientRequestId: error.lakis?.client_request_id,
      submissionDiagnostic: error.lakis?.submission_diagnostic,
      settingDiagnostic: error.lakis?.setting_diagnostic,
      diagnostics: error.lakis?.diagnostic_context || clientGenerationDiagnostics(event.detail),
      errorDetail: error.lakis?.error_detail || (transportFailure
        ? `Frontend request failure: ${error.name || "Error"}: ${error.message || String(error)}`
        : null),
    });
  } finally {
    generationSubmissionPending = false;
    engineSwitchBusy = generationActive || generationPreparationPending;
    syncGenerationEngineUI();
  }
});

window.addEventListener("lakis:generation-cancel-request", async () => {
  try {
    const response = await fetch("/api/cancel", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || result.reason || "중지 실패");
  } catch (error) {
    generationCancelRequested = false;
    showGenerationError(`생성 중지 요청에 실패했어요.\n${error.message}`);
  }
});

render();
