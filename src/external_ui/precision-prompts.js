// SPDX-License-Identifier: GPL-3.0-only
import { installPromptEditor } from "./prompt-highlighting.js?v=linked-prompt-heights-1";

export const precisionEnabled = (config, engine = "anima") =>
  engine === "anima" && config.enabled && config.toyxyz_enabled;
const readPainting = config => JSON.parse(config.toyxyz_paint_data || "null");

export function commonPromptValues(config, prompt) {
  const painting = readPainting(config), base = painting?.base?.prompt || "";
  return {
    trigger: base ? "" : prompt.trigger || "",
    quality: base ? "" : prompt.quality || "",
    global: base || [prompt.artist, prompt.fixed, prompt.general].filter(Boolean).join(", "),
    background: painting?.background?.prompt || "",
    ...config.precision_prompts,
  };
}

export function generationPrompt(config, prompt, engine = "anima", boxesEnabled = false) {
  if (!precisionEnabled(config, engine) || boxesEnabled) return structuredClone(prompt);
  const common = commonPromptValues(config, prompt);
  return { ...prompt, trigger: common.trigger, quality: common.quality,
    general: common.global, fixed: "", artist: "" };
}

export function editorPainting(config, prompt, engine = "anima") {
  const painting = readPainting(config);
  if (!painting || !precisionEnabled(config, engine)) return config.toyxyz_paint_data;
  painting.base.prompt = "";
  painting.background.prompt = commonPromptValues(config, prompt).background;
  return JSON.stringify(painting);
}

export function updateLayerPrompt(config, id, text) {
  const painting = readPainting(config), layer = painting.layers.find(item => item.id === id);
  if (!layer) throw Error("인물 구성이 바뀌었습니다. 3D 포즈의 인물 프롬프트를 다시 확인해 주세요.");
  layer.prompt = text;
  config.toyxyz_paint_data = JSON.stringify(painting);
}

export class PrecisionPrompts {
  constructor({ getConfig, getPrompt, getEngine, getRegionsEnabled = () => false, onChange }) {
    Object.assign(this, { getConfig, getPrompt, getEngine, getRegionsEnabled, onChange });
    this.cards = new Map();
    this.activeKey = "global";
    this.normal = document.querySelector(".prompt-column > .prompt-panel:not(.negative-prompt-panel)");
    this.root = document.createElement("article");
    this.root.className = "panel prompt-panel precision-prompts advanced-settings-host";
    this.root.hidden = true;
    this.root.setAttribute("aria-label", "프롬프트 ( 3D 포즈 )");
    this.root.innerHTML = `<div class="field-label prompt-field-title">
      <div class="prompt-heading-row precision-prompts-heading"><div class="advanced-settings-title-group"><strong class="prompt-section-heading">프롬프트 ( 3D 포즈 )</strong></div></div>
      <div class="prompt-tools precision-prompts-tabs" role="tablist" aria-label="3D 포즈 프롬프트 분류"></div>
      <div class="precision-prompts-cards"></div>
    </div>`;
    this.normal.before(this.root);
    this.heading = this.root.querySelector(".precision-prompts-heading");
    this.tabs = this.root.querySelector(".precision-prompts-tabs");
    this.list = this.root.querySelector(".precision-prompts-cards");
    this.translation = document.querySelector(".prompt-translation-toggle");
    this.translationAnchor = document.createComment("normal prompt translation control");
    this.translation.before(this.translationAnchor);
    this.settingsButtonAnchor = document.createComment("normal prompt settings button");
    this.normal.querySelector(".prompt-section-heading").after(this.settingsButtonAnchor);
    this.settingsOverlayAnchor = document.createComment("normal prompt settings overlay");
    this.normal.append(this.settingsOverlayAnchor);
    window.addEventListener("lakis-advanced-settings-ready", () => this.refresh());
    window.addEventListener("lakis-prompt-state-loaded", () => this.refresh());
    window.addEventListener("lakis-generation-engine-changed", () => this.refresh());
    window.addEventListener("lakis:anima-regions-change", () => this.refresh());
    this.refresh();
  }

  refresh() {
    const config = this.getConfig(), enabled = precisionEnabled(config, this.getEngine());
    const inMain = enabled && !this.getRegionsEnabled();
    if (inMain && this.normal.classList.contains("prompt-panel-maximized")) {
      document.querySelector("#positivePromptMaximizeButton").click();
    }
    this.root.hidden = !inMain;
    this.normal.classList.toggle("precision-prompt-normal-hidden", inMain);
    this.syncHeaderControls(inMain);
    if (!inMain) return;
    const common = commonPromptValues(config, this.getPrompt());
    const fields = [
      ["trigger", "트리거", common.trigger], ["quality", "품질", common.quality],
      ["global", "전역설정", common.global], ["background", "배경", common.background],
    ];
    const painting = readPainting(config);
    let person = 0, region = 0;
    for (const layer of painting?.layers || []) {
      fields.push([`layer:${layer.id}`, layer.pose_source ? `인물 ${++person}` : `영역 ${++region}`,
        layer.prompt || "", layer]);
    }
    const keys = new Set(fields.map(([key]) => key));
    if (!keys.has(this.activeKey)) this.activeKey = "global";
    for (const [key, card] of this.cards) {
      if (!keys.has(key)) { card.root.remove(); card.button.remove(); this.cards.delete(key); }
    }
    for (const [index, [key, title, value, layer]] of fields.entries()) {
      let card = this.cards.get(key);
      if (!card) {
        const root = document.createElement("section"), label = document.createElement("label");
        root.className = "fixed-prompt-panel precision-prompt-card";
        root.id = `precisionPanel-${crypto.randomUUID()}`;
        root.setAttribute("role", "tabpanel");
        const button = document.createElement("button");
        button.type = "button";
        button.id = `precisionTab-${crypto.randomUUID()}`;
        button.className = "prompt-tool precision-prompt-tab";
        button.setAttribute("role", "tab");
        button.setAttribute("aria-controls", root.id);
        root.setAttribute("aria-labelledby", button.id);
        button.onclick = () => { this.activeKey = key; this.refresh(); };
        this.tabs.append(button);
        const input = document.createElement("textarea");
        input.id = `precisionPrompt-${crypto.randomUUID()}`;
        input.maxLength = 4000;
        input.placeholder = "영문 태그 또는 한국어로 입력하세요…";
        label.htmlFor = input.id;
        const heading = document.createElement("div"), badge = document.createElement("span");
        heading.className = "fixed-prompt-heading";
        badge.className = "fixed-badge";
        badge.textContent = "3D";
        heading.append(label, badge);
        root.append(heading, input);
        this.list.append(root);
        input.addEventListener("input", () => {
          const current = this.getConfig();
          if (key.startsWith("layer:")) updateLayerPrompt(current, key.slice(6), input.value);
          else current.precision_prompts = { ...commonPromptValues(current, this.getPrompt()), [key]: input.value };
          this.onChange();
        });
        card = { root, label, input, button };
        this.cards.set(key, card);
        installPromptEditor(input);
      }
      card.label.textContent = title + (layer?.visible === false ? " · 숨김" : "");
      card.button.textContent = card.label.textContent;
      const selected = key === this.activeKey;
      card.button.setAttribute("aria-selected", String(selected));
      card.button.classList.toggle("active", selected);
      card.root.hidden = !selected;
      if (card.input.value !== value) {
        card.input.value = value;
        card.input.dispatchEvent(new Event("change"));
      }
      if (this.list.children[index] !== card.root) this.list.insertBefore(card.root, this.list.children[index] || null);
      if (this.tabs.children[index] !== card.button) this.tabs.insertBefore(card.button, this.tabs.children[index] || null);
    }
  }

  syncHeaderControls(enabled) {
    if (enabled && this.translation.parentNode !== this.heading) this.heading.append(this.translation);
    else if (!enabled && this.translation.previousSibling !== this.translationAnchor) this.translationAnchor.after(this.translation);
    const button = document.querySelector('.advanced-settings-button[data-advanced-group="prompt"]');
    const overlay = document.querySelector('.advanced-settings-overlay[data-advanced-group="prompt"]');
    if (button && overlay) {
      const title = this.heading.firstElementChild;
      if (enabled) {
        if (button.parentNode !== title) title.append(button);
        if (overlay.parentNode !== this.root) this.root.append(overlay);
      } else {
        if (button.previousSibling !== this.settingsButtonAnchor) this.settingsButtonAnchor.after(button);
        if (overlay.previousSibling !== this.settingsOverlayAnchor) this.settingsOverlayAnchor.after(overlay);
      }
    }
  }

  forGeneration(prompt) {
    return generationPrompt(this.getConfig(), prompt, this.getEngine(), this.getRegionsEnabled());
  }

  paintDataForEditor() {
    const config = this.getConfig();
    if (precisionEnabled(config, this.getEngine()) && !this.getRegionsEnabled()) {
      config.precision_prompts ??= commonPromptValues(config, this.getPrompt());
    }
    return editorPainting(config, this.getPrompt(), this.getEngine());
  }

  focusLayer(id) {
    const card = this.cards.get(`layer:${id}`);
    if (!card || this.root.hidden) return false;
    this.activeKey = `layer:${id}`;
    this.refresh();
    card.root.scrollIntoView({ block: "center" });
    card.input.focus();
    return true;
  }
}
