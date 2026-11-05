const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/desktop-window.js"), "utf8");
function load(native) {
  const sent = [], events = {}, controls = { hidden: true, dataset: {}, addEventListener: (name, callback) => { events[name] = callback; } };
  const header = { addEventListener: (name, callback) => { events[name] = callback; } };
  const maximize = { setAttribute(name, value) { this[name] = value; } };
  const root = { dataset: {} };
  const host = { postMessage: message => sent.push(message), addEventListener: (name, callback) => { events[name] = callback; } };
  vm.runInNewContext(source, {
    window: native ? { chrome: { webview: host } } : {},
    document: { documentElement: root, querySelector: selector => ({
      "#desktopWindowControls": controls, ".brand-header": header, "#desktopWindowMaximize": maximize,
    })[selector] },
  });
  return { sent, events, controls, maximize, root };
}
const browser = load(false);
assert.equal(browser.controls.hidden, true);
assert.deepEqual(browser.sent, []);
const desktop = load(true);
assert.equal(desktop.controls.hidden, false);
assert.equal(desktop.root.dataset.desktopWindow, "true");
assert.deepEqual(desktop.sent, ["lakis-window-ready"]);
for (const action of ["minimize", "maximize", "close"]) {
  desktop.events.click({ target: { closest: () => ({ dataset: { windowAction: action } }) } });
  assert.equal(desktop.sent.at(-1), "lakis-window-" + action);
}
let prevented = 0;
for (const [detail, command] of [[1, "drag"], [2, "maximize"]]) {
  desktop.events.mousedown({ button: 0, detail, target: { closest: () => null }, preventDefault() { prevented++; } });
  assert.equal(desktop.sent.at(-1), "lakis-window-" + command);
}
assert.equal(prevented, 2);
const before = desktop.sent.length;
desktop.events.mousedown({ button: 0, target: { closest: () => ({}) } });
desktop.events.mousedown({ button: 2, target: { closest: () => null } });
assert.equal(desktop.sent.length, before);
desktop.events.message({ data: { type: "lakis-window-state", maximized: true } });
assert.equal(desktop.controls.dataset.maximized, "true");
assert.equal(desktop.maximize["aria-label"], "이전 크기로");
desktop.events.message({ data: { type: "lakis-window-state", maximized: false } });
assert.equal(desktop.maximize["aria-label"], "최대화");
console.log("PASS native-only window controls, caption drag, maximize state and interactive-header exclusion");
