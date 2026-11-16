const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ui = path.join(__dirname, "../../src/external_ui");
const source = fs.readFileSync(path.join(ui, "moss-regions.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));

function harness() {
  let document;
  class Event {
    constructor(type, init = {}) { Object.assign(this, { type, defaultPrevented: false }, init); }
    preventDefault() { this.defaultPrevented = true; }
  }
  class Events {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, fn) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(fn);
    }
    removeEventListener(type, fn) {
      this.listeners.set(type, (this.listeners.get(type) || []).filter(listener => listener !== fn));
    }
    dispatchEvent(event) {
      event.target ||= this;
      for (const fn of this.listeners.get(event.type) || []) fn(event);
      return !event.defaultPrevented;
    }
    fire(type, init = {}) { return this.dispatchEvent(new Event(type, init)); }
  }
  class Element extends Events {
    constructor(tag) {
      super();
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.attributes = new Map();
      this.style = { setProperty(name, value) { this[name] = value; } };
      this.hidden = this.open = this.inert = false;
      this.className = "";
      this.clientWidth = 900;
      this.clientHeight = 700;
      this.width = 300;
      this.height = 150;
      this.captures = new Set();
      this.classList = {
        contains: name => this.className.split(/\s+/).includes(name),
        toggle: (name, force) => {
          const classes = new Set(this.className.split(/\s+/).filter(Boolean));
          const enabled = force ?? !classes.has(name);
          if (enabled) classes.add(name); else classes.delete(name);
          this.className = [...classes].join(" ");
          return enabled;
        },
        add: name => this.classList.toggle(name, true),
        remove: name => this.classList.toggle(name, false),
      };
      this.context = { measureText: text => ({ width: text.length * 8 }) };
      for (const name of ["clearRect", "fillRect", "strokeRect", "save", "restore", "setLineDash", "fillText"]) {
        this.context[name] = () => {};
      }
    }
    remove() {
      if (this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
      this.parentElement = null;
    }
    append(...nodes) { for (const node of nodes) { node.remove(); node.parentElement = this; this.children.push(node); } }
    prepend(...nodes) { for (const node of nodes.reverse()) { node.remove(); node.parentElement = this; this.children.unshift(node); } }
    replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this.append(...nodes); }
    insertBefore(node, before) { node.remove(); node.parentElement = this; this.children.splice(this.children.indexOf(before), 0, node); }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    focus() { document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; this.fire("close"); }
    getContext() { return this.context; }
    getBoundingClientRect() {
      return { left: parseFloat(this.style.left) || 0, top: parseFloat(this.style.top) || 0,
        width: parseFloat(this.style.width) || 600, height: parseFloat(this.style.height) || 400 };
    }
    hasPointerCapture(id) { return this.captures.has(id); }
    setPointerCapture(id) { this.captures.add(id); }
    releasePointerCapture(id) { this.captures.delete(id); }
  }
  const roots = new Map(["#mossRegionPanel", "#animaRegionPanel", "#imageWidth", "#imageHeight"]
    .map(id => [id, new Element("div")]));
  roots.get("#imageWidth").value = "1536";
  roots.get("#imageHeight").value = "1024";
  document = { body: new Element("body"), createElement: tag => new Element(tag), querySelector: selector => roots.get(selector) };
  const window = new Events();
  const context = { window, document, Event, CustomEvent: Event,
    requestAnimationFrame: fn => fn(), ResizeObserver: class { observe() {} } };
  vm.runInNewContext(source, context);
  const find = (root, className) => root.classList?.contains(className) ? root
    : root.children.map(child => find(child, className)).find(Boolean);
  const dialogs = document.body.children;
  return { document, window, find, roots, dialogs, api: window.LAKISAnimaRegions,
    hosts: { canvasHost: new Element("div"), toolbarHost: new Element("div"), sidebarHost: new Element("aside") } };
}

const saved = { enabled: true, future: { keep: [1, 2] }, regions: [{
  id: "person", label: "character", caption: "person", negative_prompt: "extra person",
  text: "", bbox: [100, 100, 300, 300], future: "keep",
}] };

test("turning either box card off and on only changes enabled and preserves every saved field", () => {
  const h = harness();
  for (const [api, selector, eventName] of [
    [h.api, "#animaRegionPanel", "lakis:anima-regions-change"],
    [h.window.LAKISMossRegions, "#mossRegionPanel", "lakis:moss-regions-change"],
  ]) {
    api.restore(saved);
    const before = plain(api.snapshot());
    let edits = 0;
    h.window.addEventListener(eventName, () => edits++);
    const toggle = h.find(h.roots.get(selector), "lora-switch");
    toggle.fire("click");
    assert.deepEqual(plain(api.snapshot()), { ...before, enabled: false });
    assert.equal(edits, 1);
    toggle.fire("click");
    assert.deepEqual(plain(api.snapshot()), before);
    assert.equal(edits, 2);
  }
});

test("combined editor reuses the existing fields and exact output frame without changing saved regions", () => {
  const h = harness();
  h.api.restore(saved);
  const before = plain(h.api.snapshot());
  let closed = 0;
  h.api.mountToPose({ ...h.hosts, onClose: () => closed++ });
  const canvas = h.find(h.hosts.canvasHost, "moss-region-canvas");
  const toolbar = h.find(h.hosts.toolbarHost, "moss-region-toolbar");
  const sidebar = h.find(h.hosts.sidebarHost, "moss-region-sidebar");
  assert.ok(canvas && toolbar && sidebar);
  h.api.setPoseViewport({ left: 42.5, top: 18.25, width: 600.5, height: 400.25 });
  assert.equal(canvas.style.left, "42.5px");
  assert.equal(canvas.style.top, "18.25px");
  assert.equal(canvas.style.width, "600.5px");
  assert.equal(canvas.style.height, "400.25px");
  assert.equal(canvas.hidden, false);
  h.api.setPoseViewport({ left: 0, top: 0, width: 0, height: 0 });
  assert.equal(canvas.hidden, true);
  h.api.setPoseViewport({ left: 20, top: 30, width: 300, height: 200 });
  assert.equal(canvas.hidden, false);
  assert.deepEqual(plain(h.api.snapshot()), before);
  h.api.close();
  assert.equal(closed, 1);
  h.api.unmountFromPose();
  assert.equal(canvas.parentElement.className, "moss-region-output-frame");
  assert.equal(toolbar.parentElement, h.dialogs[1]);
  assert.equal(sidebar.parentElement.className, "moss-region-workspace");
  assert.equal(canvas.inert, false);
  assert.deepEqual(plain(h.api.snapshot()), before);
  h.find(h.roots.get("#animaRegionPanel"), "moss-region-open").fire("click");
  assert.equal(h.dialogs[1].open, true);
});

test("only box mode receives box drags and switching modes cancels an unfinished drag", () => {
  const h = harness();
  h.api.restore(saved);
  let edits = 0;
  h.window.addEventListener("lakis:anima-regions-change", () => edits++);
  h.api.mountToPose({ ...h.hosts, onClose() {} });
  h.api.setPoseViewport({ left: 40, top: 50, width: 600, height: 400 });
  const canvas = h.find(h.hosts.canvasHost, "moss-region-canvas");
  const down = () => canvas.fire("pointerdown", { button: 0, pointerType: "mouse", pointerId: 1, clientX: 160, clientY: 130 });
  const move = () => canvas.fire("pointermove", { pointerId: 1, clientX: 220, clientY: 170 });
  const up = () => canvas.fire("pointerup", { pointerId: 1, clientX: 220, clientY: 170 });
  down(); move(); up();
  assert.deepEqual(plain(h.api.snapshot()), saved);
  assert.equal(edits, 0);
  h.api.setPoseInteraction("boxes");
  assert.equal(canvas.inert, false);
  assert.equal(canvas.tabIndex, 0);
  down(); move();
  h.api.setPoseInteraction("pose");
  assert.equal(canvas.hasPointerCapture(1), false);
  assert.deepEqual(plain(h.api.snapshot()), saved);
  assert.equal(edits, 0);
  h.api.setPoseInteraction("boxes");
  down(); move(); up();
  assert.deepEqual(plain(h.api.snapshot()).regions[0].bbox, [200, 200, 400, 400]);
  assert.equal(edits, 1);
});

test("ANIMA can route to the combined editor while MOSS keeps its separate editor", () => {
  const h = harness();
  let opens = 0;
  h.window.addEventListener("lakis:anima-regions-open", event => { opens++; event.preventDefault(); });
  h.find(h.roots.get("#animaRegionPanel"), "moss-region-open").fire("click");
  assert.equal(opens, 1);
  assert.equal(h.dialogs[1].open, false);
  h.find(h.roots.get("#mossRegionPanel"), "moss-region-open").fire("click");
  assert.equal(opens, 1);
  assert.equal(h.dialogs[0].open, true);
});

test("3D viewport reporting uses the rendered output rectangle, not the whole iframe or rounded coordinates", () => {
  const child = fs.readFileSync(path.join(ui, "toyxyz-editor.js"), "utf8");
  const start = child.indexOf("function publishPoseViewport()");
  const end = child.indexOf("\nconst ready =", start);
  const rect = { left: 240.25, top: 42.5, width: 432.75, height: 651.125 };
  const messages = [];
  vm.runInNewContext(child.slice(start, end) + "\npublishPoseViewport();", {
    pose: { renderer: { domElement: { getBoundingClientRect: () => ({ left: 100, top: 0, width: 1000, height: 800 }) } } },
    simple: { outputFrame: { getBoundingClientRect: () => rect } },
    reply: message => messages.push(plain(message)),
  });
  assert.deepEqual(messages, [{ type: "lakis:toyxyz-viewport", rect }]);
});

test("viewport updates preserve exact box coordinates with mode controls in the sidebar", () => {
  const host = fs.readFileSync(path.join(ui, "scene-controls.js"), "utf8");
  const start = host.indexOf("  function syncPoseViewport(");
  const end = host.indexOf("\n  function combinedEditorAvailable(", start);
  const viewports = [];
  const rects = [
    { left: 240.25, top: 42.5, width: 432.75, height: 651.125 },
    { left: 300, top: 0, width: 720, height: 480 },
  ];
  vm.runInNewContext(host.slice(start, end) + "\nrects.forEach(rect => syncPoseViewport(rect));", {
    rects,
    window: { LAKISAnimaRegions: { setPoseViewport: rect => viewports.push(plain(rect)) } },
  });
  assert.deepEqual(viewports, rects);
});

test("combined controls keep clear-all in the toolbar and restore manual tools on close", () => {
  const h = harness();
  h.api.restore(saved);
  h.api.mountToPose({ ...h.hosts, onClose() {} });
  assert.equal(h.find(h.hosts.sidebarHost, "moss-region-clear"), undefined);
  const clear = h.find(h.hosts.toolbarHost, "moss-region-clear");
  assert.ok(clear);
  assert.equal(clear.parentElement.className, "moss-region-toolbar");
  const tools = h.find(h.hosts.toolbarHost, "moss-region-tools");
  assert.equal(tools.hidden, true);
  assert.deepEqual(plain(h.api.snapshot()), saved);
  h.api.unmountFromPose();
  assert.equal(tools.hidden, false);
  assert.equal(clear.parentElement.className, "moss-region-toolbar");
  assert.deepEqual(plain(h.api.snapshot()), saved);
});

function posePanelMethods() {
  const code = fs.readFileSync(path.join(ui, "precision-pose-controls.js"), "utf8");
  const mounts = code.slice(code.indexOf("  mountControls("), code.indexOf("  historyKey("));
  const run = code.slice(code.indexOf("  async run(action)"), code.indexOf("  beforeCapture("));
  return vm.runInNewContext(`(class { ${mounts}\n${run} })`);
}

test("overview shows only boxes normally and adds the saved pose render in combined mode", () => {
  const h = harness();
  h.api.restore(saved);
  const before = plain(h.api.snapshot());
  const root = h.roots.get("#animaRegionPanel");
  const overview = h.find(root, "moss-region-overview");
  const image = "data:image/png;base64,cG9zZQ==";
  const capture = JSON.stringify({ version: 1, render: image, region_painter: { width: 1536, height: 1024 } });
  assert.equal(h.find(overview, "moss-region-overview-pose"), undefined);
  h.api.setPosePreview(true, capture);
  assert.equal(h.find(overview, "moss-region-overview-pose").src, image);
  const box = h.find(overview, "moss-region-overview-box");
  assert.equal(box.style.left, "10%");
  assert.equal(box.style.top, "10%");
  assert.equal(box.style.width, "20%");
  assert.equal(box.style.height, "20%");
  assert.equal(h.find(h.roots.get("#mossRegionPanel"), "moss-region-overview-pose"), undefined);
  h.api.setPosePreview(false, capture);
  assert.equal(h.find(overview, "moss-region-overview-pose"), undefined);
  assert.ok(h.find(overview, "moss-region-overview-box"));
  h.api.setPosePreview(true, capture);
  assert.equal(h.find(overview, "moss-region-overview-pose").src, image);
  assert.deepEqual(plain(h.api.snapshot()), before);
});

test("overview does not load remote images or show mismatched and missing pose captures", () => {
  const h = harness();
  h.api.restore(saved);
  const overview = h.find(h.roots.get("#animaRegionPanel"), "moss-region-overview");
  for (const renderData of [
    "",
    JSON.stringify({ version: 1, render: "https://example.invalid/pose.png", region_painter: { width: 1536, height: 1024 } }),
    JSON.stringify({ version: 1, render: "data:image/png;base64,cG9zZQ==", region_painter: { width: 512, height: 512 } }),
  ]) {
    h.api.setPosePreview(true, renderData);
    assert.equal(h.find(overview, "moss-region-overview-pose"), undefined);
    assert.match(h.find(overview, "moss-region-overview-empty").textContent, /포즈를 적용/);
    assert.ok(h.find(overview, "moss-region-overview-box"));
  }
  assert.deepEqual(plain(h.api.snapshot()), saved);
});

test("pose controls move intact and restore keyboard handling without duplicate listeners", () => {
  const h = harness();
  const root = h.document.createElement("div");
  const controls = h.document.createElement("section");
  const host = h.document.createElement("aside");
  root.append(controls);
  controls.value = "preserved pose settings";
  let resized = 0, shortcuts = 0;
  const panel = Object.assign(new (posePanelMethods())(), {
    editor: { root, resize() { resized++; } },
    controls, abort: { signal: {} }, historyKey() { shortcuts++; },
  });
  panel.mountControls(host);
  panel.mountControls(host);
  assert.equal(host.children[0], controls);
  assert.equal(root.classList.contains("precision-pose-controls-external"), true);
  controls.fire("keydown", { key: "z" });
  assert.equal(shortcuts, 1);
  panel.unmountControls();
  panel.unmountControls();
  assert.equal(root.children[0], controls);
  assert.equal(root.classList.contains("precision-pose-controls-external"), false);
  controls.fire("keydown", { key: "z" });
  assert.equal(shortcuts, 1);
  panel.mountControls(host);
  controls.fire("keydown", { key: "z" });
  assert.equal(shortcuts, 2);
  assert.equal(controls.value, "preserved pose settings");
  assert.equal(resized, 3);
});

test("busy pose actions lock both external controls and the canvas and recover after errors", async () => {
  const root = { inert: false }, controls = { inert: false };
  const panel = Object.assign(new (posePanelMethods())(), {
    editor: { root, loading: false }, controls, busy: false,
    finishWheel() {}, refresh() {}, status: { textContent: "" },
  });
  let finish;
  const pending = panel.run(() => new Promise(resolve => { finish = resolve; }));
  assert.equal(root.inert, true);
  assert.equal(controls.inert, true);
  finish();
  await pending;
  assert.equal(root.inert, false);
  assert.equal(controls.inert, false);
  await panel.run(() => { throw new Error("test failure"); });
  assert.equal(root.inert, false);
  assert.equal(controls.inert, false);
  assert.equal(panel.busy, false);
  assert.match(panel.status.textContent, /test failure/);
});

test("combined canvas draws on empty space and resizes existing regions without tool buttons", () => {
  const h = harness();
  h.api.restore(saved);
  h.api.mountToPose({ ...h.hosts, onClose() {} });
  h.api.setPoseViewport({ left: 0, top: 0, width: 1000, height: 1000 });
  h.api.setPoseInteraction("boxes");
  const canvas = h.find(h.hosts.canvasHost, "moss-region-canvas");
  const drag = (from, to) => {
    canvas.fire("pointerdown", { button: 0, pointerType: "mouse", pointerId: 1, clientX: from[0], clientY: from[1] });
    canvas.fire("pointermove", { pointerId: 1, clientX: to[0], clientY: to[1] });
    canvas.fire("pointerup", { pointerId: 1, clientX: to[0], clientY: to[1] });
  };
  let edits = 0;
  h.window.addEventListener("lakis:anima-regions-change", () => edits++);
  drag([600, 700], [800, 900]);
  const drawn = plain(h.api.snapshot());
  assert.equal(drawn.regions.length, 2);
  assert.deepEqual(drawn.regions[0], saved.regions[0]);
  assert.deepEqual(drawn.regions[1].bbox, [600, 700, 800, 900]);
  assert.equal(edits, 1);
  drag([800, 900], [900, 950]);
  assert.equal(h.api.snapshot().regions.length, 2);
  assert.deepEqual(plain(h.api.snapshot().regions[1].bbox), [600, 700, 900, 950]);
  assert.equal(edits, 2);
  const beforeTap = plain(h.api.snapshot());
  drag([950, 100], [950, 100]);
  assert.deepEqual(plain(h.api.snapshot()), beforeTap);
  assert.equal(h.find(h.hosts.toolbarHost, "moss-region-delete").disabled, true);
  assert.equal(edits, 2);
  h.find(h.hosts.toolbarHost, "moss-region-clear").fire("click");
  assert.deepEqual(plain(h.api.snapshot().regions), []);
  assert.deepEqual(plain(h.api.snapshot().future), saved.future);
  assert.equal(edits, 3);
});
