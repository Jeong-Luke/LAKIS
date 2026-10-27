import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { findMissingPaintPrompt } from "../../src/external_ui/toyxyz-prompt-validation.js";
import { applyBodyModel } from "../../src/external_ui/pose-body-model.js";
import { api as poseApi } from "../../src/external_ui/scripts/api.js";

const appSource = await readFile(new URL("../../src/external_ui/app.js", import.meta.url), "utf8");
const sceneSource = await readFile(new URL("../../src/external_ui/scene-controls.js", import.meta.url), "utf8");

function blockEnd(source, start) {
  let depth = 0, quote = "", lineComment = false, blockComment = false;
  for (let index = start; index < source.length; index++) {
    const character = source[index], next = source[index + 1];
    if (lineComment) { if (character === "\n") lineComment = false; continue; }
    if (blockComment) {
      if (character === "*" && next === "/") { blockComment = false; index++; }
      continue;
    }
    if (quote) {
      if (character === "\\") index++;
      else if (character === quote) quote = "";
      continue;
    }
    if (character === "/" && next === "/") { lineComment = true; index++; }
    else if (character === "/" && next === "*") { blockComment = true; index++; }
    else if ("'\"`".includes(character)) quote = character;
    else if (character === "{") depth++;
    else if (character === "}" && --depth === 0) return index + 1;
  }
  throw Error("Unclosed source block");
}
function functionSource(source, name) {
  const match = new RegExp(`\\bfunction\\s+${name}\\s*\\(`).exec(source);
  assert.ok(match, name);
  return source.slice(match.index, blockEnd(source, source.indexOf("{", match.index)));
}
function element() {
  const attributes = new Map(), classes = new Set();
  return {
    disabled: false, hidden: false,
    setAttribute: (name, value) => attributes.set(name, String(value)),
    getAttribute: name => attributes.get(name),
    classList: {
      toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
      add: name => classes.add(name), remove: name => classes.delete(name),
    },
  };
}

test("model checks load without the removed installation notice UI", async () => {
  const result = {
    state: { enabled: true, toyxyz_enabled: true },
    models: { pose: { model: "pose.safetensors", valid: true } },
  };
  const requests = [];
  const context = {
    panel: { querySelector() { assert.fail("model checks must not require notice elements"); } },
    fetch: async (url, options) => {
      requests.push([url, options.cache]);
      return { ok: true, json: async () => result };
    },
  };
  vm.runInNewContext("async " + functionSource(sceneSource, "refreshModels")
    + "; this.refreshModels = refreshModels;", context);
  assert.equal(await context.refreshModels(), result);
  assert.deepEqual(requests, [["/api/scene-controls", "no-store"]]);
  context.fetch = async () => ({ ok: false, json: async () => ({ error: "모델 상태 조회 실패" }) });
  await assert.rejects(context.refreshModels(), /모델 상태 조회 실패/);
});

test("unchanged generation windows never overwrite another editor on hide or close", async () => {
  const sent = [], timers = [];
  let succeed = true;
  const context = vm.createContext({
    state: { output: { seed_mode: "current", seed: 123 } },
    generationStateHydrated: true, generationStateSaveTimer: null,
    lastSavedGenerationState: null, Blob,
    navigator: { sendBeacon: (url, body) => { sent.push({ url, body }); return true; } },
    clearTimeout() {}, setTimeout: callback => { timers.push(callback); return timers.length; },
    fetch: async (url, options) => {
      sent.push({ url, body: options.body });
      return { ok: succeed, status: succeed ? 200 : 503 };
    },
    console: { error() {} },
  });
  vm.runInContext(["persistedGenerationState", "scheduleGenerationStateSave", "flushGenerationState"]
    .map(name => functionSource(appSource, name)).join("\n"), context);
  vm.runInContext("flushGenerationState(); lastSavedGenerationState = JSON.stringify(persistedGenerationState()); flushGenerationState(); scheduleGenerationStateSave();", context);
  await timers.shift()();
  assert.equal(sent.length, 0);
  vm.runInContext("state.output.seed = 456; scheduleGenerationStateSave();", context);
  await timers.shift()();
  vm.runInContext("flushGenerationState()", context);
  assert.equal(sent.length, 1);
  assert.equal(JSON.parse(sent[0].body).output.seed, 456);
  succeed = false;
  vm.runInContext("state.output.seed = 789; scheduleGenerationStateSave();", context);
  await timers.shift()();
  vm.runInContext("flushGenerationState(); flushGenerationState();", context);
  assert.equal(sent.length, 3);
  assert.equal(JSON.parse(await sent[2].body.text()).output.seed, 789);
});

test("unchanged or uninitialized pose windows do not beacon stale configuration", async () => {
  const sent = [];
  const context = vm.createContext({
    config: { enabled: false, pose_data: "old" }, lastSavedSceneState: null,
    toySaveTimer: null, saveTimer: null, saveQueue: Promise.resolve(), Blob,
    clearTimeout() {}, report: error => { throw error; },
    navigator: { sendBeacon: (url, body) => { sent.push({ url, body }); return true; } },
    fetch: async (url, options) => {
      sent.push({ url, body: options.body });
      return { ok: true, json: async () => ({ ok: true }) };
    },
  });
  vm.runInContext(["persist", "flushSceneState"]
    .map(name => functionSource(sceneSource, name)).join("\n"), context);
  vm.runInContext("flushSceneState(); lastSavedSceneState = JSON.stringify(config); flushSceneState();", context);
  assert.equal(sent.length, 0);
  vm.runInContext("config.pose_data = 'edited';", context);
  await context.persist();
  context.flushSceneState();
  assert.equal(sent.length, 1);
  assert.equal(JSON.parse(sent[0].body).pose_data, "edited");
  vm.runInContext("config.pose_data = 'final'; flushSceneState(); flushSceneState();", context);
  assert.equal(sent.length, 2);
  assert.equal(JSON.parse(await sent[1].body.text()).pose_data, "final");
});

test("precision prompts import the real editor and preserve ordinary and negative prompts", async () => {
  const previousDocument = globalThis.document, previousWindow = globalThis.window;
  globalThis.document = { readyState: "loading", addEventListener() {} };
  globalThis.window = { addEventListener() {} };
  try {
    const { generationPrompt, editorPainting } = await import("../../src/external_ui/precision-prompts.js");
    const prompt = { trigger: "trigger", quality: "quality", artist: "artist",
      fixed: "fixed", general: "ordinary", negative: "unchanged negative" };
    const disabled = generationPrompt({ enabled: false, toyxyz_enabled: false }, prompt);
    assert.deepEqual(disabled, prompt);
    assert.notEqual(disabled, prompt);
    const config = {
      enabled: true, toyxyz_enabled: true,
      precision_prompts: { trigger: "new trigger", quality: "new quality", global: "scene", background: "park" },
      toyxyz_paint_data: JSON.stringify({ base: { prompt: "legacy" }, background: { prompt: "" }, layers: [] }),
    };
    const generated = generationPrompt(config, prompt);
    assert.deepEqual(generated, { trigger: "new trigger", quality: "new quality",
      artist: "", fixed: "", general: "scene", negative: "unchanged negative" });
    assert.equal(prompt.general, "ordinary");
    const painting = JSON.parse(editorPainting(config, prompt));
    assert.equal(painting.base.prompt, "");
    assert.equal(painting.background.prompt, "park");
    assert.equal(JSON.parse(config.toyxyz_paint_data).base.prompt, "legacy");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});

test("pose activation locks conflicting modes without discarding their values", () => {
  const state = {
    scene_controls: { enabled: true, toyxyz_enabled: true },
    composition_enabled: true,
    i2i: { enabled: true, image_name: "kept.png", denoise: .37 },
    inpaint: { enabled: true, image_name: "source.png", mask_name: "mask.png", prompt: "kept" },
  };
  const before = structuredClone(state);
  const elements = new Map(["#compositionToggle", "#compositionControls", ".i2i-panel", ".control-column"].map(key => [key, element()]));
  const context = vm.createContext({
    state, document: { querySelector: selector => elements.get(selector) },
    i2iToggle: element(), inpaintToggle: element(),
    inpaintControls: element(), inpaintPromptPanel: element(), inpaintCanvas: element(),
    requestAnimationFrame() {}, syncInpaintCanvasLayout() {}, showI2iCompositionNotice() {},
  });
  const names = ["isToyxyzEnabled", "syncPoseModeAvailability", "setCompositionEnabled",
    "renderCompositionAvailability", "setInpaintEnabled", "setI2iEnabled"];
  vm.runInContext(names.map(name => functionSource(appSource, name)).join("\n"), context);
  vm.runInContext("syncPoseModeAvailability(); setI2iEnabled(true); setInpaintEnabled(true); setCompositionEnabled(true);", context);
  assert.deepEqual(state.i2i, { ...before.i2i, enabled: false });
  assert.deepEqual(state.inpaint, { ...before.inpaint, enabled: false });
  assert.equal(state.composition_enabled, false);
  assert.equal(context.i2iToggle.disabled, true);
  assert.equal(context.inpaintToggle.disabled, true);
  assert.equal(elements.get("#compositionToggle").disabled, true);
  state.scene_controls.enabled = state.scene_controls.toyxyz_enabled = false;
  vm.runInContext("syncPoseModeAvailability()", context);
  assert.equal(context.i2iToggle.disabled, false);
  assert.equal(context.inpaintToggle.disabled, false);
  assert.equal(elements.get("#compositionToggle").disabled, false);
});

function generationHarness() {
  let click, release;
  const pending = new Promise(resolve => { release = resolve; });
  const dispatched = [], errors = [];
  const state = {
    continuous: { enabled: false, count: 1 }, i2i: { enabled: false }, inpaint: { enabled: false },
    output: { seed_mode: "fixed", seed: 719 }, prompt: { general: "adult in a coat" },
    composition_enabled: false, translation_enabled: false,
  };
  const context = vm.createContext({
    state, generationActive: false, generationPreparationPending: false,
    generationSubmissionPending: false, generationCancelRequested: false,
    continuousAdvance: false, continuousRun: null, lastPreviewRevision: 0, lastGenerationState: "",
    generateButton: { ...element(), addEventListener: (type, listener) => { click = listener; } },
    generateButtonLabel: {}, generateButtonHint: {},
    document: { querySelector: () => ({}) }, structuredClone,
    window: {
      lakisPromptForGeneration: async prompt => { await pending; return structuredClone(prompt); },
      lakisResolveWildcardsForGeneration: async ({ prompt, inpaint }) => ({ prompt, inpaint, selections: [] }),
      lakisPrepareScene: async () => {},
      dispatchEvent: event => dispatched.push(event),
    },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    setContinuousProgress() {}, syncOutputStateFromInputs() {}, syncPromptStateFromInputs() {},
    saveLocalPromptState() {}, setPreviewModeLabel() {}, generationModeLabel: () => "FAST",
    setPreviewZoom() {}, containsKoreanPrompt: () => false,
    translatedPromptForGeneration: async value => value,
    translatedInpaintForGeneration: async value => value,
    setGenerationProgress() { context.generationActive = true; },
    showGenerationError(message) { errors.push(message); context.generationActive = false; },
  });
  const begin = appSource.indexOf('generateButton.addEventListener("click",');
  const end = appSource.indexOf('window.addEventListener("lakis:wildcard-enabled",', begin);
  assert.ok(begin >= 0 && end > begin);
  vm.runInContext(appSource.slice(begin, end), context);
  return { context, click: () => click(), release, dispatched, errors };
}

test("a second click during asynchronous pose preparation cannot submit twice", async () => {
  const h = generationHarness();
  const first = h.click();
  await h.click();
  assert.equal(h.dispatched.length, 0);
  h.release();
  await first;
  assert.equal(h.dispatched.length, 1);
  assert.equal(h.dispatched[0].type, "lakis:generate");
  assert.equal(h.dispatched[0].detail.output.seed, 719);
  assert.equal(h.context.generationPreparationPending, false);
});

test("failed pose capture submits nothing and permits a later explicit click", async () => {
  const h = generationHarness();
  h.context.window.lakisPrepareScene = async () => { throw Error("capture failed"); };
  const first = h.click();
  h.release();
  await first;
  assert.deepEqual(h.errors, ["capture failed"]);
  assert.equal(h.dispatched.length, 0);
  assert.equal(h.context.generationPreparationPending, false);
  h.context.window.lakisPrepareScene = async () => {};
  await h.click();
  assert.equal(h.dispatched.length, 1);
});

function sceneHarness() {
  const painting = { layers: [{ id: "person", visible: true, prompt: "coat" }],
    base: { prompt: "" }, background: { prompt: "sky" } };
  const config = { enabled: true, toyxyz_enabled: true, pose_data: "pose",
    toyxyz_render_data: "capture", toyxyz_paint_data: JSON.stringify(painting) };
  const calls = [];
  const context = vm.createContext({
    config, state: { translation_enabled: true },
    window: { lakisResolveWildcardsForGeneration: async ({ prompt }) => ({ prompt, selections: [] }) },
    ready: Promise.resolve(),
    refreshModels: async () => ({ models: { pose: { valid: true }, region: { valid: true } } }),
    ensureToyEditor: async () => calls.push("load"), toySaveTimer: null, toyCapture: null,
    requestToy: async (type, validate) => { calls.push([type, validate]); return { captured: true }; },
    rememberToy: result => { assert.equal(result.captured, true); calls.push("capture"); },
    saveTimer: null, clearTimeout() {}, persist: async () => calls.push("persist"),
    structuredClone, translatedPromptForGeneration: async value => ({ general: `translated:${value.general}` }),
  });
  const begin = sceneSource.indexOf("window.lakisPrepareScene =");
  const body = sceneSource.indexOf("{", begin);
  vm.runInContext(sceneSource.slice(begin, blockEnd(sceneSource, body)), context);
  const payload = { composition_enabled: true, i2i: { enabled: true }, inpaint: { enabled: true },
    output: { seed: 719 }, wildcard: { selections: [] } };
  return { painting, config, calls, context, payload };
}

test("scene payload uses current captured pose, translates a copy and disables conflicting modes", async () => {
  const { painting, config, calls, context, payload } = sceneHarness();
  await context.window.lakisPrepareScene(payload);
  assert.equal(payload.composition_enabled, false);
  assert.equal(payload.i2i.enabled, false);
  assert.equal(payload.inpaint.enabled, false);
  assert.deepEqual(calls, ["load", ["lakis:toyxyz-capture", true], "capture", "persist"]);
  assert.equal(JSON.parse(payload.scene_controls.toyxyz_paint_data).layers[0].prompt, "translated:coat");
  assert.equal(config.toyxyz_paint_data, JSON.stringify(painting));
  assert.notEqual(payload.scene_controls, config);
  calls.length = 0;
  context.refreshModels = async () => ({
    models: { pose: { model: "pose.safetensors", valid: false }, region: { valid: true } },
  });
  await assert.rejects(context.window.lakisPrepareScene({}), /pose\.safetensors/);
  assert.deepEqual(calls, []);
});

test("disabled poses keep saved scene data but exclude it from generation", async () => {
  for (const [enabled, toyxyz_enabled] of [[false, false], [false, true], [true, false]]) {
    const { config, calls, context, payload } = sceneHarness();
    Object.assign(config, { enabled, toyxyz_enabled, toyxyz_render_data: "x".repeat(1_500_000) });
    const original = JSON.stringify(config);
    context.window.lakisResolveWildcardsForGeneration = async () => assert.fail("disabled scene must not resolve prompts");
    await context.window.lakisPrepareScene(payload);
    assert.deepEqual({ ...payload.scene_controls }, { enabled: false, toyxyz_enabled: false });
    assert.equal(JSON.stringify(config), original);
    assert.equal(payload.composition_enabled, true);
    assert.equal(payload.i2i.enabled, true);
    assert.equal(payload.inpaint.enabled, true);
    assert.deepEqual(calls, ["persist"]);
  }
});

test("two-person scene wildcards resolve before optional translation without changing saved masks or templates", async () => {
  for (const translationEnabled of [false, true]) {
    const { config, context, payload } = sceneHarness();
    const painting = {
      layers: [
        { id: "first", visible: true, prompt: "__outfit__", mask: "first-mask" },
        { id: "second", visible: true, prompt: "__outfit__", mask: "second-mask" },
        { id: "hidden", visible: false, prompt: "__missing__", mask: "hidden-mask" },
      ],
      base: { prompt: "__common__" }, background: { prompt: "__background__" },
    };
    config.toyxyz_paint_data = JSON.stringify(painting);
    const original = JSON.stringify(config);
    context.state.translation_enabled = translationEnabled;
    const outfit = { name: "outfit", value: "coat" };
    const common = { name: "common", value: "daylight" };
    const background = { name: "background", value: "park" };
    payload.wildcard.selections = [outfit];
    let resolutions = 0;
    const translations = [];
    context.window.lakisResolveWildcardsForGeneration = async request => {
      resolutions++;
      assert.deepEqual({ ...request.prompt }, {
        0: "__outfit__", 1: "__outfit__", 2: "__common__", 3: "__background__",
      });
      assert.equal(request.seed, payload.output.seed);
      assert.deepEqual({ ...request.inpaint }, {});
      return {
        prompt: { 0: "coat", 1: "coat", 2: "daylight", 3: "park" },
        selections: [outfit, common, background],
      };
    };
    context.translatedPromptForGeneration = async value => {
      translations.push(value.general);
      return { general: `translated:${value.general}` };
    };
    await context.window.lakisPrepareScene(payload);
    const submitted = JSON.parse(payload.scene_controls.toyxyz_paint_data);
    const text = value => translationEnabled ? `translated:${value}` : value;
    assert.deepEqual(submitted.layers, [
      { ...painting.layers[0], prompt: text("coat") },
      { ...painting.layers[1], prompt: text("coat") },
      painting.layers[2],
    ]);
    assert.equal(submitted.base.prompt, text("daylight"));
    assert.equal(submitted.background.prompt, text("park"));
    assert.equal(resolutions, 1);
    assert.deepEqual(translations, translationEnabled ? ["coat", "coat", "daylight", "park"] : []);
    assert.deepEqual(payload.wildcard.selections, [outfit, common, background]);
    assert.equal(JSON.stringify(config), original);
  }
});

test("a scene wildcard error submits nothing and a corrected explicit retry succeeds", async () => {
  const scene = sceneHarness(), generation = generationHarness();
  generation.context.window.lakisPrepareScene = scene.context.window.lakisPrepareScene;
  scene.config.toyxyz_paint_data = JSON.stringify({
    layers: [{ id: "person", visible: true, prompt: "__outfit__" }],
    base: { prompt: "" }, background: { prompt: "" },
  });
  const original = scene.config.toyxyz_paint_data;
  scene.context.window.lakisResolveWildcardsForGeneration = async () => { throw Error("와일드카드 'outfit'을 찾을 수 없습니다."); };
  const first = generation.click();
  generation.release();
  await first;
  assert.deepEqual(generation.errors, ["와일드카드 'outfit'을 찾을 수 없습니다."]);
  assert.equal(generation.dispatched.length, 0);
  assert.equal(generation.context.generationPreparationPending, false);
  scene.context.window.lakisResolveWildcardsForGeneration = async ({ prompt }) => ({
    prompt: { ...prompt, 0: "coat" }, selections: [{ name: "outfit", value: "coat" }],
  });
  await generation.click();
  assert.equal(generation.dispatched.length, 1);
  const submitted = JSON.parse(generation.dispatched[0].detail.scene_controls.toyxyz_paint_data);
  assert.equal(submitted.layers[0].prompt, "translated:coat");
  assert.equal(scene.config.toyxyz_paint_data, original);
});

test("the editor API cannot download models or submit a second generation", () => {
  assert.throws(() => poseApi.fetchApi("/prompt"), /수동 포즈/);
  assert.throws(() => poseApi.fetchApi("/toyxyz/pose3d/sam-model"), /수동 포즈/);
});

function painter(entries) {
  const layers = entries.map((entry, index) => ({ id: String(index), visible: true, prompt: "", ...entry }));
  const masks = new Map(layers.map(layer => [layer, { canvas: { getContext: () => ({
    getImageData: () => ({ data: new Uint8ClampedArray(layer.alpha.flatMap(alpha => [0, 0, 0, alpha])) }),
  }) } }]));
  return { width: 2, height: 1, layers, layerMasks: { render: () => masks } };
}
test("only visible, uncovered painted regions require a prompt", () => {
  const missing = painter([{ alpha: [255, 0], prompt: " \n\t" }]);
  assert.equal(findMissingPaintPrompt(missing).layer, missing.layers[0]);
  for (const layers of [
    [], [{ alpha: [255, 255], visible: false }], [{ alpha: [0, 0] }],
    [{ alpha: [255, 255] }, { alpha: [255, 255], prompt: "front person" }],
  ]) assert.equal(findMissingPaintPrompt(painter(layers)), null);
  for (const alpha of [[255, 0], [254, 255]]) {
    assert.equal(findMissingPaintPrompt(painter([
      { alpha: [255, 255] }, { alpha, prompt: "front person" },
    ])).index, 0);
  }
});

test("changing an MHR body preserves its pose, the other person and undo history", async () => {
  const body = id => ({ id, body: "male", source: "MHR", ik: [{ enabled: true }],
    joints: [{ quaternion: [.2, 0, 0, Math.sqrt(.96)] }] });
  const original = { bodies: [body("one"), body("two")] };
  const editor = {
    state: structuredClone(original), selectedBody: { id: "two", source: "MHR" },
    history: [structuredClone(original)], future: [],
    get bodies() { return this.state.bodies.map(record => ({ chains: record.ik })); },
    snapshot() { return structuredClone(this.state); },
    record() {}, commit() {},
    async load(next) {
      assert.ok(next.bodies.every(record => record.ik.every(chain => !chain.enabled)));
      this.state = structuredClone(next);
      this.history = [];
    },
  };
  const female = JSON.parse(await readFile(new URL("../../src/external_ui/pose-presets/female-shape-preset.json", import.meta.url)));
  assert.equal(female.schema, "MHR.identity45.v1");
  assert.equal(female.coefficients.length, 45);
  await applyBodyModel(editor, "female", female);
  assert.deepEqual(editor.state.bodies[0], original.bodies[0]);
  assert.deepEqual(editor.state.bodies[1].joints, original.bodies[1].joints);
  assert.deepEqual(editor.state.bodies[1].ik, original.bodies[1].ik);
  assert.equal(editor.state.bodies[1].body, "female");
  assert.deepEqual(editor.history, [original]);
});
