const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "../../src/external_ui");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
const clockSource = fs.readFileSync(path.join(root, "generation-clock.js"), "utf8");

function implementation(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing ${name}`);
  return source.slice(source.lastIndexOf("\n", start) + 1, source.indexOf("\n}", start) + 2);
}

function harness() {
  let now = 1_800_000_000_000;
  let status;
  const intervals = new Map();
  let nextTimer = 0;
  const elements = new Map();
  const listeners = new Map();
  const node = id => {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        textContent: "", hidden: true,
        style: { setProperty(key, value) { this[key] = value; } },
        classList: {
          add(...names) { names.forEach(name => classes.add(name)); },
          remove(...names) { names.forEach(name => classes.delete(name)); },
          toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
        },
      });
    }
    return elements.get(id);
  };
  const context = {
    document: { getElementById: node, querySelector: node, querySelectorAll: () => [] },
    window: {
      addEventListener(name, handler) { listeners.set(name, handler); },
      dispatchEvent(event) { listeners.get(event.type)?.(event); },
      location: { href: "http://localhost/" },
    },
    CustomEvent: class { constructor(type) { this.type = type; } },
    Date: { now: () => now }, Number, Math, String, Object, URL,
    setInterval(fn) { const id = ++nextTimer; intervals.set(id, fn); return id; },
    clearInterval(id) { intervals.delete(id); },
    setTimeout() { return ++nextTimer; }, clearTimeout() {},
    fetch: async () => ({ ok: true, json: async () => status }),
    state: { inpaint: { enabled: false } },
    generateButton: node("button"), generateButtonLabel: node("label"),
    generateButtonHint: node("hint"),
    generationResetTimer: null, generationActive: false, generationCancelRequested: false,
    generationPreparationPending: false, generationSubmissionPending: false,
    continuousRun: null, continuousAdvance: false, engineSwitchBusy: false,
    lastGenerationState: "idle", lastGenerationSubmission: null,
    currentGenerationEngine: () => "anima", generationModeLabel: () => "DETAIL",
    syncGenerationEngineUI() {}, setContinuousProgress() {},
    refreshGenerationPreview: async () => {},
    showGenerationError() {
      context.window.dispatchEvent(new context.CustomEvent("lakis:generation-error"));
    },
  };
  vm.createContext(context);
  vm.runInContext(clockSource, context);
  context.generationClock = context.window.LAKISGenerationClock;
  for (const name of ["setGenerationProgress", "resetGenerationButton", "pollGenerationStatus"]) {
    vm.runInContext(implementation(name), context);
  }
  const eventStart = source.indexOf('window.addEventListener("lakis:generation-progress"');
  const eventEnd = source.indexOf("let lastGenerationState", eventStart);
  vm.runInContext(source.slice(eventStart, eventEnd), context);
  return {
    context, node,
    async poll(value) { status = value; await context.pollGenerationStatus(); },
    advance(ms) { now += ms; for (const fn of intervals.values()) fn(); },
    now: () => now, intervalCount: () => intervals.size,
  };
}

for (const mode of ["fast", "detail", "lakis_detail"]) {
  test(`${mode}: actual status drives progress while only the clock advances with time`, async () => {
    const h = harness();
    const start = h.now() / 1000 - 65;
    await h.poll({
      state: "running", request_id: mode, mode, percent: 37.3,
      stage: "생성 중 · Initial · 1/30", started_at: start,
    });
    assert.equal(h.node("hint").textContent, "Initial · 1/30 · 37%");
    assert.equal(h.node("button").style["--generation-progress"], "37.3%");
    assert.equal(h.node("generateElapsed").textContent, "01:05");
    h.advance(5000);
    assert.equal(h.node("generateElapsed").textContent, "01:10");
    assert.equal(h.node("button").style["--generation-progress"], "37.3%");
    await h.poll({
      state: "running", request_id: mode, mode, percent: 39,
      stage: "생성 중 · Initial · 2/30", started_at: start,
    });
    assert.equal(h.node("hint").textContent, "Initial · 2/30 · 39%");
    assert.equal(h.intervalCount(), 1);
  });
}

test("completion freezes the server duration and retains 100% through the completion event", async () => {
  const h = harness();
  const start = h.now() / 1000 - 90;
  await h.poll({ state: "running", request_id: "done", percent: 95, started_at: start });
  await h.poll({
    state: "complete", request_id: "done", percent: 100,
    started_at: start, finished_at: start + 80,
  });
  assert.equal(h.node("hint").textContent, "100%");
  assert.equal(h.node("generateElapsed").textContent, "01:20");
  assert.equal(h.intervalCount(), 0);
  h.advance(60000);
  assert.equal(h.node("generateElapsed").textContent, "01:20");
});

for (const terminal of ["cancelled", "error"]) {
  test(`${terminal}: the UI reset preserves the final time and stops its interval`, async () => {
    const h = harness();
    const start = h.now() / 1000 - 40;
    await h.poll({ state: "running", request_id: terminal, percent: 20, started_at: start });
    await h.poll({
      state: terminal, request_id: terminal, started_at: start, finished_at: start + 35,
    });
    assert.equal(h.node("label").textContent, "제작하기");
    assert.equal(h.node("generateElapsed").textContent, "00:35");
    assert.equal(h.intervalCount(), 0);
  });
}

test("cancelling keeps counting until the backend confirms cancellation", async () => {
  const h = harness();
  const start = h.now() / 1000 - 10;
  await h.poll({ state: "cancelling", request_id: "cancel", started_at: start });
  assert.equal(h.node("label").textContent, "중지 중");
  h.advance(2000);
  assert.equal(h.node("generateElapsed").textContent, "00:12");
  assert.equal(h.intervalCount(), 1);
});

test("a previous terminal snapshot cannot stop a new preparation or submission", async () => {
  for (const pending of ["generationPreparationPending", "generationSubmissionPending"]) {
    const h = harness();
    h.context[pending] = true;
    h.context.setGenerationProgress(0, "프롬프트 번역 중");
    h.advance(3000);
    await h.poll({
      state: "complete", request_id: "previous", percent: 100,
      started_at: h.now() / 1000 - 100, finished_at: h.now() / 1000 - 10,
    });
    assert.equal(h.node("generateElapsed").textContent, "00:03");
    assert.equal(h.node("hint").textContent, "프롬프트 번역 중 · 0%");
    assert.equal(h.intervalCount(), 1);
  }
});
