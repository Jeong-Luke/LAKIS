const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/precision-prompts.js"), "utf8")
  .replace(/^import .*;\r?\n/m, "")
  .replace(/\bexport (const|function|class) /g, "$1 ");
const context = { structuredClone, window: {}, document: { querySelector: () => null } };
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
instance.getRegionsEnabled = () => false;
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

{
  const normal = {};
  const parent = () => ({ append(node) { node.parentNode = this; node.previousSibling = null; } });
  const root = parent();
  const title = parent();
  const heading = parent();
  heading.firstElementChild = title;
  const home = () => ({ after(node) { node.parentNode = normal; node.previousSibling = this; } });
  const button = { parentNode: normal };
  const overlay = { parentNode: normal };
  const translation = { parentNode: normal };
  const precision = Object.create(PrecisionPrompts.prototype);
  Object.assign(precision, {
    root, heading, translation,
    translationAnchor: home(), settingsButtonAnchor: home(), settingsOverlayAnchor: home(),
  });
  context.document.querySelector = selector => selector.includes("button") ? button : overlay;
  precision.syncHeaderControls(true);
  assert.equal(button.parentNode, title, "the existing settings button follows the precision heading");
  assert.equal(overlay.parentNode, root, "settings content must not remain inside the hidden normal card");
  assert.equal(translation.parentNode, heading);
  precision.syncHeaderControls(false);
  assert.equal(button.previousSibling, precision.settingsButtonAnchor);
  assert.equal(overlay.previousSibling, precision.settingsOverlayAnchor);
  assert.equal(translation.previousSibling, precision.translationAnchor);
  assert.equal(button.parentNode, normal);
  assert.equal(overlay.parentNode, normal);
  assert.equal(JSON.stringify(config), before, "moving settings must not change prompt or pose settings");
  console.log("PASS: precision heading reuses and restores the same settings button, overlay and translation control");
}
