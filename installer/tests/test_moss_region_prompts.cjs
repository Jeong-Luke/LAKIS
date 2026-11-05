const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8");
const functions = source.slice(
  source.indexOf("const containsKoreanPrompt ="),
  source.indexOf("async function translatedInpaintForGeneration("),
);

function translator({ enabled = true, available = true, error = false } = {}) {
  const calls = [];
  const words = { "붉은 컵": "a red cup", "흐림": "blur", "간판": "a sign" };
  const context = {
    structuredClone,
    state: { translation_enabled: enabled },
    runtimeCapabilities: { translation: available },
    fetch: async (url, options) => {
      assert.equal(url, "/api/translate-prompt");
      const { prompt } = JSON.parse(options.body);
      calls.push(prompt);
      return {
        ok: !error,
        json: async () => error ? { ok: false, error: "translation unavailable" } : {
          ok: true,
          prompt: Object.fromEntries(Object.entries(prompt).map(([key, value]) => [
            key, value.replace(/붉은 컵|흐림|간판/g, word => words[word]),
          ])),
        },
      };
    },
  };
  vm.createContext(context);
  vm.runInContext(functions, context);
  return { calls, translate: context.translatedMossRegionsForGeneration };
}

const region = {
  id: "kept", label: "text", caption: "간판, 붉은 컵",
  negative_prompt: "흐림, blurry", text: "안녕하세요, MOSS!",
  bbox: [10, 20, 800, 900], future: { preserve: true },
};
const state = () => ({ enabled: true, regions: [structuredClone(region)], future: "keep" });

test("region descriptions and negatives translate; exact text, coordinates and source do not change", async () => {
  const input = state();
  const before = structuredClone(input);
  const t = translator();
  const result = await t.translate(input);
  assert.deepEqual(t.calls, [{ caption: region.caption, negative_prompt: region.negative_prompt }]);
  assert.deepEqual(result, {
    ...before, regions: [{ ...region, caption: "a sign, a red cup", negative_prompt: "blur, blurry" }],
  });
  assert.deepEqual(input, before);
  assert.notEqual(result.regions[0], input.regions[0]);
});

test("translation OFF, unsupported service and disabled regions preserve all values without requests", async () => {
  for (const options of [{ enabled: false }, { available: false }, {}]) {
    const input = state();
    if (Object.keys(options).length === 0) input.enabled = false;
    const t = translator(options);
    assert.deepEqual(await t.translate(input), input);
    assert.equal(t.calls.length, 0);
  }
});

test("Korean exact image text alone never triggers translation, and English punctuation remains intact", async () => {
  const input = state();
  Object.assign(input.regions[0], { caption: "long hair,\n(red cup:1.2)", negative_prompt: "" });
  const t = translator();
  assert.deepEqual(await t.translate(input), input);
  assert.equal(t.calls.length, 0);
});

test("all sixteen maximum-length regions fit individual API requests", async () => {
  const input = state();
  input.regions = Array.from({ length: 16 }, (_, index) => ({
    ...structuredClone(region), id: String(index),
    caption: "가".repeat(2000), negative_prompt: "나".repeat(2000),
  }));
  const t = translator();
  assert.deepEqual(await t.translate(input), input);
  assert.equal(t.calls.length, 16);
  assert.ok(t.calls.every(prompt => Object.values(prompt).join("").length === 4000));
});

test("translation failure stops preparation instead of silently using untranslated regions", async () => {
  const input = state();
  input.regions.push({ ...region, id: "not-submitted" });
  const before = structuredClone(input);
  const t = translator({ error: true });
  await assert.rejects(t.translate(input), /translation unavailable/);
  assert.equal(t.calls.length, 1);
  assert.deepEqual(input, before);
});
