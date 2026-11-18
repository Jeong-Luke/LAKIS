(() => {
  "use strict";

  const MAX_REFERENCES = 3;
  const WARNING_SESSION_KEY = "lakis:multi-reference-warning-dismissed";
  const DEFAULTS = { enabled: false, mode: "cs", fidelity: 1, ref_megapixels: 1, experimental_forecast: false, references: [{ image_name: "", strength: 0 }] };
  const LEGACY_IDS = ["animaReferenceDropZone", "animaReferencePreview", "animaReferenceEmpty", "animaReferenceRemove", "animaReferenceFile", "animaReferenceMode", "animaReferenceWeight", "animaReferenceTarget"];
  const panel = document.querySelector("#animaReferencePanel");
  const toggle = document.querySelector("#animaReferenceToggle");
  const notice = document.querySelector("#animaReferenceConsent");
  const checkbox = notice.querySelector("#acceptConsent");
  const confirm = notice.querySelector("#confirmConsent");
  const cancel = notice.querySelector("#cancelConsent");
  const consentError = notice.querySelector("#animaReferenceConsentError");
  const addButton = document.querySelector("#animaReferenceAdd");
  const rowsContainer = document.querySelector("#animaReferenceRows");
  const status = document.querySelector("#animaReferenceStatus");
  const forecast = document.querySelector("#animaReferenceForecast");
  const fidelityInput = document.querySelector("#animaReferenceFidelity");
  const megapixelsInput = document.querySelector("#animaReferenceMegapixels");
  const firstBody = rowsContainer ? rowsContainer.querySelector(".anima-reference-body") : null;
  const rowTemplate = firstBody.cloneNode(true);
  let defaults = structuredClone(DEFAULTS);
  let saved = structuredClone(DEFAULTS);
  let availability = { experimental: false, ready: false, missing: [] };
  let checking = true;
  let consent = null; // Only the status and consent endpoints can set this.
  let savingConsent = false;
  let restoreEnabledAfterCheck = false;
  let uploading = false;
  let errorMessage = "";
  let restoreRevision = 0;
  let rowSeq = 1;
  let previewUrls = [""];
  let rowTokens = [0];
  let rows = [];

  function bounded(value, min, max, fallback) {
    if (typeof value !== "number" && (typeof value !== "string" || !value.trim())) return fallback;
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback;
  }

  function normalizeReference(entry) {
    const source = entry && typeof entry === "object" && !Array.isArray(entry) ? structuredClone(entry) : {};
    const image_name = typeof source.image_name === "string" ? source.image_name : "";
    const strength = bounded(source.strength, -3, 3, 0);
    return { ...source, image_name, strength };
  }

  function normalize(value) {
    const source = value && typeof value === "object" && !Array.isArray(value) ? structuredClone(value) : {};
    let referencesRaw = source.references;
    if (!Array.isArray(referencesRaw)) {
      const single = {};
      if (typeof source.image_name === "string") single.image_name = source.image_name;
      if ("strength" in source) single.strength = source.strength;
      else if ("weight" in source) {
        const legacyWeight = bounded(source.weight, 0, 2, 1);
        single.strength = legacyWeight > 0 ? Math.max(-3, Math.log(legacyWeight)) : 0;
        if (legacyWeight === 0) source.enabled = false;
      }
      referencesRaw = [single];
    }
    if (referencesRaw.length === 0) referencesRaw = [{ image_name: "", strength: 0 }];
    referencesRaw = referencesRaw.slice(0, MAX_REFERENCES).map(normalizeReference);
    const { image_name: _img, strength: _str, weight: _w, references: _ref, enabled: _e, mode: _m, fidelity: _f, ref_megapixels: _mp, experimental_forecast: _ef, ...unknownRoot } = source;
    return {
      ...structuredClone(defaults),
      ...unknownRoot,
      enabled: source.enabled === true,
      mode: source.mode === "char" ? "char" : "cs",
      fidelity: bounded(source.fidelity, 0, 1, defaults.fidelity),
      ref_megapixels: bounded(source.ref_megapixels, 0.25, 2, defaults.ref_megapixels),
      experimental_forecast: source.experimental_forecast === true,
      references: referencesRaw,
    };
  }

  function dependenciesReady() {
    return !checking && availability.experimental === true && availability.ready === true;
  }

  function available() {
    return dependenciesReady() && consent?.accepted === true;
  }

  function imageUrl(name) {
    return name ? `/api/anima-reference-image?name=${encodeURIComponent(name)}` : "";
  }

  function collectRow(root) {
    return {
      root,
      dropZone: root.querySelector(".anima-reference-preview"),
      preview: root.querySelector("img"),
      empty: root.querySelector(".anima-reference-empty-text"),
      remove: root.querySelector(".anima-reference-remove"),
      file: root.querySelector(".anima-reference-file-input"),
      mode: root.querySelector(".anima-reference-mode"),
      strength: root.querySelector(".anima-reference-strength"),
      target: root.querySelector(".anima-reference-target"),
      title: root.querySelector(".anima-reference-row-title"),
      rowRemove: root.querySelector(".anima-reference-row-remove"),
    };
  }

  function targetValue(type, id, hasId = true) {
    if (type === "auto_pose") return "auto_pose";
    return type === "global" ? "global" : `target:${JSON.stringify([type, hasId, hasId ? id : null])}`;
  }

  function targetChoices(index) {
    const automatic = { type: "auto_pose", label: `자동 연결 (인물 ${index + 1})`, unavailable: true };
    const choices = [{ type: "global", label: "전체" }, automatic];
    const scene = state.scene_controls;
    if (scene?.enabled === true && scene.toyxyz_enabled === true) {
      let renderData = null;
      try { renderData = JSON.parse(scene.toyxyz_render_data); } catch {}
      const bodies = renderData?.region_painter?.bodies;
      if (Array.isArray(bodies)) {
        bodies.forEach((body, bodyIndex) => {
          if (!body || typeof body.id !== "string" || !body.id.trim()) return;
          if (bodyIndex === index) {
            automatic.id = body.id;
            automatic.unavailable = false;
          }
          choices.push({ type: "pose", id: body.id, label: `3D · ${bodyIndex + 1}` });
        });
      }
    }
    const regions = window.LAKISAnimaRegions.snapshot();
    if (regions.enabled === true && Array.isArray(regions.regions)) {
      regions.regions.forEach((region, index) => {
        if (!region || typeof region.id !== "string" || !region.id.trim()) return;
        choices.push({ type: "box", id: region.id, label: `박스 · ${index + 1}` });
      });
    }
    return choices;
  }

  function renderTargetSelector(row, reference) {
    const type = typeof reference.target_type === "string" ? reference.target_type : "global";
    const hasId = Object.prototype.hasOwnProperty.call(reference, "target_id");
    const value = targetValue(type, reference.target_id, hasId);
    const choices = targetChoices(rows.indexOf(row));
    if (!choices.some(choice => targetValue(choice.type, choice.id) === value)) {
      const kind = type === "pose" ? "3D 인물" : type === "box" ? "바운딩 박스" : type;
      const id = hasId ? ` · ${String(reference.target_id)}` : "";
      choices.push({ type, id: reference.target_id, label: `사용할 수 없는 대상 · ${kind}${id}`, unavailable: true, hasId });
    }
    row.target.replaceChildren(...choices.map(choice => {
      const option = document.createElement("option");
      option.value = targetValue(choice.type, choice.id, choice.hasId);
      option.textContent = choice.label;
      option.disabled = choice.unavailable === true;
      return option;
    }));
    row.target.value = value;
  }

  function identifyRow(row, index) {
    row.root.dataset.referenceIndex = String(index);
    row.root.setAttribute("role", "group");
    row.root.setAttribute("aria-label", `레퍼런스 ${index + 1}`);
    row.title.textContent = `레퍼런스 ${index + 1}`;
    const controls = [row.dropZone, row.preview, row.empty, row.remove, row.file,
      row.mode, row.strength, row.target];
    controls.forEach((control, i) => control.setAttribute("id",
      LEGACY_IDS[i] + (index > 0 ? `-${index + 1}` : "")));
    row.rowRemove.setAttribute("aria-label", `${index + 1}번 레퍼런스 영역 삭제`);
  }

  function closeReferenceSettings() {
    document.querySelector('.feature-settings-overlay[data-advanced-group="reference"]:not([hidden]) .advanced-settings-close')?.click();
  }

  function bindRow(row) {
    const currentIndex = () => rows.indexOf(row);
    row.dropZone.addEventListener("click", () => {
      if (available() && !uploading) row.file.click();
    });
    for (const eventName of ["dragenter", "dragover"]) {
      row.dropZone.addEventListener(eventName, event => {
        event.preventDefault();
        if (!available() || uploading) return;
        row.dropZone.classList.toggle("is-dragging", true);
        if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      });
    }
    row.dropZone.addEventListener("dragleave", event => {
      event.preventDefault();
      row.dropZone.classList.toggle("is-dragging", false);
    });
    row.dropZone.addEventListener("drop", event => {
      event.preventDefault();
      row.dropZone.classList.toggle("is-dragging", false);
      return uploadReferenceFile(event.dataTransfer?.files?.[0], currentIndex());
    });
    row.file.addEventListener("change", () => uploadReferenceFile(row.file.files?.[0], currentIndex()));
    row.remove.addEventListener("click", () => {
      const index = currentIndex();
      if (index < 0 || !available() || uploading) return;
      previewUrls[index] = "";
      commitReference(index, { image_name: "" });
    });
    row.rowRemove.addEventListener("click", () => removeReference(currentIndex()));
    row.mode.addEventListener("change", () => {
      if (available() && !uploading) commitRoot({ mode: row.mode.value });
    });
    row.target.addEventListener("change", () => {
      const index = currentIndex();
      if (index < 0 || !available() || uploading) return;
      const choice = targetChoices(index).find(item => targetValue(item.type, item.id) === row.target.value);
      if (!choice || choice.unavailable) {
        if (choice?.type === "auto_pose") {
          errorMessage = `참조 ${index + 1}에 연결할 3D 인물 ${index + 1}이 없습니다. 3D 포즈를 켜고 편집기를 적용하거나 다른 대상을 선택해 주세요.`;
        }
        render();
        return;
      }
      const next = snapshot();
      const reference = next.references[index];
      reference.target_type = choice.type === "auto_pose" ? "pose" : choice.type;
      if (choice.type === "global") delete reference.target_id;
      else reference.target_id = choice.id;
      commitReferences(next);
    });
    row.target.addEventListener("focus", () => {
      const index = currentIndex();
      if (index >= 0) renderTargetSelector(row, saved.references[index]);
    });
    const commitStrength = () => {
      const index = currentIndex();
      if (index < 0 || !available() || uploading) return;
      const raw = row.strength.value.trim() ? row.strength.value : saved.references[index].strength;
      commitReference(index, { strength: raw });
    };
    row.strength.addEventListener("change", commitStrength);
    row.strength.addEventListener("blur", commitStrength);
    row.strength.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      commitStrength();
    });
  }

  function commitShared(input, key) {
    if (!available() || uploading) return;
    const raw = input.value.trim() ? input.value : saved[key];
    commitRoot({ [key]: raw });
  }

  for (const [input, key] of [[fidelityInput, "fidelity"], [megapixelsInput, "ref_megapixels"]]) {
    input.addEventListener("change", () => commitShared(input, key));
    input.addEventListener("blur", () => commitShared(input, key));
    input.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      commitShared(input, key);
    });
  }

  function cloneRow(index) {
    const clone = rowTemplate.cloneNode(true);
    clone.querySelector("#animaReferenceAdd").remove();
    rowsContainer.appendChild(clone);
    const row = collectRow(clone);
    identifyRow(row, index);
    row.file.value = "";
    bindRow(row);
    rows.push(row);
    rowTokens.push(rowSeq++);
    previewUrls.push("");
    return row;
  }

  function syncRowCount() {
    while (rows.length < saved.references.length) cloneRow(rows.length);
    while (rows.length > saved.references.length) {
      const removed = rows.pop();
      removed.root.remove();
      rowTokens.pop();
      previewUrls.pop();
    }
    while (previewUrls.length < saved.references.length) previewUrls.push("");
    while (previewUrls.length > saved.references.length) previewUrls.pop();
    while (rowTokens.length < saved.references.length) rowTokens.push(rowSeq++);
    while (rowTokens.length > saved.references.length) rowTokens.pop();
  }

  function render({ resetNumericInputs = false } = {}) {
    syncRowCount();
    const multi = saved.references.length > 1;
    const populated = saved.references.filter(entry => typeof entry.image_name === "string" && entry.image_name).length;
    panel.hidden = availability.experimental !== true || currentGenerationEngine() !== "anima";
    panel.classList.toggle("is-enabled", saved.enabled);
    const locked = !available() || uploading;
    toggle.disabled = !dependenciesReady() || !consent || uploading || savingConsent;
    forecast.disabled = locked;
    forecast.value = saved.experimental_forecast ? "on" : "off";
    fidelityInput.disabled = locked;
    megapixelsInput.disabled = locked;
    if (resetNumericInputs || document.activeElement !== fidelityInput) fidelityInput.value = String(saved.fidelity);
    if (resetNumericInputs || document.activeElement !== megapixelsInput) megapixelsInput.value = String(saved.ref_megapixels);
    if (addButton) addButton.disabled = locked || saved.references.length >= MAX_REFERENCES;
    rows.forEach((row, index) => {
      const ref = saved.references[index] || { image_name: "", strength: 0 };
      row.dropZone.disabled = locked;
      row.file.disabled = locked;
      row.mode.disabled = locked;
      row.strength.disabled = locked;
      row.target.disabled = locked;
      row.rowRemove.disabled = locked;
      row.remove.disabled = locked || !ref.image_name;
      row.remove.hidden = !ref.image_name;
      row.rowRemove.hidden = index === 0 || saved.references.length <= 1;
      row.dropZone.classList.toggle("has-image", Boolean(ref.image_name));
      row.dropZone.setAttribute("aria-label", ref.image_name ? "레퍼런스 이미지 변경" : "레퍼런스 이미지 선택");
      toggle.classList.toggle("on", saved.enabled);
      toggle.setAttribute("aria-pressed", String(saved.enabled));
      toggle.setAttribute("aria-label", `레퍼런스 ${saved.enabled ? "끄기" : "켜기"}`);
      row.mode.value = saved.mode;
      renderTargetSelector(row, ref);
      if (resetNumericInputs || document.activeElement !== row.strength) row.strength.value = String(ref.strength);
      row.preview.hidden = !ref.image_name;
      row.empty.hidden = Boolean(ref.image_name);
      if (ref.image_name) {
        const source = previewUrls[index] || imageUrl(ref.image_name);
        if (row.preview.getAttribute("src") !== source) row.preview.setAttribute("src", source);
      } else {
        row.preview.removeAttribute("src");
      }
    });
    if (errorMessage) status.textContent = errorMessage;
    else if (checking) status.textContent = "실험 준비 상태 확인 중…";
    else if (!dependenciesReady()) {
      const missing = Array.isArray(availability.missing) ? availability.missing.join(" / ") : "";
      status.textContent = `SnapRef 준비 필요 · ${missing || "실험 의존성을 확인해 주세요."}`;
    } else if (!consent) status.textContent = "레퍼런스 이용 조건을 확인하지 못했습니다. 새로고침해 주세요.";
    else if (!consent.accepted) status.textContent = "레퍼런스를 켜려면 이용 안내를 확인하고 동의해 주세요.";
    else if (uploading) status.textContent = "참조 이미지 업로드 중…";
    else if (saved.enabled) {
      status.textContent = populated > 0
        ? (multi ? `참조 이미지 ON · ${populated}/${saved.references.length}장` : "참조 이미지 ON")
        : "참조 이미지를 선택해 주세요.";
    } else status.textContent = "참조 이미지 OFF · 이미지와 설정은 유지됩니다.";
    status.hidden = !errorMessage && !checking && available() && !uploading;
  }

  function snapshot() {
    return structuredClone(saved);
  }

  function restore(value) {
    if (value && typeof value === "object" && !Array.isArray(value) && Array.isArray(value.references) && value.references.length > MAX_REFERENCES) return;
    closeReferenceSettings();
    if (notice.open) notice.close();
    restoreRevision += 1;
    saved = normalize(value);
    restoreEnabledAfterCheck = checking && saved.enabled;
    if (consent?.accepted !== true) saved.enabled = false;
    previewUrls = saved.references.map(entry => imageUrl(entry.image_name));
    errorMessage = "";
    render({ resetNumericInputs: true });
  }

  function forGeneration({ engine, i2i, inpaint } = {}) {
    const copy = snapshot();
    if (engine !== "anima" || !available() || i2i || inpaint) copy.enabled = false;
    return copy;
  }

  function dispatchChange() {
    window.dispatchEvent(new CustomEvent("lakis:anima-reference-change", { detail: snapshot() }));
  }

  function commitRoot(patch) {
    const next = normalize({ ...snapshot(), ...patch });
    if (JSON.stringify(next) === JSON.stringify(saved)) {
      render({ resetNumericInputs: true });
      return;
    }
    saved = next;
    errorMessage = "";
    render({ resetNumericInputs: true });
    dispatchChange();
  }

  function commitReference(index, patch) {
    if (index < 0 || !saved.references[index]) return;
    const next = snapshot();
    next.references[index] = { ...next.references[index], ...patch };
    commitReferences(next);
  }

  function commitReferences(next) {
    const normalized = normalize(next);
    if (JSON.stringify(normalized) === JSON.stringify(saved)) {
      render({ resetNumericInputs: true });
      return;
    }
    saved = normalized;
    errorMessage = "";
    render({ resetNumericInputs: true });
    dispatchChange();
  }

  function syncTargetSource(event) {
    const pose = event.type === "lakis:scene-controls-change";
    const type = pose ? "pose" : "box";
    const enabled = pose
      ? state.scene_controls?.enabled === true && state.scene_controls.toyxyz_enabled === true
      : window.LAKISAnimaRegions.snapshot().enabled === true;
    const next = snapshot();
    let changed = false;
    if (!enabled) {
      for (const reference of next.references) {
        if (reference.target_type !== type) continue;
        reference.target_type = "global";
        delete reference.target_id;
        changed = true;
      }
    }
    if (changed) commitReferences(next);
    else render();
  }

  function showMultiReferenceWarning() {
    if (window.sessionStorage.getItem(WARNING_SESSION_KEY) === "1") return;
    if (document.querySelector("#animaReferenceWarning")) return;
    const dialog = document.createElement("dialog");
    dialog.id = "animaReferenceWarning";
    dialog.className = "anima-reference-warning error-dialog-card";
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-labelledby", "animaReferenceWarningTitle");
    dialog.setAttribute("aria-describedby", "animaReferenceWarningMessage");
    const title = document.createElement("h2");
    title.id = "animaReferenceWarningTitle";
    const icon = document.createElement("span");
    icon.className = "anima-reference-warning-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "⚠︎";
    title.appendChild(icon);
    const titleText = document.createElement("span");
    titleText.textContent = "주의";
    title.appendChild(titleText);
    const message = document.createElement("p");
    message.id = "animaReferenceWarningMessage";
    message.textContent = "다중 레퍼런스 사용 시 제작 시간이 대폭 증가하고 안정성과 완성도가\n떨어질 수 있으며 ,Comfy 백엔드가 종료 될 수 있습니다.";
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.autofocus = true;
    confirm.textContent = "확인";
    const label = document.createElement("label");
    const dismiss = document.createElement("input");
    dismiss.type = "checkbox";
    const labelText = document.createElement("span");
    labelText.textContent = "다음 재실행까지 보지 않기";
    label.appendChild(labelText);
    label.appendChild(dismiss);
    dialog.appendChild(title);
    dialog.appendChild(message);
    dialog.appendChild(confirm);
    dialog.appendChild(label);
    dialog.addEventListener("cancel", event => event.preventDefault());
    confirm.addEventListener("click", () => {
      if (dismiss.checked) window.sessionStorage.setItem(WARNING_SESSION_KEY, "1");
      dialog.close();
      dialog.remove();
    });
    document.body.appendChild(dialog);
    dialog.showModal();
  }

  function addReference() {
    if (!available() || uploading || saved.references.length >= MAX_REFERENCES) return;
    closeReferenceSettings();
    const next = snapshot();
    next.references.push({ image_name: "", strength: 0 });
    saved = normalize(next);
    errorMessage = "";
    render({ resetNumericInputs: true });
    dispatchChange();
    showMultiReferenceWarning();
  }

  function removeReference(index) {
    if (index <= 0 || saved.references.length <= 1 || !saved.references[index]) return;
    if (!available() || uploading) return;
    closeReferenceSettings();
    const next = snapshot();
    next.references.splice(index, 1);
    saved = normalize(next);
    previewUrls.splice(index, 1);
    const [removed] = rows.splice(index, 1);
    if (removed) removed.root.remove();
    rowTokens.splice(index, 1);
    rows.forEach(identifyRow);
    errorMessage = "";
    render({ resetNumericInputs: true });
    dispatchChange();
  }

  function openNotice() {
    if (!consent || savingConsent || uploading || notice.open) return;
    checkbox.checked = consent.accepted;
    checkbox.disabled = consent.accepted;
    confirm.disabled = !checkbox.checked;
    cancel.disabled = false;
    consentError.hidden = true;
    notice.showModal();
  }

  checkbox.addEventListener("change", () => { confirm.disabled = savingConsent || !checkbox.checked; });
  cancel.addEventListener("click", () => { if (!savingConsent) notice.close(); });
  notice.addEventListener("cancel", event => { if (savingConsent) event.preventDefault(); });
  confirm.addEventListener("click", async () => {
    if (!notice.open || savingConsent || !checkbox.checked || !consent) return;
    if (consent.accepted) {
      notice.close();
      return;
    }
    const revision = restoreRevision;
    const policy_id = consent.policy_id;
    savingConsent = true;
    checkbox.disabled = cancel.disabled = confirm.disabled = true;
    consentError.hidden = true;
    render();
    try {
      const response = await fetch("/api/anima-reference-consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accepted: true, policy_id }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (result?.accepted !== true || result.policy_id !== policy_id) throw new Error("Consent not confirmed");
      consent = { accepted: true, policy_id };
      if (notice.open) notice.close();
      if (revision === restoreRevision && available() && currentGenerationEngine() === "anima") {
        commitRoot({ enabled: true });
      }
    } catch (error) {
      console.error("Could not save ANIMA reference consent", error);
      consentError.textContent = "동의 저장을 확인하지 못했습니다. 이용 조건이 변경되었을 수 있으니 새로고침 후 다시 시도해 주세요.";
      consentError.hidden = false;
      checkbox.checked = checkbox.disabled = cancel.disabled = false;
    } finally {
      savingConsent = false;
      render();
    }
  });
  toggle.addEventListener("click", () => {
    if (toggle.disabled) return;
    if (available()) commitRoot({ enabled: !saved.enabled });
    else openNotice();
  });
  if (addButton) addButton.addEventListener("click", addReference);

  function readDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("참조 이미지 파일을 읽지 못했습니다."));
      reader.readAsDataURL(file);
    });
  }

  async function uploadReferenceFile(file, rowIndex = 0) {
    if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= saved.references.length) return;
    if (!file || !available() || uploading) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      errorMessage = "PNG, JPEG, WebP 이미지 한 장만 선택해 주세요.";
      const target = rows[rowIndex]?.file;
      if (target) {
        target.value = "";
      }
      render();
      return;
    }
    const revision = restoreRevision;
    const token = rowTokens[rowIndex];
    if (token === undefined) return;
    uploading = true;
    errorMessage = "";
    render();
    try {
      const dataUrl = await readDataUrl(file);
      const response = await fetch("/api/anima-reference", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data_url: dataUrl }),
      });
      if (!response.ok) throw new Error(`참조 이미지 업로드 실패 (HTTP ${response.status})`);
      const result = await response.json();
      if (result.ok !== true || typeof result.image_name !== "string" || !result.image_name) {
        throw new Error(result.error || "참조 이미지 업로드에 실패했습니다.");
      }
      if (revision !== restoreRevision) return;
      const currentIndex = rowTokens.indexOf(token);
      if (currentIndex === -1 || !saved.references[currentIndex]) return;
      previewUrls[currentIndex] = result.image_url || imageUrl(result.image_name);
      const next = snapshot();
      next.references[currentIndex] = { ...next.references[currentIndex], image_name: result.image_name };
      saved = normalize(next);
      errorMessage = "";
      render({ resetNumericInputs: true });
      dispatchChange();
    } catch (error) {
      errorMessage = error.message || "참조 이미지 업로드에 실패했습니다.";
    } finally {
      uploading = false;
      for (const row of rows) {
        if (row.file) {
          row.file.value = "";
        }
      }
      render();
    }
  }

  if (firstBody) {
    const initial = collectRow(firstBody);
    identifyRow(initial, 0);
    bindRow(initial);
    rows.push(initial);
  }
  forecast.addEventListener("change", () => {
    if (available() && !uploading) commitRoot({ experimental_forecast: forecast.value === "on" });
  });
  window.LAKISAnimaReference = { snapshot, restore, forGeneration };
  window.addEventListener("lakis-generation-engine-changed", render);
  window.addEventListener("lakis:scene-controls-change", syncTargetSource);
  window.addEventListener("lakis:anima-regions-change", syncTargetSource);
  restore(state.anima_reference);

  (async () => {
    try {
      const response = await fetch("/api/anima-reference", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      defaults = normalize(result.defaults);
      availability = result;
      const record = result.consent;
      if (typeof record?.accepted === "boolean" && typeof record.policy_id === "string" && record.policy_id.trim()) {
        consent = { accepted: record.accepted, policy_id: record.policy_id };
      }
    } catch (error) {
      errorMessage = "SnapRef 준비 상태를 확인하지 못했습니다.";
      console.error("Could not load ANIMA reference availability", error);
    } finally {
      checking = false;
      saved.enabled = restoreEnabledAfterCheck && consent?.accepted === true;
      render();
    }
  })();
})();
