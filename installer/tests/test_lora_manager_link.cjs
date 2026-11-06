const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8");
new vm.Script(source);
const start = source.indexOf("function syncLoraManagerLink(");
const end = source.indexOf("function enforceMossGenerationMode(", start);
const manager = {};
let engine = "anima";
const context = {
  currentGenerationEngine: () => engine,
  document: {
    querySelector(selector) {
      assert.equal(selector, 'a[aria-label="LoRA Manager"]');
      return manager;
    },
  },
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
for (const mode of ["anima", "moss", "anima"]) {
  engine = mode;
  context.syncLoraManagerLink();
  assert.equal(manager.href, `/api/lora-manager?engine=${mode}`);
  assert.equal(manager.title, `${mode.toUpperCase()} 전용 LoRA Manager`);
}
console.log("PASS: ANIMA/MOSS manager links follow the selected engine in both directions");
