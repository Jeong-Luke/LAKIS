const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { performance } = require("node:perf_hooks");

const ROOT = path.resolve(__dirname, "../..");
const appPath = path.join(ROOT, "src/external_ui/app.js");
const appSource = fs.readFileSync(appPath, "utf8").replace(/\r\n/g, "\n");

function extractBody(source, marker) {
  const markerIndex = source.indexOf(marker);
  assert.notEqual(markerIndex, -1, `missing source marker: ${marker}`);
  const opening = source.indexOf("{", markerIndex);
  assert.notEqual(opening, -1, `missing body for: ${marker}`);
  let depth = 0;
  let quote = "";
  let escaped = false;
  let lineComment = false;
  let blockComment = false;
  for (let index = opening; index < source.length; index++) {
    const char = source[index], next = source[index + 1];
    if (lineComment) {
      if (char === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (char === "*" && next === "/") { blockComment = false; index++; }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "/" && next === "/") { lineComment = true; index++; continue; }
    if (char === "/" && next === "*") { blockComment = true; index++; continue; }
    if (char === "'" || char === '"' || char === "`") { quote = char; continue; }
    if (char === "{") depth++;
    else if (char === "}" && --depth === 0) return source.slice(opening + 1, index);
  }
  assert.fail(`unterminated source body: ${marker}`);
}

function makeCrypto(mode) {
  let randomUUIDCalls = 0, randomValuesCalls = 0;
  const api = mode === "randomUUID"
    ? {
      randomUUID() { randomUUIDCalls++; return "123e4567-e89b-42d3-a456-426614174000"; },
      getRandomValues() { throw new Error("randomUUID should be preferred"); },
    }
    : {
      getRandomValues(bytes) {
        randomValuesCalls++;
        bytes.forEach((_, index) => { bytes[index] = (randomValuesCalls * 17 + index) & 0xff; });
        return bytes;
      },
    };
  return {
    api,
    get randomUUIDCalls() { return randomUUIDCalls; },
    get randomValuesCalls() { return randomValuesCalls; },
  };
}

function testPendingHydrationEditsMergeWithCanonicalState() {
  const start = appSource.indexOf("const isStateRecord =");
  const end = appSource.indexOf("function applyPersistedGenerationState", start);
  assert.ok(start >= 0 && end > start, "app.js should contain the hydration edit merger");
  const sandbox = { structuredClone };
  vm.runInNewContext(appSource.slice(start, end), sandbox, { filename: appPath });

  const initial = {
    model: { steps: 30, cfg: 5, checkpoint: "default.safetensors" },
    output: { width: 1536, height: 1024, seed_mode: "random" },
    prompt: { general: "", negative: "" },
    revision: 0,
  };
  const edits = new Map();
  const current = structuredClone(initial);
  current.model.steps = 42;
  current.output.width = 1024;
  current.prompt.general = "fresh tag";
  sandbox.recordStateEdits(initial, current, edits);
  // A user changing a value and then restoring its initial value is still an
  // intentional edit and must not be erased by a late hydration response.
  const reverted = structuredClone(current);
  reverted.model.steps = 30;
  sandbox.recordStateEdits(current, reverted, edits);

  const canonical = {
    model: { steps: 24, cfg: 7, checkpoint: "server.safetensors" },
    output: { width: 768, height: 1024, seed_mode: "current" },
    prompt: { general: "server tag", negative: "newer server negative" },
    revision: 9,
  };
  sandbox.applyStateEdits(canonical, edits);
  const merged = JSON.parse(JSON.stringify(canonical));
  assert.equal(merged.model.steps, 30);
  assert.equal(merged.model.cfg, 7, "untouched server model settings must survive");
  assert.equal(merged.model.checkpoint, "server.safetensors");
  assert.equal(merged.output.width, 1024);
  assert.equal(merged.output.height, 1024, "untouched server output settings must survive");
  assert.equal(merged.output.seed_mode, "current");
  assert.equal(merged.prompt.general, "fresh tag");
  assert.equal(merged.prompt.negative, "newer server negative");
  assert.equal(merged.revision, 9, "a newer server revision must remain canonical");
}

function makeGenerationContext(cryptoMode) {
  let resolveConfiguration;
  const configurationReady = new Promise(resolve => { resolveConfiguration = resolve; });
  const cryptoUsage = makeCrypto(cryptoMode);
  const apiRequests = [];
  const dispatched = [];
  const eventPromises = [];
  const listeners = new Map();
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) {
      nodes.set(selector, {
        hidden: false, value: "", textContent: "",
        classList: { toggle() {}, add() {}, remove() {} },
        style: { setProperty() {} },
      });
    }
    return nodes.get(selector);
  };
  const state = {
    generation: { mode: "detail", lakis_mode: false, upscale_engine: "ultimate" },
    translation_enabled: false, lora_enabled: true, composition_enabled: true,
    wildcard_enabled: false, wildcard_exclusions: {},
    continuous: { enabled: false, count: 1 },
    i2i: { enabled: false, image_name: "" },
    inpaint: { enabled: false, prompt: "", negative_prompt: "" },
    loras: [],
    camera: { x: 0, y: 0, z: 0, roll: 0, frame_y: 0 },
    output: { width: 1024, height: 1024, seed: 73, seed_mode: "current" },
    prompt: { general: "before config", negative: "" },
    model: { steps: 30, cfg: 5 },
    node_overrides: {},
  };
  const sandbox = {
    state, workflowConfigurationReady: configurationReady,
    generationPreparationPending: false, generationActive: false,
    generationCancelRequested: false, generationSubmissionPending: false,
    generationTrace: null, lastPreviewRevision: 0, lastGenerationState: "idle",
    continuousRun: null, continuousAdvance: false,
    generationModeLabel: () => "DETAIL", setContinuousProgress() {},
    syncOutputStateFromInputs() {}, syncPromptStateFromInputs() {},
    saveLocalPromptState() {}, setPreviewModeLabel() {}, setPreviewZoom() {},
    setGenerationProgress() {}, containsKoreanPrompt: () => false,
    translatedPromptForGeneration: async prompt => prompt,
    translatedInpaintForGeneration: async inpaint => inpaint,
    document: { querySelector: node, querySelectorAll: () => [] },
    CustomEvent: class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } },
    fetch: async (url, init) => {
      apiRequests.push({ url, init });
      if (url === "/api/generate") {
        return {
          ok: true, status: 200, headers: { get: () => "application/json" },
          text: async () => JSON.stringify({ ok: true, request_id: "accepted-1" }),
        };
      }
      if (url === "/api/cancel") return { ok: true, json: async () => ({ ok: true }) };
      throw new Error(`unexpected request ${url}`);
    },
    crypto: cryptoUsage.api,
    performance, Blob, structuredClone, queueMicrotask,
  };
  sandbox.window = sandbox;
  sandbox.addEventListener = (type, callback) => {
    const handlers = listeners.get(type) || [];
    handlers.push(callback);
    listeners.set(type, handlers);
  };
  sandbox.dispatchEvent = event => {
    dispatched.push(event);
    for (const callback of listeners.get(event.type) || []) {
      eventPromises.push(Promise.resolve(callback(event)));
    }
  };
  sandbox.lakisPromptForGeneration = async prompt => structuredClone(prompt);
  sandbox.lakisResolveWildcardsForGeneration = async ({ prompt, inpaint }) => ({
    prompt, inpaint, selections: [],
  });
  sandbox.lakisPrepareScene = async () => {};

  const diagnosticsSource = fs.readFileSync(
    path.join(ROOT, "src/external_ui/generation-diagnostics.js"), "utf8");
  vm.createContext(sandbox);
  vm.runInContext(diagnosticsSource, sandbox);
  const clickBody = extractBody(appSource, 'generateButton.addEventListener("click", async () =>');
  sandbox.generateButton = { addEventListener: (type, callback) => {
    assert.equal(type, "click");
    sandbox.generateClick = callback;
  } };
  vm.runInContext(`generateButton.addEventListener("click", async () => {${clickBody}\n});`,
    sandbox, { filename: appPath });
  const cancelBody = extractBody(appSource, 'window.addEventListener("lakis:generation-cancel-request", async () =>');
  vm.runInContext(`window.addEventListener("lakis:generation-cancel-request", async () => {${cancelBody}\n});`,
    sandbox, { filename: appPath });
  const submitBody = extractBody(appSource, 'window.addEventListener("lakis:generate", async event =>');
  vm.runInContext(`window.addEventListener("lakis:generate", async event => {${submitBody}\n});`,
    sandbox, { filename: appPath });

  return { sandbox, state, apiRequests, dispatched, eventPromises, resolveConfiguration, cryptoUsage };
}

async function testGenerateWaitsForHydrationAndSubmitsExactlyOnce(cryptoMode) {
  const context = makeGenerationContext(cryptoMode);
  const pendingClick = context.sandbox.generateClick();
  await Promise.resolve();
  assert.equal(context.dispatched.length, 0, "Generate must wait for initial workflow-state hydration");

  // This is the state installed by the async config response after preserving
  // the edits made while its request was pending.
  context.state.model.steps = 42;
  context.state.prompt.general = "fresh mobile tag";
  context.resolveConfiguration();
  await pendingClick;
  await Promise.all(context.eventPromises);

  assert.equal(context.dispatched.filter(event => event.type === "lakis:generate").length, 1);
  assert.equal(context.apiRequests.filter(request => request.url === "/api/generate").length, 1);
  const body = JSON.parse(context.apiRequests.find(request => request.url === "/api/generate").init.body);
  assert.equal(body.model.steps, 42);
  assert.equal(body.prompt.general, "fresh mobile tag");
  const requestId = context.apiRequests.find(request => request.url === "/api/generate")
    .init.headers["X-LAKIS-Client-Request-ID"];
  assert.match(requestId, /^[0-9a-f]{32}$/);
  assert.equal(context.cryptoUsage.randomUUIDCalls, cryptoMode === "randomUUID" ? 1 : 0);
  assert.equal(context.cryptoUsage.randomValuesCalls, cryptoMode === "randomUUID" ? 0 : 1);
}

async function testCancellationRemainsAvailable() {
  const context = makeGenerationContext("randomUUID");
  context.sandbox.dispatchEvent(new context.sandbox.CustomEvent("lakis:generation-cancel-request"));
  await Promise.all(context.eventPromises);
  assert.equal(context.apiRequests.filter(request => request.url === "/api/cancel").length, 1);
}

async function testSceneRequestCorrelationUsesSecureUUID(cryptoMode) {
  const cryptoUsage = makeCrypto(cryptoMode);
  const posted = [];
  const sandbox = {
    crypto: cryptoUsage.api, Blob, structuredClone, performance,
    toyBoot: Promise.resolve(), toyPending: new Map(),
    toyFrame: { contentWindow: { postMessage(message, target) { posted.push({ message, target }); } } },
    state: { output: { width: 1024, height: 768 } },
    config: { pose_data: "pose" },
    precisionPrompts: { paintDataForEditor: () => "[]" },
    location: { origin: "http://100.64.0.10:8767" },
    setTimeout: () => 1, clearTimeout() {},
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "src/external_ui/generation-diagnostics.js"), "utf8"), sandbox);
  const sceneSource = fs.readFileSync(path.join(ROOT, "src/external_ui/scene-controls.js"), "utf8");
  const requestBody = extractBody(sceneSource, "async function requestToy(type, validatePrompts = false)");
  vm.runInContext(`async function requestToy(type, validatePrompts = false) {${requestBody}\n}`,
    sandbox, { filename: path.join(ROOT, "src/external_ui/scene-controls.js") });

  const resultPromise = sandbox.requestToy("lakis:toyxyz-capture", true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posted.length, 1);
  const { message, target } = posted[0];
  assert.equal(message.type, "lakis:toyxyz-capture");
  assert.equal(message.validate_prompts, true);
  assert.equal(target, sandbox.location.origin);
  assert.match(message.request_id,
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(sandbox.toyPending.has(message.request_id), true);
  const response = { request_id: message.request_id, ok: true };
  sandbox.toyPending.get(message.request_id).resolve(response);
  assert.equal(await resultPromise, response);
  assert.equal(cryptoUsage.randomUUIDCalls, cryptoMode === "randomUUID" ? 1 : 0);
  assert.equal(cryptoUsage.randomValuesCalls, cryptoMode === "randomUUID" ? 0 : 1);
}

function testSecureIdsFailClosedWithoutCryptoSource() {
  const sandbox = { crypto: {} };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "src/external_ui/generation-diagnostics.js"), "utf8"), sandbox);
  assert.throws(() => sandbox.LAKISGenerationDiagnostics.createSecureUUID(), /crypto\.getRandomValues/);
}

function testMobileReorderingLeavesGenerateButtonInteractive() {
  let generateClicks = 0;
  const generateButton = { click() { generateClicks++; } };
  const panelClasses = new Set(["panel"]);
  const generationPanel = {
    classList: {
      contains: name => panelClasses.has(name),
      toggle(name, enabled) { if (enabled) panelClasses.add(name); else panelClasses.delete(name); },
    },
    closest: () => null,
    querySelector(selector) { return selector === "#generateButton" ? generateButton : null; },
  };
  const promptColumn = { insertBefore(node, before) { this.inserted = [node, before]; } };
  const previewColumn = {};
  const generationRow = {};
  const storage = new Map([["lakis-link-layout-version", "1"]]);
  const sandbox = {
    window: { matchMedia: () => ({ matches: true }) },
    document: {
      querySelector(selector) {
        return ({
          ".prompt-column": promptColumn,
          ".preview-column": previewColumn,
          ".generation-action-row": generationRow,
        })[selector] || null;
      },
      querySelectorAll: () => [generationPanel],
    },
    localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(ROOT, "src/external_ui/lakis-link-mobile.js"), "utf8"),
    sandbox,
  );
  assert.deepEqual(promptColumn.inserted, [previewColumn, generationRow]);
  generateButton.click();
  assert.equal(generateClicks, 1);
  assert.equal(panelClasses.has("mobile-panel-collapsed"), false);
}

async function main() {
  testPendingHydrationEditsMergeWithCanonicalState();
  for (const mode of ["randomUUID", "getRandomValues"]) {
    await testGenerateWaitsForHydrationAndSubmitsExactlyOnce(mode);
    await testSceneRequestCorrelationUsesSecureUUID(mode);
  }
  await testCancellationRemainsAvailable();
  testSecureIdsFailClosedWithoutCryptoSource();
  testMobileReorderingLeavesGenerateButtonInteractive();
  console.log("PASS LAKIS Link/mobile hydration, secure IDs, single generation submission, scene correlation, cancellation and mobile layout");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
