const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ui = path.join(__dirname, "../../src/external_ui");
const app = fs.readFileSync(path.join(ui, "app.js"), "utf8");
const precision = fs.readFileSync(path.join(ui, "precision-prompts.js"), "utf8")
  .replace(/^import .*;\r?\n/m, "").replace(/\bexport (const|function|class) /g, "$1 ");
const plain = value => JSON.parse(JSON.stringify(value));
const moduleContext = { structuredClone };
vm.runInNewContext(precision + "\nthis.api={generationPrompt,editorPainting,PrecisionPrompts};", moduleContext);
const { generationPrompt, editorPainting, PrecisionPrompts } = moduleContext.api;

test("positive labels follow the mode while every negative label stays fixed without editing state", () => {
  const start = app.indexOf("function syncPromptHeadings()");
  const end = app.indexOf("\nfunction syncMossI2iAvailability()", start);
  for (const [engine, pose, boxes, positive, negative] of [
    ["anima", false, false, "프롬프트", "네거티브 프롬프트"],
    ["anima", true, false, "프롬프트 ( 3D 포즈 )", "네거티브 프롬프트"],
    ["anima", false, true, "프롬프트 ( 바운딩 박스 )", "네거티브 프롬프트"],
    ["anima", true, true, "프롬프트 ( 3D포즈 · 바운딩 박스 )", "네거티브 프롬프트"],
    ["moss", true, true, "프롬프트 ( 바운딩 박스 )", "네거티브 프롬프트"],
    ["moss", true, false, "프롬프트", "네거티브 프롬프트"],
  ]) {
    const nodes = { "#positivePromptHeading": {}, "#negativePromptHeading": {} };
    const state = { anima_regions: { enabled: boxes }, moss_regions: { enabled: boxes }, prompt: { general: "keep" } };
    const before = structuredClone(state);
    vm.runInNewContext(app.slice(start, end) + "\nsyncPromptHeadings();", {
      state, currentGenerationEngine: () => engine, isToyxyzEnabled: () => pose,
      document: { querySelector: selector => nodes[selector] },
    });
    assert.equal(nodes["#positivePromptHeading"].textContent, positive);
    assert.equal(nodes["#negativePromptHeading"].textContent, negative);
    assert.deepEqual(state, before);
  }
});

test("combined generation uses the ordinary main prompt while preserving the saved pose-only prompt and layers", () => {
  const config = { enabled: true, toyxyz_enabled: true,
    precision_prompts: { trigger: "pose trigger", global: "pose-only main", background: "pose background" },
    toyxyz_paint_data: JSON.stringify({ base: { prompt: "old base" }, background: { prompt: "" },
      layers: [{ id: "person", prompt: "blue coat", future: "keep" }] }),
  };
  const prompt = { general: "combined scene", trigger: "main trigger", negative: "keep negative", future: { keep: true } };
  const before = structuredClone({ config, prompt });
  const combined = generationPrompt(config, prompt, "anima", true);
  assert.deepEqual(plain(combined), prompt);
  assert.notEqual(combined, prompt);
  assert.equal(generationPrompt(config, prompt, "anima", false).general, "pose-only main");
  assert.deepEqual(plain(generationPrompt(config, prompt, "moss", true)), prompt);
  const painting = JSON.parse(editorPainting(config, prompt, "anima"));
  assert.equal(painting.base.prompt, "");
  assert.equal(painting.background.prompt, "pose background");
  assert.deepEqual(painting.layers, JSON.parse(config.toyxyz_paint_data).layers);
  assert.deepEqual({ config, prompt }, before);
});

test("combined mode hides pose-specific inputs and leaves the ordinary main prompt visible without editing settings", () => {
  const instance = Object.create(PrecisionPrompts.prototype);
  const config = { enabled: true, toyxyz_enabled: true, precision_prompts: { global: "keep pose-only text" } };
  const before = structuredClone(config);
  let ordinaryHidden = true, headerInPose = true;
  instance.getConfig = () => config;
  instance.getEngine = () => "anima";
  instance.getRegionsEnabled = () => true;
  instance.root = { hidden: false };
  instance.normal = { classList: {
    contains: () => false,
    toggle(name, enabled) { ordinaryHidden = enabled; },
  } };
  instance.syncHeaderControls = enabled => { headerInPose = enabled; };
  instance.refresh();
  assert.equal(instance.root.hidden, true);
  assert.equal(ordinaryHidden, false);
  assert.equal(headerInPose, false);
  assert.deepEqual(config, before);
});

test("only visible pose-only inputs can be focused for a missing person prompt", () => {
  const instance = Object.create(PrecisionPrompts.prototype);
  let focused = false;
  instance.cards = new Map([["layer:person", {
    root: { scrollIntoView() {} },
    input: { focus() { focused = true; } },
  }]]);
  instance.root = { hidden: true };
  instance.refresh = () => {};
  assert.equal(instance.focusLayer("person"), false);
  assert.equal(focused, false);
  instance.root.hidden = false;
  assert.equal(instance.focusLayer("person"), true);
  assert.equal(focused, true);
});

test("combined scene preparation skips old pose text validation, translation and regional weights", async () => {
  const source = fs.readFileSync(path.join(ui, "scene-controls.js"), "utf8");
  const start = source.indexOf("window.lakisPrepareScene = async payload =>");
  const end = source.indexOf("\n  function flushSceneState()", start);
  for (const combined of [true, false]) {
    const config = { enabled: true, toyxyz_enabled: true, future: "keep",
      toyxyz_paint_data: JSON.stringify({
        layers: [{ visible: true, prompt: "old person text" }],
        base: { prompt: "old base text" }, background: { prompt: "old background text" },
      }) };
    const before = structuredClone(config);
    const captures = [];
    let translations = 0, wildcards = 0;
    const context = { structuredClone, ready: Promise.resolve(), config,
      toySaveTimer: null, toyCapture: null, saveTimer: null, clearTimeout() {},
      state: { translation_enabled: true },
      refreshModels: async () => ({ models: {
        "anima_3dpose_6200.safetensors": { valid: true },
        "anima_regional_4335.safetensors": { valid: !combined },
      } }),
      ensureToyEditor: async () => {},
      requestToy: async (type, validate) => { captures.push({ type, validate }); return {}; },
      rememberToy() {}, persist: async () => {},
      translatedPromptForGeneration: async prompt => { translations++; return prompt; },
      window: {
        lakisResolveWildcardsForGeneration: async input => { wildcards++; return { prompt: input.prompt, selections: [] }; },
      },
    };
    vm.runInNewContext(source.slice(start, end), context);
    const payload = { anima_regions: { enabled: combined }, composition_enabled: true,
      i2i: { enabled: false }, inpaint: { enabled: false }, output: { seed: 42 }, wildcard: { selections: [] } };
    await context.window.lakisPrepareScene(payload);
    assert.deepEqual(captures, [{ type: "lakis:toyxyz-capture", validate: !combined }]);
    assert.equal(wildcards, combined ? 0 : 1);
    assert.equal(translations, combined ? 0 : 3);
    assert.equal(payload.composition_enabled, false);
    assert.deepEqual(config, before);
  }
});
