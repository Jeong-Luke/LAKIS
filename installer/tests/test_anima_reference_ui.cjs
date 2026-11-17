const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const uiPath = path.join(__dirname, "../../src/external_ui");
const referenceSource = fs.readFileSync(path.join(uiPath, "anima-reference.js"), "utf8");
const appSource = fs.readFileSync(path.join(uiPath, "app.js"), "utf8");
const html = fs.readFileSync(path.join(uiPath, "index.html"), "utf8");
const DEFAULTS = { enabled: false, mode: "cs", fidelity: 1, ref_megapixels: 1, experimental_forecast: false, references: [{ image_name: "", strength: 0 }] };
const POLICY = "snapref-test-policy-v1";
const READY = { experimental: true, ready: true, missing: [], defaults: DEFAULTS };
const accepted = { accepted: true, policy_id: POLICY };
const firstUse = { ...READY, consent: { accepted: false, policy_id: POLICY } };
const plain = value => JSON.parse(JSON.stringify(value));
const settle = () => new Promise(resolve => setImmediate(resolve));

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }
  dispatchEvent(event) {
    event.target ||= this;
    for (const listener of this.listeners.get(event.type) || []) listener(event);
    return true;
  }
  async fire(type, init = {}) {
    const event = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...init };
    for (const listener of this.listeners.get(type) || []) await listener(event);
    return event;
  }
}

class Element extends Events {
  constructor(tag, attributes) {
    super();
    this.tagName = tag.toUpperCase();
    this.attributes = new Map(attributes);
    this.children = [];
    this.parent = null;
    this.value = this.attributes.get("value") || "";
    this.disabled = this.attributes.has("disabled");
    this.hidden = this.attributes.has("hidden");
    this.textContent = "";
    this.files = [];
    this.clickCount = 0;
    this.dataset = {};
    for (const [name, val] of this.attributes) {
      if (name.startsWith("data-")) {
        const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        this.dataset[key] = val;
      }
    }
    const classes = new Set((this.attributes.get("class") || "").split(/\s+/).filter(Boolean));
    this._classes = classes;
    this.classList = {
      toggle: (name, enabled) => {
        if (enabled === undefined) enabled = !classes.has(name);
        if (enabled) classes.add(name); else classes.delete(name);
        this.attributes.set("class", [...classes].join(" "));
        return enabled;
      },
      contains: name => classes.has(name),
      add: (...names) => { for (const n of names) classes.add(n); this.attributes.set("class", [...classes].join(" ")); },
      remove: (...names) => { for (const n of names) classes.delete(n); this.attributes.set("class", [...classes].join(" ")); },
    };
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this._classes = new Set(String(value).split(/\s+/).filter(Boolean));
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = String(value);
    }
  }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  get id() { return this.getAttribute("id") || ""; }
  set id(value) { this.setAttribute("id", value); }
  get className() { return this.getAttribute("class") || ""; }
  set className(value) { this.classList.remove(...this._classes); this.classList.add(...value.split(/\s+/).filter(Boolean)); }
  removeAttribute(name) { this.attributes.delete(name); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  appendChild(child) {
    if (child.parent) child.parent.removeChild(child);
    this.children.push(child);
    child.parent = this;
    return child;
  }
  replaceChildren(...children) {
    for (const child of this.children) child.parent = null;
    this.children = [];
    for (const child of children) this.appendChild(child);
  }
  removeChild(child) {
    const at = this.children.indexOf(child);
    if (at >= 0) this.children.splice(at, 1);
    child.parent = null;
    return child;
  }
  remove() {
    if (this.parent) this.parent.removeChild(this);
  }
  before(...nodes) {
    if (!this.parent) return;
    const at = this.parent.children.indexOf(this);
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      if (node.parent) node.parent.removeChild(node);
      node.parent = this.parent;
      this.parent.children.splice(at + i, 0, node);
    }
  }
  after(...nodes) {
    if (!this.parent) return;
    const at = this.parent.children.indexOf(this);
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      if (node.parent) node.parent.removeChild(node);
      node.parent = this.parent;
      this.parent.children.splice(at + 1 + i, 0, node);
    }
  }
  matches(selector) {
    if (!selector) return false;
    if (selector.startsWith("#")) return this.getAttribute("id") === selector.slice(1);
    if (selector.startsWith(".")) return this._classes.has(selector.slice(1));
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }
  querySelector(selector) {
    const all = this.querySelectorAll(selector);
    return all[0] || null;
  }
  querySelectorAll(selector) {
    const out = [];
    const walk = node => {
      for (const child of node.children) {
        if (child.matches(selector)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
  cloneNode(deep = false) {
    const clone = new Element(this.tagName.toLowerCase(), [...this.attributes.entries()]);
    clone.value = this.value;
    clone.disabled = this.disabled;
    clone.hidden = this.hidden;
    clone.textContent = this.textContent;
    clone.files = [...this.files];
    clone.dataset = { ...this.dataset };
    if (deep) for (const child of this.children) clone.appendChild(child.cloneNode(true));
    return clone;
  }
  get parentElement() { return this.parent; }
  get isConnected() {
    let node = this;
    while (node.parent) node = node.parent;
    return node.isDocumentRoot === true;
  }
  click() {
    if (this.disabled) return;
    this.clickCount += 1;
    return this.fire("click");
  }
}

function el(tag, attrs = {}, children = []) {
  const node = new Element(tag, Object.entries(attrs).map(([k, v]) => [k, v]));
  for (const child of children) node.appendChild(child);
  return node;
}

function buildDocument() {
  const preview = el("img", { id: "animaReferencePreview", alt: "레퍼런스 이미지", hidden: "" });
  const empty = el("span", { id: "animaReferenceEmpty", class: "anima-reference-empty-text" });
  const dropZone = el("button", { id: "animaReferenceDropZone", class: "anima-reference-preview", type: "button", "aria-label": "레퍼런스 이미지 선택", disabled: "" }, [preview, empty]);
  const remove = el("button", { id: "animaReferenceRemove", class: "mini-button anima-reference-remove", type: "button", "aria-label": "레퍼런스 이미지 제거", title: "이미지 제거", hidden: "", disabled: "" });
  const file = el("input", { id: "animaReferenceFile", class: "anima-reference-file-input", type: "file", accept: "image/png,image/jpeg,image/webp", "aria-label": "레퍼런스 이미지 파일", hidden: "", disabled: "" });
  const image = el("div", { class: "anima-reference-image" }, [dropZone, remove, file]);
  const mode = el("select", { id: "animaReferenceMode", class: "anima-reference-mode", "data-reference-field": "mode", disabled: "" });
  mode.value = "cs";
  const strength = el("input", { id: "animaReferenceWeight", class: "anima-reference-strength", "data-reference-field": "strength", type: "number", min: "-3", max: "3", step: "0.1", value: "0", disabled: "" });
  strength.value = "0";
  const fidelity = el("input", { id: "animaReferenceFidelity", class: "anima-reference-fidelity", "data-reference-field": "fidelity", type: "number", min: "0", max: "1", step: "0.05", value: "1", disabled: "" });
  fidelity.value = "1";
  const megapixels = el("input", { id: "animaReferenceMegapixels", class: "anima-reference-megapixels", "data-reference-field": "megapixels", type: "number", min: "0.25", max: "2", step: "0.25", value: "1", disabled: "" });
  megapixels.value = "1";
  const target = el("select", { id: "animaReferenceTarget", class: "anima-reference-target", "data-reference-field": "target", "aria-label": "레퍼런스 적용 대상", disabled: "" });
  target.value = "global";
  const rowRemove = el("button", { class: "mini-button anima-reference-row-remove", type: "button", "data-row-remove": "", hidden: "", disabled: "" });
  rowRemove.textContent = "−";
  const title = el("h3", { class: "anima-reference-row-title" });
  const rowHeading = el("div", { class: "anima-reference-row-heading" }, [title, rowRemove]);
  const settings = el("div", { class: "anima-reference-settings" }, [rowHeading, mode, strength, target]);
  const body = el("div", { class: "anima-reference-body", "data-reference-index": "0" }, [image, settings]);
  const rows = el("div", { id: "animaReferenceRows", class: "anima-reference-rows" }, [body]);
  const toggle = el("button", { id: "animaReferenceToggle", class: "lora-switch", type: "button", "aria-label": "레퍼런스 켜기", "aria-pressed": "false", disabled: "" });
  const add = el("button", { id: "animaReferenceAdd", class: "mini-button", type: "button", "aria-label": "레퍼런스 영역 추가", title: "레퍼런스 영역 추가", disabled: "" });
  add.textContent = "＋";
  const statusEl = el("p", { id: "animaReferenceStatus", class: "anima-reference-status", role: "status" });
  rowHeading.appendChild(add);
  const review = el("button", { id: "animaReferenceConsentReview", hidden: "", disabled: "" });
  const heading = el("div", { class: "panel-heading" }, [review, toggle]);
  const forecast = el("select", { id: "animaReferenceForecast", disabled: "" });
  forecast.value = "off";
  const common = el("div", { class: "anima-reference-common-settings" }, [
    el("label", {}, [megapixels]), el("label", {}, [fidelity]), el("label", {}, [forecast]),
  ]);
  const panel = el("section", { id: "animaReferencePanel", class: "anima-reference-panel", hidden: "" }, [heading, statusEl, common, rows]);
  const notice = el("dialog", { id: "animaReferenceConsent" }, [
    el("input", { id: "acceptConsent", type: "checkbox" }),
    el("button", { id: "confirmConsent", disabled: "" }),
    el("button", { id: "cancelConsent" }),
    el("p", { id: "animaReferenceConsentError", hidden: "" }),
  ]);
  const root = el("div", { id: "test-root" }, [panel, notice]);
  root.isDocumentRoot = true;
  return { root, panel, toggle, add, statusEl, rows, body };
}

function harness(status = { ...READY, consent: accepted }, options = {}) {
  const built = buildDocument();
  const { root, panel, toggle, add, statusEl, rows } = built;
  const byId = id => {
    const search = node => {
      if (node.getAttribute("id") === id) return node;
      for (const child of node.children) {
        const found = search(child);
        if (found) return found;
      }
      return null;
    };
    return search(root);
  };
  const window = new Events();
  const session = options.session || new Map();
  window.sessionStorage = {
    getItem: key => session.get(key) ?? null,
    setItem: (key, value) => session.set(key, String(value)),
  };
  let animaRegions = { enabled: false, regions: [] };
  window.LAKISAnimaRegions = {
    snapshot: () => structuredClone(animaRegions),
    restore: value => { animaRegions = structuredClone(value); },
  };
  const calls = [];
  const changes = [];
  const errors = [];
  let saves = 0;
  const context = {
    window, structuredClone,
    document: {
      body: root,
      querySelector: selector => {
        if (selector.startsWith("#")) return byId(selector.slice(1));
        const all = root.querySelectorAll(selector);
        return all[0] || null;
      },
      querySelectorAll: selector => root.querySelectorAll(selector),
      createElement: tag => new Element(tag, []),
      createComment: text => {
        const node = new Element("#comment", []);
        node.textContent = text;
        return node;
      },
      activeElement: null,
    },
    CustomEvent: class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } },
    console: { error: (...args) => errors.push(args) },
    captureGenerationEngineProfile() {},
    scheduleGenerationStateSave() { saves += 1; },
    FileReader: class {
      readAsDataURL(file) {
        this.result = file.data_url;
        queueMicrotask(() => this.onload());
      }
    },
    fetch: async (url, request = {}) => {
      calls.push({ url, ...request });
      if (url === "/api/anima-reference-consent" && request.method === "POST") {
        if (options.saveConsent) return options.saveConsent();
        return { ok: true, json: async () => ({ accepted: true, policy_id: status.consent.policy_id }) };
      }
      if (request.method === "POST") {
        if (options.upload) return options.upload(url, request);
        return { ok: true, json: async () => ({
          ok: true, image_name: "snap ref/한 장.png",
          image_url: "/api/anima-reference-image?name=uploaded",
          width: 1024, height: 768,
        }) };
      }
      if (options.get) return options.get();
      return { ok: true, json: async () => status };
    },
  };
  vm.createContext(context);
  vm.runInContext(appSource.slice(0, appSource.indexOf("function normalizeContinuousCount(")), context);
  const state = vm.runInContext("state", context);
  if (options.initialReference) state.anima_reference = structuredClone(options.initialReference);
  context.currentGenerationEngine = () => state.generation.engine;
  vm.runInContext(appSource.slice(
    appSource.indexOf("function persistedGenerationState("),
    appSource.indexOf("function syncEditedGenerationControls("),
  ), context);
  vm.runInContext(appSource.slice(
    appSource.indexOf('window.addEventListener("lakis:anima-reference-change"'),
    appSource.indexOf('for (const [id, key, convert] of ['),
  ), context);
  window.addEventListener("lakis:anima-reference-change", event => changes.push(plain(event.detail)));
  vm.runInContext(referenceSource, context);
  const firstIds = ["Toggle", "Add", "Panel", "Status", "Rows", "DropZone", "Preview", "Empty", "Remove", "File", "Mode", "Weight", "Fidelity", "Megapixels"];
  return {
    api: window.LAKISAnimaReference, state, window, context, calls, changes, errors,
    node: id => byId(`animaReference${id}`),
    row: index => {
      const bodies = rows.querySelectorAll(".anima-reference-body");
      const body = bodies[index];
      if (!body) return null;
      const q = sel => body.querySelector(sel);
      return {
        root: body,
        dropZone: q(".anima-reference-preview"),
        preview: q("img"),
        empty: q(".anima-reference-empty-text"),
        remove: q(".anima-reference-remove"),
        file: q(".anima-reference-file-input"),
        mode: q(".anima-reference-mode"),
        strength: q(".anima-reference-strength"),
        target: q(".anima-reference-target"),
        title: q(".anima-reference-row-title"),
        rowRemove: q(".anima-reference-row-remove"),
      };
    },
    rowCount: () => rows.querySelectorAll(".anima-reference-body").length,
    setAnimaRegions: value => { animaRegions = structuredClone(value); },
    get controls() {
      return panel.querySelectorAll("button").concat(panel.querySelectorAll("input")).concat(panel.querySelectorAll("select"));
    },
    savedCount: () => saves,
    persisted: () => plain(context.persistedGenerationState()),
  };
}

function noticeControls(h) {
  const dialog = h.node("Consent");
  return { dialog, checkbox: dialog.querySelector("#acceptConsent"), confirm: dialog.querySelector("#confirmConsent"), cancel: dialog.querySelector("#cancelConsent") };
}

test("the standalone notice uses the approved copy, icon, license link and checkbox before actions", () => {
  const dialog = html.match(/<dialog id="animaReferenceConsent"[\s\S]*?<\/dialog>/)[0];
  const text = dialog.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
  assert.equal(text, "⚠︎ 중요 레퍼런스 기능에 사용되는 snapref_v2a.safetensors는 CircleStone Labs Non-Commercial License v1.2 라이선스로 제공되고 있습니다. 레퍼런스 기능을 사용한 유료 이미지 생성 서비스 제공, 기능 판매·임대 등 상업적 이용 및 프로덕션 운영은 별도 상업용 허가 없이 엄격히 금지됩니다. 생성물의 이용 권리는 모델 사용 조건과 구분됩니다. 라이선스 원문 보기 레퍼런스 기능의 상업적 이용 불가에 대해 이해했으며 동의합니다 취소 확인");
  assert.ok(dialog.includes('href="https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2/LICENSE.md"'));
  assert.match(dialog, /<label for="acceptConsent">[\s\S]*?<input id="acceptConsent" type="checkbox">[\s\S]*?class="consent-actions"/);
});

test("first enable waits for explicit, policy-matched server confirmation; review never saves or enables", async () => {
  let finish;
  const h = harness(firstUse, { saveConsent: () => new Promise(resolve => { finish = resolve; }) });
  await settle();
  const { dialog, checkbox, confirm, cancel } = noticeControls(h);
  await h.node("Toggle").click();
  assert.equal(dialog.open, true);
  assert.equal(checkbox.checked, false);
  assert.equal(confirm.disabled, true);
  await confirm.fire("click");
  assert.equal(h.calls.length, 1);
  checkbox.checked = true;
  await checkbox.fire("change");
  const save = confirm.click();
  await confirm.fire("click");
  assert.equal(cancel.disabled, true);
  assert.equal((await dialog.fire("cancel")).defaultPrevented, true);
  assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, false);
  assert.equal(h.api.snapshot().enabled, false);
  assert.equal(h.changes.length, 0);
  assert.deepEqual(h.calls.map(c => [c.url, c.method || "GET"]), [
    ["/api/anima-reference", "GET"], ["/api/anima-reference-consent", "POST"],
  ]);
  assert.deepEqual(JSON.parse(h.calls[1].body), accepted);
  finish({ ok: true, json: async () => accepted });
  await save;
  assert.equal(dialog.open, false);
  assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, true);
  assert.equal(h.changes.length, 1);
  assert.equal(h.node("Warning"), null);
  await h.node("Toggle").click();
  assert.equal(h.node("ConsentReview").hidden, false);
  await h.node("ConsentReview").click();
  assert.equal(dialog.open, true);
  assert.equal(checkbox.checked, true);
  await confirm.click();
  assert.equal(dialog.open, false);
  assert.equal(h.api.snapshot().enabled, false);
  await h.node("Toggle").click();
  assert.equal(h.api.snapshot().enabled, true);
  assert.equal(h.calls.length, 2);
  await h.node("Add").click();
  assert.equal(h.node("Warning").open, true);
});

test("cancel and Escape discard the checkbox and never post, edit, or enable", async () => {
  const h = harness(firstUse, { session: new Map([["lakis:multi-reference-warning-dismissed", "1"]]) });
  await settle();
  const { dialog, checkbox, confirm, cancel } = noticeControls(h);
  for (const escape of [false, true]) {
    await h.node("Toggle").click();
    assert.equal(dialog.open, true);
    assert.equal(checkbox.checked, false);
    assert.equal(confirm.disabled, true);
    checkbox.checked = true;
    await checkbox.fire("change");
    if (escape) {
      assert.equal((await dialog.fire("cancel")).defaultPrevented, false);
      dialog.close(); // Native default action of an uncanceled dialog cancel event.
    } else await cancel.click();
    assert.equal(dialog.open, false);
    assert.equal(h.api.snapshot().enabled, false);
    assert.equal(h.changes.length, 0);
    assert.equal(h.calls.length, 1);
  }
});

test("startup and persisted restore cannot supply consent, including for changed or malformed terms", async () => {
  const saved = { ...DEFAULTS, enabled: true, mode: "char", fidelity: 0.45, ref_megapixels: 2, experimental_forecast: true,
    consent: accepted, references: [{ image_name: "keep.png", strength: -0.5, target_type: "box", target_id: "box", note: "keep" }] };
  const off = { ...saved, enabled: false };
  for (const record of [undefined, { accepted: "true", policy_id: POLICY }, { accepted: true, policy_id: " " }, { accepted: false, policy_id: "revised" }]) {
    const h = harness({ ...READY, consent: record }, { initialReference: saved });
    assert.deepEqual(plain(h.api.snapshot()), off);
    assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, false);
    await settle();
    assert.deepEqual(h.persisted().anima_reference, off);
    h.context.applyPersistedGenerationState({ ...h.persisted(), anima_reference: saved });
    assert.deepEqual(plain(h.api.forGeneration({ engine: "anima" })), off);
    assert.deepEqual(plain(h.api.snapshot()), off);
    assert.equal(h.node("Panel").classList.contains("is-enabled"), false);
    assert.equal(h.node("Toggle").getAttribute("aria-pressed"), "false");
    assert.equal(h.changes.length, 0);
    assert.ok(h.row(0).file.disabled);
    await h.node("Toggle").click();
    const { dialog, checkbox, confirm } = noticeControls(h);
    if (record?.policy_id === "revised") {
      assert.equal(dialog.open, true);
      checkbox.checked = true;
      await checkbox.fire("change");
      await confirm.click();
      assert.deepEqual(JSON.parse(h.calls[1].body), { accepted: true, policy_id: "revised" });
      assert.deepEqual(plain(h.api.snapshot()), saved);
    } else {
      assert.equal(h.node("Toggle").disabled, true);
      assert.ok(!dialog.open);
      assert.equal(h.calls.length, 1);
    }
  }
});

test("failed saves and mismatched acknowledgements leave the notice open and references off", async () => {
  for (const saveConsent of [
    async () => { throw new Error("offline"); },
    async () => ({ ok: false, status: 409, json: async () => accepted }),
    async () => ({ ok: true, json: async () => { throw new SyntaxError("invalid JSON"); } }),
    ...[{}, { accepted: false, policy_id: POLICY }, { accepted: "true", policy_id: POLICY }, { accepted: true, policy_id: "other" }]
      .map(result => async () => ({ ok: true, json: async () => result })),
  ]) {
    const h = harness(firstUse, { saveConsent });
    await settle();
    await h.node("Toggle").click();
    const { dialog, checkbox, confirm, cancel } = noticeControls(h);
    checkbox.checked = true;
    await checkbox.fire("change");
    await confirm.click();
    assert.equal(dialog.open, true);
    assert.equal(h.node("ConsentError").hidden, false);
    assert.equal(checkbox.checked, false);
    assert.equal(confirm.disabled, true);
    assert.equal(cancel.disabled, false);
    assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, false);
    assert.equal(h.node("ConsentReview").hidden, true);
    assert.equal(h.changes.length, 0);
  }
});

test("consent acknowledged during restore does not enable the replacement profile", async () => {
  let finish;
  const h = harness(firstUse, { saveConsent: () => new Promise(resolve => { finish = resolve; }) });
  await settle();
  await h.node("Toggle").click();
  const { checkbox, confirm } = noticeControls(h);
  checkbox.checked = true;
  await checkbox.fire("change");
  const pending = confirm.click();
  const restored = { ...DEFAULTS, references: [{ image_name: "replacement.png", strength: 0.3 }] };
  h.api.restore(restored);
  finish({ ok: true, json: async () => accepted });
  await pending;
  assert.deepEqual(plain(h.api.snapshot()), restored);
  assert.equal(h.changes.length, 0);
});

test("adding a second reference shows the requested modal and requires confirmation", async () => {
  const h = harness();
  await settle();
  assert.equal(h.node("Warning"), null);
  await h.node("Add").fire("click");
  const dialog = h.node("Warning");
  assert.equal(dialog.open, true);
  assert.equal(dialog.getAttribute("role"), "alertdialog");
  assert.equal(dialog.querySelector("p").textContent, "다중 레퍼런스 사용 시 제작 시간이 대폭 증가하고 안정성과 완성도가\n떨어질 수 있으며 ,Comfy 백엔드가 종료 될 수 있습니다.");
  assert.equal(dialog.querySelector("h2").querySelector("span").getAttribute("aria-hidden"), "true");
  assert.equal(dialog.querySelector("h2").querySelectorAll("span")[1].textContent, "주의");
  assert.equal(dialog.querySelector("label").querySelector("span").textContent, "다음 재실행까지 보지 않기");
  assert.equal(dialog.querySelector("button").textContent, "확인");
  assert.equal(h.rowCount(), 2);
  const event = await dialog.fire("cancel");
  assert.equal(event.defaultPrevented, true);
  assert.equal(dialog.open, true);
  await dialog.querySelector("button").fire("click");
  assert.equal(h.node("Warning"), null);
  assert.equal(h.changes.length, 1);
});

test("confirmation without the checkbox warns again on the next added reference", async () => {
  const h = harness();
  await settle();
  await h.node("Add").fire("click");
  await h.node("Warning").querySelector("button").fire("click");
  await h.node("Add").fire("click");
  assert.equal(h.node("Warning").open, true);
  assert.equal(h.rowCount(), 3);
});

test("checked confirmation suppresses warnings for this window session, including reloads", async () => {
  const session = new Map();
  const h = harness(undefined, { session });
  await settle();
  await h.node("Add").fire("click");
  const dialog = h.node("Warning");
  dialog.querySelector("input").checked = true;
  await dialog.querySelector("button").fire("click");
  await h.node("Add").fire("click");
  assert.equal(h.node("Warning"), null);
  const reloaded = harness(undefined, { session });
  await settle();
  await reloaded.node("Add").fire("click");
  assert.equal(reloaded.node("Warning"), null);
  const restarted = harness();
  await settle();
  await restarted.node("Add").fire("click");
  assert.equal(restarted.node("Warning").open, true);
});

test("checking without confirming does not suppress warnings", async () => {
  const session = new Map();
  const h = harness(undefined, { session });
  await settle();
  await h.node("Add").fire("click");
  h.node("Warning").querySelector("input").checked = true;
  await h.node("Warning").fire("cancel");
  const reloaded = harness(undefined, { session });
  await settle();
  await reloaded.node("Add").fire("click");
  assert.equal(reloaded.node("Warning").open, true);
});

test("uploading the first reference does not show a multi-reference warning", async () => {
  const h = harness();
  await settle();
  h.row(0).file.files = [{ type: "image/png", data_url: "data:image/png;base64,AQ==" }];
  await h.row(0).file.fire("change");
  assert.equal(h.node("Warning"), null);
  assert.equal(h.api.snapshot().references[0].image_name, "snap ref/한 장.png");
});

test("canonical snapshot/restore preserves unknown fields, bounds entries, and rejects oversized arrays", async () => {
  const h = harness();
  await settle();
  assert.deepEqual(plain(h.api.snapshot()), DEFAULTS);
  const original = { enabled: true, mode: "char", fidelity: -1, ref_megapixels: 0, future: { list: [1, 2] }, references: [{ image_name: "folder/한 장.webp", strength: 8, note: "keep" }, { image_name: "", strength: -9 }] };
  h.api.restore(original);
  original.future.list.push(3);
  original.references[0].note = "mutated";
  const snapshot = h.api.snapshot();
  assert.deepEqual(plain(snapshot), { enabled: true, mode: "char", fidelity: 0, ref_megapixels: 0.25, experimental_forecast: false, future: { list: [1, 2] }, references: [{ image_name: "folder/한 장.webp", strength: 3, note: "keep" }, { image_name: "", strength: -3 }] });
  assert.equal("image_name" in snapshot, false);
  assert.equal("strength" in snapshot, false);
  assert.equal("weight" in snapshot, false);
  snapshot.future.list.push(99);
  snapshot.references[0].note = "dirty";
  assert.deepEqual(plain(h.api.snapshot().future), { list: [1, 2] });
  assert.equal(h.api.snapshot().references[0].note, "keep");
  assert.equal(h.row(0).preview.getAttribute("src"), `/api/anima-reference-image?name=${encodeURIComponent("folder/한 장.webp")}`);
  assert.equal(h.row(0).preview.hidden, false);
  assert.equal(h.row(0).empty.hidden, true);
  assert.equal(h.row(0).mode.value, "char");
  assert.equal(h.row(0).strength.value, "3");
  assert.equal(h.node("Toggle").getAttribute("aria-pressed"), "true");
  assert.equal(h.changes.length, 0);
  assert.equal(h.savedCount(), 0);
  const before = plain(h.api.snapshot());
  h.api.restore({ ...plain(h.api.snapshot()), references: [{ image_name: "a", strength: 0 }, { image_name: "b", strength: 0 }, { image_name: "c", strength: 0 }, { image_name: "d", strength: 0 }] });
  assert.deepEqual(plain(h.api.snapshot()), before);
  assert.equal(h.rowCount(), 2);
  assert.equal(h.changes.length, 0);
  h.api.restore({ enabled: "true", mode: "invalid", fidelity: NaN, ref_megapixels: Infinity, references: [{ image_name: 42, strength: "" }] });
  assert.deepEqual(plain(h.api.snapshot()), DEFAULTS);
  h.api.restore({ references: [{ image_name: "", strength: "-1.25" }], fidelity: "0.75", ref_megapixels: 9 });
  assert.deepEqual(plain(h.api.snapshot()), { ...DEFAULTS, fidelity: 0.75, ref_megapixels: 2, references: [{ image_name: "", strength: -1.25 }] });
  h.api.restore(null);
  assert.equal(h.row(0).preview.getAttribute("src"), null);
  assert.equal(h.row(0).preview.hidden, true);
});

test("legacy flat image/strength and log(weight) migrate once without edits or lost fields", async () => {
  const h = harness();
  await settle();
  for (const [weight, expected] of [[0, 0], [0.01, -3], [0.5, Math.log(0.5)], [1, 0], [1.2, Math.log(1.2)], [2, Math.log(2)]]) {
    const saved = { enabled: true, image_name: "keep.png", mode: "char", weight, future: { keep: [1] } };
    const before = structuredClone(saved);
    h.api.restore(saved);
    const migrated = plain(h.api.snapshot());
    assert.deepEqual(migrated.references, [{ image_name: "keep.png", strength: expected }]);
    assert.equal(migrated.enabled, weight !== 0);
    assert.equal("weight" in migrated, false);
    assert.equal("image_name" in migrated, false);
    assert.equal("strength" in migrated, false);
    assert.deepEqual(migrated.future, saved.future);
    assert.deepEqual(saved, before);
    h.api.restore(migrated);
    assert.deepEqual(plain(h.api.snapshot()), migrated);
    assert.deepEqual(h.persisted().anima_reference, migrated);
  }
  h.api.restore({ enabled: true, image_name: "flat.png", strength: -2 });
  assert.deepEqual(plain(h.api.snapshot().references), [{ image_name: "flat.png", strength: -2 }]);
  h.api.restore({ enabled: true, strength: -2, weight: 2, references: [{ image_name: "ref.png", strength: 1 }] });
  assert.deepEqual(plain(h.api.snapshot().references), [{ image_name: "ref.png", strength: 1 }]);
  assert.equal(h.changes.length, 0);
  assert.equal(h.savedCount(), 0);
});

test("log strength stays within -3..3 per reference and zero keeps the reference enabled", async () => {
  const h = harness();
  await settle();
  assert.equal(h.row(0).strength.getAttribute("min"), "-3");
  assert.equal(h.row(0).strength.getAttribute("max"), "3");
  assert.equal(h.row(0).strength.getAttribute("value"), "0");
  h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "keep.png", strength: 0 }] });
  for (const [input, expected] of [["-4", -3], ["-1", -1], ["0", 0], ["1", 1], ["4", 3]]) {
    h.row(0).strength.value = input;
    await h.row(0).strength.fire("change");
    assert.equal(h.api.snapshot().references[0].strength, expected);
    assert.equal(h.api.forGeneration({ engine: "anima" }).references[0].strength, expected);
    assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, true);
    assert.equal(h.row(0).strength.value, String(expected));
  }
});

test("numeric keyboard drafts survive background refreshes without changing saved settings", async () => {
  const h = harness();
  await settle();
  const cases = [
    ["strength", ["", "-", "-1", "-1.", "-1.2"]],
    ["fidelity", ["", "0", "0.", "0.65"]],
    ["megapixels", ["", "1", "1.", "1.25"]],
  ];
  for (const [field, drafts] of cases) {
    const input = field === "strength" ? h.row(0).strength : h.node(field === "fidelity" ? "Fidelity" : "Megapixels");
    h.context.document.activeElement = input;
    for (const draft of drafts) {
      input.value = draft;
      await input.fire("input");
      h.window.dispatchEvent({ type: "lakis-generation-engine-changed" });
      assert.equal(input.value, draft);
      assert.deepEqual(plain(h.api.snapshot()), DEFAULTS);
    }
  }
  assert.equal(h.changes.length, 0);
  assert.equal(h.savedCount(), 0);
});

test("numeric fields commit keyboard input on Enter or blur and retain their bounds", async () => {
  const h = harness();
  await settle();
  for (const [field, key, draft, expected, event] of [
    ["strength", "references", "-1.2", -1.2, "keydown"],
    ["fidelity", "fidelity", "0.65", 0.65, "blur"],
    ["megapixels", "ref_megapixels", "1.25", 1.25, "keydown"],
    ["strength", "references", "-9", -3, "blur"],
    ["strength", "references", "9", 3, "keydown"],
    ["fidelity", "fidelity", "-1", 0, "keydown"],
    ["fidelity", "fidelity", "2", 1, "blur"],
    ["megapixels", "ref_megapixels", "0", 0.25, "blur"],
    ["megapixels", "ref_megapixels", "9", 2, "keydown"],
  ]) {
    const input = field === "strength" ? h.row(0).strength : h.node(field === "fidelity" ? "Fidelity" : "Megapixels");
    h.context.document.activeElement = input;
    input.value = draft;
    await input.fire("input");
    const before = h.savedCount();
    const committed = await input.fire(event, { key: "Enter" });
    if (event === "keydown") assert.equal(committed.defaultPrevented, true);
    if (key === "references") assert.equal(h.api.snapshot().references[0].strength, expected);
    else assert.equal(h.api.snapshot()[key], expected);
    assert.equal(input.value, String(expected));
    assert.equal(h.savedCount(), before + 1);
    await input.fire("change");
    await input.fire("blur");
    assert.equal(h.savedCount(), before + 1);
    input.value = "";
    await input.fire("keydown", { key: "Enter" });
    if (key === "references") assert.equal(h.api.snapshot().references[0].strength, expected);
    else assert.equal(h.api.snapshot()[key], expected);
    assert.equal(h.savedCount(), before + 1);
  }
});

test("explicit restore replaces focused numeric drafts without emitting an edit", async () => {
  const h = harness();
  await settle();
  const input = h.row(0).strength;
  h.context.document.activeElement = input;
  input.value = "-";
  h.api.restore({ ...DEFAULTS, references: [{ image_name: "", strength: -0.5 }] });
  assert.equal(input.value, "-0.5");
  assert.equal(h.api.snapshot().references[0].strength, -0.5);
  assert.equal(h.savedCount(), 0);
  assert.equal(h.changes.length, 0);
});

test("reference off/on collapses all areas but preserves every image and setting", async () => {
  const h = harness();
  await settle();
  await h.node("Add").fire("click");
  const saved = { ...DEFAULTS, enabled: true, mode: "char", fidelity: 0.4, ref_megapixels: 0.5, future: { keep: [1] }, references: [{ image_name: "keep.png", strength: -1 }, { image_name: "second.png", strength: 1.5 }] };
  h.api.restore(saved);
  assert.equal(h.rowCount(), 2);
  assert.equal(h.node("Panel").classList.contains("is-enabled"), true);
  await h.node("Toggle").fire("click");
  assert.equal(h.node("Panel").classList.contains("is-enabled"), false);
  assert.deepEqual(plain(h.api.snapshot()), { ...saved, enabled: false });
  assert.equal(h.rowCount(), 2);
  assert.equal(h.row(0).preview.getAttribute("src"), `/api/anima-reference-image?name=${encodeURIComponent("keep.png")}`);
  await h.node("Toggle").fire("click");
  assert.equal(h.node("Panel").classList.contains("is-enabled"), true);
  assert.deepEqual(plain(h.api.snapshot()), saved);
  assert.equal(h.row(1).strength.value, "1.5");
});

test("generation gating preserves slots and leaves enabled empty references for server rejection", async () => {
  const h = harness();
  const saved = { ...DEFAULTS, enabled: true, future: { keep: [1] }, references: [{ image_name: "keep.png", strength: 0.5 }, { image_name: "", strength: -1 }] };
  h.api.restore(saved);
  assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, false, "availability must be established first");
  await settle();
  for (const engine of ["anima", "moss"]) {
    for (const i2i of [false, true]) {
      for (const inpaint of [false, true]) {
        const request = h.api.forGeneration({ engine, i2i, inpaint });
        const expectEnabled = engine === "anima" && !i2i && !inpaint;
        assert.equal(request.enabled, expectEnabled);
        assert.deepEqual(request.references.map(r => r.image_name), ["keep.png", ""]);
        request.future.keep.push(2);
        request.references[0].strength = 99;
        assert.deepEqual(plain(h.api.snapshot()), saved);
      }
    }
  }
  h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "", strength: 0 }] });
  assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, true);
  assert.deepEqual(h.api.forGeneration({ engine: "anima" }).references, [{ image_name: "", strength: 0 }]);
  h.api.restore({ ...saved, enabled: false });
  assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, false);
  assert.equal(h.changes.length, 0);
});

test("experiment visibility, missing dependencies and engine changes never erase saved settings", async () => {
  for (const status of [
    { experimental: false, ready: true, missing: [] },
    { experimental: true, ready: false, missing: ["SnapRef nodes", "reference model"] },
  ]) {
    const h = harness({ ...status, consent: accepted });
    h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "keep.png", strength: 0 }] });
    await settle();
    assert.equal(h.node("Panel").hidden, !status.experimental);
    assert.ok(h.controls.filter(node => node !== h.node("ConsentReview")).every(node => node.disabled));
    if (status.experimental) {
      assert.match(h.node("Status").textContent, /SnapRef nodes/);
      assert.match(h.node("Status").textContent, /reference model/);
    }
    assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, false);
    await h.node("Toggle").fire("click");
    assert.equal(h.api.snapshot().enabled, true);
    assert.equal(h.changes.length, 0);
  }
  const h = harness();
  await settle();
  const before = plain(h.api.snapshot());
  assert.equal(h.node("Panel").hidden, false);
  h.state.generation.engine = "moss";
  h.window.dispatchEvent({ type: "lakis-generation-engine-changed" });
  assert.equal(h.node("Panel").hidden, true);
  h.state.generation.engine = "anima";
  h.window.dispatchEvent({ type: "lakis-generation-engine-changed" });
  assert.equal(h.node("Panel").hidden, false);
  assert.deepEqual(plain(h.api.snapshot()), before);
  assert.deepEqual(h.calls.map(call => [call.url, call.method || "GET"]), [["/api/anima-reference", "GET"]]);
});

test("availability failure fails closed without losing restored images or settings", async () => {
  const h = harness(undefined, { get: async () => ({ ok: false, status: 503 }) });
  h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "keep.png", strength: 0 }] });
  await settle();
  assert.equal(h.errors.length, 1);
  assert.equal(h.node("Panel").hidden, true);
  assert.ok(h.controls.every(node => node.disabled));
  assert.equal(h.api.forGeneration({ engine: "anima" }).enabled, false);
  assert.deepEqual(plain(h.api.snapshot()), { ...DEFAULTS, references: [{ image_name: "keep.png", strength: 0 }] });
});

test("meaningful control edits emit once, persist independently, and ignore equivalent or empty numeric changes", async () => {
  const h = harness();
  await settle();
  h.state.generation.profiles = { anima: { custom: "keep" }, moss: { custom: "separate" } };
  h.state.i2i.image_name = "i2i.png";
  h.state.inpaint.image_name = "inpaint.png";
  h.state.loras = [{ name: "keep.safetensors", enabled: true, strength: 0.5 }];
  h.state.prompt.general = "do not edit";
  const independent = plain({
    i2i: h.state.i2i, inpaint: h.state.inpaint, loras: h.state.loras,
    prompt: h.state.prompt, generation: h.state.generation,
  });
  await h.node("Toggle").fire("click");
  assert.equal(h.api.snapshot().enabled, true);
  assert.equal(h.node("Toggle").classList.contains("on"), true);
  h.row(0).mode.value = "char";
  await h.row(0).mode.fire("change");
  h.row(0).strength.value = "1.50";
  await h.row(0).strength.fire("change");
  h.row(0).strength.value = "1.5";
  await h.row(0).strength.fire("change");
  h.row(0).strength.value = "";
  await h.row(0).strength.fire("change");
  h.node("Fidelity").value = "0.4";
  await h.node("Fidelity").fire("change");
  h.node("Megapixels").value = "0.5";
  await h.node("Megapixels").fire("change");
  assert.equal(h.changes.length, 5);
  assert.equal(h.savedCount(), 5);
  assert.equal(h.row(0).strength.value, "1.5");
  assert.deepEqual(h.persisted().anima_reference, { enabled: true, mode: "char", fidelity: 0.4, ref_megapixels: 0.5, experimental_forecast: false, references: [{ image_name: "", strength: 1.5 }] });
  assert.deepEqual(plain({
    i2i: h.state.i2i, inpaint: h.state.inpaint, loras: h.state.loras,
    prompt: h.state.prompt, generation: h.state.generation,
  }), independent);
  h.changes[0].references[0].strength = 99;
  assert.equal(h.api.snapshot().references[0].strength, 1.5);
});

test("persisted hydration restores the panel and round-trips unknown reference fields without edits", async () => {
  const h = harness();
  await settle();
  const saved = { ...h.persisted(), anima_reference: { ...DEFAULTS, enabled: true, mode: "char", future: { version: 2 }, references: [{ image_name: "old.jpg", strength: 0.5, note: "keep" }] } };
  h.context.applyPersistedGenerationState(saved);
  assert.deepEqual(plain(h.api.snapshot()), saved.anima_reference);
  assert.deepEqual(h.persisted().anima_reference, saved.anima_reference);
  assert.equal(h.row(0).mode.value, "char");
  assert.equal(h.changes.length, 0);
  saved.anima_reference.future.version = 9;
  saved.anima_reference.references[0].note = "dirty";
  assert.equal(h.api.snapshot().future.version, 2);
  assert.equal(h.api.snapshot().references[0].note, "keep");
});

test("generation payload uses the request gate, including when the experiment script is unavailable", async () => {
  const h = harness();
  await settle();
  h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "request.png", strength: 0.5 }, { image_name: "", strength: 0 }] });
  const start = appSource.indexOf("    generationPayload = structuredClone(state);");
  const end = appSource.indexOf("    if (mossMode) {", start);
  for (const [engine, i2i, inpaint, expected] of [
    ["anima", false, false, true], ["moss", false, false, false],
    ["anima", true, false, false], ["anima", false, true, false],
  ]) {
    h.state.generation.engine = engine;
    h.state.i2i.enabled = i2i;
    h.state.inpaint.enabled = inpaint;
    const request = vm.runInContext(`(() => { let generationPayload; ${appSource.slice(start, end)} return generationPayload; })()`, h.context);
    assert.equal(request.anima_reference.enabled, expected);
    assert.deepEqual(request.anima_reference.references.map(r => r.image_name), ["request.png", ""]);
    assert.equal(h.api.snapshot().enabled, true);
    assert.deepEqual(plain(request.i2i), plain(h.state.i2i));
    assert.deepEqual(plain(request.inpaint), plain(h.state.inpaint));
  }
  h.state.anima_reference = structuredClone(h.api.snapshot());
  delete h.window.LAKISAnimaReference;
  const fallback = vm.runInContext(`(() => { let generationPayload; ${appSource.slice(start, end)} return generationPayload; })()`, h.context);
  assert.equal(fallback.anima_reference.enabled, false);
  assert.equal(h.state.anima_reference.enabled, true);
});

test("add button appends blank areas up to three and fourth is prevented", async () => {
  const h = harness();
  await settle();
  assert.ok(html.includes('id="animaReferenceAdd"'));
  assert.ok(html.includes('id="animaReferenceRows"'));
  assert.ok(html.includes("＋"));
  assert.equal(h.rowCount(), 1);
  assert.equal(h.row(0).rowRemove.hidden, true);
  assert.equal(h.node("Add").disabled, false);
  await h.node("Add").fire("click");
  assert.equal(h.rowCount(), 2);
  assert.equal(h.node("Add").disabled, false);
  assert.equal(h.row(0).rowRemove.hidden, true);
  assert.equal(h.row(1).rowRemove.hidden, false);
  await h.node("Add").fire("click");
  assert.equal(h.rowCount(), 3);
  assert.equal(h.node("Add").disabled, true);
  assert.equal(h.node("Fidelity").parentElement.hidden, false);
  assert.equal(h.node("Megapixels").parentElement.hidden, false);
  assert.equal(h.context.document.querySelectorAll(".anima-reference-fidelity").length, 1);
  assert.equal(h.context.document.querySelectorAll(".anima-reference-megapixels").length, 1);
  assert.equal(h.context.document.querySelectorAll("#animaReferenceAdd").length, 1);
  assert.equal(h.row(0).title.textContent, "레퍼런스 1");
  for (const index of [1, 2]) {
    assert.equal(h.row(index).title.textContent, `레퍼런스 ${index + 1}`);
  }
  assert.deepEqual(h.api.snapshot().references, [{ image_name: "", strength: 0 }, { image_name: "", strength: 0 }, { image_name: "", strength: 0 }]);
  await h.node("Add").fire("click");
  assert.equal(h.rowCount(), 3);
  assert.equal(h.changes.length, 2);
  assert.notEqual(h.row(1).strength.getAttribute("id"), h.row(0).strength.getAttribute("id"));
  assert.notEqual(h.row(2).dropZone.getAttribute("id"), h.row(0).dropZone.getAttribute("id"));
});

test("independent images and strengths per reference with shared mode/fidelity/megapixels", async () => {
  const h = harness();
  await settle();
  await h.node("Add").fire("click");
  await h.node("Add").fire("click");
  h.row(0).strength.value = "1";
  await h.row(0).strength.fire("change");
  h.row(1).strength.value = "-2";
  await h.row(1).strength.fire("change");
  h.row(2).strength.value = "0.5";
  await h.row(2).strength.fire("change");
  assert.deepEqual(h.api.snapshot().references.map(r => r.strength), [1, -2, 0.5]);
  h.row(1).mode.value = "char";
  await h.row(1).mode.fire("change");
  assert.equal(h.row(0).mode.value, "char");
  assert.equal(h.row(2).mode.value, "char");
  h.node("Fidelity").value = "0.2";
  await h.node("Fidelity").fire("change");
  h.node("Megapixels").value = "0.5";
  await h.node("Megapixels").fire("change");
  assert.equal(h.api.snapshot().fidelity, 0.2);
  assert.equal(h.api.forGeneration({ engine: "anima" }).ref_megapixels, 0.5);
  assert.equal(h.persisted().anima_reference.fidelity, 0.2);
  assert.equal(h.api.snapshot().mode, "char");
});

test("middle-area deletion preserves neighbors without touching their images", async () => {
  const h = harness();
  await settle();
  await h.node("Add").fire("click");
  await h.node("Add").fire("click");
  h.api.restore({ ...DEFAULTS, references: [{ image_name: "first.png", strength: 1 }, { image_name: "middle.png", strength: 2 }, { image_name: "last.png", strength: 3 }] });
  assert.equal(h.rowCount(), 3);
  await h.row(1).rowRemove.fire("click");
  assert.equal(h.rowCount(), 2);
  assert.deepEqual(h.api.snapshot().references, [{ image_name: "first.png", strength: 1 }, { image_name: "last.png", strength: 3 }]);
  assert.equal(h.row(1).preview.getAttribute("src"), `/api/anima-reference-image?name=${encodeURIComponent("last.png")}`);
  await h.node("Add").fire("click");
  const ids = [];
  for (let i = 0; i < h.rowCount(); i++) {
    for (const key of ["dropZone", "preview", "empty", "remove", "file", "mode", "strength", "target"]) {
      ids.push(h.row(i)[key].getAttribute("id"));
    }
  }
  assert.equal(new Set(ids).size, ids.length);
  await h.row(2).rowRemove.fire("click");
  await h.row(1).rowRemove.fire("click");
  assert.equal(h.rowCount(), 1);
  assert.deepEqual(h.api.snapshot().references, [{ image_name: "first.png", strength: 1 }]);
  assert.equal(h.row(0).rowRemove.hidden, true);
});

test("a late file event from a removed area cannot replace the first reference", async () => {
  const h = harness();
  await settle();
  h.api.restore({ ...DEFAULTS, enabled: true, references: [
    { image_name: "first.png", strength: 0 }, { image_name: "removed.png", strength: 1 },
  ] });
  const detached = h.row(1).file;
  await h.row(1).rowRemove.fire("click");
  detached.files = [{ type: "image/png", data_url: "data:image/png;base64,WA==" }];
  await detached.fire("change");
  assert.equal(h.calls.filter(call => call.method === "POST").length, 0);
  assert.deepEqual(h.api.snapshot().references, [{ image_name: "first.png", strength: 0 }]);
});

test("per-area uploads change only their own image and invalid files emit no edit", async () => {
  for (const type of ["image/png", "image/jpeg", "image/webp"]) {
    const h = harness();
    await settle();
    await h.node("Add").fire("click");
    h.row(1).file.files = [{ type, data_url: `data:${type};base64,QUJD` }];
    await h.row(1).file.fire("change");
    const posts = h.calls.filter(call => call.method === "POST");
    assert.equal(posts.length, 1);
    assert.equal(posts[0].url, "/api/anima-reference");
    assert.deepEqual(JSON.parse(posts[0].body), { data_url: `data:${type};base64,QUJD` });
    assert.equal(posts[0].headers["Content-Type"], "application/json");
    assert.deepEqual(h.api.snapshot().references.map(r => r.image_name), ["", "snap ref/한 장.png"]);
    assert.equal(h.row(1).preview.getAttribute("src"), "/api/anima-reference-image?name=uploaded");
    assert.equal(h.row(0).preview.getAttribute("src"), null);
    await h.row(1).remove.fire("click");
    assert.deepEqual(h.api.snapshot().references.map(r => r.image_name), ["", ""]);
  }
});

test("in-flight upload locks controls and cannot overwrite a newer restored image", async () => {
  let finish;
  const h = harness(undefined, { upload: () => new Promise(resolve => { finish = resolve; }) });
  await settle();
  h.row(0).file.files = [{ type: "image/png", data_url: "data:image/png;base64,WA==" }];
  const upload = h.row(0).file.fire("change");
  await settle();
  assert.ok(h.controls.every(node => node.disabled));
  assert.equal(h.node("Add").disabled, true);
  assert.equal(h.node("Forecast").disabled, true);
  h.node("Forecast").value = "on";
  await h.node("Forecast").fire("change");
  assert.equal(h.api.snapshot().experimental_forecast, false);
  h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "newer.png", strength: 0 }] });
  finish({ ok: true, json: async () => ({ ok: true, image_name: "stale.png", image_url: "/stale.png" }) });
  await upload;
  assert.deepEqual(h.api.snapshot().references.map(r => r.image_name), ["newer.png"]);
  assert.equal(h.row(0).file.disabled, false);
  assert.equal(h.node("Forecast").disabled, false);
  assert.equal(h.changes.length, 0);
});

test("regional acceleration defaults OFF and selection round-trips persistence and request state", async () => {
  const h = harness();
  await settle();
  assert.ok(html.includes('id="animaReferenceForecast"'));
  assert.ok(html.includes("RAM에 예측 이력을 보관"));
  assert.ok(!html.includes("약 2.3GiB"));
  assert.equal(h.node("Forecast").value, "off");
  assert.equal(h.api.snapshot().experimental_forecast, false);
  h.api.restore({ ...DEFAULTS, enabled: true, future: { keep: true }, references: [
    { image_name: "one.png", strength: 0, target_type: "pose", target_id: "body-a" },
  ] });
  h.node("Forecast").value = "on";
  await h.node("Forecast").fire("change");
  assert.equal(h.api.snapshot().experimental_forecast, true);
  assert.equal(h.persisted().anima_reference.experimental_forecast, true);
  assert.equal(h.api.forGeneration({ engine: "anima" }).experimental_forecast, true);
  assert.equal(h.api.snapshot().references[0].target_id, "body-a");
  assert.deepEqual(plain(h.api.snapshot().future), { keep: true });
  assert.equal(h.changes.length, 1);
  assert.equal(h.savedCount(), 1);
  await h.node("Forecast").fire("change");
  assert.equal(h.changes.length, 1);
  h.api.restore(h.persisted().anima_reference);
  assert.equal(h.node("Forecast").value, "on");
  // A global-only selection retains the preference without rebinding a target.
  h.api.restore({ ...h.api.snapshot(), references: [{ image_name: "one.png", strength: 0 }] });
  assert.equal(h.api.forGeneration({ engine: "anima" }).experimental_forecast, true);
  h.node("Forecast").value = "off";
  await h.node("Forecast").fire("change");
  assert.equal(h.api.snapshot().experimental_forecast, false);
  assert.equal(h.persisted().anima_reference.experimental_forecast, false);
  for (const value of ["true", 1, null]) {
    h.api.restore({ ...DEFAULTS, experimental_forecast: value });
    assert.equal(h.node("Forecast").value, "off");
    assert.equal(h.api.snapshot().experimental_forecast, false);
  }
});

test("regional acceleration cannot be changed when dependencies are unavailable", async () => {
  const h = harness({ experimental: true, ready: false, missing: ["SnapRef"] });
  await settle();
  assert.equal(h.node("Forecast").disabled, true);
  h.node("Forecast").value = "on";
  await h.node("Forecast").fire("change");
  assert.equal(h.api.snapshot().experimental_forecast, false);
  assert.equal(h.changes.length, 0);
});

test("the preview opens the hidden file picker for selection and replacement only when ready", async () => {
  const h = harness();
  await settle();
  assert.equal(h.row(0).file.hidden, true);
  assert.equal(h.node("Status").hidden, true);
  await h.row(0).dropZone.fire("click");
  assert.equal(h.row(0).file.clickCount, 1);
  h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "keep.png", strength: 0 }] });
  assert.equal(h.row(0).dropZone.getAttribute("aria-label"), "레퍼런스 이미지 변경");
  assert.equal(h.row(0).remove.hidden, false);
  await h.row(0).dropZone.fire("click");
  assert.equal(h.row(0).file.clickCount, 2);
  const unavailable = harness({ experimental: true, ready: false, missing: ["SnapRef"] });
  await settle();
  await unavailable.row(0).dropZone.fire("click");
  assert.equal(unavailable.row(0).file.clickCount, 0);
});

test("PNG JPEG and WebP drops route to their own area and preserve reference settings", async () => {
  for (const type of ["image/png", "image/jpeg", "image/webp"]) {
    const h = harness();
    await settle();
    const saved = { ...DEFAULTS, enabled: true, mode: "char", fidelity: 0.3, future: { keep: true }, references: [{ image_name: "first.png", strength: 0.5 }, { image_name: "", strength: -1.2 }] };
    h.api.restore(saved);
    const transfer = { files: [{ type, data_url: `data:${type};base64,QUJD` }], dropEffect: "none" };
    const over = await h.row(1).dropZone.fire("dragover", { dataTransfer: transfer });
    assert.equal(over.defaultPrevented, true);
    assert.equal(transfer.dropEffect, "copy");
    assert.equal(h.row(1).dropZone.classList.contains("is-dragging"), true);
    const drop = await h.row(1).dropZone.fire("drop", { dataTransfer: transfer });
    assert.equal(drop.defaultPrevented, true);
    assert.equal(h.row(1).dropZone.classList.contains("is-dragging"), false);
    const posts = h.calls.filter(call => call.method === "POST");
    assert.equal(posts.length, 1);
    assert.equal(posts[0].url, "/api/anima-reference");
    assert.deepEqual(JSON.parse(posts[0].body), { data_url: `data:${type};base64,QUJD` });
    assert.deepEqual(plain(h.api.snapshot()), { ...saved, references: [{ image_name: "first.png", strength: 0.5 }, { image_name: "snap ref/한 장.png", strength: -1.2 }] });
    assert.equal(h.node("Status").hidden, true);
    await h.row(1).remove.fire("click");
    assert.equal(h.row(1).remove.hidden, true);
    assert.deepEqual(plain(h.api.snapshot()), saved);
  }
});

test("leaving the drop area clears its highlight without uploading or editing", async () => {
  const h = harness();
  await settle();
  await h.row(0).dropZone.fire("dragenter", { dataTransfer: {} });
  assert.equal(h.row(0).dropZone.classList.contains("is-dragging"), true);
  const leave = await h.row(0).dropZone.fire("dragleave");
  assert.equal(leave.defaultPrevented, true);
  assert.equal(h.row(0).dropZone.classList.contains("is-dragging"), false);
  assert.equal(h.calls.filter(call => call.method === "POST").length, 0);
  assert.equal(h.changes.length, 0);
});

test("unsupported drops preserve the previous image and expose the format error", async () => {
  const h = harness();
  await settle();
  const saved = { ...DEFAULTS, enabled: true, mode: "char", references: [{ image_name: "keep.jpg", strength: 0 }] };
  h.api.restore(saved);
  await h.row(0).dropZone.fire("drop", { dataTransfer: { files: [{ type: "text/plain" }] } });
  assert.deepEqual(plain(h.api.snapshot()), saved);
  assert.equal(h.changes.length, 0);
  assert.equal(h.calls.filter(call => call.method === "POST").length, 0);
  assert.equal(h.node("Status").hidden, false);
  assert.match(h.node("Status").textContent, /PNG, JPEG, WebP/);
});

test("concurrent drops are blocked and an older upload cannot replace a newer restored image", async () => {
  let finish;
  const h = harness(undefined, { upload: () => new Promise(resolve => { finish = resolve; }) });
  await settle();
  const transfer = { files: [{ type: "image/png", data_url: "data:image/png;base64,WA==" }] };
  const upload = h.row(0).dropZone.fire("drop", { dataTransfer: transfer });
  await settle();
  assert.ok(h.controls.every(node => node.disabled));
  await h.row(0).dropZone.fire("drop", { dataTransfer: transfer });
  assert.equal(h.calls.filter(call => call.method === "POST").length, 1);
  h.api.restore({ ...DEFAULTS, enabled: true, references: [{ image_name: "newer.jpg", strength: 0 }] });
  finish({ ok: true, json: async () => ({ ok: true, image_name: "older.png" }) });
  await upload;
  assert.deepEqual(h.api.snapshot().references.map(r => r.image_name), ["newer.jpg"]);
  assert.equal(h.changes.length, 0);
});

test("invalid files and removed areas never replace another area image", async () => {
  const h = harness(undefined, {
    upload: async url => ({ ok: false, status: 413 }),
  });
  await settle();
  const saved = { ...DEFAULTS, enabled: true, references: [{ image_name: "previous.png", strength: 0 }, { image_name: "", strength: 0 }] };
  h.api.restore(saved);
  h.row(0).file.files = [{ type: "image/gif", data_url: "data:image/gif;base64,WA==" }];
  await h.row(0).file.fire("change");
  assert.deepEqual(plain(h.api.snapshot()), saved);
  assert.match(h.node("Status").textContent, /PNG, JPEG, WebP/);
  let finish;
  const pending = harness(undefined, { upload: () => new Promise(resolve => { finish = resolve; }) });
  await settle();
  await pending.node("Add").fire("click");
  pending.row(0).file.files = [{ type: "image/png", data_url: "data:image/png;base64,WA==" }];
  const upload = pending.row(0).file.fire("change");
  await settle();
  await pending.row(1).rowRemove.fire("click");
  assert.equal(pending.rowCount(), 2, "area removal stays locked while an upload is in flight");
  finish({ ok: true, json: async () => ({ ok: true, image_name: "stale.png" }) });
  await upload;
  assert.deepEqual(pending.api.snapshot().references.map(r => r.image_name), ["stale.png", ""]);
  assert.equal(pending.changes.length, 2);
});

test("each reference selects and restores stable pose and box targets, including unavailable saved targets", async () => {
  const h = harness();
  await settle();
  h.state.scene_controls = {
    enabled: true,
    toyxyz_enabled: true,
    toyxyz_render_data: JSON.stringify({ region_painter: { bodies: [
      { id: "body-second", name: "두 번째 인물" },
      { id: "body-first", name: "첫 번째 인물" },
    ] } }),
  };
  h.setAnimaRegions({ enabled: true, regions: [{ id: "box-main", label: "character", caption: "상자" }] });
  h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
  h.window.dispatchEvent({ type: "lakis:anima-regions-change" });
  await h.node("Add").fire("click");

  const optionLabels = select => select.children.map(option => option.textContent);
  assert.deepEqual(optionLabels(h.row(0).target), ["전체", "자동 연결 (인물 1)", "3D · 1", "3D · 2", "박스 · 1"]);
  h.row(0).target.value = 'target:["pose",true,"body-first"]';
  await h.row(0).target.fire("change");
  h.row(1).target.value = 'target:["box",true,"box-main"]';
  await h.row(1).target.fire("change");
  assert.deepEqual(plain(h.api.snapshot().references), [
    { image_name: "", strength: 0, target_type: "pose", target_id: "body-first" },
    { image_name: "", strength: 0, target_type: "box", target_id: "box-main" },
  ]);
  assert.equal(h.changes.length, 3);

  h.api.restore({ ...DEFAULTS, references: [{ image_name: "restored.png", strength: 0, target_type: "pose", target_id: "body-first" }] });
  assert.equal(h.row(0).target.value, 'target:["pose",true,"body-first"]');
  h.state.scene_controls.toyxyz_render_data = JSON.stringify({ region_painter: { bodies: [
    { id: "body-first", name: "첫 번째 인물" },
    { id: "body-second", name: "두 번째 인물" },
  ] } });
  h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
  assert.equal(h.row(0).target.value, 'target:["pose",true,"body-first"]');

  h.api.restore({ ...DEFAULTS, references: [
    { image_name: "pose.png", strength: 0, target_type: "pose", target_id: "missing-body", future: "kept" },
    { image_name: "box.png", strength: 0, target_type: "box", target_id: "box-main" },
  ] });
  assert.equal(h.row(0).target.value, 'target:["pose",true,"missing-body"]');
  assert.match(optionLabels(h.row(0).target).at(-1), /사용할 수 없는 대상.*missing-body/);
  assert.equal(h.row(1).target.value, 'target:["box",true,"box-main"]');
  assert.equal(h.api.snapshot().references[0].target_id, "missing-body");
  assert.equal(h.api.snapshot().references[0].future, "kept");

  h.state.scene_controls.toyxyz_render_data = JSON.stringify({ region_painter: { bodies: [
    { id: "body-first", name: "첫 번째 인물" },
    { id: "body-second", name: "두 번째 인물" },
  ] } });
  h.row(0).target.value = "global";
  await h.row(0).target.fire("focus");
  assert.equal(h.row(0).target.value, 'target:["pose",true,"missing-body"]');
  assert.match(optionLabels(h.row(0).target).at(-1), /사용할 수 없는 대상.*missing-body/);
  assert.equal(h.api.snapshot().references[0].target_type, "pose");
  assert.equal(h.api.snapshot().references[0].target_id, "missing-body");
});

test("disabling 3D resets only pose targets in the selector, persisted state and generation request", async () => {
  for (const flags of [
    { enabled: false, toyxyz_enabled: false },
    { enabled: true, toyxyz_enabled: false },
    { enabled: false, toyxyz_enabled: true },
  ]) {
    const h = harness();
    await settle();
    h.state.scene_controls = {
      enabled: true, toyxyz_enabled: true,
      toyxyz_render_data: JSON.stringify({ region_painter: { bodies: [{ id: "body-one" }] } }),
    };
    h.setAnimaRegions({ enabled: true, regions: [{ id: "box-one" }] });
    const original = {
      ...DEFAULTS, enabled: true, mode: "char", fidelity: 0.6, ref_megapixels: 0.25,
      references: [
        { image_name: "pose.png", strength: 1.1, target_type: "pose", target_id: "body-one", future: { keep: true } },
        { image_name: "box.png", strength: 0.7, target_type: "box", target_id: "box-one" },
        { image_name: "global.png", strength: -0.2, target_type: "global" },
      ],
    };
    h.api.restore(original);
    Object.assign(h.state.scene_controls, flags);
    h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
    const expected = { ...original, references: [
      { image_name: "pose.png", strength: 1.1, target_type: "global", future: { keep: true } },
      original.references[1], original.references[2],
    ] };
    assert.equal(h.row(0).target.value, "global");
    assert.equal(h.row(1).target.value, 'target:["box",true,"box-one"]');
    assert.deepEqual(plain(h.api.snapshot()), expected);
    assert.deepEqual(h.persisted().anima_reference, expected);
    assert.deepEqual(plain(h.api.forGeneration({ engine: "anima" })), expected);
    assert.equal(h.savedCount(), 1);
    h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
    Object.assign(h.state.scene_controls, { enabled: true, toyxyz_enabled: true });
    h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
    assert.deepEqual(plain(h.api.snapshot()), expected, "re-enabling must not silently rebind references");
    assert.equal(h.row(0).target.value, "global");
    assert.equal(h.changes.length, 1);
    assert.equal(h.calls.filter(call => call.method === "POST").length, 0);
  }
});

test("disabling boxes resets all box targets without changing active pose references", async () => {
  const h = harness();
  await settle();
  h.state.scene_controls = {
    enabled: true, toyxyz_enabled: true,
    toyxyz_render_data: JSON.stringify({ region_painter: { bodies: [{ id: "body-one" }] } }),
  };
  h.setAnimaRegions({ enabled: true, regions: [{ id: "box-one" }, { id: "box-two" }] });
  const original = { ...DEFAULTS, enabled: true, references: [
    { image_name: "pose.png", strength: 1, target_type: "pose", target_id: "body-one" },
    { image_name: "box1.png", strength: 0.8, target_type: "box", target_id: "box-one" },
    { image_name: "box2.png", strength: 1.2, target_type: "box", target_id: "box-two", future: "keep" },
  ] };
  h.api.restore(original);
  h.setAnimaRegions({ enabled: false, regions: [{ id: "box-one" }, { id: "box-two" }] });
  h.window.dispatchEvent({ type: "lakis:anima-regions-change" });
  const expected = { ...original, references: [
    original.references[0],
    { image_name: "box1.png", strength: 0.8, target_type: "global" },
    { image_name: "box2.png", strength: 1.2, target_type: "global", future: "keep" },
  ] };
  assert.equal(h.row(0).target.value, 'target:["pose",true,"body-one"]');
  assert.equal(h.row(1).target.value, "global");
  assert.equal(h.row(2).target.value, "global");
  assert.deepEqual(h.persisted().anima_reference, expected);
  assert.deepEqual(plain(h.api.forGeneration({ engine: "anima" })), expected);
  h.setAnimaRegions({ enabled: true, regions: [{ id: "box-one" }, { id: "box-two" }] });
  h.window.dispatchEvent({ type: "lakis:anima-regions-change" });
  assert.deepEqual(plain(h.api.snapshot()), expected);
  assert.equal(h.changes.length, 1);
});

test("turning both target sources off leaves only global references and removes stale IDs", async () => {
  const h = harness();
  await settle();
  h.state.scene_controls = { enabled: true, toyxyz_enabled: true };
  h.setAnimaRegions({ enabled: true, regions: [{ id: "box-one" }] });
  h.api.restore({ ...DEFAULTS, enabled: true, references: [
    { image_name: "pose.png", strength: 1, target_type: "pose", target_id: "body-one" },
    { image_name: "box.png", strength: 1, target_type: "box", target_id: "box-one" },
  ] });
  h.state.scene_controls.toyxyz_enabled = false;
  h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
  h.setAnimaRegions({ enabled: false, regions: [{ id: "box-one" }] });
  h.window.dispatchEvent({ type: "lakis:anima-regions-change" });
  const expected = [
    { image_name: "pose.png", strength: 1, target_type: "global" },
    { image_name: "box.png", strength: 1, target_type: "global" },
  ];
  assert.deepEqual(plain(h.api.forGeneration({ engine: "anima" }).references), expected);
  assert.deepEqual(h.persisted().anima_reference.references, expected);
  assert.equal(h.changes.length, 2);
});

test("turning 3D off during an upload does not restore the stale pose target on completion", async () => {
  let finish;
  const h = harness(undefined, { upload: () => new Promise(resolve => { finish = resolve; }) });
  await settle();
  h.state.scene_controls = { enabled: true, toyxyz_enabled: true };
  h.api.restore({ ...DEFAULTS, enabled: true, references: [
    { image_name: "before.png", strength: 1.1, target_type: "pose", target_id: "body-one" },
  ] });
  h.row(0).file.files = [{ type: "image/png", data_url: "data:image/png;base64,AQ==" }];
  const upload = h.row(0).file.fire("change");
  await settle();
  h.state.scene_controls.toyxyz_enabled = false;
  h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
  assert.equal(h.row(0).target.value, "global");
  finish({ ok: true, json: async () => ({ ok: true, image_name: "after.png" }) });
  await upload;
  const expected = [{ image_name: "after.png", strength: 1.1, target_type: "global" }];
  assert.deepEqual(plain(h.api.snapshot().references), expected);
  assert.deepEqual(h.persisted().anima_reference.references, expected);
  assert.deepEqual(plain(h.api.forGeneration({ engine: "anima" }).references), expected);
});

test("target choices refresh only from scene and box changes or selector focus; absent targets stay global", async () => {
  const h = harness();
  await settle();
  assert.equal(h.row(0).target.value, "global");
  assert.deepEqual(plain(h.api.snapshot().references[0]), { image_name: "", strength: 0 });
  h.state.scene_controls = {
    enabled: false, toyxyz_enabled: false,
    toyxyz_render_data: JSON.stringify({ region_painter: { bodies: [{ id: "off-body", name: "꺼진 인물" }] } }),
  };
  h.setAnimaRegions({ enabled: true, regions: [{ id: "box-one", label: "character", caption: "박스 1" }] });
  h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
  assert.deepEqual(h.row(0).target.children.map(option => option.textContent), ["전체", "자동 연결 (인물 1)", "박스 · 1"]);
  h.state.scene_controls = {
    enabled: true, toyxyz_enabled: true,
    toyxyz_render_data: JSON.stringify({ region_painter: { bodies: [{ id: "body-one", name: "인물 1" }] } }),
  };
  h.row(0).target.value = "global";
  await h.row(0).target.fire("focus");
  assert.deepEqual(h.row(0).target.children.map(option => option.textContent), ["전체", "자동 연결 (인물 1)", "3D · 1", "박스 · 1"]);
  assert.equal(h.api.snapshot().references[0].target_type, undefined);
  h.row(0).target.value = 'target:["pose",true,"body-one"]';
  await h.row(0).target.fire("change");
  assert.deepEqual(plain(h.api.snapshot().references[0]), { image_name: "", strength: 0, target_type: "pose", target_id: "body-one" });
  h.row(0).target.value = "global";
  await h.row(0).target.fire("change");
  assert.deepEqual(plain(h.api.snapshot().references[0]), { image_name: "", strength: 0, target_type: "global" });
});

test("numbered connection binds each reference to its corresponding pose ID and persists the generation targets", async () => {
  const h = harness();
  await settle();
  const ids = ["body-c", "body-a", "body-b"];
  h.state.scene_controls = {
    enabled: true, toyxyz_enabled: true,
    toyxyz_render_data: JSON.stringify({ region_painter: { bodies: ids.map((id, index) => ({ id, name: `인물 ${index + 1}` })) } }),
  };
  const saved = { ...DEFAULTS, enabled: true, mode: "char", references: ids.map((id, index) => ({
    image_name: `reference-${index + 1}.png`, strength: index - 1, future: { keep: id },
  })) };
  h.api.restore(saved);
  for (let index = 0; index < ids.length; index += 1) {
    const automatic = h.row(index).target.children.find(option => option.value === "auto_pose");
    assert.equal(automatic.disabled, false);
    assert.equal(automatic.textContent, `자동 연결 (인물 ${index + 1})`);
    h.row(index).target.value = "auto_pose";
    await h.row(index).target.fire("change");
    assert.equal(h.row(index).target.value, `target:["pose",true,"${ids[index]}"]`);
  }
  const expected = { ...saved, references: saved.references.map((entry, index) => ({
    ...entry, target_type: "pose", target_id: ids[index],
  })) };
  assert.deepEqual(plain(h.api.snapshot()), expected);
  assert.deepEqual(h.persisted().anima_reference, expected);
  assert.deepEqual(plain(h.api.forGeneration({ engine: "anima" })), expected);
  assert.equal(h.changes.length, 3);
  assert.equal(h.calls.filter(call => call.method === "POST").length, 0);
});

test("numbered bindings survive pose reorder, deleted people, reference removal and restore without rebinding", async () => {
  const h = harness();
  await settle();
  let bodies = [{ id: "body-a" }, { id: "body-b" }, { id: "body-c" }];
  const updateScene = () => {
    h.state.scene_controls = {
      enabled: true, toyxyz_enabled: true,
      toyxyz_render_data: JSON.stringify({ region_painter: { bodies } }),
    };
    h.window.dispatchEvent({ type: "lakis:scene-controls-change" });
  };
  updateScene();
  h.api.restore({ ...DEFAULTS, enabled: true, references: bodies.map((_, index) => ({
    image_name: `reference-${index + 1}.png`, strength: 0,
  })) });
  for (let index = 0; index < bodies.length; index += 1) {
    h.row(index).target.value = "auto_pose";
    await h.row(index).target.fire("change");
  }
  const saved = plain(h.api.snapshot());
  bodies = [bodies[2], bodies[0], bodies[1]];
  updateScene();
  assert.deepEqual(plain(h.api.snapshot()), saved);
  assert.equal(h.changes.length, 3);
  bodies = bodies.filter(body => body.id !== "body-a");
  updateScene();
  assert.deepEqual(plain(h.api.forGeneration({ engine: "anima" })), saved);
  assert.equal(h.row(0).target.value, 'target:["pose",true,"body-a"]');
  assert.equal(h.row(0).target.children.at(-1).disabled, true);
  assert.match(h.row(0).target.children.at(-1).textContent, /사용할 수 없는 대상.*body-a/);
  await h.row(1).rowRemove.fire("click");
  assert.deepEqual(h.api.snapshot().references.map(entry => entry.target_id), ["body-a", "body-c"]);
  h.api.restore(saved);
  assert.deepEqual(plain(h.api.snapshot()), saved);
  h.row(0).target.value = "global";
  await h.row(0).target.fire("change");
  assert.equal(h.api.snapshot().references[0].target_type, "global");
  assert.equal("target_id" in h.api.snapshot().references[0], false);
  h.row(1).target.value = 'target:["pose",true,"body-c"]';
  await h.row(1).target.fire("change");
  assert.equal(h.api.snapshot().references[1].target_id, "body-c");
});

test("unavailable numbered connections never compact person indices or overwrite an existing target", async () => {
  const scenes = [
    { enabled: false, toyxyz_enabled: false, bodies: [{ id: "body-a" }, { id: "body-b" }] },
    { enabled: true, toyxyz_enabled: true, bodies: [{ id: "body-a" }] },
    { enabled: true, toyxyz_enabled: true, bodies: [{ id: "body-a" }, { id: "" }, { id: "body-c" }] },
    { enabled: true, toyxyz_enabled: true, render: "not-json" },
  ];
  for (const scene of scenes) {
    const h = harness();
    await settle();
    h.state.scene_controls = {
      enabled: scene.enabled, toyxyz_enabled: scene.toyxyz_enabled,
      toyxyz_render_data: scene.render || JSON.stringify({ region_painter: { bodies: scene.bodies } }),
    };
    h.api.restore({ ...DEFAULTS, references: [
      { image_name: "", strength: 0 },
      { image_name: "reference.png", strength: 1, target_type: "pose", target_id: "saved-body" },
    ] });
    const before = plain(h.api.snapshot());
    const automatic = h.row(1).target.children.find(option => option.value === "auto_pose");
    assert.equal(automatic.disabled, true);
    h.row(1).target.value = "auto_pose";
    await h.row(1).target.fire("change");
    assert.deepEqual(plain(h.api.snapshot()), before);
    assert.equal(h.row(1).target.value, 'target:["pose",true,"saved-body"]');
    assert.match(h.node("Status").textContent, /참조 2.*3D 인물 2.*편집기/);
    assert.equal(h.node("Status").hidden, false);
    assert.equal(h.changes.length, 0);
  }
});
