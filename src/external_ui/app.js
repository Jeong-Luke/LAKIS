const state = {
  generation: { mode: "detail" },
  translation_enabled: true,
  lora_enabled: true,
  composition_enabled: true,
  i2i: { enabled: false, denoise: 0.5, image_name: "", auto_size: false, image_width: 0, image_height: 0 },
  loras: [],
  camera: { x: 0, y: .35, z: -.45, roll: 0, frame_y: 0 },
  output: { width: 1536, height: 1024, seed: 579441119814924, seed_mode: "random", aspect_locked: false },
  prompt: {
    negative: "", fixed: "", general: "", quality: "", artist: "", trigger: "",
    negative_fixed: "", negative_quality: "", negative_artist: ""
  },
  model: {
    checkpoint: "anima_baseV10.safetensors",
    vae: "qwen_image_vae.safetensors",
    clip: "qwen_3_06b_base.safetensors",
    sampler: "euler_ancestral",
    scheduler: "normal",
    steps: 30,
    cfg: 5.0
  },
  node_overrides: {}
};

// The packaged application owns a dedicated ComfyUI port so it never opens a
// different portable installation that happens to be running on port 8188.
const loraManagerLink = document.querySelector('a[aria-label="LoRA Manager"]');

const COMFYUI_SEED_MAX = 1125899906842624;
const PROMPT_STORAGE_KEY = "lakis.prompt-state.v2";
const TRANSLATION_STORAGE_KEY = "lakis.prompt-translation-enabled.v1";
let loraOptions = [];
let loraInventorySignature = "";
let loraInventoryRefreshActive = false;
let generationStateSaveTimer = null;

function scheduleGenerationStateSave() {
  clearTimeout(generationStateSaveTimer);
  generationStateSaveTimer = setTimeout(async () => {
    try {
      await fetch("/api/generation-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: state.model,
          output: state.output,
          loras: state.loras,
          lora_enabled: state.lora_enabled,
          node_overrides: state.node_overrides,
        }),
      });
    } catch (error) {
      console.error("Could not persist LAKIS model configuration", error);
    }
  }, 250);
}

const previewStage = document.querySelector(".preview-stage");
const previewImage = document.querySelector("#previewImage");
const previewEmptyState = document.querySelector("#previewEmptyState");
const previewBadge = document.querySelector(".preview-badge");
const previewPromptButton = document.querySelector("#previewPromptButton");
const promptInspector = document.querySelector("#promptInspector");
const promptInspectorClose = document.querySelector("#promptInspectorClose");
const usedPositivePrompt = document.querySelector("#usedPositivePrompt");
const usedNegativePrompt = document.querySelector("#usedNegativePrompt");
const previewZoomValue = document.querySelector("#previewZoomValue");
const PREVIEW_ZOOM_MIN = 25;
const PREVIEW_ZOOM_MAX = 400;
const PREVIEW_ZOOM_STEP = 10;
let previewZoom = 100;
let previewPanX = 0;
let previewPanY = 0;
let currentPreviewPrompt = null;

function syncPreviewPromptButton() {
  previewPromptButton.hidden = previewImage.hidden || !currentPreviewPrompt;
}

function setCurrentPreviewPrompt(promptSnapshot) {
  currentPreviewPrompt = promptSnapshot && typeof promptSnapshot === "object"
    ? structuredClone(promptSnapshot)
    : null;
  syncPreviewPromptButton();
}

function joinPromptParts(promptSnapshot, keys) {
  return keys
    .map(key => String(promptSnapshot?.[key] || "").trim())
    .filter(Boolean)
    .join(", ");
}

function closePromptInspector() {
  promptInspector.hidden = true;
}

previewPromptButton.addEventListener("click", () => {
  if (!currentPreviewPrompt) return;
  usedPositivePrompt.value = joinPromptParts(currentPreviewPrompt, ["trigger", "artist", "quality", "fixed", "general", "composition"]);
  usedNegativePrompt.value = joinPromptParts(currentPreviewPrompt, ["negative_artist", "negative_quality", "negative_fixed", "negative"]);
  promptInspector.hidden = false;
  promptInspectorClose.focus();
});

promptInspectorClose.addEventListener("click", closePromptInspector);
promptInspector.addEventListener("click", event => {
  if (event.target === promptInspector) closePromptInspector();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !promptInspector.hidden) closePromptInspector();
});

function setPreviewAvailability(hasImage) {
  previewImage.hidden = !hasImage;
  previewEmptyState.hidden = hasImage;
  previewBadge.hidden = !hasImage;
  syncPreviewPromptButton();
}

previewImage.addEventListener("load", () => setPreviewAvailability(true));
previewImage.addEventListener("error", () => {
  previewImage.removeAttribute("src");
  setPreviewAvailability(false);
});
setPreviewAvailability(false);

function clampPreviewPan(scale) {
  if (scale <= 1) {
    previewPanX = 0;
    previewPanY = 0;
    return;
  }
  const maxX = previewStage.clientWidth * (scale - 1) / 2;
  const maxY = previewStage.clientHeight * (scale - 1) / 2;
  previewPanX = Math.max(-maxX, Math.min(maxX, previewPanX));
  previewPanY = Math.max(-maxY, Math.min(maxY, previewPanY));
}

function applyPreviewTransform() {
  const scale = previewZoom / 100;
  clampPreviewPan(scale);
  previewImage.style.setProperty("--preview-zoom", String(scale));
  previewImage.style.setProperty("--preview-pan-x", `${previewPanX}px`);
  previewImage.style.setProperty("--preview-pan-y", `${previewPanY}px`);
}

function setPreviewZoom(nextZoom, anchor = null) {
  const previousScale = previewZoom / 100;
  const next = Math.max(PREVIEW_ZOOM_MIN, Math.min(PREVIEW_ZOOM_MAX, Math.round(nextZoom)));
  const nextScale = next / 100;
  if (anchor && next !== previewZoom) {
    const centerX = previewStage.clientWidth / 2;
    const centerY = previewStage.clientHeight / 2;
    const offsetX = anchor.x - centerX;
    const offsetY = anchor.y - centerY;
    previewPanX = offsetX - ((offsetX - previewPanX) / previousScale) * nextScale;
    previewPanY = offsetY - ((offsetY - previewPanY) / previousScale) * nextScale;
  }
  previewZoom = next;
  applyPreviewTransform();
  previewZoomValue.textContent = `${previewZoom}%`;
  document.querySelector("#previewZoomOut").disabled = previewZoom <= PREVIEW_ZOOM_MIN;
  document.querySelector("#previewZoomIn").disabled = previewZoom >= PREVIEW_ZOOM_MAX;
}

document.querySelector("#previewZoomOut").addEventListener("click", () => setPreviewZoom(previewZoom - PREVIEW_ZOOM_STEP));
document.querySelector("#previewZoomIn").addEventListener("click", () => setPreviewZoom(previewZoom + PREVIEW_ZOOM_STEP));
previewStage.addEventListener("wheel", event => {
  event.preventDefault();
  const rect = previewStage.getBoundingClientRect();
  setPreviewZoom(previewZoom + (event.deltaY < 0 ? PREVIEW_ZOOM_STEP : -PREVIEW_ZOOM_STEP), {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  });
}, { passive: false });
previewStage.addEventListener("dblclick", () => {
  previewPanX = 0;
  previewPanY = 0;
  setPreviewZoom(100);
});
window.addEventListener("resize", applyPreviewTransform);
setPreviewZoom(100);

function renderLoras() {
  const list = document.querySelector("#loraList");
  const count = document.querySelector("#loraCount");
  list.replaceChildren();
  state.loras.forEach((lora, index) => {
    const row = document.createElement("div");
    row.className = "lora-row";

    const select = document.createElement("input");
    select.type = "search";
    select.className = "lora-select";
    select.placeholder = "로라 검색 또는 선택";
    select.autocomplete = "off";
    select.spellcheck = false;
    const optionList = document.createElement("datalist");
    optionList.id = `loraOptions${index}`;
    select.setAttribute("list", optionList.id);
    const choices = loraOptions.includes(lora.name) ? loraOptions : [lora.name, ...loraOptions];
    for (const name of choices) {
      const option = document.createElement("option");
      option.value = name;
      optionList.append(option);
    }
    select.value = lora.name;
    select.title = loraOptions.includes(lora.name) ? lora.name : `${lora.name} (파일 없음)`;
    select.addEventListener("focus", event => event.target.select());
    const commitLoraSelection = () => {
      const selectedName = select.value.trim();
      if (!loraOptions.includes(selectedName)) {
        select.value = state.loras[index].name;
        return false;
      }
      if (selectedName === state.loras[index].name) return true;
      state.loras[index].name = selectedName;
      state.loras[index].enabled = true;
      select.title = selectedName;
      scheduleGenerationStateSave();
      renderLoras();
      return true;
    };
    select.addEventListener("change", commitLoraSelection);
    select.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        commitLoraSelection();
      } else if (event.key === "Escape") {
        select.value = state.loras[index].name;
        select.blur();
      }
    });

    const strength = document.createElement("input");
    strength.type = "number";
    strength.min = "-20";
    strength.max = "20";
    strength.step = "0.05";
    strength.value = Number(lora.strength).toFixed(2);
    strength.title = "로라 강도";
    strength.addEventListener("change", event => {
      const value = Number(event.target.value);
      state.loras[index].strength = Number.isFinite(value) ? value : 1;
      event.target.value = state.loras[index].strength.toFixed(2);
      scheduleGenerationStateSave();
    });

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = `lora-switch${lora.enabled ? " on" : ""}`;
    toggle.setAttribute("aria-label", `${lora.name} ${lora.enabled ? "끄기" : "켜기"}`);
    toggle.setAttribute("aria-pressed", String(lora.enabled));
    toggle.addEventListener("click", () => {
      state.loras[index].enabled = !state.loras[index].enabled;
      scheduleGenerationStateSave();
      renderLoras();
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "lora-remove";
    remove.textContent = "×";
    remove.title = "로라 제거";
    remove.addEventListener("click", () => {
      state.loras.splice(index, 1);
      scheduleGenerationStateSave();
      renderLoras();
    });

    const orderControls = document.createElement("div");
    orderControls.className = "lora-order-controls";
    const moveUp = document.createElement("button");
    moveUp.type = "button";
    moveUp.className = "lora-order-button";
    moveUp.textContent = "▲";
    moveUp.title = "위 로라와 순서 바꾸기";
    moveUp.setAttribute("aria-label", `${lora.name || `로라 ${index + 1}`} 위로 이동`);
    moveUp.disabled = index === 0;
    moveUp.addEventListener("click", () => {
      if (index === 0) return;
      [state.loras[index - 1], state.loras[index]] = [state.loras[index], state.loras[index - 1]];
      scheduleGenerationStateSave();
      renderLoras();
    });
    const moveDown = document.createElement("button");
    moveDown.type = "button";
    moveDown.className = "lora-order-button";
    moveDown.textContent = "▼";
    moveDown.title = "아래 로라와 순서 바꾸기";
    moveDown.setAttribute("aria-label", `${lora.name || `로라 ${index + 1}`} 아래로 이동`);
    moveDown.disabled = index === state.loras.length - 1;
    moveDown.addEventListener("click", () => {
      if (index >= state.loras.length - 1) return;
      [state.loras[index], state.loras[index + 1]] = [state.loras[index + 1], state.loras[index]];
      scheduleGenerationStateSave();
      renderLoras();
    });
    orderControls.append(moveUp, moveDown);

    const rowActions = document.createElement("div");
    rowActions.className = "lora-row-actions";
    rowActions.append(remove, orderControls);

    row.append(rowActions, select, optionList, strength, toggle);
    list.append(row);
  });
  count.textContent = `(${state.loras.length})`;
}

document.querySelector("#addLoraButton").addEventListener("click", () => {
  state.loras.push({ name: "", enabled: false, strength: 1 });
  scheduleGenerationStateSave();
  renderLoras();
  document.querySelector("#loraList").lastElementChild?.scrollIntoView({ block: "nearest" });
});

document.querySelector("#allLorasToggle").addEventListener("click", event => {
  state.lora_enabled = !state.lora_enabled;
  event.currentTarget.classList.toggle("on", state.lora_enabled);
  event.currentTarget.setAttribute("aria-pressed", String(state.lora_enabled));
  event.currentTarget.setAttribute("aria-label", `전체 로라 ${state.lora_enabled ? "끄기" : "켜기"}`);
  document.querySelector("#loraList").classList.toggle("all-disabled", !state.lora_enabled);
  scheduleGenerationStateSave();
});

const modeButtons = [...document.querySelectorAll(".mode-option")];
const cameraCanvas = document.querySelector("#cameraCanvas");
const cameraStatus = document.querySelector("#cameraStatus");
const clamp = value => Math.max(-1, Math.min(1, Number(value)));
const WIDTH = 560;
const HEIGHT = 360;
const dpr = Math.min(window.devicePixelRatio || 1, 2);
cameraCanvas.width = WIDTH * dpr;
cameraCanvas.height = HEIGHT * dpr;
const cameraContext = cameraCanvas.getContext("2d");
cameraContext.scale(dpr, dpr);
let viewYaw = 0;
let viewPitch = .42;

function project3d(x, y, z) {
  const cosine = Math.cos(viewYaw);
  const sine = Math.sin(viewYaw);
  const horizontal = x * cosine + z * sine;
  const depth = -x * sine + z * cosine;
  const scale = 78;
  return {
    x: WIDTH / 2 + horizontal * scale,
    y: HEIGHT / 2 - (y - .7) * scale * Math.cos(viewPitch) + depth * scale * Math.sin(viewPitch)
  };
}

function drawOrbit(radius, elevation, color, dashed = true) {
  cameraContext.beginPath();
  for (let index = 0; index <= 80; index++) {
    const angle = index / 80 * Math.PI * 2;
    const point = project3d(radius * Math.sin(angle), elevation, radius * Math.cos(angle));
    index ? cameraContext.lineTo(point.x, point.y) : cameraContext.moveTo(point.x, point.y);
  }
  cameraContext.strokeStyle = color;
  cameraContext.lineWidth = 1.8;
  cameraContext.setLineDash(dashed ? [5,7] : []);
  cameraContext.stroke();
  cameraContext.setLineDash([]);
}

function drawVerticalOrbit(radius, azimuth, color) {
  cameraContext.beginPath();
  for (let index = 0; index <= 80; index++) {
    const angle = index / 80 * Math.PI * 2;
    const horizontal = radius * Math.cos(angle);
    const point = project3d(horizontal * Math.sin(azimuth), .7 + radius * Math.sin(angle), horizontal * Math.cos(azimuth));
    index ? cameraContext.lineTo(point.x, point.y) : cameraContext.moveTo(point.x, point.y);
  }
  cameraContext.strokeStyle = color;
  cameraContext.lineWidth = 1.8;
  cameraContext.setLineDash([5,7]);
  cameraContext.stroke();
  cameraContext.setLineDash([]);
}

function drawElevationOrbit(radius, elevation, color) {
  const horizontal = radius * Math.cos(elevation);
  const height = .7 + radius * Math.sin(elevation);
  cameraContext.beginPath();
  for (let index = 0; index <= 80; index++) {
    const angle = index / 80 * Math.PI * 2;
    const point = project3d(horizontal * Math.sin(angle), height, horizontal * Math.cos(angle));
    index ? cameraContext.lineTo(point.x, point.y) : cameraContext.moveTo(point.x, point.y);
  }
  cameraContext.strokeStyle = color;
  cameraContext.lineWidth = 1.4;
  cameraContext.setLineDash([3,7]);
  cameraContext.stroke();
  cameraContext.setLineDash([]);
}

function drawMarker(x, y, z, label) {
  const point = project3d(x,y,z);
  cameraContext.fillStyle = "#75d9e9";
  cameraContext.beginPath();
  cameraContext.arc(point.x,point.y,5,0,Math.PI*2);
  cameraContext.fill();
  cameraContext.fillStyle = "#eef8ff";
  cameraContext.font = "700 13px Consolas";
  cameraContext.textAlign = "center";
  cameraContext.fillText(label,point.x,point.y-10);
}

function drawCamera3d() {
  const ctx = cameraContext;
  ctx.clearRect(0,0,WIDTH,HEIGHT);
  const background = ctx.createLinearGradient(0,0,0,HEIGHT);
  background.addColorStop(0,"#151a20");
  background.addColorStop(1,"#222932");
  ctx.fillStyle = background;
  ctx.fillRect(0,0,WIDTH,HEIGHT);
  const radius = 1.7 - .7 * state.camera.z;
  const angle = state.camera.x * Math.PI;
  const elevation = state.camera.y * Math.PI / 2;
  drawOrbit(radius,.7,"rgba(74,201,217,.34)");
  drawVerticalOrbit(radius,angle,"rgba(255,137,75,.38)");
  drawElevationOrbit(radius,elevation,"rgba(111,215,235,.25)");
  const horizontal = radius * Math.cos(elevation);
  const camera = {x:horizontal*Math.sin(angle),y:.7+radius*Math.sin(elevation),z:horizontal*Math.cos(angle)};
  drawMarker(0,.7,radius,"F"); drawMarker(0,.7,-radius,"B"); drawMarker(radius,.7,0,"L"); drawMarker(-radius,.7,0,"R");
  const center = project3d(0,.7,0);
  const cameraPoint = project3d(camera.x,camera.y,camera.z);
  ctx.strokeStyle = "rgba(255,210,103,.7)";
  ctx.setLineDash([5,6]); ctx.beginPath(); ctx.moveTo(center.x,center.y); ctx.lineTo(cameraPoint.x,cameraPoint.y); ctx.stroke(); ctx.setLineDash([]);
  ctx.save();
  ctx.translate(center.x, center.y);
  ctx.scale(1.7, 1.7);
  ctx.shadowColor = "rgba(83,211,226,.72)";
  ctx.shadowBlur = 12;
  const personGradient = ctx.createLinearGradient(-8,-16,9,17);
  personGradient.addColorStop(0,"#e8ffff");
  personGradient.addColorStop(.45,"#73d9e5");
  personGradient.addColorStop(1,"#2d7885");
  ctx.fillStyle = personGradient;
  ctx.strokeStyle = "rgba(221,255,255,.72)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(0,-11,5,0,Math.PI*2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(-7,-4);
  ctx.quadraticCurveTo(0,-8,7,-4);
  ctx.lineTo(5,7);
  ctx.lineTo(3,7);
  ctx.lineTo(3,16);
  ctx.lineTo(0,16);
  ctx.lineTo(0,8);
  ctx.lineTo(-3,16);
  ctx.lineTo(-6,16);
  ctx.lineTo(-4,7);
  ctx.lineTo(-6,7);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
  ctx.save(); ctx.translate(cameraPoint.x,cameraPoint.y); ctx.rotate(Math.atan2(center.y-cameraPoint.y,center.x-cameraPoint.x)+state.camera.roll*Math.PI/4);
  ctx.fillStyle="#ff9555"; ctx.fillRect(-13,-8,26,16); ctx.fillStyle="#10151b"; ctx.beginPath(); ctx.arc(6,0,5,0,Math.PI*2); ctx.fill(); ctx.restore();
  const degrees = Math.round(state.camera.x*180);
  cameraStatus.textContent = Math.abs(state.camera.x)>.85 ? "뒤" : state.camera.x<-.05 ? `왼쪽 ${Math.abs(degrees)}°` : state.camera.x>.05 ? `오른쪽 ${degrees}°` : "정면 0°";
}

function renderCamera() {
  const { x, y, z, roll, frame_y } = state.camera;
  for (const [id, value] of [["cameraX",x],["cameraY",y],["cameraZ",z],["cameraRoll",roll]]) {
    document.querySelector(`#${id}`).value = value.toFixed(2);
  }
  document.querySelector("#cameraXSlider").value = x;
  document.querySelector("#cameraYSlider").value = y;
  document.querySelector("#cameraZSlider").value = z;
  document.querySelector("#frameYSlider").value = frame_y;
  document.querySelector("#cameraRollSlider").value = roll;
  document.querySelector("#frameYInput").value = frame_y.toFixed(2);
  drawCamera3d();
}

function render() {
  modeButtons.forEach(button => button.classList.toggle("active", button.dataset.mode === state.generation.mode));
  const detail = state.generation.mode === "detail";
  const generationActionRow = document.querySelector(".generation-action-row");
  generationActionRow.classList.toggle("mode-fast", !detail);
  generationActionRow.classList.toggle("mode-detail", detail);
  document.querySelector("#detailContract").innerHTML = `<span class="contract-dot ${detail ? "on" : ""}"></span>Face · Eye · USDU ${detail ? "ON" : "OFF"}`;
  document.querySelector("#timeEstimate").textContent = detail ? "1분 이상" : "약 1분";
  document.querySelector("#generateHint").textContent = `${detail ? "DETAIL" : "FAST"} · COMPOSITION READY`;
  renderCamera();
}

modeButtons.forEach(button => button.addEventListener("click", () => {
  state.generation.mode = button.dataset.mode;
  render();
}));

function canvasPoint(event) {
  const rect = cameraCanvas.getBoundingClientRect();
  return {x:(event.clientX-rect.left)*WIDTH/rect.width,y:(event.clientY-rect.top)*HEIGHT/rect.height};
}
let cameraDrag = null;
cameraCanvas.addEventListener("pointerdown", event => {
  event.preventDefault();
  cameraCanvas.setPointerCapture(event.pointerId);
  const point=canvasPoint(event);
  cameraDrag={mode:event.button===2||event.altKey?"view":"camera",pointerId:event.pointerId,x:point.x,y:point.y,posX:state.camera.x,posY:state.camera.y,viewYaw,viewPitch};
  cameraCanvas.style.cursor=cameraDrag.mode==="view"?"move":"grabbing";
});
cameraCanvas.addEventListener("pointermove", event => {
  if(!cameraDrag||cameraDrag.pointerId!==event.pointerId)return;
  const point=canvasPoint(event);
  if(cameraDrag.mode==="view"){
    viewYaw=cameraDrag.viewYaw-(point.x-cameraDrag.x)/WIDTH*Math.PI*2;
    viewPitch=Math.max(.12,Math.min(1.15,cameraDrag.viewPitch+(point.y-cameraDrag.y)/HEIGHT*1.5));
  }else{
    let value=cameraDrag.posX+(point.x-cameraDrag.x)/(WIDTH/2);
    while(value>1)value-=2; while(value<-1)value+=2;
    state.camera.x=value;
    state.camera.y=clamp(cameraDrag.posY-(point.y-cameraDrag.y)/(HEIGHT/2));
  }
  renderCamera();
});
function stopCameraDrag(event){if(!cameraDrag||cameraDrag.pointerId!==event.pointerId)return;cameraDrag=null;cameraCanvas.style.cursor="crosshair";}
cameraCanvas.addEventListener("pointerup",stopCameraDrag);
cameraCanvas.addEventListener("pointercancel",stopCameraDrag);
cameraCanvas.addEventListener("contextmenu",event=>event.preventDefault());
cameraCanvas.addEventListener("wheel", event => {
  event.preventDefault();
  const amount=event.deltaY*.0003;
  if(event.shiftKey)state.camera.roll=clamp(state.camera.roll-amount*3);
  else state.camera.z=clamp(state.camera.z-amount);
  renderCamera();
}, { passive:false });
cameraCanvas.addEventListener("dblclick",event=>{if(event.shiftKey){viewYaw=0;viewPitch=.42;}else{state.camera.x=0;state.camera.y=0;}renderCamera();});
cameraCanvas.addEventListener("keydown", event => {
  const delta = event.shiftKey ? .1 : .02;
  if (["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(event.key)) event.preventDefault();
  if (event.key === "ArrowLeft") state.camera.x = clamp(state.camera.x - delta);
  if (event.key === "ArrowRight") state.camera.x = clamp(state.camera.x + delta);
  if (event.key === "ArrowUp") state.camera.y = clamp(state.camera.y + delta);
  if (event.key === "ArrowDown") state.camera.y = clamp(state.camera.y - delta);
  renderCamera();
});

// Superseded by the source-faithful LightMap mockup module loaded by index.html.
if (false) {
const lightOrbitCanvas = document.querySelector("#lightOrbitCanvas");
const lightOrbitStatus = document.querySelector("#lightOrbitStatus");
const lightState = { azimuth: Math.PI, elevation: 0, x: 0, y: 0, z: -1, intensity: .8, ambient: .2, shadow: .65, exposure: 0, rim: 0, color: "Neutral" };
let lightDrag = null;
let lightViewYaw = 0;
let lightViewPitch = .42;
let lightMockEnabled = true;

function updateLightVector() {
  const horizontal = Math.cos(lightState.elevation);
  lightState.x = horizontal * Math.sin(lightState.azimuth);
  lightState.y = Math.sin(lightState.elevation);
  lightState.z = horizontal * Math.cos(lightState.azimuth);
  syncLightMockControls();
}

function syncLightMockControls() {
  for (const [key, sliderId, numberId] of [
    ["x", "lightXSlider", "lightX"], ["y", "lightYSlider", "lightY"], ["z", "lightZSlider", "lightZ"],
    ["intensity", "lightIntensitySlider", "lightIntensity"], ["ambient", "lightAmbientSlider", "lightAmbient"],
    ["shadow", "lightShadowSlider", "lightShadow"], ["exposure", "lightExposureSlider", "lightExposure"],
    ["rim", "lightRimSlider", "lightRim"]
  ]) {
    document.querySelector(`#${sliderId}`).value = lightState[key];
    document.querySelector(`#${numberId}`).value = Number(lightState[key]).toFixed(2);
  }
  document.querySelector("#lightColor").value = lightState.color;
}

function lightDirectionName() {
  const { x, y, z } = lightState;
  const axes = [
    [Math.abs(x), x >= 0 ? "왼쪽" : "오른쪽"],
    [Math.abs(y), y >= 0 ? "상단" : "하단"],
    [Math.abs(z), z >= 0 ? "정면" : "후면"]
  ];
  return axes.sort((a, b) => b[0] - a[0])[0][1];
}

function drawLightOrbit() {
  const rect = lightOrbitCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.round(rect.width);
  const height = Math.round(rect.height);
  const pixelWidth = Math.round(width * ratio);
  const pixelHeight = Math.round(height * ratio);
  if (lightOrbitCanvas.width !== pixelWidth || lightOrbitCanvas.height !== pixelHeight) {
    lightOrbitCanvas.width = pixelWidth;
    lightOrbitCanvas.height = pixelHeight;
  }
  const ctx = lightOrbitCanvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const cx = width / 2;
  const cy = height / 2 - 3;
  const radius = Math.min(width * .34, height * .36);

  const project = (x, y, z) => {
    const cosYaw = Math.cos(lightViewYaw);
    const sinYaw = Math.sin(lightViewYaw);
    const horizontal = x * cosYaw + z * sinYaw;
    const depth = -x * sinYaw + z * cosYaw;
    return {
      x: cx + horizontal * radius,
      y: cy - y * radius * Math.cos(lightViewPitch) + depth * radius * Math.sin(lightViewPitch),
      depth: depth * Math.cos(lightViewPitch) + y * Math.sin(lightViewPitch)
    };
  };
  const ring = (pointAt, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([4,5]);
    ctx.beginPath();
    for (let index = 0; index <= 96; index += 1) {
      const point = project(...pointAt(index / 96 * Math.PI * 2));
      index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y);
    }
    ctx.stroke();
  };
  ring(angle => [Math.sin(angle),0,Math.cos(angle)], "rgba(74,201,217,.46)");
  ring(angle => [0,Math.sin(angle),Math.cos(angle)], "rgba(255,151,83,.34)");
  ring(angle => [Math.sin(angle),Math.cos(angle),0], "rgba(111,215,235,.23)");
  ctx.setLineDash([]);
  ctx.fillStyle = "#c7d7e5";
  ctx.font = "700 9px Consolas,monospace";
  ctx.textAlign = "center";
  for (const [label, vector] of [["R",[-1,0,0]],["L",[1,0,0]],["B",[0,0,-1]],["F",[0,0,1]]]) {
    const marker = project(...vector);
    ctx.fillText(label, marker.x, marker.y - 6);
  }

  const depthScale = .48 + .52 * ((lightState.z + 1) / 2);
  const knobPoint = project(lightState.x, lightState.y, lightState.z);
  const knobX = knobPoint.x;
  const knobY = knobPoint.y;
  const line = ctx.createLinearGradient(cx, cy, knobX, knobY);
  line.addColorStop(0, "rgba(120,211,229,.18)");
  line.addColorStop(1, "rgba(255,210,103,.78)");
  ctx.strokeStyle = line;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(knobX, knobY);
  ctx.stroke();

  const subjectGlow = ctx.createRadialGradient(cx - 3, cy - 4, 2, cx, cy, 15);
  subjectGlow.addColorStop(0, "#d9ffff");
  subjectGlow.addColorStop(1, "#348a96");
  ctx.fillStyle = subjectGlow;
  ctx.beginPath();
  ctx.arc(cx, cy, 13, 0, Math.PI * 2);
  ctx.fill();

  const knobRadius = 8 + depthScale * 3;
  const glow = ctx.createRadialGradient(knobX - 3, knobY - 4, 1, knobX, knobY, knobRadius * 2.3);
  glow.addColorStop(0, "#fffbe0");
  glow.addColorStop(.35, "#ffd267");
  glow.addColorStop(1, "rgba(255,190,67,0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(knobX, knobY, knobRadius * 2.3, 0, Math.PI * 2);
  ctx.fill();
  ctx.save();
  ctx.translate(knobX, knobY);
  ctx.strokeStyle = "#ffd267";
  ctx.lineWidth = 1.5;
  for (let index = 0; index < 8; index += 1) {
    ctx.rotate(Math.PI / 4);
    ctx.beginPath();
    ctx.moveTo(0, -knobRadius - 4);
    ctx.lineTo(0, -knobRadius - 8);
    ctx.stroke();
  }
  ctx.rotate(Math.PI / 4);
  ctx.fillStyle = "#ffd267";
  ctx.strokeStyle = "#fff7cf";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, -knobRadius);
  ctx.lineTo(knobRadius * .78, 0);
  ctx.lineTo(0, knobRadius);
  ctx.lineTo(-knobRadius * .78, 0);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#fffbe0";
  ctx.beginPath();
  ctx.arc(0, 0, 2.6, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  lightOrbitStatus.textContent = `${lightDirectionName()} · X ${lightState.x.toFixed(2)} Y ${lightState.y.toFixed(2)} Z ${lightState.z.toFixed(2)}`;
}

lightOrbitCanvas.addEventListener("pointerdown", event => {
  event.preventDefault();
  lightOrbitCanvas.setPointerCapture(event.pointerId);
  lightDrag = { mode: event.button === 2 || event.altKey ? "view" : "light", pointerId: event.pointerId, x: event.clientX, y: event.clientY, azimuth: lightState.azimuth, elevation: lightState.elevation, viewYaw: lightViewYaw, viewPitch: lightViewPitch };
});
lightOrbitCanvas.addEventListener("pointermove", event => {
  if (!lightDrag || lightDrag.pointerId !== event.pointerId) return;
  const rect = lightOrbitCanvas.getBoundingClientRect();
  if (lightDrag.mode === "view") {
    lightViewYaw = lightDrag.viewYaw - (event.clientX - lightDrag.x) / Math.max(rect.width, 1) * Math.PI * 2;
    lightViewPitch = Math.max(.12, Math.min(1.15, lightDrag.viewPitch + (event.clientY - lightDrag.y) / Math.max(rect.height, 1) * 1.5));
  } else {
    lightState.azimuth = lightDrag.azimuth + (event.clientX - lightDrag.x) / Math.max(rect.width, 1) * Math.PI * 2;
    lightState.elevation = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, lightDrag.elevation - (event.clientY - lightDrag.y) / Math.max(rect.height, 1) * Math.PI));
    updateLightVector();
  }
  drawLightOrbit();
});
function stopLightDrag(event) {
  if (!lightDrag || lightDrag.pointerId !== event.pointerId) return;
  lightDrag = null;
}
lightOrbitCanvas.addEventListener("pointerup", stopLightDrag);
lightOrbitCanvas.addEventListener("pointercancel", stopLightDrag);
lightOrbitCanvas.addEventListener("contextmenu", event => event.preventDefault());
lightOrbitCanvas.addEventListener("keydown", event => {
  const delta = event.shiftKey ? .15 : .04;
  if (event.key === "ArrowLeft") lightState.azimuth -= delta;
  else if (event.key === "ArrowRight") lightState.azimuth += delta;
  else if (event.key === "ArrowUp") lightState.elevation = Math.min(Math.PI / 2, lightState.elevation + delta);
  else if (event.key === "ArrowDown") lightState.elevation = Math.max(-Math.PI / 2, lightState.elevation - delta);
  else return;
  event.preventDefault();
  updateLightVector();
  drawLightOrbit();
});
for (const [key, sliderId, numberId] of [
  ["x", "lightXSlider", "lightX"], ["y", "lightYSlider", "lightY"], ["z", "lightZSlider", "lightZ"],
  ["intensity", "lightIntensitySlider", "lightIntensity"], ["ambient", "lightAmbientSlider", "lightAmbient"],
  ["shadow", "lightShadowSlider", "lightShadow"], ["exposure", "lightExposureSlider", "lightExposure"],
  ["rim", "lightRimSlider", "lightRim"]
]) {
  const apply = event => {
    lightState[key] = Number(event.target.value);
    if (["x", "y", "z"].includes(key)) {
      const length = Math.hypot(lightState.x, lightState.y, lightState.z) || 1;
      lightState.azimuth = Math.atan2(lightState.x / length, lightState.z / length);
      lightState.elevation = Math.asin(Math.max(-1, Math.min(1, lightState.y / length)));
    }
    syncLightMockControls();
    drawLightOrbit();
  };
  document.querySelector(`#${sliderId}`).addEventListener("input", apply);
  document.querySelector(`#${numberId}`).addEventListener("change", apply);
}
document.querySelector("#lightColor").addEventListener("change", event => {
  lightState.color = event.target.value;
});
document.querySelector("#lightMockToggle").addEventListener("click", event => {
  lightMockEnabled = !lightMockEnabled;
  event.currentTarget.classList.toggle("on", lightMockEnabled);
  event.currentTarget.setAttribute("aria-pressed", String(lightMockEnabled));
  event.currentTarget.setAttribute("aria-label", `광원 설정 목업 ${lightMockEnabled ? "끄기" : "켜기"}`);
  document.querySelector("#lightMockControls").classList.toggle("is-disabled", !lightMockEnabled);
});
document.querySelector("#lightMockReset").addEventListener("click", () => {
  Object.assign(lightState, { azimuth: Math.PI, elevation: 0, x: 0, y: 0, z: -1, intensity: .8, ambient: .2, shadow: .65, exposure: 0, rim: 0, color: "Neutral" });
  lightViewYaw = 0;
  lightViewPitch = .42;
  syncLightMockControls();
  drawLightOrbit();
});
new ResizeObserver(drawLightOrbit).observe(lightOrbitCanvas);
updateLightVector();
drawLightOrbit();
}

for (const [id,key] of [["cameraX","x"],["cameraY","y"],["cameraZ","z"],["cameraRoll","roll"]]) {
  document.querySelector(`#${id}`).addEventListener("change", event => {
    state.camera[key] = clamp(event.target.value);
    renderCamera();
  });
}
document.querySelector("#frameYInput").addEventListener("change", event => {
  state.camera.frame_y = clamp(event.target.value);
  renderCamera();
});
for (const [id,key] of [["cameraXSlider","x"],["cameraYSlider","y"],["cameraZSlider","z"],["frameYSlider","frame_y"],["cameraRollSlider","roll"]]) {
  document.querySelector(`#${id}`).addEventListener("input", event => {
    state.camera[key] = clamp(event.target.value);
    renderCamera();
  });
}

const cameraPresets = {
  front:{x:0,y:0,z:0,roll:0,frame_y:0},
  left:{x:.5,y:0,z:0,roll:0,frame_y:0},
  center:{x:0,y:.35,z:-.45,roll:0,frame_y:0},
  right:{x:-.5,y:0,z:0,roll:0,frame_y:0},
  rear:{x:1,y:0,z:0,roll:0,frame_y:0}
};
document.querySelectorAll("[data-camera-preset]").forEach(button => button.addEventListener("click", () => {
  state.camera = {...cameraPresets[button.dataset.cameraPreset]};
  document.querySelectorAll("[data-camera-preset]").forEach(item => item.classList.toggle("active", item === button));
  renderCamera();
}));
document.querySelector("#cameraReset").addEventListener("click", () => {
  state.camera = {...cameraPresets.center};
  document.querySelectorAll("[data-camera-preset]").forEach(item => item.classList.toggle("active", item.dataset.cameraPreset === "center"));
  renderCamera();
});

function setCompositionEnabled(enabled) {
  state.composition_enabled = Boolean(enabled);
  const toggle = document.querySelector("#compositionToggle");
  toggle.classList.toggle("on", state.composition_enabled);
  toggle.setAttribute("aria-pressed", String(state.composition_enabled));
  toggle.setAttribute("aria-label", `구도 설정 ${state.composition_enabled ? "끄기" : "켜기"}`);
  document.querySelector("#compositionControls").classList.toggle("is-disabled", !state.composition_enabled);
}

async function refreshLoraInventory() {
  if (loraInventoryRefreshActive) return false;
  loraInventoryRefreshActive = true;
  try {
    const response = await fetch("/api/lora-options", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const inventory = await response.json();
    const options = Array.isArray(inventory.options) ? inventory.options.map(String) : [];
    const signature = String(inventory.signature || JSON.stringify(options));
    if (signature === loraInventorySignature) return false;
    loraInventorySignature = signature;
    loraOptions = options;
    renderLoras();
    return true;
  } catch (error) {
    console.error("Could not refresh LoRA inventory", error);
    return false;
  } finally {
    loraInventoryRefreshActive = false;
  }
}

window.addEventListener("focus", () => refreshLoraInventory());
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshLoraInventory();
});

document.querySelector("#compositionToggle").addEventListener("click", () => {
  setCompositionEnabled(!state.composition_enabled);
});

document.querySelector("#outputFolderButton").addEventListener("click", async () => {
  const button = document.querySelector("#outputFolderButton");
  try {
    const response = await fetch("/api/open-output-folder", { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  } catch (error) {
    button.title = "LAKIS Desktop Bridge가 실행 중이 아닙니다";
    console.error("Could not open output folder through LAKIS Desktop Bridge", error);
  }
});

const workflowButton = document.querySelector("#workflowButton");
const workflowMenu = document.querySelector("#workflowMenu");
function closeWorkflowMenu() {
  workflowMenu.hidden = true;
  workflowButton.setAttribute("aria-expanded", "false");
}
workflowButton.addEventListener("click", event => {
  event.stopPropagation();
  workflowMenu.hidden = !workflowMenu.hidden;
  workflowButton.setAttribute("aria-expanded", String(!workflowMenu.hidden));
});
workflowMenu.addEventListener("click", async event => {
  const option = event.target.closest("[data-workflow-kind]");
  if (!option) return;
  const kind = option.dataset.workflowKind;
  closeWorkflowMenu();
  const workflowWindow = window.open("about:blank", "_blank");
  try {
    const response = await fetch("/api/open-workflow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
    if (workflowWindow) workflowWindow.location.replace(result.comfy_url || "http://127.0.0.1:8189/");
    else window.open(result.comfy_url || "http://127.0.0.1:8189/", "_blank", "noopener");
  } catch (error) {
    workflowWindow?.close();
    showGenerationError(error.message || "LAKIS 워크플로를 열지 못했어요.");
  }
});

let latestSystemStatus = null;
const gib = bytes => bytes ? bytes / (1024 ** 3) : 0;
function setMeter(id, used, total) {
  document.querySelector(`#${id}`).style.width = `${total ? Math.min(100, used / total * 100) : 0}%`;
}
async function refreshSystemStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const status = await response.json();
    latestSystemStatus = status;
    document.querySelector("#workflowVersion").textContent = `v${status.lakis_version || status.workflow_version}`;
    document.querySelector("#comfyStatusText").textContent = status.comfyui_running ? "실행 중" : "연결 안 됨";
    document.querySelector("#comfyStatusDot").className = `footer-dot ${status.comfyui_running ? "online" : "offline"}`;
    const vramUsed = Math.max(0, status.vram_total - status.vram_free);
    const ramUsed = Math.max(0, status.ram_total - status.ram_free);
    document.querySelector("#vramText").textContent = status.vram_total ? `${gib(vramUsed).toFixed(1)} / ${gib(status.vram_total).toFixed(0)} GB` : "-- / -- GB";
    document.querySelector("#ramText").textContent = status.ram_total ? `${gib(ramUsed).toFixed(1)} / ${gib(status.ram_total).toFixed(0)} GB` : "-- / -- GB";
    document.querySelector("#cpuText").textContent = status.cpu_percent == null ? "--%" : `${status.cpu_percent.toFixed(0)}%`;
    setMeter("vramMeter", vramUsed, status.vram_total);
    setMeter("ramMeter", ramUsed, status.ram_total);
  } catch (_) {
    document.querySelector("#comfyStatusText").textContent = "브리지 연결 안 됨";
    document.querySelector("#comfyStatusDot").className = "footer-dot offline";
  }
}
refreshSystemStatus();
setInterval(refreshSystemStatus, 3000);

document.querySelectorAll("[data-prompt-panel]").forEach(button => {
  button.addEventListener("click", () => {
    const panel = document.querySelector(`#${button.dataset.promptPanel}`);
    if (!panel.hidden) return;
    const group = button.closest("[data-prompt-group]");
    group.querySelectorAll("[data-prompt-panel]").forEach(item => {
      item.classList.remove("active");
      item.setAttribute("aria-expanded", "false");
      document.querySelector(`#${item.dataset.promptPanel}`).hidden = true;
    });
    panel.hidden = false;
    button.classList.add("active");
    button.setAttribute("aria-expanded", "true");
    panel.querySelector("textarea")?.focus();
  });
});
const promptInputBindings = [
  ["fixedPromptInput", "fixed"], ["generalPromptInput", "general"],
  ["qualityPromptInput", "quality"], ["artistPromptInput", "artist"],
  ["triggerPromptInput", "trigger"],
  ["negativeFixedPromptInput", "negative_fixed"],
  ["negativeQualityPromptInput", "negative_quality"],
  ["negativeArtistPromptInput", "negative_artist"],
  ["negativePrompt", "negative"],
];

const promptTranslationToggle = document.querySelector("#promptTranslationToggle");
try {
  const savedTranslation = localStorage.getItem(TRANSLATION_STORAGE_KEY);
  state.translation_enabled = savedTranslation === null ? true : savedTranslation === "true";
} catch (_) {
  state.translation_enabled = true;
}
promptTranslationToggle.checked = state.translation_enabled;
promptTranslationToggle.addEventListener("change", event => {
  state.translation_enabled = Boolean(event.target.checked);
  try {
    localStorage.setItem(TRANSLATION_STORAGE_KEY, String(state.translation_enabled));
  } catch (_) {}
});

const containsKoreanPrompt = value => /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/u.test(String(value || ""));

async function translatedPromptForGeneration(prompt) {
  const original = structuredClone(prompt);
  if (!state.translation_enabled || !Object.values(original).some(containsKoreanPrompt)) return original;
  const response = await fetch("/api/translate-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: original }),
  });
  const result = await response.json();
  if (!response.ok || !result.ok || !result.prompt) {
    throw new Error(result.error || "프롬프트 자동 번역에 실패했어요.");
  }
  return result.prompt;
}

function syncPromptStateFromInputs() {
  for (const [id, key] of promptInputBindings) {
    state.prompt[key] = document.querySelector(`#${id}`).value;
  }
}

function loadLocalPromptState() {
  try {
    const value = JSON.parse(localStorage.getItem(PROMPT_STORAGE_KEY) || "null");
    return value && typeof value === "object" ? value : {};
  } catch (_) {
    return {};
  }
}

function saveLocalPromptState() {
  try {
    localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(state.prompt));
  } catch (error) {
    console.error("Could not persist browser-local prompt state", error);
  }
}

let promptSaveTimer = null;
function schedulePromptStateSave() {
  clearTimeout(promptSaveTimer);
  promptSaveTimer = setTimeout(async () => {
    syncPromptStateFromInputs();
    saveLocalPromptState();
    try {
      await fetch("/api/prompt-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: state.prompt }),
      });
    } catch (error) {
      console.error("Could not persist LAKIS prompt state", error);
    }
  }, 250);
}

for (const [id, key] of promptInputBindings) {
  document.querySelector(`#${id}`).addEventListener("input", event => {
    state.prompt[key] = event.target.value;
    schedulePromptStateSave();
  });
}

for (const [id,key] of [["checkpointSelect","checkpoint"],["vaeSelect","vae"],
  ["clipSelect","clip"],["samplerSelect","sampler"],["schedulerSelect","scheduler"],
  ["stepsInput","steps"],["cfgInput","cfg"]]) {
  document.querySelector(`#${id}`).addEventListener("change", event => {
    state.model[key] = ["steps", "cfg"].includes(key) ? Number(event.target.value) : event.target.value;
    scheduleGenerationStateSave();
  });
}

function populateWorkflowSelect(id, configKey, config) {
  const select = document.querySelector(`#${id}`);
  select.replaceChildren(...config.options.map(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    return option;
  }));
  select.value = config.current;
  state.model[configKey] = config.current;
  select.title = `${config.loader_class} · ${config.options.length} options`;
}

async function refreshWorkflowConfiguration() {
  try {
    const response = await fetch("/api/workflow-config", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    if (loraManagerLink && Number(config.comfy_port)) {
      loraManagerLink.href = `http://127.0.0.1:${Number(config.comfy_port)}/loras`;
    }
    populateWorkflowSelect("checkpointSelect", "checkpoint", config.checkpoint);
    populateWorkflowSelect("vaeSelect", "vae", config.vae);
    populateWorkflowSelect("clipSelect", "clip", config.clip);
    populateWorkflowSelect("samplerSelect", "sampler", config.sampler);
    populateWorkflowSelect("schedulerSelect", "scheduler", config.scheduler);
    const savedGeneration = config.generation_state || {};
    Object.assign(state.model, savedGeneration.model || {});
    Object.assign(state.output, savedGeneration.output || {});
    state.node_overrides = savedGeneration.node_overrides && typeof savedGeneration.node_overrides === "object"
      ? structuredClone(savedGeneration.node_overrides)
      : {};
    for (const [id, key] of [["samplerSelect", "sampler"], ["schedulerSelect", "scheduler"],
      ["stepsInput", "steps"], ["cfgInput", "cfg"]]) {
      document.querySelector(`#${id}`).value = state.model[key];
    }
    for (const [id, key] of [["imageWidth", "width"], ["imageHeight", "height"], ["seedInput", "seed"]]) {
      document.querySelector(`#${id}`).value = state.output[key];
    }
    document.querySelector("#aspectRatioLock").checked = state.output.aspect_locked === true;
    lockedAspectRatio = clampImageDimension(state.output.width) / clampImageDimension(state.output.height);
    document.querySelectorAll("[data-seed-mode]").forEach(button => {
      button.classList.toggle("active", button.dataset.seedMode === state.output.seed_mode);
    });
    loraOptions = Array.isArray(config.lora?.options) ? config.lora.options : [];
    loraInventorySignature = "";
    state.lora_enabled = config.lora?.enabled !== false;
    const allLorasToggle = document.querySelector("#allLorasToggle");
    allLorasToggle.classList.toggle("on", state.lora_enabled);
    allLorasToggle.setAttribute("aria-pressed", String(state.lora_enabled));
    document.querySelector("#loraList").classList.toggle("all-disabled", !state.lora_enabled);
    state.loras = Array.isArray(config.lora?.current)
      ? config.lora.current.map(item => ({
          name: String(item.name || ""),
          enabled: Boolean(item.enabled),
          strength: Number(item.strength ?? 1),
        }))
      : [];
    renderLoras();
    refreshLoraInventory();
    const promptInputs = {
      general: "generalPromptInput", quality: "qualityPromptInput",
      artist: "artistPromptInput", trigger: "triggerPromptInput", fixed: "fixedPromptInput",
      negative: "negativePrompt", negative_quality: "negativeQualityPromptInput",
      negative_artist: "negativeArtistPromptInput", negative_fixed: "negativeFixedPromptInput",
    };
    const localPrompt = loadLocalPromptState();
    for (const [key, id] of Object.entries(promptInputs)) {
      const source = Object.prototype.hasOwnProperty.call(localPrompt, key)
        ? localPrompt[key]
        : config.prompt?.[key];
      const value = String(source || "");
      state.prompt[key] = value;
      document.querySelector(`#${id}`).value = value;
    }
    window.dispatchEvent(new CustomEvent("lakis-prompt-state-loaded"));
  } catch (error) {
    console.error("Could not load ComfyUI workflow model configuration", error);
  }
}
refreshWorkflowConfiguration();

function syncOutputStateFromInputs() {
  for (const [id, key] of [["imageWidth", "width"], ["imageHeight", "height"]]) {
    const input = document.querySelector(`#${id}`);
    const value = clampImageDimension(input.value);
    input.value = String(value);
    state.output[key] = value;
  }
  const seed = Number(document.querySelector("#seedInput").value);
  if (Number.isFinite(seed)) state.output.seed = seed;
}

const aspectRatioLock = document.querySelector("#aspectRatioLock");
const sizeInputs = {
  width: document.querySelector("#imageWidth"),
  height: document.querySelector("#imageHeight"),
};
let lockedAspectRatio = state.output.width / state.output.height;
let syncingAspectRatio = false;

function clampImageDimension(value) {
  const bounded = Math.max(64, Math.min(8192, Math.round(Number(value) || 64)));
  return Math.round(bounded / 16) * 16;
}

function syncLockedImageDimension(changedKey) {
  if (!aspectRatioLock.checked || syncingAspectRatio || !Number.isFinite(lockedAspectRatio) || lockedAspectRatio <= 0) return;
  const otherKey = changedKey === "width" ? "height" : "width";
  const changedValue = clampImageDimension(sizeInputs[changedKey].value);
  const calculated = changedKey === "width" ? changedValue / lockedAspectRatio : changedValue * lockedAspectRatio;
  // Anima/Spectrum requires an even latent width/height, so keep dimensions
  // on a 16-pixel boundary. Preserve the
  // locked ratio as closely as possible while keeping the paired value valid.
  const pairedValue = clampImageDimension(Math.round(calculated / 16) * 16);
  syncingAspectRatio = true;
  sizeInputs[otherKey].value = String(pairedValue);
  state.output[otherKey] = pairedValue;
  syncingAspectRatio = false;
}

for (const [key, input] of Object.entries(sizeInputs)) {
  input.addEventListener("input", event => {
    const value = Number(event.target.value);
    if (!Number.isFinite(value)) return;
    state.output[key] = clampImageDimension(value);
    syncLockedImageDimension(key);
    scheduleGenerationStateSave();
  });
  input.addEventListener("change", event => {
    event.target.value = String(clampImageDimension(event.target.value));
    event.target.dispatchEvent(new Event("input", { bubbles: true }));
  });
  input.addEventListener("wheel", event => {
    event.preventDefault();
    const step = Number(input.step) || 64;
    input.value = String(clampImageDimension(Number(input.value) + (event.deltaY < 0 ? step : -step)));
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, { passive: false });
}

aspectRatioLock.addEventListener("change", () => {
  state.output.aspect_locked = aspectRatioLock.checked;
  if (aspectRatioLock.checked) {
    const width = clampImageDimension(sizeInputs.width.value);
    const height = clampImageDimension(sizeInputs.height.value);
    lockedAspectRatio = width / height;
  }
  scheduleGenerationStateSave();
});

document.querySelector("#seedInput").addEventListener("input", event => {
  const value = Number(event.target.value);
  if (!Number.isFinite(value)) return;
  state.output.seed = value;
  scheduleGenerationStateSave();
});
document.querySelectorAll("[data-seed-mode]").forEach(button => button.addEventListener("click", () => {
  state.output.seed_mode = button.dataset.seedMode;
  document.querySelectorAll("[data-seed-mode]").forEach(item => item.classList.toggle("active", item === button));
  document.querySelector("#seedInput").classList.toggle("seed-locked", state.output.seed_mode === "current");
  scheduleGenerationStateSave();
}));

document.querySelector(".history-strip").addEventListener("click", event => {
  const button = event.target.closest(".history-thumb");
  if (!button) return;
  document.querySelectorAll(".history-thumb").forEach(item => item.classList.remove("selected"));
  button.classList.add("selected");
  document.querySelector("#previewImage").src = button.querySelector("img").src;
  setCurrentPreviewPrompt(button._lakisPrompt || null);
  if (button.dataset.mode) {
    document.querySelector("#previewMode").textContent = button.dataset.mode.toUpperCase();
  }
  document.querySelector("#previewI2i").hidden = button.dataset.i2i !== "true";
  if (button.dataset.seed) {
    document.querySelector("#previewSeed").textContent = `SEED ${button.dataset.seed}`;
  }
  const durationBadge = document.querySelector("#previewDuration");
  if (button.dataset.duration) {
    durationBadge.textContent = `${Number(button.dataset.duration).toFixed(1)}초`;
    durationBadge.hidden = false;
  } else {
    durationBadge.hidden = true;
  }
  if (state.output.seed_mode === "current" && button.dataset.seed) {
    state.output.seed = Number(button.dataset.seed);
    document.querySelector("#seedInput").value = state.output.seed;
  }
});

const i2iToggle = document.querySelector("#i2iToggle");
const i2iFileInput = document.querySelector("#i2iFileInput");
const i2iDropZone = document.querySelector("#i2iDropZone");
const i2iPreview = document.querySelector("#i2iPreview");
const i2iPlaceholder = document.querySelector("#i2iPlaceholder");
const i2iDenoise = document.querySelector("#i2iDenoise");
const i2iDenoiseNumber = document.querySelector("#i2iDenoiseNumber");
const i2iRemove = document.querySelector("#i2iRemove");
const i2iStatus = document.querySelector("#i2iStatus");
const i2iAutoSize = document.querySelector("#i2iAutoSize");
const imageWidthInput = document.querySelector("#imageWidth");
const imageHeightInput = document.querySelector("#imageHeight");
let manualI2iSize = { width: Number(imageWidthInput.value), height: Number(imageHeightInput.value) };

function setModelImageSize(width, height) {
  const safeWidth = clampImageDimension(width);
  const safeHeight = clampImageDimension(height);
  if (aspectRatioLock.checked && safeWidth > 0 && safeHeight > 0) {
    lockedAspectRatio = safeWidth / safeHeight;
  }
  syncingAspectRatio = true;
  imageWidthInput.value = String(safeWidth);
  imageHeightInput.value = String(safeHeight);
  imageWidthInput.dispatchEvent(new Event("input", { bubbles: true }));
  imageHeightInput.dispatchEvent(new Event("input", { bubbles: true }));
  syncingAspectRatio = false;
}

function applyI2iAutoSize() {
  if (!state.i2i.auto_size || !state.i2i.image_width || !state.i2i.image_height) return;
  setModelImageSize(state.i2i.image_width, state.i2i.image_height);
}

function readImageDimensions(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => reject(new Error("이미지 크기를 확인하지 못했어요."));
    image.src = dataUrl;
  });
}

function setI2iEnabled(enabled) {
  const wasEnabled = state.i2i.enabled;
  state.i2i.enabled = Boolean(enabled);
  if (state.i2i.enabled) {
    setCompositionEnabled(false);
    if (!wasEnabled) showI2iCompositionNotice();
  }
  i2iToggle.classList.toggle("on", state.i2i.enabled);
  i2iToggle.setAttribute("aria-pressed", String(state.i2i.enabled));
  i2iToggle.setAttribute("aria-label", state.i2i.enabled ? "Image to Image 끄기" : "Image to Image 켜기");
  document.querySelector(".i2i-panel").classList.toggle("is-disabled", !state.i2i.enabled);
}

let i2iNoticeTimer = null;
function showI2iCompositionNotice() {
  const notice = document.querySelector("#i2iCompositionNotice");
  clearTimeout(i2iNoticeTimer);
  notice.hidden = false;
  requestAnimationFrame(() => notice.classList.add("visible"));
  i2iNoticeTimer = setTimeout(() => {
    notice.classList.remove("visible");
    setTimeout(() => { notice.hidden = true; }, 180);
  }, 3200);
}

async function uploadI2iFile(file) {
  if (!file || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    i2iStatus.textContent = "PNG, JPEG 또는 WebP 이미지를 선택해 주세요.";
    return;
  }
  if (file.size > 32 * 1024 * 1024) {
    i2iStatus.textContent = "입력 이미지는 32MB 이하여야 합니다.";
    return;
  }
  i2iStatus.textContent = "입력 이미지 준비 중…";
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("이미지를 읽지 못했어요."));
    reader.readAsDataURL(file);
  });
  try {
    const dimensions = await readImageDimensions(dataUrl);
    const response = await fetch("/api/i2i-image", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data_url: dataUrl }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "이미지 업로드 실패");
    state.i2i.image_name = result.image_name;
    state.i2i.image_width = dimensions.width;
    state.i2i.image_height = dimensions.height;
    i2iPreview.src = dataUrl;
    i2iPreview.hidden = false;
    i2iPlaceholder.hidden = true;
    i2iRemove.disabled = false;
    setI2iEnabled(state.i2i.enabled);
    applyI2iAutoSize();
    i2iStatus.textContent = "원본 이미지 크기 자동 입력하기";
  } catch (error) {
    setI2iEnabled(false);
    i2iStatus.textContent = error.message || "입력 이미지를 준비하지 못했어요.";
  }
}

i2iToggle.addEventListener("click", () => {
  setI2iEnabled(!state.i2i.enabled);
  i2iStatus.textContent = "원본 이미지 크기 자동 입력하기";
});
i2iAutoSize.addEventListener("change", () => {
  state.i2i.auto_size = i2iAutoSize.checked;
  if (state.i2i.auto_size) {
    manualI2iSize = { width: Number(imageWidthInput.value), height: Number(imageHeightInput.value) };
    applyI2iAutoSize();
  } else {
    setModelImageSize(manualI2iSize.width, manualI2iSize.height);
  }
});
i2iDropZone.addEventListener("click", event => {
  if (!event.target.closest("#i2iRemove")) i2iFileInput.click();
});
i2iDropZone.addEventListener("keydown", event => {
  if ((event.key === "Enter" || event.key === " ") && !event.target.closest("#i2iRemove")) {
    event.preventDefault();
    i2iFileInput.click();
  }
});
i2iFileInput.addEventListener("change", () => uploadI2iFile(i2iFileInput.files?.[0]));
for (const eventName of ["dragenter", "dragover"]) i2iDropZone.addEventListener(eventName, event => {
  event.preventDefault(); i2iDropZone.classList.add("is-dragging");
});
for (const eventName of ["dragleave", "drop"]) i2iDropZone.addEventListener(eventName, event => {
  event.preventDefault(); i2iDropZone.classList.remove("is-dragging");
});
i2iDropZone.addEventListener("drop", event => uploadI2iFile(event.dataTransfer?.files?.[0]));
i2iDenoise.addEventListener("input", () => {
  state.i2i.denoise = Number(i2iDenoise.value);
  i2iDenoiseNumber.value = state.i2i.denoise.toFixed(2);
});
i2iDenoiseNumber.addEventListener("input", () => {
  const value = Math.min(1, Math.max(0, Number(i2iDenoiseNumber.value)));
  if (!Number.isFinite(value)) return;
  state.i2i.denoise = value;
  i2iDenoise.value = String(value);
});
i2iDenoiseNumber.addEventListener("change", () => {
  const value = Math.min(1, Math.max(0, Number(i2iDenoiseNumber.value) || 0));
  state.i2i.denoise = value;
  i2iDenoise.value = String(value);
  i2iDenoiseNumber.value = value.toFixed(2);
});
i2iRemove.addEventListener("click", event => {
  event.stopPropagation();
  state.i2i.image_name = ""; setI2iEnabled(false);
  state.i2i.image_width = 0; state.i2i.image_height = 0;
  if (state.i2i.auto_size) setModelImageSize(manualI2iSize.width, manualI2iSize.height);
  state.i2i.auto_size = false; i2iAutoSize.checked = false;
  i2iPreview.removeAttribute("src"); i2iPreview.hidden = true; i2iPlaceholder.hidden = false;
  i2iRemove.disabled = true; i2iFileInput.value = "";
  i2iStatus.textContent = "원본 이미지 크기 자동 입력하기";
});
setI2iEnabled(false);

const generateButton = document.querySelector("#generateButton");
const generateButtonLabel = generateButton.querySelector("span");
const generateButtonHint = document.querySelector("#generateHint");
const errorDialog = document.querySelector("#errorDialog");
const errorDialogMessage = document.querySelector("#errorDialogMessage");
let generationActive = false;
let generationCancelRequested = false;
let lastPreviewRevision = 0;
let previewObjectUrl = null;
let generationResetTimer = null;
let generationSubmissionPending = false;

async function refreshGenerationPreview(revision) {
  if (!revision || revision === lastPreviewRevision) return;
  const response = await fetch(`/api/generation-preview?r=${revision}`, { cache: "no-store" });
  lastPreviewRevision = revision;
  if (response.status === 204 || !response.ok) return;
  const blob = await response.blob();
  const nextUrl = URL.createObjectURL(blob);
  document.querySelector("#previewImage").src = nextUrl;
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = nextUrl;
}

function setGenerationProgress(percent, stage = "최종 이미지 생성 중") {
  if (generationResetTimer) {
    clearTimeout(generationResetTimer);
    generationResetTimer = null;
  }
  const progress = Math.max(0, Math.min(100, Number(percent) || 0));
  const phase = String(stage || "")
    .replace(/^생성 중\s*·\s*/, "")
    .replace(/^생성 중$/, "준비")
    .trim() || "처리";
  generationActive = progress < 100;
  generateButton.style.setProperty("--generation-progress", `${progress}%`);
  generateButton.classList.toggle("is-generating", progress < 100);
  generateButton.classList.toggle("is-complete", progress >= 100);
  generateButtonLabel.textContent = progress >= 100 ? "완료" : "제작 중";
  generateButtonHint.textContent = progress >= 100 ? "100%" : `${phase} · ${Math.round(progress)}%`;
}

function resetGenerationButton() {
  if (generationResetTimer) {
    clearTimeout(generationResetTimer);
    generationResetTimer = null;
  }
  generationActive = false;
  generationCancelRequested = false;
  generateButton.style.setProperty("--generation-progress", "0%");
  generateButton.classList.remove("is-generating", "is-complete", "is-cancelling");
  generateButtonLabel.textContent = "제작하기";
  generateButtonHint.textContent = `${state.generation.mode === "detail" ? "DETAIL" : "FAST"} · COMPOSITION READY`;
}

let lastErrorReport = null;

function showGenerationError(message, errorCode = "", context = {}) {
  resetGenerationButton();
  const code = String(errorCode || "").trim();
  const details = [];
  if (code) details.push(`오류 코드: ${code}`);
  if (context.stage) details.push(`실패 단계: ${context.stage}`);
  if (context.nodeType || context.nodeId) details.push(`실패 노드: ${context.nodeType || "알 수 없음"}${context.nodeId ? ` (${context.nodeId})` : ""}`);
  if (context.requestId) details.push(`추적 ID: ${String(context.requestId).slice(0, 12)}`);
  errorDialogMessage.textContent = `${message || "생성 중 오류가 발생했어요."}${details.length ? `\n\n${details.join("\n")}` : ""}`;
  lastErrorReport = {
    error_code: code || "LKS-GEN-1001",
    message: message || "생성 중 오류가 발생했어요.",
    failure_stage: context.stage || null,
    node_id: context.nodeId || null,
    node_type: context.nodeType || null,
    exception_type: context.exceptionType || null,
    request_id: context.requestId || null,
    prompt_id: context.promptId || null,
    occurred_at: new Date().toISOString(),
    settings: context.diagnostics || null,
    setting_diagnostic: context.settingDiagnostic || null,
    runtime_trace: context.runtimeTrace || null,
  };
  errorDialog.hidden = false;
  document.querySelector("#errorDialogClose").focus();
}

function closeGenerationError() {
  errorDialog.hidden = true;
  generateButton.focus();
}

document.querySelector("#errorDialogClose").addEventListener("click", closeGenerationError);
document.querySelector("#errorDialogCopy").addEventListener("click", async event => {
  if (!lastErrorReport) return;
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "복사 중...";
  let version = "unknown";
  try {
    const response = await fetch("/api/launcher-identity", { cache: "no-store" });
    if (response.ok) version = String((await response.json()).version || version);
  } catch (_) {}
  const report = `LAKIS 오류 보고\n버전: ${version}\n${JSON.stringify(lastErrorReport, null, 2)}`;
  let copied = false;
  try {
    await navigator.clipboard.writeText(report);
    copied = true;
  } catch (_) {
    try {
      const field = document.createElement("textarea");
      field.value = report; field.style.position = "fixed"; field.style.opacity = "0";
      document.body.append(field); field.select(); copied = document.execCommand("copy"); field.remove();
    } catch (_) {}
  }
  button.textContent = copied ? "복사 완료" : "복사 실패";
  setTimeout(() => {
    button.textContent = "오류 정보 복사하기";
    button.disabled = false;
  }, 1800);
});
errorDialog.addEventListener("click", event => {
  if (event.target === errorDialog) closeGenerationError();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !errorDialog.hidden) closeGenerationError();
});

window.addEventListener("lakis:generation-progress", event => {
  setGenerationProgress(event.detail?.percent, event.detail?.stage);
});
window.addEventListener("lakis:generation-complete", () => {
  setGenerationProgress(100, "완료");
  generationResetTimer = setTimeout(() => {
    generationResetTimer = null;
    resetGenerationButton();
  }, 1400);
});
window.addEventListener("lakis:generation-error", resetGenerationButton);
window.addEventListener("lakis:generation-cancelled", resetGenerationButton);
window.LAKISGenerationProgress = setGenerationProgress;

window.LAKISDevTriggerError = payload => {
  if (!payload || typeof payload !== "object") return false;
  showGenerationError(payload.message, payload.error_code, {
    stage: payload.error_stage, nodeId: payload.error_node_id,
    nodeType: payload.error_node_type, exceptionType: payload.error_exception_type,
    requestId: payload.request_id, promptId: payload.prompt_id,
    diagnostics: payload.diagnostic_context,
    settingDiagnostic: payload.setting_diagnostic,
  });
  return true;
};

let lastGenerationState = "idle";
async function pollGenerationStatus() {
  try {
    const response = await fetch("/api/generation-status", { cache: "no-store" });
    if (!response.ok) return;
    const status = await response.json();
    // While /api/generate is being accepted, the bridge may still report the
    // previous job's terminal state for one poll. Ignore only that stale
    // terminal snapshot so it cannot unlock the button mid-submission.
    if (generationSubmissionPending && ["idle", "complete", "cancelled", "error"].includes(status.state)) return;
    if (["preparing", "running"].includes(status.state)) {
      setGenerationProgress(status.percent, status.stage || "생성 중");
      refreshGenerationPreview(status.preview_revision).catch(() => {});
    } else if (status.state === "cancelling") {
      generationActive = true;
      generationCancelRequested = true;
      generateButton.classList.add("is-generating", "is-cancelling");
      generateButtonLabel.textContent = "중지 중";
      generateButtonHint.textContent = "현재 작업 종료 요청됨";
    } else if (status.state === "complete" && lastGenerationState !== "complete") {
      if (status.output_url) {
        const imageUrl = `${status.output_url}&lakis=${Date.now()}`;
        document.querySelector("#previewImage").src = imageUrl;
        if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
        previewObjectUrl = null;
        const thumb = document.createElement("button");
        thumb.className = "history-thumb selected";
        thumb.dataset.seed = String(status.seed ?? state.output.seed);
        thumb.dataset.mode = status.mode === "detail" ? "detail" : "fast";
        thumb.dataset.i2i = String(status.i2i_enabled === true);
        thumb._lakisPrompt = status.prompt_used && typeof status.prompt_used === "object"
          ? structuredClone(status.prompt_used)
          : null;
        const durationSeconds = Math.max(0, Number(status.finished_at || 0) - Number(status.started_at || 0));
        thumb.dataset.duration = durationSeconds.toFixed(3);
        thumb.innerHTML = `<img src="${imageUrl}" alt="LAKIS generated image">`;
        document.querySelectorAll(".history-thumb").forEach(item => item.classList.remove("selected"));
        const historyStrip = document.querySelector(".history-strip");
        historyStrip.prepend(thumb);
        historyStrip.scrollLeft = 0;
        document.querySelector("#previewMode").textContent = thumb.dataset.mode.toUpperCase();
        document.querySelector("#previewI2i").hidden = thumb.dataset.i2i !== "true";
        document.querySelector("#previewSeed").textContent = `SEED ${thumb.dataset.seed}`;
        document.querySelector("#previewDuration").textContent = `${durationSeconds.toFixed(1)}초`;
        document.querySelector("#previewDuration").hidden = false;
        setCurrentPreviewPrompt(thumb._lakisPrompt);
      }
      window.dispatchEvent(new CustomEvent("lakis:generation-complete"));
    } else if (status.state === "cancelled" && lastGenerationState !== "cancelled") {
      window.dispatchEvent(new CustomEvent("lakis:generation-cancelled"));
    } else if (status.state === "error" && lastGenerationState !== "error") {
      showGenerationError(status.error, status.error_code, {
        stage: status.error_stage, nodeId: status.error_node_id,
        nodeType: status.error_node_type, exceptionType: status.error_exception_type,
        requestId: status.request_id, promptId: status.prompt_id,
        diagnostics: status.diagnostic_context,
        runtimeTrace: {
          last_node_id: status.last_node_id || null,
          last_node_type: status.last_node_type || null,
          last_activity_at: status.last_activity_at || null,
          last_node_started_at: status.last_node_started_at || null,
        },
      });
    }
    lastGenerationState = status.state;
  } catch (_) {
    // Main status polling already displays bridge connectivity.
  }
}
setInterval(pollGenerationStatus, 500);

generateButton.addEventListener("click", async () => {
  if (generationActive) {
    if (generationCancelRequested) return;
    generationCancelRequested = true;
    generateButton.classList.add("is-cancelling");
    generateButtonLabel.textContent = "중지 중";
    generateButtonHint.textContent = "현재 작업 종료 요청됨";
    window.dispatchEvent(new CustomEvent("lakis:generation-cancel-request"));
    return;
  }

  if (state.i2i.enabled && !state.i2i.image_name) {
    i2iStatus.textContent = "i2i 입력 이미지를 먼저 선택해 주세요.";
    i2iDropZone.focus();
    return;
  }

  // Number inputs do not always dispatch `change` before a nearby button is
  // activated (notably with spinner/IME interaction). Read the visible size
  // again so every generation uses the ratio currently shown in the UI.
  syncOutputStateFromInputs();
  if (state.output.seed_mode === "random") {
    state.output.seed = Math.floor(Math.random() * (COMFYUI_SEED_MAX + 1));
    document.querySelector("#seedInput").value = state.output.seed;
  }
  // Read the visible controls again at submission time. This prevents a stale
  // startup/default state from replacing text the user has just entered.
  syncPromptStateFromInputs();
  saveLocalPromptState();
  document.querySelector("#previewMode").textContent = state.generation.mode === "detail" ? "DETAIL" : "FAST";
  document.querySelector("#previewI2i").hidden = !state.i2i.enabled;
  document.querySelector("#previewSeed").textContent = `SEED ${state.output.seed}`;
  document.querySelector("#previewDuration").hidden = true;
  // A zoom chosen for the previous aspect ratio must not make the next image
  // appear cropped or locked to that ratio.
  setPreviewZoom(100);
  const generationPayload = structuredClone(state);
  try {
    if (state.translation_enabled && Object.values(state.prompt).some(containsKoreanPrompt)) {
      setGenerationProgress(0, "프롬프트 번역 중");
    }
    generationPayload.prompt = await translatedPromptForGeneration(state.prompt);
    lastPreviewRevision = 0;
    lastGenerationState = "preparing";
    setGenerationProgress(0, "생성 중");
    generationSubmissionPending = true;
    window.dispatchEvent(new CustomEvent("lakis:generate", { detail: generationPayload }));
  } catch (error) {
    showGenerationError(error.message || "프롬프트 자동 번역에 실패했어요.");
  }

});
document.addEventListener("click", event => {
  if (!event.target.closest(".workflow-launcher")) closeWorkflowMenu();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeWorkflowMenu();
});

window.addEventListener("lakis:generate", async event => {
  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event.detail)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      const failure = new Error(result.error || `HTTP ${response.status}`);
      failure.lakis = result;
      throw failure;
    }
    lastGenerationState = "preparing";
  } catch (error) {
    showGenerationError(error.message, error.lakis?.error_code, {
      stage: error.lakis?.error_stage || "요청 검증",
      nodeId: error.lakis?.error_node_id, nodeType: error.lakis?.error_node_type,
      requestId: error.lakis?.request_id,
      settingDiagnostic: error.lakis?.setting_diagnostic,
    });
  } finally {
    generationSubmissionPending = false;
  }
});

window.addEventListener("lakis:generation-cancel-request", async () => {
  try {
    const response = await fetch("/api/cancel", { method: "POST" });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || result.reason || "중지 실패");
  } catch (error) {
    generationCancelRequested = false;
    showGenerationError(`생성 중지 요청에 실패했어요.\n${error.message}`);
  }
});

render();
