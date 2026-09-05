(() => {
  const groups = [
    ["model", ".model-panel", "모델 세팅"],
    ["lora", ".lora-panel", "로라"],
    ["composition", ".composition-panel", "구도 설정"],
    ["i2i", ".i2i-panel", "i2i"],
    ["prompt", ".prompt-panel", "프롬프트"],
    ["generation", ".compact-mode-panel", "생성 모드", true],
  ];
  let configuration = {};
  const generationModeSwitches = new Set(["2138", "2139", "2140"]);
  const tooltip = document.createElement("div");
  tooltip.className = "advanced-settings-tooltip";
  tooltip.textContent = "세부설정";
  tooltip.hidden = true;
  document.body.append(tooltip);

  const icon = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.3 15.3 5 5"/></svg>`;

  function cloneValue(value) {
    return value && typeof value === "object" ? structuredClone(value) : value;
  }

  function currentValue(nodeId, field) {
    if (Object.prototype.hasOwnProperty.call(state.node_overrides[nodeId] || {}, field.name)) {
      return state.node_overrides[nodeId][field.name];
    }
    if (generationModeSwitches.has(nodeId) && field.name === "value") {
      return state.generation.mode === "detail";
    }
    return cloneValue(field.value);
  }

  function syncGenerationModeSwitches() {
    const enabled = state.generation.mode === "detail";
    for (const nodeId of generationModeSwitches) saveValue(nodeId, "value", enabled);
    const body = document.querySelector(".generation-advanced-overlay:not([hidden]) .advanced-settings-body");
    if (body) render("generation", body);
  }

  function saveValue(nodeId, name, value) {
    (state.node_overrides[nodeId] ||= {})[name] = value;
  }

  function makeField(nodeId, field) {
    const row = document.createElement("label");
    row.className = "advanced-field";
    const name = document.createElement("span");
    name.textContent = field.name;
    name.title = field.name;
    row.append(name);
    const value = currentValue(nodeId, field);
    if (field.type === "boolean") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `advanced-field-switch${value ? " on" : ""}`;
      button.setAttribute("aria-pressed", String(Boolean(value)));
      button.addEventListener("click", () => {
        const next = button.getAttribute("aria-pressed") !== "true";
        button.setAttribute("aria-pressed", String(next));
        button.classList.toggle("on", next);
        saveValue(nodeId, field.name, next);
      });
      row.append(button);
      return row;
    }
    const longValue = field.type === "json" || String(value ?? "").length > 70;
    const input = document.createElement(longValue ? "textarea" : "input");
    if (!longValue) input.type = field.type === "number" ? "number" : "text";
    if (field.type === "number") input.step = "any";
    input.value = field.type === "json" && !field.encoded_json
      ? JSON.stringify(value, null, 2) : String(value ?? "");
    const commit = () => {
      try {
        let next = input.value;
        if (field.type === "number") {
          next = Number(next);
          if (!Number.isFinite(next)) throw new Error("number");
        } else if (field.type === "json") {
          const parsed = JSON.parse(next);
          next = field.encoded_json ? JSON.stringify(parsed) : parsed;
        }
        saveValue(nodeId, field.name, next);
        input.classList.remove("advanced-field-error");
      } catch (_) {
        input.classList.add("advanced-field-error");
      }
    };
    input.addEventListener("change", commit);
    input.addEventListener("blur", commit);
    row.append(input);
    return row;
  }

  function render(group, body) {
    body.replaceChildren();
    const nodes = configuration[group] || [];
    if (!nodes.length) {
      const empty = document.createElement("div");
      empty.className = "advanced-settings-empty";
      empty.textContent = "연결된 노드 설정이 없습니다.";
      body.append(empty);
      return;
    }
    for (const node of nodes) {
      const card = document.createElement("section");
      card.className = "advanced-node-card";
      const heading = document.createElement("div");
      heading.className = "advanced-node-title";
      heading.innerHTML = `<span></span><small></small>`;
      heading.firstElementChild.textContent = node.title;
      heading.lastElementChild.textContent = `${node.class_type} · ${node.id}`;
      card.append(heading);
      for (const field of node.fields) card.append(makeField(node.id, field));
      body.append(card);
    }
  }

  function placeGenerationOverlay(overlay) {
    const preview = document.querySelector(".preview-panel")?.getBoundingClientRect();
    const row = document.querySelector(".generation-action-row")?.getBoundingClientRect();
    if (!row) return;
    const gap = 8;
    const width = Math.min(row.width, Math.max(360, window.innerWidth - row.left - 12));
    const availableHeight = Math.max(260, row.top - 20);
    const height = Math.min(Math.max(360, window.innerHeight * .68), availableHeight);
    overlay.style.left = `${Math.max(12, preview ? preview.right + gap : row.left)}px`;
    overlay.style.top = `${Math.max(12, row.top - height - gap)}px`;
    overlay.style.width = `${width}px`;
    overlay.style.height = `${height}px`;
  }

  function install(group, selector, title, floating = false) {
    const panel = document.querySelector(selector);
    if (!panel) return;
    panel.classList.add("advanced-settings-host");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "advanced-settings-button";
    button.setAttribute("aria-label", `${title} 세부설정`);
    button.setAttribute("aria-expanded", "false");
    button.innerHTML = icon;
    const moveTooltip = event => {
      tooltip.style.left = `${event.clientX}px`;
      tooltip.style.top = `${event.clientY}px`;
    };
    button.addEventListener("mouseenter", event => { moveTooltip(event); tooltip.hidden = false; });
    button.addEventListener("mousemove", moveTooltip);
    button.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    button.addEventListener("click", () => { tooltip.hidden = true; });
    const categoryTitle = panel.querySelector(".panel-heading .section-title-accent") || panel.querySelector(".prompt-heading-row .prompt-section-heading") || panel.querySelector(".compact-mode-head h2");
    if (categoryTitle) {
      if (floating) {
        const titleGroup = document.createElement("div");
        titleGroup.className = "advanced-settings-title-group";
        categoryTitle.parentElement.insertBefore(titleGroup, categoryTitle);
        titleGroup.append(categoryTitle, button);
      } else {
        categoryTitle.parentElement.classList.add("advanced-settings-title-group");
        categoryTitle.insertAdjacentElement("afterend", button);
      }
    }

    const overlay = document.createElement("section");
    overlay.className = "advanced-settings-overlay";
    if (floating) overlay.classList.add("generation-advanced-overlay");
    overlay.hidden = true;
    overlay.innerHTML = `<header class="advanced-settings-header"><div><h3></h3><span>연결된 ComfyUI 노드의 전체 입력 설정</span></div><button class="advanced-settings-close" type="button" aria-label="닫기">×</button></header><div class="advanced-settings-body"></div>`;
    overlay.querySelector("h3").textContent = `${title} · 노드 설정`;
    (floating ? document.body : panel).append(overlay);
    const close = () => { overlay.hidden = true; button.setAttribute("aria-expanded", "false"); };
    button.addEventListener("click", () => {
      const opening = overlay.hidden;
      document.querySelectorAll(".advanced-settings-overlay:not([hidden])").forEach(item => { item.hidden = true; });
      document.querySelectorAll(".advanced-settings-button[aria-expanded='true']").forEach(item => item.setAttribute("aria-expanded", "false"));
      if (opening) {
        render(group, overlay.querySelector(".advanced-settings-body"));
        if (floating) placeGenerationOverlay(overlay);
        overlay.hidden = false;
        button.setAttribute("aria-expanded", "true");
      }
    });
    overlay.querySelector(".advanced-settings-close").addEventListener("click", close);
    if (floating) window.addEventListener("resize", () => { if (!overlay.hidden) placeGenerationOverlay(overlay); });
  }

  async function initialize() {
    groups.forEach(args => install(...args));
    document.querySelectorAll(".mode-option[data-mode]").forEach(button => {
      button.addEventListener("click", () => queueMicrotask(syncGenerationModeSwitches));
    });
    try {
      const response = await fetch("/api/workflow-config", { cache: "no-store" });
      const payload = await response.json();
      configuration = payload.advanced_nodes || {};
    } catch (error) {
      console.error("Could not load advanced node settings", error);
    }
  }
  initialize();
})();
