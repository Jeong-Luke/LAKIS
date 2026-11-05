const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/prompt-highlighting.js"), "utf8")
  .replace("export { install as installPromptEditor };", "");

function editor(region) {
  const classes = new Set();
  class Element {
    constructor() {
      this.children = [];
      this.listeners = {};
      this.dataset = {};
      this.style = { setProperty(name, value) { this[name] = value; } };
      this.classList = { add: name => classes.add(name), remove: name => classes.delete(name) };
      this.value = "";
      this.clientHeight = 120;
      this.scrollHeight = 120;
      this.captured = new Set();
    }
    setAttribute() {}
    append(...nodes) { this.children.push(...nodes); nodes.forEach(n => { n.parentNode = this; }); }
    insertBefore(node) { this.children.push(node); node.parentNode = this; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    closest(selector) {
      if (selector === ".moss-region-field") return region ? field : null;
      if (selector === ".moss-region-dialog") return region ? { clientHeight: 600 } : null;
      if (selector === ".fixed-prompt-panel") return region ? null : panel;
      if (selector === ".prompt-field-title") return region ? null : promptField;
      return null;
    }
    getBoundingClientRect() { return { top: 100, bottom: 220, height: 120 }; }
    setPointerCapture(id) { this.captured.add(id); }
    hasPointerCapture(id) { return this.captured.has(id); }
    releasePointerCapture(id) { this.captured.delete(id); }
    fire(name, props = {}) { this.listeners[name]({ pointerId: 1, clientY: 220, preventDefault() {}, ...props }); }
  }
  const field = new Element();
  const panel = new Element();
  const promptField = { getBoundingClientRect: () => ({ bottom: 512 }) };
  const textarea = new Element();
  field.append(textarea);
  const context = {
    textarea, setTimeout, clearTimeout,
    document: { readyState: "loading", createElement: () => new Element(), addEventListener() {}, body: new Element() },
    window: { addEventListener() {} },
    getComputedStyle: node => { assert.ok(node, "style target must exist"); return { paddingBottom: "12px" }; },
    ResizeObserver: class { observe() {} },
  };
  vm.createContext(context);
  vm.runInContext(source + "\ninstall(textarea);", context);
  const host = textarea.parentNode;
  const handle = host.children.find(node => node.className === "prompt-resize-handle");
  return { host, handle, panel, textarea, classes };
}

test("region prompt handle grows and shrinks the editor within dialog bounds without changing its text", () => {
  const e = editor(true);
  e.textarea.value = "붉은 컵, long hair";
  e.handle.fire("pointerdown");
  e.handle.fire("pointermove", { clientY: 340 });
  assert.equal(e.host.style["--moss-region-prompt-height"], "240px");
  e.handle.fire("pointermove", { clientY: 10000 });
  assert.equal(e.host.style["--moss-region-prompt-height"], "600px");
  e.handle.fire("pointermove", { clientY: -1000 });
  assert.equal(e.host.style["--moss-region-prompt-height"], "120px");
  e.handle.fire("pointerup");
  assert.equal(e.textarea.value, "붉은 컵, long hair");
  assert.equal(e.handle.hasPointerCapture(1), false);
  assert.equal(e.classes.has("prompt-resizing"), false);
});

test("existing ANIMA category resizing retains its original bounds and panel adjustment", () => {
  const e = editor(false);
  e.handle.fire("pointerdown");
  e.handle.fire("pointermove", { clientY: 320 });
  assert.equal(e.host.style.height, "220px");
  assert.equal(e.panel.style.height, "232px");
  e.handle.fire("pointermove", { clientY: 1000 });
  assert.equal(e.host.style.height, "400px");
  e.handle.fire("pointercancel");
  assert.equal(e.handle.hasPointerCapture(1), false);
  assert.equal(e.classes.has("prompt-resizing"), false);
});
