const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appSource = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8");

function translator(kind) {
  const functions = appSource.slice(
    appSource.indexOf("const containsKoreanPrompt ="),
    appSource.indexOf("async function translatedInpaintForGeneration("),
  );
  const calls = [];
  const context = {
    structuredClone,
    state: { translation_enabled: true },
    runtimeCapabilities: {},
    fetch: async (url, options) => {
      const { prompt } = JSON.parse(options.body);
      calls.push(prompt);
      return {
        ok: true,
        json: async () => ({
          ok: true,
          prompt: Object.fromEntries(Object.entries(prompt).map(([key, value]) => [key, `${value}|en`])),
        }),
      };
    },
  };
  vm.createContext(context);
  vm.runInContext(functions, context);
  const fn = kind === "anima" ? context.translatedAnimaRegionsForGeneration : context.translatedMossRegionsForGeneration;
  assert.equal(typeof fn, "function", `missing translator for ${kind}`);
  return { calls, translate: fn };
}

test("ANIMA translation reuses caption/negative flow and preserves text, bbox and engine separation", async () => {
  const mossInput = {
    enabled: true,
    regions: [{ id: "m", label: "text", caption: "빨간 컵", negative_prompt: "흐림", text: "정확한 TEXT", bbox: [10, 20, 800, 900], extra: { keep: 1 } }],
    future: "keep",
  };
  const animaInput = {
    enabled: true,
    regions: [{ id: "a", label: "character", caption: "긴 머리", negative_prompt: "나쁜 손", text: "ANIMA TEXT", bbox: [0, 0, 1000, 1000] }],
  };
  const mossBefore = structuredClone(mossInput);
  const animaBefore = structuredClone(animaInput);
  const mossT = translator("moss");
  const animaT = translator("anima");
  const mossOut = await mossT.translate(mossInput);
  const animaOut = await animaT.translate(animaInput);
  assert.deepEqual(mossInput, mossBefore, "MOSS input must not mutate");
  assert.deepEqual(animaInput, animaBefore, "ANIMA input must not mutate");
  assert.equal(mossOut.regions[0].caption, "빨간 컵|en");
  assert.equal(animaOut.regions[0].caption, "긴 머리|en");
  assert.equal(mossOut.regions[0].text, "정확한 TEXT", "exact text preserved");
  assert.equal(animaOut.regions[0].text, "ANIMA TEXT", "exact text preserved");
  assert.deepEqual(mossOut.regions[0].bbox, [10, 20, 800, 900], "coordinates preserved");
  assert.deepEqual(animaOut.regions[0].bbox, [0, 0, 1000, 1000], "coordinates preserved");
  assert.deepEqual(mossOut.regions[0].extra, { keep: 1 }, "unknown fields preserved");
  assert.equal(mossOut.future, "keep", "unknown state preserved");
  assert.notEqual(mossOut.regions[0].caption, animaOut.regions[0].caption, "engines must stay separate");
});

function loadGateHelper() {
  const start = appSource.indexOf("function gateRegionPayloadForRequest(");
  assert.ok(start >= 0, "missing gateRegionPayloadForRequest");
  const bodyStart = appSource.indexOf("{", appSource.indexOf(")", start));
  let depth = 0;
  let end = bodyStart;
  for (; end < appSource.length; end += 1) {
    if (appSource[end] === "{") depth += 1;
    else if (appSource[end] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  const context = { structuredClone };
  vm.createContext(context);
  vm.runInContext(appSource.slice(start, end + 1), context);
  return context.gateRegionPayloadForRequest;
}

function loadSyncAnima() {
  const start = appSource.indexOf("function syncAnimaAvailability()");
  assert.ok(start >= 0, "missing syncAnimaAvailability");
  let depth = 0;
  let end = start;
  for (; end < appSource.length; end += 1) {
    if (appSource[end] === "{") depth += 1;
    else if (appSource[end] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  return appSource.slice(start, end + 1);
}

test("conflicts lock and close the ANIMA editor without mutating saved state or snapshot", () => {
  const fnSource = loadSyncAnima();
  for (const conflict of [
    { i2i: { enabled: true }, inpaint: { enabled: false }, pose: false, label: "i2i" },
    { i2i: { enabled: false }, inpaint: { enabled: true }, pose: false, label: "inpaint" },
  ]) {
    const saved = { enabled: true, regions: [{ id: "a1", label: "object", caption: "keep", negative_prompt: "", text: "", bbox: [0, 0, 500, 500] }] };
    const savedBefore = structuredClone(saved);
    const snapshotBefore = structuredClone(saved);
    let closed = 0;
    let restored = 0;
    const panel = { inert: false, setAttribute() {}, title: "" };
    const context = {
      state: { i2i: conflict.i2i, inpaint: conflict.inpaint, anima_regions: saved, generation: { engine: "anima" } },
      document: { querySelector: () => panel },
      window: {
        LAKISAnimaRegions: {
          snapshot: () => structuredClone(snapshotBefore),
          restore: () => { restored += 1; },
          close: () => { closed += 1; },
        },
      },
      currentGenerationEngine: () => "anima",
      isToyxyzEnabled: () => conflict.pose,
    };
    vm.createContext(context);
    vm.runInContext(`${fnSource}; syncAnimaAvailability();`, context);
    assert.equal(panel.inert, true, `${conflict.label} must lock the panel`);
    assert.equal(closed, 1, `${conflict.label} must close the dialog`);
    assert.equal(restored, 0, `${conflict.label} must not restore the editor`);
    assert.deepEqual(saved, savedBefore, `${conflict.label} must retain stored enabled state and regions`);
    assert.deepEqual(context.window.LAKISAnimaRegions.snapshot(), snapshotBefore, `${conflict.label} must leave the editor snapshot unchanged`);
  }
  const calmPanel = { inert: true, setAttribute() {}, title: "x" };
  const calm = {
    state: { i2i: { enabled: false }, inpaint: { enabled: false }, anima_regions: { enabled: true, regions: [] }, generation: { engine: "anima" } },
    document: { querySelector: () => calmPanel },
    window: { LAKISAnimaRegions: { snapshot: () => ({ enabled: true, regions: [] }), restore: () => { throw new Error("must not restore"); }, close: () => { throw new Error("must not close when available"); } } },
    currentGenerationEngine: () => "anima",
    isToyxyzEnabled: () => true,
  };
  vm.createContext(calm);
  vm.runInContext(`${fnSource}; syncAnimaAvailability();`, calm);
  assert.equal(calmPanel.inert, false, "3D pose must leave the bounding-box panel available");
});

test("request copies enable only the active engine without mutating saved snapshots", () => {
  const gate = loadGateHelper();
  const mossSaved = { enabled: true, regions: [{ id: "m", label: "object", caption: "m", negative_prompt: "", text: "", bbox: [0, 0, 10, 10] }] };
  const animaSaved = { enabled: true, regions: [{ id: "a", label: "character", caption: "a", negative_prompt: "", text: "", bbox: [5, 5, 50, 50] }] };
  const mossBefore = structuredClone(mossSaved);
  const animaBefore = structuredClone(animaSaved);
  const mossReq = gate({ mossMode: true, mossSnapshot: mossSaved, animaSnapshot: animaSaved, i2iEnabled: false, inpaintEnabled: false, poseEnabled: false });
  assert.equal(mossReq.moss_regions.enabled, true, "MOSS request keeps enabled state");
  assert.equal(mossReq.anima_regions.enabled, false, "ANIMA copy must disable during MOSS");
  assert.deepEqual(mossSaved, mossBefore, "MOSS saved state must not mutate");
  assert.deepEqual(animaSaved, animaBefore, "ANIMA saved state must not mutate");
  const animaReq = gate({ mossMode: false, mossSnapshot: mossSaved, animaSnapshot: animaSaved, i2iEnabled: false, inpaintEnabled: false, poseEnabled: false });
  assert.equal(animaReq.anima_regions.enabled, true, "ANIMA request keeps enabled state");
  assert.equal(animaReq.moss_regions.enabled, false, "MOSS copy must disable during ANIMA");
  for (const flags of [
    { i2iEnabled: true, inpaintEnabled: false, poseEnabled: false },
    { i2iEnabled: false, inpaintEnabled: true, poseEnabled: false },
  ]) {
    const gated = gate({ mossMode: false, mossSnapshot: mossSaved, animaSnapshot: animaSaved, ...flags });
    assert.equal(gated.anima_regions.enabled, false, `ANIMA copy must disable on ${JSON.stringify(flags)}`);
    assert.deepEqual(gated.anima_regions.regions, animaSaved.regions, "regions must survive conflict gating");
  }
  const mossConflict = gate({ mossMode: true, mossSnapshot: mossSaved, animaSnapshot: animaSaved, i2iEnabled: true, inpaintEnabled: false, poseEnabled: false });
  assert.equal(mossConflict.moss_regions.enabled, false, "MOSS copy must disable on i2i");
  assert.deepEqual(mossSaved, mossBefore, "conflict gating must not mutate saved snapshots");
  assert.deepEqual(animaSaved, animaBefore, "conflict gating must not mutate saved snapshots");
});
