// SPDX-FileCopyrightText: 2026 灰暗x
// SPDX-FileCopyrightText: 2026 Luke Jeong
// SPDX-License-Identifier: AGPL-3.0-or-later
// LAKIS Light Control - LightMap v0.3.19
// Mouse/orbit interaction adapted from the existing LAKIS camera-style light controller.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const LIGHT_NODE_TYPE = "LAKIS_LightControl";
const EXECUTION_SETTINGS_NODE_TYPE = "LAKIS_ExecutionSettings";
const DEFAULT_PRODUCTION_FINAL_NODE_ID = "775";

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, Number(v) || 0));
const fmt = (v) => (Math.round(Number(v) * 100) / 100).toFixed(2);

function findWidget(node, name) {
  return node?.widgets?.find((w) => w?.name === name) || null;
}
function setWidget(node, name, value) {
  const w = findWidget(node, name);
  if (!w) return;
  w.value = value;
  try { w.callback?.(value); } catch {}
  node.graph?.setDirtyCanvas?.(true, true);
}
function getWidgetValue(node, name, fallback) {
  const w = findWidget(node, name);
  return w?.value ?? fallback;
}

function graphNodes(graph) {
  if (!graph) return [];
  if (Array.isArray(graph._nodes)) return graph._nodes.filter(Boolean);
  if (graph._nodes_by_id) return Object.values(graph._nodes_by_id).filter(Boolean);
  return [];
}

function nestedGraphsFromNode(node) {
  const result = [];
  for (const key of ["subgraph", "graph", "innerGraph", "_graph"]) {
    const g = node?.[key];
    if (g && (Array.isArray(g._nodes) || g._nodes_by_id)) result.push(g);
  }
  return result;
}

function allGraphNodesDeep() {
  const out = [];
  const seenGraphs = new Set();
  const queue = [app.graph];

  while (queue.length) {
    const graph = queue.shift();
    if (!graph || seenGraphs.has(graph)) continue;
    seenGraphs.add(graph);

    for (const n of graphNodes(graph)) {
      out.push(n);
      for (const child of nestedGraphsFromNode(n)) queue.push(child);
    }
  }
  return out;
}

function widgetName(widget) {
  return String(widget?.name ?? widget?.label ?? "");
}

function normalizeWidgetName(name) {
  return String(name ?? "").trim().toLowerCase();
}

function isSeedWidgetName(name) {
  const n = normalizeWidgetName(name);
  return n === "seed" || n.endsWith(".seed") || n.includes(" seed");
}

function seedBindingFromNode(node) {
  if (!node) return null;

  // Direct Seed (rgthree) node.
  const direct = (node.widgets || []).find((w) => isSeedWidgetName(widgetName(w)));
  const type = String(node?.comfyClass ?? node?.type ?? node?.title ?? "");
  if (direct && type.includes("Seed (rgthree)")) {
    return {node, widget: direct, kind:"direct"};
  }

  // Subgraph promoted/proxy seed.  In this workflow the checkpoint-loader
  // exposes inner node 1864 / widget "seed".  Runtime widget naming differs
  // between ComfyUI frontend revisions, so first match by name, then use the
  // proxyWidgets array index as a guarded fallback.
  const proxy = Array.isArray(node?.properties?.proxyWidgets)
    ? node.properties.proxyWidgets
    : null;

  if (proxy) {
    const seedProxyIndex = proxy.findIndex((entry) =>
      Array.isArray(entry) &&
      String(entry[1] ?? "").toLowerCase() === "seed"
    );

    if (seedProxyIndex >= 0) {
      let widget = (node.widgets || []).find((w) => isSeedWidgetName(widgetName(w)));

      if (!widget) {
        const candidate = node.widgets?.[seedProxyIndex];
        if (candidate && !String(widgetName(candidate)).includes("Randomize")) {
          widget = candidate;
        }
      }

      if (widget) return {node, widget, kind:"subgraph-proxy"};
    }
  }

  return null;
}

function findSeedBinding() {
  const nodes = allGraphNodesDeep();

  // Prefer the checkpoint-loader subgraph proxy, because that is the actual
  // seed value serialized by the outer workflow.
  for (const n of nodes) {
    const proxy = Array.isArray(n?.properties?.proxyWidgets)
      ? n.properties.proxyWidgets
      : [];
    const hasSeedProxy = proxy.some((entry) =>
      Array.isArray(entry) &&
      String(entry[1] ?? "").toLowerCase() === "seed"
    );
    if (hasSeedProxy) {
      const binding = seedBindingFromNode(n);
      if (binding) return binding;
    }
  }

  for (const n of nodes) {
    const binding = seedBindingFromNode(n);
    if (binding) return binding;
  }

  return null;
}

function setSeedBinding(binding, seed) {
  if (!binding?.widget) return false;
  const value = Math.max(0, Math.floor(Number(seed)));

  try {
    binding.widget.value = value;
    binding.widget.callback?.(value, binding.node, binding.widget);
    binding.node?.graph?.setDirtyCanvas?.(true, true);
    return Number(binding.widget.value) === value;
  } catch (e) {
    console.warn("[LAKIS] seed write failed", e);
    return false;
  }
}

function randomConcreteSeed() {
  // rgthree's default max is 2^50.  Generate safely inside Number's exact
  // integer range without using the special negative seed values.
  const MAX = 1125899906842624n;
  try {
    const data = new Uint32Array(2);
    crypto.getRandomValues(data);
    const raw = (BigInt(data[0]) << 32n) | BigInt(data[1]);
    return Number(raw % MAX);
  } catch {
    return Math.floor(Math.random() * Number(MAX));
  }
}

function lightControllerNodes() {
  return allGraphNodesDeep().filter((n) =>
    String(n?.comfyClass ?? n?.type ?? "") === LIGHT_NODE_TYPE
  );
}

function primaryLightController() {
  return lightControllerNodes()[0] || null;
}

function currentConcreteSeed(binding) {
  const value = Number(binding?.widget?.value);
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
}

function updateModeStatus(node, text, ok=true) {
  if (!node) return;
  node.__lakisExecutionStatusText = text;
  node.__lakisExecutionStatusOk = !!ok;
  try { node.__lakisRefreshExecutionStatus?.(); } catch {}
}

function applyExecutionMode(mode, lightNode=null) {
  const controller = lightNode || primaryLightController();
  if (!controller) return {ok:false, message:"광원 제어 노드를 찾지 못함"};

  controller.properties ||= {};
  controller.properties.lakis_execution_mode = mode === "light" ? "light" : "new";

  const binding = findSeedBinding();
  if (!binding) {
    const result = {ok:false, message:"Seed 제어 입력을 찾지 못함"};
    updateModeStatus(controller, result.message, false);
    return result;
  }

  if (mode === "light") {
    // If a queue has already run in LAKIS new-image mode, this is the exact
    // concrete seed that produced the visible image.
    let seed = Number(controller.properties.lakis_last_generation_seed);
    if (!Number.isFinite(seed) || seed < 0) {
      seed = currentConcreteSeed(binding);
    }

    if (Number.isFinite(seed) && seed >= 0) {
      seed = Math.floor(seed);
      controller.properties.lakis_last_generation_seed = seed;
      const ok = setSeedBinding(binding, seed);
      const result = {
        ok,
        message: ok ? `이미지 고정 · Seed ${seed}` : "Seed 고정 실패",
      };
      updateModeStatus(controller, result.message, ok);
      return result;
    }

    // If the workflow was just loaded with rgthree -1 and there is no previous
    // concrete LAKIS seed yet, allocate one now. The next queue creates exactly
    // one source image; subsequent light-only queues reuse it.
    seed = randomConcreteSeed();
    controller.properties.lakis_last_generation_seed = seed;
    const ok = setSeedBinding(binding, seed);
    const result = {
      ok,
      message: ok ? `첫 이미지 고정 준비 · Seed ${seed}` : "Seed 준비 실패",
    };
    updateModeStatus(controller, result.message, ok);
    return result;
  }

  const result = {ok:true, message:"다음 실행마다 새 Seed"};
  updateModeStatus(controller, result.message, true);
  return result;
}

function prepareLakisSeedForQueue() {
  const controller = primaryLightController();
  if (!controller) return;

  controller.properties ||= {};
  const mode = controller.properties.lakis_execution_mode === "light" ? "light" : "new";
  const binding = findSeedBinding();

  if (!binding) {
    updateModeStatus(controller, "Queue: Seed 입력을 찾지 못함", false);
    return;
  }

  if (mode === "new") {
    const seed = randomConcreteSeed();
    controller.properties.lakis_last_generation_seed = seed;
    const ok = setSeedBinding(binding, seed);
    updateModeStatus(
      controller,
      ok ? `새 이미지 · Seed ${seed}` : "새 Seed 쓰기 실패",
      ok,
    );
    return;
  }

  let seed = Number(controller.properties.lakis_last_generation_seed);
  if (!Number.isFinite(seed) || seed < 0) {
    seed = currentConcreteSeed(binding);
  }
  if (!Number.isFinite(seed) || seed < 0) {
    seed = randomConcreteSeed();
  }

  seed = Math.floor(seed);
  controller.properties.lakis_last_generation_seed = seed;
  const ok = setSeedBinding(binding, seed);
  updateModeStatus(
    controller,
    ok ? `조명만 갱신 · Seed ${seed}` : "고정 Seed 쓰기 실패",
    ok,
  );
}

const LAKIS_QUEUE_WRAP = Symbol.for("LAKIS.LightControl.QueueWrap.v036");
const LAKIS_API_QUEUE_WRAP = Symbol.for("LAKIS.ExecutionSettings.ApiQueueWrap.v039");

function workflowExecutionSettings(promptEnvelope) {
  const direct = promptEnvelope?.lakis_execution_settings;
  if (direct && typeof direct.debug_outputs_enabled === "boolean") {
    return {debug_outputs_enabled: direct.debug_outputs_enabled, source: "bridge"};
  }

  const workflow = promptEnvelope?.workflow;
  const node = workflow?.nodes?.find?.((candidate) =>
    String(candidate?.type ?? candidate?.comfyClass ?? "") === EXECUTION_SETTINGS_NODE_TYPE
  );
  if (node) {
    return {debug_outputs_enabled: Boolean(node.widgets_values?.[0]), source: "workflow-node"};
  }

  const saved = workflow?.extra?.lakis_execution_settings;
  if (saved && typeof saved.debug_outputs_enabled === "boolean") {
    return {debug_outputs_enabled: saved.debug_outputs_enabled, source: "workflow-metadata"};
  }
  // Legacy workflows keep their historical scheduling behavior.
  return null;
}

function apiNodeDependencies(output, nodeId) {
  const node = output?.[nodeId];
  if (!node) return [];
  const inputs = node.inputs || {};
  if (node.class_type === "LAKIS_ShadowCleanupSwitch" && inputs.cleanup_enabled === false) {
    const image = inputs.image;
    return Array.isArray(image) && image.length === 2 ? [String(image[0])] : [];
  }
  return Object.values(inputs)
    .filter((value) => Array.isArray(value) && value.length === 2 && output[String(value[0])])
    .map((value) => String(value[0]));
}

function finalOnlyOutput(output, rootId) {
  if (!output?.[rootId]) throw new Error(`[LAKIS] production Final Saver ${rootId} is missing`);
  const retained = new Set();
  const pending = [rootId];
  while (pending.length) {
    const nodeId = pending.pop();
    if (retained.has(nodeId)) continue;
    retained.add(nodeId);
    pending.push(...apiNodeDependencies(output, nodeId));
  }

  const result = {};
  for (const nodeId of retained) result[nodeId] = structuredClone(output[nodeId]);
  for (const node of Object.values(result)) {
    if (node?.class_type !== "LAKIS_ShadowCleanupSwitch" || node.inputs?.cleanup_enabled !== false) continue;
    delete node.inputs.cleanup_image;
    delete node.inputs.old_shadow_mask;
    delete node.inputs.semantic_shadow_preview;
  }
  return result;
}

function applyLakisExecutionPolicy(promptEnvelope) {
  const settings = workflowExecutionSettings(promptEnvelope);
  if (!settings || settings.debug_outputs_enabled) return promptEnvelope;
  const rootId = String(
    promptEnvelope?.workflow?.extra?.lakis_execution_settings?.production_final_output_node_id
      ?? DEFAULT_PRODUCTION_FINAL_NODE_ID
  );
  promptEnvelope.output = finalOnlyOutput(promptEnvelope.output, rootId);
  console.info(`[LAKIS] production execution: Final Saver ${rootId} dependency graph (${Object.keys(promptEnvelope.output).length} nodes)`);
  return promptEnvelope;
}

function ensureApiQueueWrapper() {
  const current = api.queuePrompt;
  if (typeof current !== "function") return false;
  if (current[LAKIS_API_QUEUE_WRAP]) return true;
  const wrapped = async function(index, prompt, ...args) {
    applyLakisExecutionPolicy(prompt);
    return await current.apply(this, [index, prompt, ...args]);
  };
  Object.defineProperty(wrapped, LAKIS_API_QUEUE_WRAP, {value: true});
  wrapped.__lakisOriginalApiQueuePrompt = current;
  api.queuePrompt = wrapped;
  return true;
}

function ensureQueueWrapper() {
  const current = app.queuePrompt;
  if (typeof current !== "function") return false;
  if (current[LAKIS_QUEUE_WRAP]) return true;

  const wrapped = async function(...args) {
    // This happens before ComfyUI serializes/queues the workflow, so the
    // sampler receives the intended concrete seed.
    prepareLakisSeedForQueue();
    return await current.apply(this, args);
  };

  try {
    Object.defineProperty(wrapped, LAKIS_QUEUE_WRAP, {
      value: true,
      configurable: false,
      enumerable: false,
    });
  } catch {
    wrapped[LAKIS_QUEUE_WRAP] = true;
  }

  wrapped.__lakisOriginalQueuePrompt = current;
  app.queuePrompt = wrapped;
  return true;
}

function hideWidget(widget) {
  if (!widget || widget.__lakisHidden) return;
  widget.__lakisHidden = true;
  widget.__lakisOriginalType = widget.type;
  widget.__lakisOriginalComputeSize = widget.computeSize;
  widget.__lakisOriginalDraw = widget.draw;

  // Node 2.0 can still render a "converted-widget" combo row.  Keep the
  // serializable widget itself, but make both legacy-canvas and DOM renderers
  // treat it as hidden.
  widget.hidden = true;
  widget.type = "hidden";
  widget.computeSize = () => [0, 0];
  widget.draw = () => {};

  for (const el of [widget.inputEl, widget.element, widget.el]) {
    if (el?.style) {
      el.style.display = "none";
      el.style.height = "0px";
      el.style.minHeight = "0px";
      el.style.margin = "0";
      el.style.padding = "0";
    }
  }
}

function makeSlider(node, root, def, onChange) {
  const row = document.createElement("div");
  row.className = "lakis-light-slider-row";

  const label = document.createElement("span");
  label.textContent = def.label;

  const range = document.createElement("input");
  range.type = "range";
  range.min = String(def.min);
  range.max = String(def.max);
  range.step = String(def.step);

  const number = document.createElement("input");
  number.type = "number";
  number.min = String(def.min);
  number.max = String(def.max);
  number.step = String(def.step);

  const sync = () => {
    const v = Number(getWidgetValue(node, def.name, def.default ?? 0));
    range.value = String(v);
    number.value = fmt(v);
  };

  const apply = (v) => {
    const next = clamp(v, def.min, def.max);
    setWidget(node, def.name, next);
    sync();
    onChange?.();
  };

  range.addEventListener("input", () => apply(range.value));
  number.addEventListener("change", () => apply(number.value));
  number.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      apply(number.value);
      number.blur();
    }
  });

  row.append(label, range, number);
  root.appendChild(row);
  sync();
  return { sync };
}

function lightVector(posX, posY) {
  const az = clamp(posX, -1, 1) * Math.PI;
  const el = clamp(posY, -1, 1) * Math.PI / 2;
  const h = Math.cos(el);
  const x = -Math.sin(az) * h;
  const y = Math.sin(el);
  const z = Math.cos(az) * h;
  const len = Math.hypot(x, y, z) || 1;
  return [x / len, y / len, z / len];
}

function installLightUI(node) {
  if (!node || node.__lakisLightMapInstalled) return;
  node.__lakisLightMapInstalled = true;
  node.properties ||= {};

  [
    "enabled", "pos_x", "pos_y", "pos_z",
    "intensity", "ambient", "shadow", "exposure", "rim", "color_mode"
  ].forEach((name) => hideWidget(findWidget(node, name)));

  const root = document.createElement("div");
  root.className = "lakis-light-root";
  root.innerHTML = `
    <style>
      .lakis-light-root{box-sizing:border-box;width:100%;padding:8px 10px 12px;color:#dce6ef;font:13px system-ui,sans-serif;user-select:none;position:relative;z-index:2}
      .lakis-light-toolbar{display:grid;grid-template-columns:auto minmax(210px,1fr);gap:7px;align-items:center;margin:0 0 8px}
      .lakis-light-toolbar button,.lakis-light-toolbar select{height:30px;min-width:0;border:1px solid #526171;border-radius:6px;background:#283342;color:#e6edf4;padding:0 10px;box-sizing:border-box}
      .lakis-light-toolbar button:hover{background:#354356}
      .lakis-light-mode{display:grid;grid-template-columns:92px minmax(180px,1fr) auto;gap:8px;align-items:center;padding:8px 10px;border:1px solid #43586b;border-radius:7px;background:#202a35;margin:7px 0}.lakis-light-mode select{height:30px;min-width:0;border:1px solid #526171;border-radius:6px;background:#171d25;color:#edf2f7;padding:0 8px}.lakis-light-mode-status{font:11px Consolas,monospace;color:#72d79a;white-space:nowrap}.lakis-light-switch{display:flex;align-items:center;gap:9px;padding:8px 10px;border:1px solid #43586b;border-radius:7px;background:#202a35;margin:7px 0}
      .lakis-light-switch span:first-of-type{font-weight:650;flex:1}
      .lakis-light-status{font:12px Consolas,monospace;color:#72d79a}
      .lakis-light-stage{position:relative;width:100%;margin:10px 0 8px}
      .lakis-light-stage canvas{display:block;width:100%;height:auto;aspect-ratio:14/9;background:#171b20;border:1px solid #414955;border-radius:8px;cursor:crosshair;touch-action:none;user-select:none;box-sizing:border-box}
      .lakis-light-help{position:absolute;left:11px;top:9px;color:#9eacb9;font-size:12px;pointer-events:none}
      .lakis-light-readout{position:absolute;right:11px;top:9px;color:#ffc16d;font:12px Consolas,monospace;pointer-events:none}
      .lakis-light-slider-row{display:grid;grid-template-columns:92px minmax(120px,1fr) 88px;gap:8px;align-items:center;margin:6px 0}
      .lakis-light-slider-row input[type=range]{width:100%;accent-color:#ffd36a}
      .lakis-light-slider-row input[type=number],.lakis-light-color{height:30px;border:1px solid #445364;border-radius:6px;background:#171d25;color:#edf2f7;padding:0 8px;box-sizing:border-box}
      .lakis-light-color-row{display:grid;grid-template-columns:92px 1fr;gap:8px;align-items:center;margin:8px 0}
      .lakis-light-color{width:100%}
      .lakis-light-data{margin-top:8px;border:1px solid #43505d;border-radius:7px;background:#151b21;padding:9px 10px;color:#a9d9ff;font:12px Consolas,monospace;line-height:1.55}
      .lakis-light-caption{font-size:11px;color:#82909d;margin-top:7px}
    </style>

    <div class="lakis-light-toolbar">
      <button type="button" data-act="reset">초기화</button>
      <select data-role="preset">
        <option value="">프리셋 불러오기</option>
        <option value="front">정면광 · vector (0, 0, +1)</option>
        <option value="left">좌측광 · vector (-1, 0, 0)</option>
        <option value="right">우측광 · vector (+1, 0, 0)</option>
        <option value="back">후면광 · vector (0, 0, -1)</option>
        <option value="top">상부광 · vector (0, +1, 0)</option>
        <option value="bottom">하부광 · vector (0, -1, 0)</option>
        <option value="neon">네온</option>
      </select>
    </div>

    <div class="lakis-light-mode">
      <span>실행 모드</span>
      <select data-role="execution-mode">
        <option value="new">새 이미지 생성</option>
        <option value="light">조명만 갱신</option>
      </select>
      <span class="lakis-light-mode-status" data-role="execution-status"></span>
    </div>

    <label class="lakis-light-switch">
      <input type="checkbox" data-role="enabled">
      <span>광원 사용</span>
      <span class="lakis-light-status" data-role="enabled-status">ON</span>
    </label>

    <div class="lakis-light-stage">
      <canvas data-role="canvas"></canvas>
      <div class="lakis-light-help">좌드래그: 광원 · 우드래그/Alt: 보기 회전 · 휠: 거리 · 더블클릭: 방향 초기화</div>
      <div class="lakis-light-readout" data-role="readout"></div>
    </div>

    <div data-role="sliders"></div>
    <div class="lakis-light-color-row"><span>광원 색상</span><select class="lakis-light-color" data-role="color"></select></div>
    <div class="lakis-light-data" data-role="vector"></div>
    <div class="lakis-light-caption">
      프롬프트를 생성하지 않습니다. LIGHT 출력 → LAKIS Relight (LightMap)에 연결하세요.
    </div>
  `;

  const domWidget = node.addDOMWidget("light_ui", "div", root, {
    serialize: false,
    hideOnZoom: false,
  });
  // IMPORTANT: do NOT reorder node.widgets.
  // ComfyUI restores widgets_values by widget-array order. Moving this DOM widget
  // in front of backend widgets shifts enabled/X/Y/Z/intensity/... on workflow load.
  // Native backend widgets are hidden in-place; the LAKIS DOM widget stays appended.
  domWidget.computeSize = (width) => [
    Math.max(620, width || 620),
    Math.max(520, root.scrollHeight + 8),
  ];

  const executionMode = root.querySelector('[data-role="execution-mode"]');
  const executionStatus = root.querySelector('[data-role="execution-status"]');
  const enabledBox = root.querySelector('[data-role="enabled"]');
  const enabledStatus = root.querySelector('[data-role="enabled-status"]');
  const preset = root.querySelector('[data-role="preset"]');
  const color = root.querySelector('[data-role="color"]');
  const vectorBox = root.querySelector('[data-role="vector"]');
  const readout = root.querySelector('[data-role="readout"]');
  const canvas = root.querySelector('[data-role="canvas"]');
  const slidersRoot = root.querySelector('[data-role="sliders"]');

  const colorOptions = ["Neutral","Warm","Cool","Cyan","Magenta","Cyan + Magenta","Golden","Moonlight"];
  for (const item of colorOptions) {
    const opt = document.createElement("option");
    opt.value = item;
    opt.textContent = item;
    color.appendChild(opt);
  }

  const controls = {};
  const sliderDefs = [
    {name:"pos_x", label:"좌우 (X)", min:-1, max:1, step:0.01, default:0},
    {name:"pos_y", label:"상하 (Y)", min:-1, max:1, step:0.01, default:0},
    {name:"pos_z", label:"거리 (Z)", min:-1, max:1, step:0.01, default:0.1},
    {name:"intensity", label:"광량", min:0, max:2, step:0.01, default:0.8},
    {name:"ambient", label:"주변광", min:0, max:1, step:0.01, default:0.2},
    {name:"shadow", label:"암부 강도", min:0, max:1, step:0.01, default:0.65},
    {name:"exposure", label:"노출", min:-1, max:1, step:0.01, default:0},
    {name:"rim", label:"림라이트", min:0, max:1, step:0.01, default:0.1},
  ];

  const WIDTH = 560;
  const HEIGHT = 360;
  const WHEEL_STEP = 0.0003;

  const savedView = node.properties.lakis_light_preview_view || {};
  let viewYaw = Number.isFinite(Number(savedView.yaw)) ? Number(savedView.yaw) : 0;
  let viewPitch = Number.isFinite(Number(savedView.pitch))
    ? clamp(Number(savedView.pitch), 0.12, 1.15)
    : 0.42;

  let stopped = false;
  let raf = 0;
  let dragging = null;

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = WIDTH * dpr;
  canvas.height = HEIGHT * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  function project(x, y, z) {
    const cosine = Math.cos(viewYaw);
    const sine = Math.sin(viewYaw);
    const horizontal = x * cosine + z * sine;
    const depth = -x * sine + z * cosine;
    const scale = 78;
    return {
      x: WIDTH / 2 + horizontal * scale,
      y: HEIGHT / 2 - (y - 0.7) * scale * Math.cos(viewPitch) + depth * scale * Math.sin(viewPitch),
      depth,
    };
  }

  function ellipse(radius, elevation, stroke, dashed = true) {
    ctx.beginPath();
    for (let i = 0; i <= 80; i++) {
      const a = i / 80 * Math.PI * 2;
      const p = project(radius * Math.sin(a), elevation, radius * Math.cos(a));
      if (i) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y);
    }
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.8;
    ctx.setLineDash(dashed ? [5,7] : []);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function verticalOrbit(radius, azimuth, stroke) {
    ctx.beginPath();
    for (let i = 0; i <= 80; i++) {
      const a = i / 80 * Math.PI * 2;
      const horizontal = radius * Math.cos(a);
      const p = project(
        horizontal * Math.sin(azimuth),
        0.7 + radius * Math.sin(a),
        horizontal * Math.cos(azimuth),
      );
      if (i) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y);
    }
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.8;
    ctx.setLineDash([5,7]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function elevationOrbit(radius, elevation, stroke) {
    const horizontal = radius * Math.cos(elevation);
    const height = 0.7 + radius * Math.sin(elevation);
    ctx.beginPath();
    for (let i = 0; i <= 80; i++) {
      const a = i / 80 * Math.PI * 2;
      const p = project(horizontal * Math.sin(a), height, horizontal * Math.cos(a));
      if (i) ctx.lineTo(p.x, p.y); else ctx.moveTo(p.x, p.y);
    }
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.4;
    ctx.setLineDash([3,7]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function point3d(x, y, z, label) {
    const p = project(x, y, z);
    ctx.fillStyle = "#75d9e9";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#eef8ff";
    ctx.font = "700 13px Consolas";
    ctx.textAlign = "center";
    ctx.fillText(label, p.x, p.y - 10);
  }

  function drawLightIcon(point, intensity) {
    const r = 10 + Math.min(1, intensity) * 4;
    ctx.save();
    ctx.translate(point.x, point.y);

    ctx.strokeStyle = "rgba(255,215,105,.82)";
    ctx.lineWidth = 1.7;
    for (let i = 0; i < 8; i++) {
      const a = i * Math.PI / 4;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * (r + 4), Math.sin(a) * (r + 4));
      ctx.lineTo(Math.cos(a) * (r + 11), Math.sin(a) * (r + 11));
      ctx.stroke();
    }

    ctx.fillStyle = "#ffb84f";
    ctx.strokeStyle = "#ffe19a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, -r);
    ctx.lineTo(r * 0.82, 0);
    ctx.lineTo(0, r);
    ctx.lineTo(-r * 0.82, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#fff0ad";
    ctx.beginPath();
    ctx.arc(0, 0, 4.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function draw() {
    ctx.clearRect(0, 0, WIDTH, HEIGHT);

    const bg = ctx.createLinearGradient(0, 0, 0, HEIGHT);
    bg.addColorStop(0, "#151a20");
    bg.addColorStop(1, "#222932");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);

    const posX = clamp(getWidgetValue(node, "pos_x", 0), -1, 1);
    const posY = clamp(getWidgetValue(node, "pos_y", 0), -1, 1);
    const posZ = clamp(getWidgetValue(node, "pos_z", 0.1), -1, 1);
    const intensity = clamp(getWidgetValue(node, "intensity", 0.8), 0, 2);

    const radius = 1.7 - 0.7 * posZ;
    const angle = posX * Math.PI;
    const elevation = posY * Math.PI / 2;

    ellipse(radius, 0.7, "rgba(74,201,217,.34)");
    verticalOrbit(radius, angle, "rgba(255,137,75,.38)");
    elevationOrbit(radius, elevation, "rgba(111,215,235,.25)");

    const horizontal = radius * Math.cos(elevation);
    const light = {
      x: horizontal * Math.sin(angle),
      y: 0.7 + radius * Math.sin(elevation),
      z: horizontal * Math.cos(angle),
    };

    point3d(0, 0.7, radius, "F");
    point3d(0, 0.7, -radius, "B");
    point3d(radius, 0.7, 0, "L");
    point3d(-radius, 0.7, 0, "R");

    const center = project(0, 0.7, 0);
    const lightPoint = project(light.x, light.y, light.z);

    ctx.strokeStyle = "rgba(255,210,103,.72)";
    ctx.setLineDash([5,6]);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(center.x, center.y);
    ctx.lineTo(lightPoint.x, lightPoint.y);
    ctx.stroke();
    ctx.setLineDash([]);

    const glow = ctx.createRadialGradient(center.x - 4, center.y - 5, 2, center.x, center.y, 17);
    glow.addColorStop(0, "#d9ffff");
    glow.addColorStop(1, "#348a96");
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(center.x, center.y, 15, 0, Math.PI * 2);
    ctx.fill();

    drawLightIcon(lightPoint, intensity);

    const degrees = Math.round(posX * 180);
    let side;
    if (Math.abs(posX) > 0.85) side = "후면";
    else if (posX > 0.05) side = `좌측 ${Math.abs(degrees)}°`;
    else if (posX < -0.05) side = `우측 ${Math.abs(degrees)}°`;
    else side = "정면 0°";

    const elevDeg = Math.round(posY * 90);
    const distanceText = posZ > 0.2 ? "가까움" : posZ < -0.2 ? "멀음" : "중간";
    readout.textContent = `${side} · 상하 ${elevDeg}° · 거리 ${distanceText}`;

    const [vx, vy, vz] = lightVector(posX, posY);
    vectorBox.innerHTML =
      `LIGHT VECTOR&nbsp;&nbsp;X ${vx.toFixed(3)}&nbsp;&nbsp;Y ${vy.toFixed(3)}&nbsp;&nbsp;Z ${vz.toFixed(3)}<br>` +
      `좌표: 화면 기준 X/Y/Z\n` +
      `후면광: Depth 실루엣 + Normal 림 자동 보정\n` +
      `출력: LAKIS_LIGHT → Relight`;
  }

  function refresh() {
    for (const c of Object.values(controls)) c.sync();
    enabledBox.checked = !!getWidgetValue(node, "enabled", true);
    enabledStatus.textContent = enabledBox.checked ? "ON" : "OFF";
    enabledStatus.style.color = enabledBox.checked ? "#72d79a" : "#8795a3";
    color.value = String(getWidgetValue(node, "color_mode", "Neutral"));
    const mode = node.properties.lakis_execution_mode === "light" ? "light" : "new";
    executionMode.value = mode;

    const px = Number(getWidgetValue(node, "pos_x", 0));
    const py = Number(getWidgetValue(node, "pos_y", 0));
    const pz = Number(getWidgetValue(node, "pos_z", 0.10));
    const near = (a,b) => Math.abs(a-b) < 0.0005;

    let exactKey = "";
    if (near(px,0.00) && near(py,0.00) && near(pz,0.10)) exactKey = "front";
    if (near(px,+0.50) && near(py,0.00) && near(pz,0.10)) exactKey = "left";
    if (near(px,-0.50) && near(py,0.00) && near(pz,0.10)) exactKey = "right";
    if ((near(px,+1.00) || near(px,-1.00)) && near(py,0.00) && near(pz,0.10)) exactKey = "back";
    if (near(px,0.00) && near(py,+1.00) && near(pz,0.10)) exactKey = "top";
    if (near(px,0.00) && near(py,-1.00) && near(pz,0.10)) exactKey = "bottom";

    if (exactKey) preset.value = exactKey;
    draw();
    node.graph?.setDirtyCanvas?.(true, true);
  }

  for (const def of sliderDefs) {
    controls[def.name] = makeSlider(node, slidersRoot, def, refresh);
  }

  enabledBox.checked = !!getWidgetValue(node, "enabled", true);
  color.value = String(getWidgetValue(node, "color_mode", "Neutral"));
  node.properties.lakis_execution_mode =
    node.properties.lakis_execution_mode === "light" ? "light" : "new";
  executionMode.value = node.properties.lakis_execution_mode;

  node.__lakisRefreshExecutionStatus = () => {
    executionStatus.textContent = node.__lakisExecutionStatusText || "";
    executionStatus.style.color = node.__lakisExecutionStatusOk === false
      ? "#ffb36b"
      : "#72d79a";
  };

  const syncExecutionMode = () => {
    const mode = executionMode.value === "light" ? "light" : "new";
    const result = applyExecutionMode(mode, node);
    executionStatus.textContent = result.message;
    executionStatus.style.color = result.ok ? "#72d79a" : "#ffb36b";
    ensureQueueWrapper();
    node.graph?.setDirtyCanvas?.(true, true);
  };

  executionMode.addEventListener("change", syncExecutionMode);

  enabledBox.addEventListener("change", () => {
    setWidget(node, "enabled", enabledBox.checked);
    refresh();
  });
  color.addEventListener("change", () => {
    setWidget(node, "color_mode", color.value);
    refresh();
  });

  root.querySelector('[data-act="reset"]').addEventListener("click", () => {
    const values = {
      pos_x:0.00, pos_y:0.00, pos_z:0.10,
      intensity:0.80, ambient:0.20, shadow:0.65,
      exposure:0.00, rim:0.00, color_mode:"Neutral"
    };
    for (const [k,v] of Object.entries(values)) setWidget(node, k, v);
    preset.value = "";
    refresh();
  });

  const CARDINAL = {
    pos_z:0.10,
    intensity:0.80,
    ambient:0.20,
    shadow:0.65,
    exposure:0.00,
    rim:0.00,
    color_mode:"Neutral",
  };

  // Exact cardinal directions under LAKIS spherical mapping:
  // X  0.00 = front   (0°)
  // X +0.50 = left    (90°)
  // X -0.50 = right   (90°)
  // X +1.00 = back    (180°)
  // Y +1.00 = top     (90° elevation)
  // Y -1.00 = bottom  (90° elevation)
  // Cardinal presets intentionally share the same photometric values so the
  // only changed variable is direction.
  const presets = {
    front:  {...CARDINAL, pos_x: 0.00, pos_y: 0.00},
    left:   {...CARDINAL, pos_x:+0.50, pos_y: 0.00},
    right:  {...CARDINAL, pos_x:-0.50, pos_y: 0.00},
    back:   {...CARDINAL, pos_x:+1.00, pos_y: 0.00},
    top:    {...CARDINAL, pos_x: 0.00, pos_y:+1.00},
    bottom: {...CARDINAL, pos_x: 0.00, pos_y:-1.00},
    neon:   {pos_x:0.72,pos_y:0.28,pos_z:0.15,intensity:1.05,ambient:0.12,shadow:0.72,exposure:-0.10,rim:0.30,color_mode:"Cyan + Magenta"},
  };

  preset.addEventListener("change", () => {
    const key = preset.value;
    const p = presets[key];
    if (!p) return;

    // Write every backend field by name.  No reliance on widget-array position.
    for (const [k,v] of Object.entries(p)) setWidget(node, k, v);

    node.properties.lakis_last_cardinal_preset = key;
    refresh();
  });

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * WIDTH / rect.width,
      y: (event.clientY - rect.top) * HEIGHT / rect.height,
    };
  }

  canvas.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
    canvas.setPointerCapture(event.pointerId);
    const p = canvasPoint(event);
    const mode = event.button === 2 || event.altKey ? "view" : "light";
    dragging = {
      mode,
      pointerId:event.pointerId,
      x:p.x, y:p.y,
      posX:clamp(getWidgetValue(node,"pos_x",0),-1,1),
      posY:clamp(getWidgetValue(node,"pos_y",0),-1,1),
      viewYaw, viewPitch,
    };
    canvas.style.cursor = mode === "view" ? "move" : "grabbing";
    event.preventDefault();
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!dragging || dragging.pointerId !== event.pointerId) return;
    const p = canvasPoint(event);

    if (dragging.mode === "view") {
      viewYaw = dragging.viewYaw - (p.x - dragging.x) / WIDTH * Math.PI * 2;
      viewPitch = clamp(
        dragging.viewPitch + (p.y - dragging.y) / HEIGHT * 1.5,
        0.12, 1.15
      );
      node.properties.lakis_light_preview_view = {yaw:viewYaw, pitch:viewPitch};
      draw();
    } else {
      let value = dragging.posX + (p.x - dragging.x) / (WIDTH / 2);
      while (value > 1) value -= 2;
      while (value < -1) value += 2;

      const nextY = clamp(
        dragging.posY - (p.y - dragging.y) / (HEIGHT / 2),
        -1, 1
      );

      setWidget(node, "pos_x", value);
      setWidget(node, "pos_y", nextY);
      refresh();
    }
    event.preventDefault();
  });

  function stopDrag(event) {
    if (!dragging || dragging.pointerId !== event.pointerId) return;
    dragging = null;
    canvas.style.cursor = "crosshair";
    try { canvas.releasePointerCapture?.(event.pointerId); } catch {}
  }

  canvas.addEventListener("pointerup", stopDrag);
  canvas.addEventListener("pointercancel", stopDrag);
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const amount = event.deltaY * WHEEL_STEP;
    setWidget(
      node, "pos_z",
      clamp(getWidgetValue(node,"pos_z",0.1) - amount, -1, 1)
    );
    refresh();
  }, {passive:false});

  canvas.addEventListener("dblclick", (event) => {
    if (event.shiftKey) {
      viewYaw = 0;
      viewPitch = 0.42;
      node.properties.lakis_light_preview_view = {yaw:viewYaw, pitch:viewPitch};
      draw();
    } else {
      setWidget(node, "pos_x", 0);
      setWidget(node, "pos_y", 0);
      refresh();
    }
  });

  function tick() {
    if (stopped) return;
    draw();
    raf = requestAnimationFrame(tick);
  }

  let resizeFrame = 0;
  const resizeNode = () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      const width = Math.max(620, node.size?.[0] || 620);
      const height = Math.max(500, root.scrollHeight + 22);
      if (!node.size || Math.abs(node.size[0] - width) > 1 || Math.abs(node.size[1] - height) > 1) {
        node.setSize?.([width, height]);
      }
      node.graph?.setDirtyCanvas?.(true, true);
    });
  };
  const resizeObserver = new ResizeObserver(resizeNode);
  resizeObserver.observe(root);

  const originalRemoved = node.onRemoved;
  node.onRemoved = function() {
    stopped = true;
    cancelAnimationFrame(raf);
    cancelAnimationFrame(resizeFrame);
    try { resizeObserver.disconnect(); } catch {}
    return originalRemoved?.apply(this, arguments);
  };

  refresh();
  resizeNode();
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      // Default behavior: normal Queue Prompt creates a new image every time.
      // Users can switch to "조명만 갱신" to lock the last queued seed.
      ensureQueueWrapper();
      const mode = node.properties.lakis_execution_mode === "light" ? "light" : "new";
      executionMode.value = mode;
      const result = applyExecutionMode(mode, node);
      executionStatus.textContent = result.message;
      executionStatus.style.color = result.ok ? "#72d79a" : "#ffb36b";
    });
  });
  raf = requestAnimationFrame(tick);
}

app.registerExtension({
  name: "LAKIS.LightControl.LightMap",

  setup() {
    ensureQueueWrapper();
    ensureApiQueueWrapper();
    setTimeout(() => ensureQueueWrapper(), 750);
    setTimeout(() => ensureApiQueueWrapper(), 750);
  },

  afterConfigureGraph() {
    // Some extensions wrap queuePrompt during graph setup. Re-check once the
    // workflow and subgraph promoted widgets are ready.
    ensureQueueWrapper();
    ensureApiQueueWrapper();
    setTimeout(() => ensureQueueWrapper(), 250);
    setTimeout(() => ensureApiQueueWrapper(), 250);
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== LIGHT_NODE_TYPE && nodeType.comfyClass !== LIGHT_NODE_TYPE) return;

    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function() {
      const result = originalCreated?.apply(this, arguments);
      requestAnimationFrame(() => installLightUI(this));
      return result;
    };
  },
});
