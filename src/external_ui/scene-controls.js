// LAKIS 8.0: manual 3D pose only; no automatic pose extraction or model download.
(() => {
  const panel = document.querySelector("#sceneControls");
  const status = panel.querySelector("[data-scene-status]");
  const strengthSettings = document.querySelector("#toyxyzStrengthSettings");
  const toyEditor = document.querySelector("#toyxyzSceneEditor");
  const toyFrame = toyEditor.querySelector("iframe");
  const toyStatus = toyEditor.querySelector("[data-toyxyz-status]");
  const toyOpenButton = panel.querySelector("[data-open-toyxyz]");
  const toyToggle = panel.querySelector("[data-toyxyz-toggle]");
  const toyCloseButton = toyEditor.querySelector("[data-toyxyz-close]");
  const refreshButton = panel.querySelector("[data-models-refresh]");
  const toyPending = new Map();
  let toyBoot, toyBootResolve, toyBootReject, toyBootTimer;
  let toyInitialized = false, toyInitializing, toyCapture, toySaveTimer, toyRevision = 0;
  let config, saveTimer, saveQueue = Promise.resolve(), precisionPrompts;
  let lastSavedSceneState = null;

  function report(error) {
    status.hidden = false;
    status.textContent = error.message || String(error);
  }
  function showModels(models) {
    const list = panel.querySelector("[data-model-status]");
    const entries = Object.values(models);
    panel.querySelector("[data-model-notice]").textContent =
      [...new Set(entries.map(model => model.notice))].join("\n");
    list.replaceChildren(...entries.map(model => {
      const item = document.createElement("li"), link = document.createElement("a");
      link.href = model.model_card;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = model.model;
      item.append(link, ` · ${model.valid ? "공식 파일 확인됨" : model.installed ? "파일 해시 불일치" : "미설치"}`);
      return item;
    }));
  }
  async function refreshModels() {
    const response = await fetch("/api/scene-controls", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "장면 설정을 불러오지 못했습니다.");
    showModels(result.models);
    return result;
  }
  function persist() {
    if (!config) return Promise.resolve();
    const body = JSON.stringify(config);
    saveQueue = saveQueue.catch(() => {}).then(async () => {
      const response = await fetch("/api/scene-controls", {
        method: "POST", headers: { "Content-Type": "application/json" }, body,
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      lastSavedSceneState = body;
    });
    saveQueue.catch(report);
    return saveQueue;
  }
  function syncToyVisibility() {
    const enabled = Boolean(config.enabled && config.toyxyz_enabled);
    config.pose_enabled = config.region_enabled = enabled;
    syncPoseModeAvailability();
    toyToggle.disabled = false;
    toyToggle.classList.toggle("on", enabled);
    toyToggle.setAttribute("aria-pressed", String(enabled));
    toyToggle.setAttribute("aria-label", `3D 포즈 ${enabled ? "끄기" : "켜기"}`);
    toyOpenButton.disabled = !enabled;
    if (!enabled && toyEditor.open) toyEditor.close();
  }
  function changed() {
    config.enabled = Boolean(config.toyxyz_enabled);
    state.scene_controls = config;
    precisionPrompts?.refresh();
    syncToyVisibility();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => persist().catch(report), 300);
  }
  const ready = (async () => {
    const result = await refreshModels();
    config = result.state;
    if (!config.enabled) config.toyxyz_enabled = false;
    state.scene_controls = config;
    const { PrecisionPrompts } = await import("./precision-prompts.js");
    precisionPrompts = new PrecisionPrompts({
      getConfig: () => config, getPrompt: () => state.prompt, onChange: changed,
    });
    for (const input of strengthSettings.querySelectorAll("[data-field]")) {
      input.value = config[input.dataset.field];
      input.onchange = () => {
        if (!input.checkValidity()) { input.reportValidity(); return; }
        config[input.dataset.field] = Number(input.value);
        changed();
      };
    }
    strengthSettings.disabled = false;
    refreshButton.disabled = false;
    syncToyVisibility();
    lastSavedSceneState = JSON.stringify(config);
  })();
  ready.catch(report);
  refreshButton.onclick = () => refreshModels().catch(report);
  toyToggle.onclick = () => {
    config.toyxyz_enabled = !(config.enabled && config.toyxyz_enabled);
    changed();
  };
  async function requestToy(type, validatePrompts = false) {
    if (!toyBoot) {
      toyBoot = new Promise((resolve, reject) => {
        toyBootResolve = resolve;
        toyBootReject = reject;
        toyBootTimer = setTimeout(() => reject(Error("3D 편집기를 불러오지 못했습니다. 설치 파일을 확인하고 창을 다시 열어 주세요.")), 30000);
      });
      toyFrame.src = "toyxyz-editor.html";
    }
    await toyBoot;
    return new Promise((resolve, reject) => {
      const id = crypto.randomUUID();
      const timer = setTimeout(() => {
        toyPending.delete(id);
        reject(Error("3D 인물·영역 편집기의 처리가 완료되지 않았습니다."));
      }, 30000);
      toyPending.set(id, { resolve, reject, timer });
      toyFrame.contentWindow.postMessage({
        type, request_id: id, width: state.output.width, height: state.output.height,
        pose_data: config.pose_data, paint_data: precisionPrompts.paintDataForEditor(),
        validate_prompts: validatePrompts,
      }, location.origin);
    });
  }
  function rememberToy(result) {
    if (result.revision < toyRevision) return;
    const latest = JSON.parse(precisionPrompts.paintDataForEditor() || "null");
    const painting = JSON.parse(result.paint_data);
    if (latest) {
      const prompts = new Map(latest.layers.map(layer => [layer.id, layer.prompt]));
      for (const layer of painting.layers) {
        if (prompts.has(layer.id)) layer.prompt = prompts.get(layer.id);
      }
      painting.background.prompt = latest.background.prompt;
      painting.base.prompt = latest.base.prompt;
    }
    config.pose_data = result.pose_data;
    config.toyxyz_render_data = result.render_data;
    config.toyxyz_paint_data = JSON.stringify(painting);
    changed();
  }
  async function ensureToyEditor() {
    if (toyInitialized) return;
    if (!toyInitializing) {
      toyInitializing = (async () => {
        await requestToy("lakis:toyxyz-load");
        toyInitialized = true;
        rememberToy(await requestToy("lakis:toyxyz-capture"));
      })().finally(() => { toyInitializing = null; });
    }
    await toyInitializing;
  }
  function captureToyChanges() {
    if (!toyCapture) {
      toyCapture = requestToy("lakis:toyxyz-capture").then(rememberToy)
        .finally(() => { toyCapture = null; });
    }
    return toyCapture;
  }
  toyOpenButton.onclick = async () => {
    toyEditor.showModal();
    toyStatus.textContent = "포즈를 불러오는 중…";
    try {
      await ensureToyEditor();
      await requestToy("lakis:toyxyz-size");
      toyStatus.textContent = "포즈는 자동 저장됩니다. 인물별 내용은 메인 화면의 정밀 프롬프트에 입력하세요.";
    } catch (error) { toyStatus.textContent = error.message; }
  };
  async function closeToyEditor() {
    if (toyCloseButton.disabled) return;
    toyCloseButton.disabled = true;
    try {
      await ensureToyEditor();
      clearTimeout(toySaveTimer);
      await toyCapture;
      rememberToy(await requestToy("lakis:toyxyz-capture"));
      clearTimeout(saveTimer);
      await persist();
      toyEditor.close();
      toyOpenButton.focus();
    } catch (error) { toyStatus.textContent = error.message; }
    finally { toyCloseButton.disabled = false; }
  }
  toyCloseButton.onclick = closeToyEditor;
  toyEditor.addEventListener("cancel", event => {
    event.preventDefault();
    closeToyEditor();
  });
  window.addEventListener("message", event => {
    if (event.origin !== location.origin || event.source !== toyFrame.contentWindow) return;
    const message = event.data;
    if (message?.type === "lakis:toyxyz-ready" && toyBoot) {
      clearTimeout(toyBootTimer);
      if (message.error) toyBootReject(Error(message.error));
      else {
        const slot = toyFrame.contentDocument.querySelector("[data-generation-controls]");
        slot.append(strengthSettings);
        slot.hidden = strengthSettings.hidden = false;
        toyBootResolve();
      }
    } else if (message?.type === "lakis:toyxyz-changed" && toyInitialized) {
      toyRevision = message.revision;
      config.pose_data = message.pose_data;
      config.toyxyz_render_data = "";
      changed();
      clearTimeout(toySaveTimer);
      toySaveTimer = setTimeout(() => captureToyChanges().catch(report), 600);
    } else if (message?.type === "lakis:toyxyz-result") {
      const pending = toyPending.get(message.request_id);
      if (!pending) return;
      toyPending.delete(message.request_id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(Object.assign(Error(message.error), {
        code: message.error_code, missingLayerId: message.missing_layer_id,
      }));
      else pending.resolve(message);
    }
  });
  function syncEditorSize() {
    if (config) syncPoseModeAvailability();
    if (toyInitialized) requestToy("lakis:toyxyz-size").catch(report);
  }
  for (const id of ["imageWidth", "imageHeight"]) {
    document.querySelector(`#${id}`).addEventListener("input", syncEditorSize);
  }
  window.addEventListener("lakis-prompt-state-loaded", syncEditorSize);
  window.lakisPromptForGeneration = async prompt => {
    await ready;
    return precisionPrompts.forGeneration(prompt);
  };
  window.lakisPrepareScene = async payload => {
    await ready;
    if (config.enabled && config.toyxyz_enabled) {
      const result = await refreshModels();
      const missing = Object.values(result.models).filter(model => !model.valid);
      if (missing.length) throw Error("공식 제어 모델을 확인해 주세요: " + missing.map(model => model.model).join(", "));
      try {
        await ensureToyEditor();
        clearTimeout(toySaveTimer);
        await toyCapture;
        rememberToy(await requestToy("lakis:toyxyz-capture", true));
      } catch (error) {
        if (error.missingLayerId) {
          if (toyEditor.open) toyEditor.close();
          precisionPrompts.focusLayer(error.missingLayerId);
        } else if (!toyEditor.open) toyEditor.showModal();
        toyStatus.textContent = error.message;
        throw error;
      }
    }
    clearTimeout(saveTimer);
    await persist();
    payload.scene_controls = structuredClone(config);
    const scene = payload.scene_controls;
    if (!scene.enabled) return;
    payload.composition_enabled = false;
    payload.i2i.enabled = false;
    payload.inpaint.enabled = false;
    if (state.translation_enabled) {
      const painting = JSON.parse(scene.toyxyz_paint_data);
      const entries = [...painting.layers.filter(layer => layer.visible), painting.base, painting.background];
      for (const entry of entries) {
        if (!entry.prompt.trim()) continue;
        const translated = await translatedPromptForGeneration({ general: entry.prompt, negative: "" });
        entry.prompt = translated.general;
      }
      scene.toyxyz_paint_data = JSON.stringify(painting);
    }
  };
  function flushSceneState() {
    clearTimeout(toySaveTimer);
    clearTimeout(saveTimer);
    if (!config || lastSavedSceneState === null) return;
    const body = JSON.stringify(config);
    if (body === lastSavedSceneState) return;
    if (navigator.sendBeacon("/api/scene-controls", new Blob([body], { type: "application/json" }))) {
      lastSavedSceneState = body;
    }
  }
  window.addEventListener("pagehide", flushSceneState);
})();
