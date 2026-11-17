const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8").replace(/\r\n/g, "\n");
new vm.Script(source);
const names = [
  "setCompositionEnabled", "renderCompositionAvailability", "setI2iEnabled",
  "setInpaintEnabled", "syncI2iControls", "applyPersistedGenerationState",
  "persistedGenerationState", "syncPoseModeAvailability",
];
const script = names.map(name => {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf("\n}\n", start);
  assert.ok(start >= 0 && end > start, name);
  return source.slice(start, end + 3);
}).join("\n");

function element() {
  const classes = new Set();
  return {
    hidden: false, disabled: false, attributes: {},
    classList: {
      toggle(name, enabled) {
        if (enabled) classes.add(name);
        else classes.delete(name);
      },
      contains(name) { return classes.has(name); },
    },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
  };
}

function fixture(engine = "anima") {
  const elements = new Map();
  const state = {
    generation: { engine, profiles: {} }, composition_enabled: true,
    i2i: { enabled: false, image_name: "keep-i2i.webp", denoise: 0.5 },
    inpaint: { enabled: false, image_name: "keep-inpaint.webp", prompt: "keep prompt" },
    model: {}, output: {}, loras: [], camera: {}, continuous: {},
    moss_regions: {}, moss_detail: {},
  };
  const context = {
    state, structuredClone, window: {},
    engineConfiguration: { moss: { capabilities: { i2i: false, composition: true } } },
    currentGenerationEngine: () => state.generation.engine,
    isToyxyzEnabled: () => false,
    isStateRecord: value => value !== null && typeof value === "object" && !Array.isArray(value),
    document: {
      querySelector(selector) {
        if (!elements.has(selector)) elements.set(selector, element());
        return elements.get(selector);
      },
    },
    i2iPreviewUrls: new Map(),
    showI2iCompositionNotice() {}, syncMossI2iAvailability() {}, syncAnimaAvailability() {},
    syncPromptHeadings() {}, captureGenerationEngineProfile() {},
    requestAnimationFrame() {}, syncInpaintCanvasLayout() {}, drawCamera3d() {},
  };
  for (const name of [
    "i2iToggle", "i2iDenoise", "i2iDenoiseNumber", "i2iAutoSize",
    "i2iPreview", "i2iPlaceholder", "i2iRemove",
    "inpaintToggle", "inpaintControls", "inpaintPromptPanel", "inpaintCanvas",
  ]) context[name] = element();
  vm.createContext(context);
  vm.runInContext(script, context);
  return { context, state, elements };
}

{
  const { context, state, elements } = fixture();
  context.setI2iEnabled(true);
  assert.equal(state.i2i.enabled, true);
  assert.equal(state.composition_enabled, false);
  assert.equal(elements.get("#compositionToggle").attributes["aria-pressed"], "false");
  assert.equal(elements.get("#compositionToggle").classList.contains("on"), false);
  assert.equal(context.persistedGenerationState().composition_enabled, false);
  assert.equal(state.i2i.image_name, "keep-i2i.webp");
  context.setCompositionEnabled(true);
  assert.equal(state.composition_enabled, false);
  context.setI2iEnabled(false);
  context.setCompositionEnabled(true);
  assert.equal(state.composition_enabled, true);
}

{
  const { context, state } = fixture();
  state.i2i.enabled = true;
  context.setInpaintEnabled(true);
  assert.equal(state.inpaint.enabled, true);
  assert.equal(state.i2i.enabled, false);
  assert.equal(state.composition_enabled, false);
  assert.equal(state.inpaint.image_name, "keep-inpaint.webp");
  assert.equal(state.inpaint.prompt, "keep prompt");
  assert.equal(state.i2i.image_name, "keep-i2i.webp");
  context.setCompositionEnabled(true);
  assert.equal(state.composition_enabled, false);
  context.setI2iEnabled(true);
  assert.equal(state.inpaint.enabled, false);
  assert.equal(state.i2i.enabled, true);
  assert.equal(state.composition_enabled, false);
}

{
  const { context, state } = fixture();
  context.applyPersistedGenerationState({
    composition_enabled: true,
    i2i: { enabled: true, image_name: "restored-input.webp", denoise: 0.4 },
  });
  context.syncI2iControls();
  const saved = context.persistedGenerationState();
  assert.equal(saved.composition_enabled, false);
  assert.equal(saved.i2i.enabled, true);
  assert.equal(saved.i2i.image_name, "restored-input.webp");
  assert.equal(state.i2i.denoise, 0.4);
}

{
  const { context, state } = fixture("moss");
  context.setI2iEnabled(true);
  assert.equal(state.i2i.enabled, false);
  assert.equal(state.composition_enabled, true);
  assert.equal(state.i2i.image_name, "keep-i2i.webp");
}

{
  const { context, state, elements } = fixture();
  state.i2i = { enabled: true, image_name: "keep-i2i.webp", denoise: 0.37, auto_size: true };
  context.i2iPreviewUrls.set("anima", { name: "keep-i2i.webp", url: "data:image/webp;base64,WA==" });
  context.syncI2iControls();
  const panel = elements.get(".i2i-panel");
  assert.equal(panel.classList.contains("is-disabled"), false);
  const saved = structuredClone(state.i2i);
  context.setI2iEnabled(false);
  assert.equal(panel.classList.contains("is-disabled"), true);
  assert.deepEqual(state.i2i, { ...saved, enabled: false });
  context.setI2iEnabled(true);
  assert.equal(panel.classList.contains("is-disabled"), false);
  assert.deepEqual(state.i2i, saved);
  assert.equal(context.i2iPreview.src, "data:image/webp;base64,WA==");
  state.i2i.enabled = false;
  context.syncI2iControls();
  assert.equal(panel.classList.contains("is-disabled"), true);
  assert.equal(state.i2i.image_name, saved.image_name);
  assert.equal(state.i2i.denoise, saved.denoise);
  assert.equal(state.i2i.auto_size, true);
}

{
  const { context, state, elements } = fixture();
  state.camera = { x: 0.3, y: -0.2, z: 0.6, roll: 0.1, frame_y: 0.4 };
  const camera = structuredClone(state.camera);
  let poseEnabled = true, redraws = 0;
  context.isToyxyzEnabled = () => poseEnabled;
  context.drawCamera3d = () => { redraws++; };
  context.syncPoseModeAvailability();
  assert.equal(elements.get("#compositionControls").hidden, true);
  assert.equal(elements.get(".composition-panel").classList.contains("is-pose-collapsed"), true);
  assert.equal(elements.get("#compositionToggle").disabled, true);
  assert.equal(state.composition_enabled, false);
  assert.deepEqual(state.camera, camera);
  poseEnabled = false;
  context.syncPoseModeAvailability();
  assert.equal(elements.get("#compositionControls").hidden, false);
  assert.equal(elements.get(".composition-panel").classList.contains("is-pose-collapsed"), false);
  assert.equal(elements.get("#compositionToggle").disabled, false);
  assert.deepEqual(state.camera, camera);
  assert.equal(redraws, 1);
  context.renderCompositionAvailability();
  assert.equal(redraws, 1);
}

console.log("PASS: ANIMA i2i/inpaint/composition exclusivity, persisted hydration, source preservation, MOSS i2i lock, OFF/ON expansion, 3D composition collapse/restore");
