const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/toyxyz-editor.js"), "utf8");
const start = source.indexOf("function bindParentTheme()");
const end = source.indexOf("\nif (parent !== window)", start);

test("3D editor follows initial and live host themes without changing scene state", () => {
  const host = { dataset: { synapseTheme: "true" } };
  const editor = { dataset: {} };
  const scene = { pose_data: "keep pose", camera: { x: 1 }, strength: 0.5 };
  const before = structuredClone(scene);
  let observer;
  const events = new Map();
  const context = {
    parent: { document: { documentElement: host } },
    document: { documentElement: editor },
    scene,
    window: { addEventListener(name, handler) { events.set(name, handler); } },
    MutationObserver: class {
      constructor(update) { this.update = update; observer = this; }
      observe(target, options) { this.target = target; this.options = options; this.connected = true; }
      disconnect() { this.connected = false; }
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + "\nbindParentTheme();", context);
  assert.equal(editor.dataset.synapseTheme, "true");
  host.dataset.synapseTheme = "false";
  observer.update();
  assert.equal(editor.dataset.synapseTheme, "false");
  host.dataset.synapseTheme = "true";
  observer.update();
  assert.equal(editor.dataset.synapseTheme, "true");
  assert.deepEqual(scene, before);
  events.get("pagehide")();
  assert.equal(observer.connected, false);
});
