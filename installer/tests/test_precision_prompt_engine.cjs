const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/precision-prompts.js"), "utf8")
  .replace(/^import .*;\r?\n/m, "")
  .replace(/\bexport (const|function|class) /g, "$1 ");
const context = { structuredClone, window: {}, document: {} };
vm.createContext(context);
vm.runInContext(source + "\nthis.api = { precisionEnabled, generationPrompt, editorPainting, PrecisionPrompts };", context);
const { precisionEnabled, generationPrompt, editorPainting, PrecisionPrompts } = context.api;
const config = {
  enabled: true, toyxyz_enabled: true,
  precision_prompts: { trigger: "ANIMA trigger", quality: "ANIMA quality", global: "ANIMA pose prompt", background: "ANIMA background" },
  toyxyz_paint_data: JSON.stringify({ base: { prompt: "pose base" }, background: { prompt: "pose background" }, layers: [] }),
};
const prompt = { trigger: "MOSS trigger", quality: "", artist: "", fixed: "", general: "MOSS main", negative: "keep negative" };
const before = JSON.stringify(config);
assert.equal(precisionEnabled(config, "anima"), true);
assert.equal(precisionEnabled(config, "moss"), false);
const moss = generationPrompt(config, prompt, "moss");
assert.deepEqual(JSON.parse(JSON.stringify(moss)), prompt);
assert.notEqual(moss, prompt);
assert.equal(generationPrompt(config, prompt, "anima").general, "ANIMA pose prompt");
assert.equal(editorPainting(config, prompt, "moss"), config.toyxyz_paint_data);

let engine = "moss";
const instance = Object.create(PrecisionPrompts.prototype);
instance.getConfig = () => config;
instance.getPrompt = () => prompt;
instance.getEngine = () => engine;
instance.root = { hidden: false };
const classes = new Set(["precision-prompt-normal-hidden"]);
instance.normal = { classList: {
  contains: name => classes.has(name),
  toggle(name, value) { if (value) classes.add(name); else classes.delete(name); },
} };
instance.heading = {};
instance.translation = { parentNode: instance.heading, previousSibling: null };
let restored = false;
instance.translationAnchor = { after() { restored = true; } };
instance.refresh();
assert.equal(instance.root.hidden, true);
assert.equal(classes.has("precision-prompt-normal-hidden"), false);
assert.equal(restored, true);
assert.deepEqual(JSON.parse(JSON.stringify(instance.forGeneration(prompt))), prompt);
assert.equal(instance.paintDataForEditor(), config.toyxyz_paint_data);
engine = "anima";
assert.equal(instance.forGeneration(prompt).general, "ANIMA pose prompt");
assert.equal(JSON.stringify(config), before);
console.log("PASS: ANIMA precision prompts stay out of MOSS UI/payload and survive switching back");
