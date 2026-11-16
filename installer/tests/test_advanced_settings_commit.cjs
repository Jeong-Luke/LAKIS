const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/advanced-node-settings.js"), "utf8");

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.listeners = new Map();
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
    };
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
}

function editor(field) {
  let saves = 0;
  const state = { generation: { engine: "anima" }, node_overrides: {}, moss_node_overrides: {} };
  const context = {
    state, structuredClone, JSON, Object, Array, Number,
    generationModeSwitches: new Set(["2138", "2139", "2140"]),
    scheduleGenerationStateSave: () => { saves += 1; },
    document: { createElement: tag => new Element(tag) },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("function cloneValue("),
    source.indexOf("function render(group, body)")), context);
  const row = context.makeField("2133", field);
  return { input: row.children[1], state, saves: () => saves };
}

test("actual blur handlers do not save unchanged text, numbers or equivalent JSON", () => {
  const cases = [
    [{ name: "advanced_fields", type: "json", encoded_json: true,
      value: '[{"id":"naia","meta":{"b":2,"a":1}}]' },
    '[ { "meta": { "a": 1, "b": 2 }, "id": "naia" } ]'],
    [{ name: "options", type: "json", value: { b: 2, a: 1 } }, '{"a":1,"b":2}'],
    [{ name: "steps", type: "number", value: 8 }, "8"],
    [{ name: "description", type: "text", value: "same" }, "same"],
  ];
  for (const [field, value] of cases) {
    const h = editor(field);
    h.input.value = value;
    h.input.listeners.get("blur")();
    assert.equal(h.saves(), 0);
    assert.equal(h.state.node_overrides["2133"], undefined);
  }
});

test("meaningful edits save their values once and the following blur is a no-op", () => {
  const cases = [
    [{ name: "advanced_fields", type: "json", encoded_json: true,
      value: '[{"id":"naia","text":"old"}]' }, '[{"id":"naia","text":"new"}]'],
    [{ name: "options", type: "json", value: { order: [1, 2] } }, '{"order":[2,1]}'],
    [{ name: "steps", type: "number", value: 8 }, "9"],
    [{ name: "description", type: "text", value: "old" }, "new"],
  ];
  for (const [field, value] of cases) {
    const h = editor(field);
    h.input.value = value;
    h.input.listeners.get("change")();
    assert.equal(h.saves(), 1);
    const stored = h.state.node_overrides["2133"][field.name];
    if (field.type === "json") {
      assert.equal(JSON.stringify(field.encoded_json ? JSON.parse(stored) : stored),
        JSON.stringify(JSON.parse(value)));
    } else {
      assert.equal(stored, field.type === "number" ? Number(value) : value);
    }
    h.input.listeners.get("blur")();
    assert.equal(h.saves(), 1);
  }
});

test("invalid edits show an error without saving and valid unchanged input clears it", () => {
  for (const [field, invalid, valid] of [
    [{ name: "advanced_fields", type: "json", encoded_json: true, value: "[]" }, "{", "[]"],
    [{ name: "steps", type: "number", value: 8 }, "Infinity", "8"],
  ]) {
    const h = editor(field);
    h.input.value = invalid;
    h.input.listeners.get("change")();
    assert.equal(h.saves(), 0);
    assert.ok(h.input.classes.has("advanced-field-error"));
    h.input.value = valid;
    h.input.listeners.get("blur")();
    assert.equal(h.saves(), 0);
    assert.equal(h.input.classes.has("advanced-field-error"), false);
  }
});

class LiveElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.dataset = {};
    this.classes = new Set();
    this.className = "";
    this.hidden = false;
    this.style = {};
    this.parentNode = null;
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
      contains: name => this.classes.has(name),
      toggle: (name, force = !this.classes.has(name)) => {
        if (force) this.classes.add(name);
        else this.classes.delete(name);
        return force;
      },
    };
  }
  append(...nodes) {
    for (const node of nodes) {
      node.remove();
      node.parentNode = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.append(...nodes);
  }
  before(node) {
    const index = this.parentNode.children.indexOf(this);
    node.remove();
    node.parentNode = this.parentNode;
    this.parentNode.children.splice(index, 0, node);
  }
  after(node) {
    const index = this.parentNode.children.indexOf(this);
    node.remove();
    node.parentNode = this.parentNode;
    this.parentNode.children.splice(index + 1, 0, node);
  }
  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index >= 0) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }
  contains(target) {
    return this === target || this.children.some(child => child.contains(target));
  }
  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
  removeAttribute(name) {
    this.attributes.delete(name);
  }
  click() {
    this.listeners.get("click")?.({ target: this, currentTarget: this });
  }
  get firstElementChild() {
    return this.children[0] || null;
  }
  get lastElementChild() {
    return this.children.at(-1) || null;
  }
  get isConnected() {
    return this.parentNode !== null;
  }
  set innerHTML(value) {
    this._innerHTML = value;
    if (value === "<span></span><small></small>") {
      this.replaceChildren(new LiveElement("span"), new LiveElement("small"));
    }
  }
  get innerHTML() {
    return this._innerHTML || "";
  }
}

function sourceSection(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  return source.slice(start, end);
}

function mossLoraOverlayFixture() {
  const advancedSource = fs.readFileSync(
    path.join(__dirname, "../../src/external_ui/advanced-node-settings.js"),
    "utf8",
  );
  const appSource = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8");
  const appRender = sourceSection(
    appSource,
    "function renderLoras() {",
    '\ndocument.querySelector("#addLoraButton")',
  );
  const allToggle = appSource.match(
    /document\.querySelector\("#allLorasToggle"\)\.addEventListener\("click", event => \{[\s\S]*?\r?\n\}\);/,
  );
  assert.ok(allToggle, "the existing global LoRA toggle handler is present");

  const documentBody = new LiveElement("body");
  const panel = new LiveElement("article");
  const heading = new LiveElement("header");
  const actions = new LiveElement("div");
  const allLorasToggle = new LiveElement("button");
  const addLoraButton = new LiveElement("button");
  const loraList = new LiveElement("div");
  const loraCount = new LiveElement("small");
  const overlay = new LiveElement("section");
  const body = new LiveElement("div");
  const title = new LiveElement("h3");
  const subtitle = new LiveElement("span");
  const gear = new LiveElement("button");
  const nodeTitle = new LiveElement("span");
  const nodeType = new LiveElement("small");
  actions.append(allLorasToggle, addLoraButton);
  panel.append(heading, actions, loraList, overlay);
  overlay.dataset.advancedGroup = "lora";
  overlay.hidden = true;
  overlay.querySelector = selector => ({
    ".advanced-settings-body": body,
    "h3": title,
    ".advanced-settings-header span": subtitle,
  })[selector] || null;
  body.closest = selector => selector === ".advanced-settings-overlay" ? overlay : null;
  gear.dataset.advancedGroup = "lora";
  gear.setAttribute("aria-expanded", "false");
  documentBody.append(panel);

  const state = {
    generation: { engine: "moss" },
    loras: [{ name: "", enabled: false, strength: 1 }],
    lora_enabled: true,
    node_overrides: {},
    moss_node_overrides: {},
  };
  const loraOptions = ["moss/example.safetensors"];
  let saves = 0;
  const document = {
    body: documentBody,
    createElement: tag => new LiveElement(tag),
    createComment: text => {
      const comment = new LiveElement("comment");
      comment.textContent = text;
      return comment;
    },
    querySelector(selector) {
      if (selector === "#loraList") return loraList;
      if (selector === "#loraCount") return loraCount;
      if (selector === "#allLorasToggle") return allLorasToggle;
      if (selector === ".advanced-settings-overlay[data-advanced-group=\"lora\"]") return overlay;
      if (selector === ".advanced-settings-button[data-advanced-group=\"lora\"]") return gear;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === ".lora-heading-actions, #loraList") return [actions, loraList];
      if (selector === ".advanced-settings-button") return [gear];
      if (selector === ".advanced-settings-overlay:not([hidden])") return overlay.hidden ? [] : [overlay];
      if (selector === ".advanced-settings-button[aria-expanded='true']") {
        return gear.getAttribute("aria-expanded") === "true" ? [gear] : [];
      }
      return [];
    },
  };
  const configurationByEngine = {
    moss: { model: [{ id: "moss-model", fields: [] }] },
    anima: { lora: [{ id: "1925", title: "ANIMA LoRA loader", class_type: "LoraLoader", fields: [] }] },
  };
  const context = {
    state,
    configuration: {},
    configurationByEngine,
    featureSelectors: {},
    featureControls: new Map(),
    referenceHomes: new Map(),
    mossLoraHomes: new Map(),
    mossDetailControls: null,
    mossDetailHome: null,
    actions: new Map(),
    tooltip: { hidden: true },
    document,
    window: {},
    closeLoraSearchMenu() {},
    updateLoraSearchMenu() {},
    scheduleGenerationStateSave() { saves += 1; },
    loraOptions,
    activeLoraSearchInput: null,
  };
  vm.createContext(context);
  vm.runInContext(
    [
      sourceSection(advancedSource, "function liveMossLoraControls()", "\n  const actions"),
      sourceSection(advancedSource, "  function render(group, body) {", "\n  function placeGenerationOverlay"),
      sourceSection(advancedSource, "  function closeOverlay(overlay, button) {", "\n  function toggleOverlay"),
      sourceSection(advancedSource, "  function toggleOverlay(button) {", "\n  function install"),
      appRender,
      allToggle[0],
      "renderLoras();",
    ].join("\n"),
    context,
  );
  const syncMethod = advancedSource.match(
    /    (syncGenerationEngine\(\) \{[\s\S]*?\r?\n    \}),\r?\n  \};/,
  );
  assert.ok(syncMethod, "the advanced settings engine synchronizer is present");
  const sync = vm.runInContext(`({${syncMethod[1]}}).syncGenerationEngine`, context);

  return { actions, allLorasToggle, body, configurationByEngine, context, gear, loraList,
    loraPanel: panel, overlay, state, sync, title, subtitle, saves: () => saves };
}

test("MOSS LoRA overlay reuses live selection, strength and enabled controls and cleans up on engine switch", () => {
  const h = mossLoraOverlayFixture();
  h.sync();
  assert.equal(h.gear.disabled, false);

  h.context.toggleOverlay(h.gear);
  assert.equal(h.overlay.hidden, false);
  assert.equal(h.title.textContent, "MOSS · 로라 설정");
  assert.equal(h.subtitle.textContent, "현재 MOSS LoRA의 선택·강도·활성 상태를 설정합니다.");
  assert.equal(h.actions.parentNode, h.body);
  assert.equal(h.loraList.parentNode, h.body);

  let row = h.loraList.children[0];
  let select = row.children[1];
  select.value = "moss/example.safetensors";
  select.listeners.get("change")({ target: select });
  assert.deepEqual(h.state.loras[0], {
    name: "moss/example.safetensors", enabled: true, strength: 1,
  });
  assert.equal(h.loraList.parentNode, h.body);

  row = h.loraList.children[0];
  const strength = row.children[2];
  strength.value = "0.70";
  strength.listeners.get("change")({ target: strength });
  assert.equal(h.state.loras[0].strength, .7);

  row = h.loraList.children[0];
  row.children[3].click();
  assert.equal(h.state.loras[0].enabled, false);
  h.loraList.children[0].children[3].click();
  assert.equal(h.state.loras[0].enabled, true);

  h.allLorasToggle.click();
  assert.equal(h.state.lora_enabled, false);
  assert.equal(h.loraList.classList.contains("all-disabled"), true);
  assert.deepEqual(h.state.moss_node_overrides, {});
  assert.ok(h.saves() >= 5);

  h.context.closeOverlay(h.overlay, h.gear);
  assert.equal(h.overlay.hidden, true);
  assert.equal(h.title.textContent, "로라 · 노드 설정");
  assert.equal(h.subtitle.textContent, "연결된 ComfyUI 노드의 전체 입력 설정");
  assert.equal(h.actions.parentNode, h.loraPanel);
  assert.equal(h.loraList.parentNode, h.loraPanel);

  h.state.generation.engine = "moss";
  h.context.toggleOverlay(h.gear);
  h.state.generation.engine = "anima";
  h.sync();
  assert.equal(h.overlay.hidden, true);
  assert.equal(h.title.textContent, "로라 · 노드 설정");
  assert.equal(h.subtitle.textContent, "연결된 ComfyUI 노드의 전체 입력 설정");
  assert.equal(h.actions.parentNode, h.loraPanel);
  assert.equal(h.loraList.parentNode, h.loraPanel);

  h.context.toggleOverlay(h.gear);
  assert.equal(h.overlay.hidden, false);
  assert.equal(h.title.textContent, "로라 · 노드 설정");
  assert.equal(h.subtitle.textContent, "연결된 ComfyUI 노드의 전체 입력 설정");
  assert.equal(h.body.children.some(child => child.className === "advanced-node-card"), true);
  assert.equal(h.actions.parentNode, h.loraPanel);
  assert.equal(h.loraList.parentNode, h.loraPanel);
  h.context.closeOverlay(h.overlay, h.gear);

  h.state.generation.engine = "moss";
  h.sync();
  h.context.toggleOverlay(h.gear);
  assert.equal(h.overlay.hidden, false);
  assert.equal(h.title.textContent, "MOSS · 로라 설정");
  assert.equal(h.subtitle.textContent, "현재 MOSS LoRA의 선택·강도·활성 상태를 설정합니다.");
  assert.equal(h.actions.parentNode, h.body);
  assert.equal(h.loraList.parentNode, h.body);
  h.context.closeOverlay(h.overlay, h.gear);
  assert.equal(h.title.textContent, "로라 · 노드 설정");
  assert.equal(h.subtitle.textContent, "연결된 ComfyUI 노드의 전체 입력 설정");
  assert.equal(h.actions.parentNode, h.loraPanel);
  assert.equal(h.loraList.parentNode, h.loraPanel);
});
