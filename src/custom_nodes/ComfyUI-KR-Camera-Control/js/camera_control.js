// SPDX-FileCopyrightText: 2026 灰暗x
// SPDX-FileCopyrightText: 2026 ComfyUI-KR-Camera-Control contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { app } from "../../scripts/app.js";

const NODE_TYPE = "KR_CameraControl";
const VERSION = "1.1.1";
const SERIAL_WIDGET_ORDER = ["pos_x", "pos_y", "pos_z", "roll", "config", "frame_y"];
const DEFAULT_CAMERA_PRESETS = [
    { name: "정면", pos_x: 0.0, pos_y: 0.0, pos_z: 0.0, roll: 0.0, frame_y: 0.0, user_prompt: "" },
    { name: "왼쪽", pos_x: 0.5, pos_y: 0.0, pos_z: 0.0, roll: 0.0, frame_y: 0.0, user_prompt: "" },
    { name: "오른쪽", pos_x: -0.5, pos_y: 0.0, pos_z: 0.0, roll: 0.0, frame_y: 0.0, user_prompt: "" },
    { name: "후면", pos_x: 1.0, pos_y: 0.0, pos_z: 0.0, roll: 0.0, frame_y: 0.0, user_prompt: "" },
];

const DEFAULT_CONFIG = {
    weight_min: 0.1,
    weight_max: 10.0,
    no_weight: false,
    no_weight_threshold: 0.5,
    active_user_prompt: "",
    camera_presets: DEFAULT_CAMERA_PRESETS,
    azimuth: {
        enabled: true,
        weight: 5.0,
        deadzone_ratio: 0.2,
        directions: {
            front: { tag: "from front", enabled: true },
            back: { tag: "from behind", enabled: true },
            left: { tag: "from right", enabled: true },
            right: { tag: "from left", enabled: true },
        },
    },
    elevation: {
        enabled: true,
        weight: 5.0,
        categories: {
            bird: { tag: "directly above, from above, aerial view", enabled: true },
            high: { tag: "high angle, from above", enabled: true },
            eye: { tag: "eye-level", enabled: true },
            low: { tag: "low angle, from below", enabled: true },
            worm: { tag: "directly below", enabled: true },
        },
    },
    distance: {
        enabled: true,
        weight: 5.0,
        categories: {
            ecu: { tag: "extreme close-up", enabled: true },
            cu: { tag: "close-up", enabled: true },
            medium: { tag: "medium shot", enabled: true },
            full: { tag: "full body", enabled: true },
            wide: { tag: "wide shot", enabled: true },
        },
    },
    vertical_framing: {
        enabled: true,
        weight: 5.0,
        deadzone: 0.05,
        up_tag: "subject positioned high in frame, ample visible foreground below subject",
        down_tag: "subject positioned low in frame",
    },
    tilt: {
        enabled: true,
        deadzone: 0.15,
        extra: 0.0,
        dutch_tag: "dutch angle",
    },
    wheel_step: 0.0003,
    extras: {
        lens: { enabled: false, value: "85mm lens" },
        dof: { enabled: false, value: "shallow depth of field", weight: 1.3 },
        movement: { enabled: false, value: "handheld camera" },
        composition: { enabled: false, value: "rule of thirds" },
        style: { enabled: false, value: "cinematic" },
    },
};

const DISTANCE_RANGES = {
    ecu: [0.7, 1.0],
    cu: [0.2, 0.7],
    medium: [-0.2, 0.2],
    full: [-0.7, -0.2],
    wide: [-1.0, -0.7],
};
const FARTHER_IS_STRONGER = new Set(["medium", "full", "wide"]);

function clone(value) {
    return JSON.parse(JSON.stringify(value));
}

function mergeDefaults(target, defaults) {
    for (const [key, value] of Object.entries(defaults)) {
        if (!(key in target)) target[key] = clone(value);
        else if (value && typeof value === "object" && !Array.isArray(value) && target[key] && typeof target[key] === "object") {
            mergeDefaults(target[key], value);
        }
    }
    return target;
}

function normalizePreset(item, index) {
    if (!item || typeof item !== "object") return null;
    return {
        name: String(item.name || `프리셋 ${index}`),
        pos_x: clamp(item.pos_x),
        pos_y: clamp(item.pos_y),
        pos_z: clamp(item.pos_z),
        roll: clamp(item.roll),
        frame_y: clamp(item.frame_y),
        user_prompt: String(item.user_prompt ?? item.prompt ?? ""),
    };
}

function loadConfig(raw) {
    try {
        const parsed = typeof raw === "string" ? JSON.parse(raw) : clone(raw);
        const legacyTotalWeight = Number(parsed?.total_weight);
        const hadCameraPresets = Array.isArray(parsed?.camera_presets);
        const legacyPresetPrompts = parsed?.preset_prompts;
        const config = parsed && typeof parsed === "object" ? mergeDefaults(parsed, clone(DEFAULT_CONFIG)) : clone(DEFAULT_CONFIG);
        if (Number.isFinite(legacyTotalWeight)) {
            for (const name of ["azimuth", "elevation", "distance"]) config[name].weight = legacyTotalWeight;
        }
        delete config.total_weight;
        if (config.elevation) delete config.elevation.extra;
        if (config.distance) delete config.distance.extra;
        delete config.extra_master;
        config.camera_presets = (Array.isArray(config.camera_presets) ? config.camera_presets : clone(DEFAULT_CAMERA_PRESETS))
            .map(normalizePreset)
            .filter(Boolean);
        if (!hadCameraPresets && legacyPresetPrompts && typeof legacyPresetPrompts === "object") {
            config.camera_presets.forEach((preset, index) => {
                preset.user_prompt = String(legacyPresetPrompts[index] || "");
            });
        }
        delete config.preset_prompts;
        delete config.preset_library_version;
        delete config.legacy_presets_imported;
        return config;
    } catch {
        return clone(DEFAULT_CONFIG);
    }
}

function clamp(value, min = -1, max = 1) {
    return Math.max(min, Math.min(max, Number(value) || 0));
}

function splitTags(tag) {
    return String(tag || "").split(",").map((part) => part.trim()).filter(Boolean);
}

function weighted(tag, weight) {
    return splitTags(tag).map((part) => `(${part}:${Number(weight).toFixed(2)})`);
}

function appendUserPrompt(prompt, userPrompt) {
    const extra = splitTags(userPrompt);
    if (!extra.length) return prompt;
    const base = String(prompt || "").replace(/,\s*$/, "").trim();
    return `${[...(base ? [base] : []), ...extra].join(", ")},`;
}

function elevationKey(value) {
    if (value > 0.7) return "bird";
    if (value > 0.2) return "high";
    if (value >= -0.2) return "eye";
    if (value >= -0.7) return "low";
    return "worm";
}

function distanceKey(value) {
    if (value > 0.7) return "ecu";
    if (value > 0.2) return "cu";
    if (value >= -0.2) return "medium";
    if (value >= -0.7) return "full";
    return "wide";
}

function azimuthRatios(value) {
    const angle = value * Math.PI;
    const ratios = {
        front: Math.max(0, Math.cos(angle)),
        back: Math.max(0, -Math.cos(angle)),
        right: Math.max(0, Math.sin(angle)),
        left: Math.max(0, -Math.sin(angle)),
    };
    const total = Object.values(ratios).reduce((sum, part) => sum + part, 0);
    if (total) for (const key of Object.keys(ratios)) ratios[key] /= total;
    return ratios;
}

function framingParts(config, frameY, useWeights) {
    const framing = config.vertical_framing || {};
    const amount = clamp(frameY);
    if (framing.enabled === false || Math.abs(amount) < Number(framing.deadzone ?? 0.05)) return [];
    const tag = amount > 0 ? framing.up_tag : framing.down_tag;
    if (!tag) return [];
    if (!useWeights) return splitTags(tag);
    const minWeight = Number(config.weight_min ?? 0.1);
    const maxWeight = Number(config.weight_max ?? 10.0);
    const framingWeight = clamp(Number(framing.weight ?? 5.0), minWeight, maxWeight);
    const weight = 1 + Math.abs(amount) * Math.max(0, framingWeight - 1);
    return weighted(tag, clamp(weight, minWeight, maxWeight));
}

function computePrompt(posX, posY, posZ, roll, config, frameY = 0) {
    if (config.no_weight) return computePlainPrompt(posX, posY, posZ, roll, config, frameY);
    const parts = [];
    const minWeight = Number(config.weight_min ?? 0.1);
    const maxWeight = Number(config.weight_max ?? 10.0);
    const azimuthWeight = clamp(Number(config.azimuth?.weight ?? 5.0), minWeight, maxWeight);
    const elevationWeight = clamp(Number(config.elevation?.weight ?? 5.0), minWeight, maxWeight);
    const distanceWeight = clamp(Number(config.distance?.weight ?? 5.0), minWeight, maxWeight);
    const deadzone = Number(config.azimuth?.deadzone_ratio ?? 0.2);

    if (config.azimuth?.enabled !== false) {
        const ratios = azimuthRatios(posX);
        const poleGate = clamp((1 - Math.abs(posY)) / 0.1, 0, 1);
        const budget = azimuthWeight * poleGate;
        for (const name of ["front", "back", "left", "right"]) {
            const direction = config.azimuth.directions?.[name] || {};
            const weight = ratios[name] * budget;
            if (direction.enabled === false || !direction.tag || ratios[name] <= 0 || weight < deadzone) continue;
            parts.push(...weighted(direction.tag, clamp(weight, minWeight, maxWeight)));
        }
    }

    if (config.elevation?.enabled !== false) {
        const category = config.elevation.categories?.[elevationKey(posY)] || {};
        const weight = Math.abs(posY) * elevationWeight;
        if (category.enabled !== false && category.tag && weight >= deadzone) {
            parts.push(...weighted(category.tag, clamp(weight, minWeight, maxWeight)));
        }
    }

    if (config.distance?.enabled !== false) {
        const key = distanceKey(posZ);
        const category = config.distance.categories?.[key] || {};
        if (category.enabled !== false && category.tag) {
            const [start, end] = DISTANCE_RANGES[key];
            const rawFraction = FARTHER_IS_STRONGER.has(key) ? (end - posZ) / (end - start) : (posZ - start) / (end - start);
            const fraction = clamp(rawFraction, 0, 1);
            const weight = 1 + fraction * Math.max(0, distanceWeight - 1);
            parts.push(...weighted(category.tag, clamp(weight, minWeight, maxWeight)));
        }
    }

    parts.push(...framingParts(config, frameY, true));

    if (config.tilt?.enabled !== false && Math.abs(roll) >= Number(config.tilt.deadzone ?? 0.15)) {
        const weight = 1 + Number(config.tilt.extra ?? 0);
        parts.push(...weighted(config.tilt.dutch_tag, clamp(weight, 0.1, maxWeight)));
    }

    for (const name of ["lens", "dof", "movement", "composition", "style"]) {
        const extra = config.extras?.[name];
        const value = String(extra?.value || "").trim();
        if (!extra?.enabled || !value) continue;
        parts.push(name === "dof" ? `(${value}:${Number(extra.weight ?? 1.3).toFixed(2)})` : value);
    }
    return parts.length ? `${parts.join(", ")},` : "";
}

function computePlainPrompt(posX, posY, posZ, roll, config, frameY = 0) {
    const parts = [];
    const threshold = Number(config.no_weight_threshold ?? 0.5);
    if (config.azimuth?.enabled !== false && Math.abs(posY) < 1) {
        const ratios = azimuthRatios(posX);
        const enabled = Object.entries(ratios).filter(([name]) => config.azimuth.directions?.[name]?.enabled !== false);
        if (enabled.length) {
            const dominant = enabled.reduce((best, item) => item[1] > best[1] ? item : best);
            parts.push(...splitTags(config.azimuth.directions[dominant[0]]?.tag));
            for (const [name, ratio] of enabled) {
                if (name !== dominant[0] && ratio >= threshold) parts.push(...splitTags(config.azimuth.directions[name]?.tag));
            }
        }
    }

    const elev = elevationKey(posY);
    if (config.elevation?.enabled !== false && elev !== "eye") {
        const category = config.elevation.categories?.[elev];
        if (category?.enabled !== false) parts.push(...splitTags(category?.tag));
    }
    const distance = distanceKey(posZ);
    if (config.distance?.enabled !== false && distance !== "medium") {
        const category = config.distance.categories?.[distance];
        if (category?.enabled !== false) parts.push(...splitTags(category?.tag));
    }
    parts.push(...framingParts(config, frameY, false));
    if (config.tilt?.enabled !== false && Math.abs(roll) >= Number(config.tilt.deadzone ?? 0.15)) {
        parts.push(...splitTags(config.tilt.dutch_tag));
    }
    for (const name of ["lens", "dof", "movement", "composition", "style"]) {
        const extra = config.extras?.[name];
        const value = String(extra?.value || "").trim();
        if (extra?.enabled && value) parts.push(value);
    }
    return parts.length ? `${parts.join(", ")},` : "";
}

function getPath(object, path) {
    return path.split(".").reduce((value, key) => value?.[key], object);
}

function setPath(object, path, value) {
    const keys = path.split(".");
    const last = keys.pop();
    const owner = keys.reduce((value, key) => value[key], object);
    owner[last] = value;
}

function element(tag, className, text) {
    const value = document.createElement(tag);
    if (className) value.className = className;
    if (text !== undefined) value.textContent = text;
    return value;
}

function ensureStyles() {
    if (document.getElementById("kr-camera-control-styles")) return;
    const style = document.createElement("style");
    style.id = "kr-camera-control-styles";
    style.textContent = `
        .kr-camera { box-sizing:border-box; width:100%; padding:10px; display:flex; flex-direction:column; gap:8px; color:#ecf2f8; background:#22272e; border:1px solid #3b424c; border-radius:9px; font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",sans-serif; }
        .kr-camera * { box-sizing:border-box; }
        .kr-camera-toolbar { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
        .kr-camera button, .kr-camera select { min-height:30px; padding:4px 9px; color:#eaf0f6; background:#343b44; border:1px solid #4b5563; border-radius:5px; cursor:pointer; }
        .kr-camera button:hover { background:#46515e; }
        .kr-camera select { flex:1; min-width:150px; }
        .kr-camera-canvas-wrap { position:relative; width:100%; }
        .kr-camera canvas { display:block; width:100%; aspect-ratio:14/9; background:#171b20; border:1px solid #414955; border-radius:8px; cursor:crosshair; touch-action:none; user-select:none; }
        .kr-camera-overlay { position:absolute; inset:8px 10px auto; display:flex; justify-content:space-between; color:#abb5c0; pointer-events:none; font-size:12px; }
        .kr-camera-overlay span:last-child { color:#ffae6b; font-family:Consolas,monospace; text-align:right; }
        .kr-camera-axis { display:grid; grid-template-columns:72px minmax(120px,1fr) 72px; gap:8px; align-items:center; }
        .kr-camera-axis input[type=range] { width:100%; accent-color:#75b9ff; }
        .kr-camera-axis input[type=number], .kr-camera-setting input[type=number], .kr-camera-setting input[type=text], .kr-camera-preset-prompt input, .kr-camera textarea { width:100%; min-width:0; padding:5px 7px; color:#eaf0f6; background:#171b20; border:1px solid #4b5563; border-radius:4px; }
        .kr-camera-axis input:disabled { opacity:.45; cursor:not-allowed; }
        .kr-camera details { border:1px solid #424b56; border-radius:6px; background:#292f37; }
        .kr-camera summary { padding:8px 10px; cursor:pointer; font-weight:650; user-select:none; }
        .kr-camera-details { display:flex; flex-direction:column; gap:7px; padding:2px 10px 10px; }
        .kr-camera-setting { display:grid; grid-template-columns:112px 1fr 52px; gap:8px; align-items:center; }
        .kr-camera-setting.wide { grid-template-columns:112px 28px 1fr; }
        .kr-camera-setting label { color:#cbd5df; }
        .kr-camera-setting input[type=checkbox] { width:17px; height:17px; accent-color:#67aef5; }
        .kr-camera-group-title { margin-top:5px; padding-top:7px; color:#8fc8ff; border-top:1px solid #3b434d; font-weight:650; }
        .kr-camera-prompt { min-height:58px; resize:vertical; color:#fff2a6 !important; font-family:Consolas,monospace; }
        .kr-camera-preset-prompt { display:grid; grid-template-columns:148px minmax(0,1fr); gap:8px; align-items:center; }
        .kr-camera-preset-prompt label { color:#8fc8ff; font-weight:650; }
        .kr-camera-help { color:#9ba7b3; font-size:11px; }
        .kr-camera-toast { position:fixed; top:18px; left:50%; z-index:100000; transform:translateX(-50%); padding:7px 14px; color:#fff; background:rgba(20,24,29,.94); border:1px solid #53606d; border-radius:6px; pointer-events:none; }
    `;
    document.head.appendChild(style);
}

function hideWidget(widget) {
    if (!widget) return;
    widget.hidden = true;
    widget.options ||= {};
    widget.options.hidden = true;
    widget.computeSize = () => [0, -4];
    widget.draw = () => {};
    if (widget.element) widget.element.style.display = "none";
}

app.registerExtension({
    name: "KR.CameraControl",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE && nodeType.comfyClass !== NODE_TYPE) return;

        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (...args) {
            const serialized = args[0];
            const values = serialized?.widgets_values;
            // v1.0 workflows ended after config (some contain a trailing empty
            // non-serializing DOM-widget slot). Keep X/Y/Z/R/config indices intact
            // and migrate only the new final frame_y slot.
            if (Array.isArray(values)) {
                while (values.length < SERIAL_WIDGET_ORDER.length) values.push(0);
                const frameValue = values[5];
                if (frameValue === "" || frameValue == null || !Number.isFinite(Number(frameValue))) values[5] = 0;
            }
            const result = originalConfigure?.apply(this, args);
            queueMicrotask(() => this._krCameraResync?.());
            return result;
        };

        const originalSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (...args) {
            this._krCameraSyncForSerialize?.();
            return originalSerialize?.apply(this, args);
        };

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            ensureStyles();

            const node = this;
            const widget = Object.fromEntries(["pos_x", "pos_y", "pos_z", "roll", "config", "frame_y"].map((name) => [name, node.widgets.find((item) => item.name === name)]));
            Object.values(widget).forEach(hideWidget);

            let config = loadConfig(widget.config?.value);
            let activePresetIndex = null;
            const state = {
                pos_x: Number(widget.pos_x?.value) || 0,
                pos_y: Number(widget.pos_y?.value) || 0,
                pos_z: Number(widget.pos_z?.value) || 0,
                roll: Number(widget.roll?.value) || 0,
                frame_y: Number(widget.frame_y?.value) || 0,
            };
            let viewYaw = 0;
            let viewPitch = 0.42;
            function loadPreviewView() {
                const savedYaw = Number(config.preview_view?.yaw);
                const savedPitch = Number(config.preview_view?.pitch);
                viewYaw = Number.isFinite(savedYaw) ? savedYaw : 0;
                viewPitch = Number.isFinite(savedPitch) ? clamp(savedPitch, 0.12, 1.15) : 0.42;
            }
            loadPreviewView();
            const axisControls = {};
            const root = element("div", "kr-camera");
            const toolbar = element("div", "kr-camera-toolbar");
            const presetSelect = element("select");
            const promptOutput = element("textarea", "kr-camera-prompt");
            promptOutput.readOnly = true;
            const presetUserPrompt = element("input");
            presetUserPrompt.type = "text";
            presetUserPrompt.placeholder = "예: eye focus, back focus";
            const presetPromptRow = element("div", "kr-camera-preset-prompt");
            presetPromptRow.append(element("label", "", "프리셋 사용자 프롬프트"), presetUserPrompt);
            const presetLockNotice = element("div", "kr-camera-help", "preset_index가 연결되어 X·Y·Z·세로 프레이밍 조절이 잠겼습니다.");
            presetLockNotice.hidden = true;
            const presetIndexHelp = element("div", "kr-camera-help");

            function toast(message) {
                const notice = element("div", "kr-camera-toast", message);
                document.body.appendChild(notice);
                setTimeout(() => notice.remove(), 1500);
            }

            function button(label, handler) {
                const value = element("button", "", label);
                value.type = "button";
                value.addEventListener("click", (event) => {
                    event.stopPropagation();
                    handler(event);
                });
                return value;
            }

            function syncWidgets() {
                for (const key of ["pos_x", "pos_y", "pos_z", "roll", "frame_y"]) if (widget[key]) widget[key].value = state[key];
                if (widget.config) widget.config.value = JSON.stringify(config);
                node.properties ||= {};
                node.properties.kr_camera_version = VERSION;
                node.properties.camera_settings = {
                    x: state.pos_x,
                    y: state.pos_y,
                    z: state.pos_z,
                    roll: state.roll,
                    frame_y: state.frame_y,
                };
            }

            function updatePrompt() {
                const base = computePrompt(state.pos_x, state.pos_y, state.pos_z, state.roll, config, state.frame_y);
                promptOutput.value = appendUserPrompt(base, config.active_user_prompt);
            }

            function updateAxisControls() {
                for (const [key, controls] of Object.entries(axisControls)) {
                    controls.range.value = state[key];
                    controls.number.setAttribute("aria-valuenow", String(state[key]));
                    if (document.activeElement !== controls.number) controls.number.value = Number(state[key]).toFixed(2);
                }
            }

            function updatePresetInputLock() {
                const connected = node.inputs?.some((input) => input.name === "preset_index" && input.link != null) ?? false;
                for (const key of ["pos_x", "pos_y", "pos_z", "frame_y"]) {
                    if (!axisControls[key]) continue;
                    axisControls[key].range.disabled = connected;
                    axisControls[key].number.disabled = connected;
                }
                presetLockNotice.hidden = !connected;
            }

            function updateAll(redraw = true) {
                syncWidgets();
                updateAxisControls();
                updatePresetInputLock();
                if (document.activeElement !== presetUserPrompt) presetUserPrompt.value = String(config.active_user_prompt || "");
                updatePrompt();
                if (redraw) drawCamera();
                node.graph?.setDirtyCanvas(true, true);
            }

            function applySnapshot(snapshot) {
                if (!snapshot || typeof snapshot !== "object") throw new Error("올바른 설정이 아닙니다.");
                activePresetIndex = null;
                config = loadConfig(snapshot.config ?? snapshot);
                loadPreviewView();
                for (const key of ["pos_x", "pos_y", "pos_z", "roll", "frame_y"]) {
                    if (Number.isFinite(Number(snapshot[key]))) state[key] = clamp(Number(snapshot[key]));
                }
                rebuildSettings();
                refreshPresets();
                updateAll();
            }

            function snapshot() {
                return { ...state, config: clone(config) };
            }

            function applyPreset(index) {
                const presets = config.camera_presets;
                if (!presets.length) throw new Error("저장된 프리셋이 없습니다.");
                const wrapped = ((Math.trunc(Number(index)) % presets.length) + presets.length) % presets.length;
                const preset = presets[wrapped];
                state.pos_x = preset.pos_x;
                state.pos_y = preset.pos_y;
                state.pos_z = preset.pos_z;
                state.roll = preset.roll ?? 0;
                state.frame_y = preset.frame_y ?? 0;
                activePresetIndex = wrapped;
                config.active_user_prompt = String(preset.user_prompt || "");
                presetSelect.value = String(wrapped);
                updateAll();
                return preset;
            }

            function savePreset(name) {
                const cleanName = String(name || "").trim();
                if (!cleanName) throw new Error("프리셋 이름이 필요합니다.");
                const entry = {
                    name: cleanName,
                    pos_x: state.pos_x,
                    pos_y: state.pos_y,
                    pos_z: state.pos_z,
                    roll: state.roll,
                    frame_y: state.frame_y,
                    user_prompt: String(config.active_user_prompt || ""),
                };
                const existingIndex = config.camera_presets.findIndex((preset) => preset.name === cleanName);
                if (existingIndex >= 0) {
                    config.camera_presets[existingIndex] = entry;
                    activePresetIndex = existingIndex;
                } else {
                    config.camera_presets.push(entry);
                    activePresetIndex = config.camera_presets.length - 1;
                }
                refreshPresets(activePresetIndex);
                updateAll();
                return activePresetIndex;
            }

            function refreshPresets(selected = activePresetIndex) {
                presetSelect.replaceChildren();
                const placeholder = element("option", "", config.camera_presets.length ? "프리셋 불러오기" : "프리셋 없음");
                placeholder.value = "";
                presetSelect.appendChild(placeholder);
                for (const [index, preset] of config.camera_presets.entries()) {
                    const coordinates = [preset.pos_x, preset.pos_y, preset.pos_z].map((value) => Number(value).toFixed(2)).join(", ");
                    const option = element("option", "", `${index} · ${preset.name} (${coordinates})`);
                    option.value = String(index);
                    presetSelect.appendChild(option);
                }
                presetSelect.value = selected === null || selected === "" ? "" : String(selected);
                const count = config.camera_presets.length;
                presetIndexHelp.textContent = count
                    ? `프리셋 인덱스: 0~${count - 1}. Random Int 범위를 0~${count - 1}로 설정하면 기본·추가 프리셋 전체에서 랜덤 선택됩니다.`
                    : "프리셋이 없습니다. 현재 상태를 저장하면 인덱스 0부터 생성됩니다.";
            }

            presetSelect.addEventListener("change", () => {
                if (!presetSelect.value) return;
                try {
                    const preset = applyPreset(Number(presetSelect.value));
                    toast(`[${activePresetIndex}] '${preset.name}' 프리셋을 불러왔습니다.`);
                } catch (error) {
                    toast(error.message);
                }
            });
            toolbar.append(
                button("초기화", () => applySnapshot({ pos_x: 0, pos_y: 0, pos_z: 0, roll: 0, frame_y: 0, config: clone(DEFAULT_CONFIG) })),
                button("저장", () => {
                    const name = window.prompt("프리셋 이름", `카메라 ${new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}`)?.trim();
                    if (!name) return;
                    savePreset(name);
                    toast(`[${activePresetIndex}] '${name}' 프리셋을 저장했습니다.`);
                }),
                presetSelect,
                button("랜덤", () => {
                    activePresetIndex = null;
                    presetSelect.value = "";
                    for (const key of ["pos_x", "pos_y", "pos_z"]) {
                        state[key] = Math.round((Math.random() * 2 - 1) * 100) / 100;
                    }
                    updateAll();
                    toast(`X ${state.pos_x.toFixed(2)} · Y ${state.pos_y.toFixed(2)} · Z ${state.pos_z.toFixed(2)}`);
                }),
                button("삭제", () => {
                    if (presetSelect.value === "") return toast("삭제할 프리셋을 선택하세요.");
                    const index = Number(presetSelect.value);
                    const [removed] = config.camera_presets.splice(index, 1);
                    activePresetIndex = null;
                    refreshPresets();
                    updateAll();
                    toast(`[${index}] '${removed.name}' 프리셋을 삭제했습니다. 남은 번호를 다시 매겼습니다.`);
                }),
                button("복사", async () => {
                    await navigator.clipboard.writeText(JSON.stringify(snapshot(), null, 2));
                    toast("카메라 설정을 복사했습니다.");
                }),
                button("붙여넣기", async () => {
                    try {
                        applySnapshot(JSON.parse(await navigator.clipboard.readText()));
                        toast("카메라 설정을 붙여넣었습니다.");
                    } catch {
                        toast("클립보드에서 올바른 설정을 읽지 못했습니다.");
                    }
                }),
            );
            root.appendChild(toolbar);
            refreshPresets();

            presetUserPrompt.addEventListener("input", () => {
                config.active_user_prompt = presetUserPrompt.value;
                if (activePresetIndex !== null && config.camera_presets[activePresetIndex]) {
                    config.camera_presets[activePresetIndex].user_prompt = presetUserPrompt.value;
                }
                updateAll(false);
            });

            const originalConnectionsChange = node.onConnectionsChange;
            node.onConnectionsChange = function () {
                const connectionResult = originalConnectionsChange?.apply(this, arguments);
                queueMicrotask(() => {
                    updatePresetInputLock();
                    node.graph?.setDirtyCanvas(true, true);
                });
                return connectionResult;
            };

            const canvasWrap = element("div", "kr-camera-canvas-wrap");
            const canvas = element("canvas");
            const overlay = element("div", "kr-camera-overlay");
            const overlayHelp = element("span", "", "좌드래그: 카메라 · 우드래그: 보기 회전 · 휠: 거리 · Shift+휠: 롤");
            const overlayStatus = element("span");
            overlay.append(overlayHelp, overlayStatus);
            canvasWrap.append(canvas, overlay);
            root.appendChild(canvasWrap);

            const WIDTH = 560;
            const HEIGHT = 360;
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

            function ellipse(radius, elevation, color, dashed = true) {
                ctx.beginPath();
                for (let index = 0; index <= 80; index++) {
                    const angle = index / 80 * Math.PI * 2;
                    const point = project(radius * Math.sin(angle), elevation, radius * Math.cos(angle));
                    if (index) ctx.lineTo(point.x, point.y); else ctx.moveTo(point.x, point.y);
                }
                ctx.strokeStyle = color;
                ctx.lineWidth = 1.8;
                ctx.setLineDash(dashed ? [5, 7] : []);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            function verticalOrbit(radius, azimuth, color) {
                ctx.beginPath();
                for (let index = 0; index <= 80; index++) {
                    const angle = index / 80 * Math.PI * 2;
                    const horizontal = radius * Math.cos(angle);
                    const point = project(
                        horizontal * Math.sin(azimuth),
                        0.7 + radius * Math.sin(angle),
                        horizontal * Math.cos(azimuth),
                    );
                    if (index) ctx.lineTo(point.x, point.y); else ctx.moveTo(point.x, point.y);
                }
                ctx.strokeStyle = color;
                ctx.lineWidth = 1.8;
                ctx.setLineDash([5, 7]);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            function elevationOrbit(radius, elevation, color) {
                const horizontal = radius * Math.cos(elevation);
                const height = 0.7 + radius * Math.sin(elevation);
                ctx.beginPath();
                for (let index = 0; index <= 80; index++) {
                    const angle = index / 80 * Math.PI * 2;
                    const point = project(horizontal * Math.sin(angle), height, horizontal * Math.cos(angle));
                    if (index) ctx.lineTo(point.x, point.y); else ctx.moveTo(point.x, point.y);
                }
                ctx.strokeStyle = color;
                ctx.lineWidth = 1.4;
                ctx.setLineDash([3, 7]);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            function point3d(x, y, z, label) {
                const point = project(x, y, z);
                ctx.fillStyle = "#75d9e9";
                ctx.beginPath();
                ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = "#eef8ff";
                ctx.font = "700 13px Consolas";
                ctx.textAlign = "center";
                ctx.fillText(label, point.x, point.y - 10);
            }

            function drawCamera() {
                ctx.clearRect(0, 0, WIDTH, HEIGHT);
                const background = ctx.createLinearGradient(0, 0, 0, HEIGHT);
                background.addColorStop(0, "#151a20");
                background.addColorStop(1, "#222932");
                ctx.fillStyle = background;
                ctx.fillRect(0, 0, WIDTH, HEIGHT);

                const radius = 1.7 - 0.7 * state.pos_z;
                ellipse(radius, 0.7, "rgba(74,201,217,.34)");
                const angle = state.pos_x * Math.PI;
                const elevation = state.pos_y * Math.PI / 2;
                verticalOrbit(radius, angle, "rgba(255,137,75,.38)");
                elevationOrbit(radius, elevation, "rgba(111,215,235,.25)");
                const horizontal = radius * Math.cos(elevation);
                const camera = {
                    x: horizontal * Math.sin(angle),
                    y: 0.7 + radius * Math.sin(elevation),
                    z: horizontal * Math.cos(angle),
                };

                point3d(0, 0.7, radius, "F");
                point3d(0, 0.7, -radius, "B");
                point3d(radius, 0.7, 0, "L");
                point3d(-radius, 0.7, 0, "R");
                const center = project(0, 0.7, 0);
                const cameraPoint = project(camera.x, camera.y, camera.z);
                ctx.strokeStyle = "rgba(255,210,103,.7)";
                ctx.setLineDash([5, 6]);
                ctx.beginPath();
                ctx.moveTo(center.x, center.y);
                ctx.lineTo(cameraPoint.x, cameraPoint.y);
                ctx.stroke();
                ctx.setLineDash([]);

                const centerGlow = ctx.createRadialGradient(center.x - 4, center.y - 5, 2, center.x, center.y, 17);
                centerGlow.addColorStop(0, "#d9ffff");
                centerGlow.addColorStop(1, "#348a96");
                ctx.fillStyle = centerGlow;
                ctx.beginPath();
                ctx.arc(center.x, center.y, 15, 0, Math.PI * 2);
                ctx.fill();

                ctx.save();
                ctx.translate(cameraPoint.x, cameraPoint.y);
                ctx.rotate(Math.atan2(center.y - cameraPoint.y, center.x - cameraPoint.x) + state.roll * Math.PI / 4);
                ctx.fillStyle = "#ff9555";
                ctx.fillRect(-13, -8, 26, 16);
                ctx.fillStyle = "#10151b";
                ctx.beginPath();
                ctx.arc(6, 0, 5, 0, Math.PI * 2);
                ctx.fill();
                ctx.restore();

                const degrees = Math.round(state.pos_x * 180);
                const side = Math.abs(state.pos_x) > 0.85 ? "뒤" : state.pos_x < -0.05 ? `왼쪽 ${Math.abs(degrees)}°` : state.pos_x > 0.05 ? `오른쪽 ${degrees}°` : "정면 0°";
                overlayStatus.textContent = `${side}\n롤 ${Math.round(state.roll * 45)}°`;
            }

            function canvasPoint(event) {
                const rect = canvas.getBoundingClientRect();
                return { x: (event.clientX - rect.left) * WIDTH / rect.width, y: (event.clientY - rect.top) * HEIGHT / rect.height };
            }

            let dragging = null;
            canvas.addEventListener("pointerdown", (event) => {
                event.stopPropagation();
                canvas.setPointerCapture(event.pointerId);
                const point = canvasPoint(event);
                const mode = event.button === 2 || event.altKey ? "view" : "camera";
                dragging = {
                    mode,
                    pointerId: event.pointerId,
                    x: point.x,
                    y: point.y,
                    posX: state.pos_x,
                    posY: state.pos_y,
                    viewYaw,
                    viewPitch,
                };
                canvas.style.cursor = mode === "view" ? "move" : "grabbing";
                event.preventDefault();
            });
            canvas.addEventListener("pointermove", (event) => {
                if (!dragging || dragging.pointerId !== event.pointerId) return;
                const point = canvasPoint(event);
                if (dragging.mode === "view") {
                    viewYaw = dragging.viewYaw - (point.x - dragging.x) / WIDTH * Math.PI * 2;
                    viewPitch = clamp(dragging.viewPitch + (point.y - dragging.y) / HEIGHT * 1.5, 0.12, 1.15);
                    config.preview_view = { yaw: viewYaw, pitch: viewPitch };
                } else {
                    activePresetIndex = null;
                    presetSelect.value = "";
                    let value = dragging.posX + (point.x - dragging.x) / (WIDTH / 2);
                    while (value > 1) value -= 2;
                    while (value < -1) value += 2;
                    state.pos_x = value;
                    state.pos_y = clamp(dragging.posY - (point.y - dragging.y) / (HEIGHT / 2));
                }
                updateAll();
                event.preventDefault();
            });
            function stopDrag(event) {
                if (!dragging || dragging.pointerId !== event.pointerId) return;
                dragging = null;
                canvas.style.cursor = "crosshair";
            }
            canvas.addEventListener("pointerup", stopDrag);
            canvas.addEventListener("pointercancel", stopDrag);
            canvas.addEventListener("contextmenu", (event) => event.preventDefault());
            canvas.addEventListener("wheel", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const amount = event.deltaY * Number(config.wheel_step || 0.0003);
                if (event.shiftKey) state.roll = clamp(state.roll - amount * 3);
                else {
                    activePresetIndex = null;
                    presetSelect.value = "";
                    state.pos_z = clamp(state.pos_z - amount);
                }
                updateAll();
            }, { passive: false });
            canvas.addEventListener("dblclick", (event) => {
                if (event.shiftKey) {
                    viewYaw = 0;
                    viewPitch = 0.42;
                    config.preview_view = { yaw: viewYaw, pitch: viewPitch };
                } else {
                    activePresetIndex = null;
                    presetSelect.value = "";
                    state.pos_x = 0;
                    state.pos_y = 0;
                }
                updateAll();
            });

            function createAxis(label, key) {
                const row = element("div", "kr-camera-axis");
                const title = element("label", "", label);
                const range = element("input");
                range.type = "range";
                range.min = "-1";
                range.max = "1";
                range.step = "0.01";
                const number = element("input");
                number.type = "number";
                number.min = "-1";
                number.max = "1";
                number.step = "0.01";
                number.inputMode = "decimal";
                number.autocomplete = "off";
                number.spellcheck = false;
                number.setAttribute("aria-label", label);
                number.title = "Enter 적용 · Esc 취소 · Shift+↑↓ 0.10 조절";
                function clearPreset() {
                    if (key === "roll") return;
                    activePresetIndex = null;
                    presetSelect.value = "";
                }
                function change(value) {
                    clearPreset();
                    state[key] = clamp(value);
                    updateAll();
                }
                range.addEventListener("input", () => change(range.value));
                number.addEventListener("input", () => {
                    const raw = number.value.trim();
                    if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw)) return;
                    const value = Number(raw);
                    if (!Number.isFinite(value)) return;
                    clearPreset();
                    state[key] = clamp(value);
                    syncWidgets();
                    range.value = state[key];
                    number.setAttribute("aria-valuenow", String(state[key]));
                    updatePrompt();
                    drawCamera();
                    node.graph?.setDirtyCanvas(true, true);
                });
                number.addEventListener("change", () => {
                    const value = Number(number.value);
                    if (Number.isFinite(value)) {
                        clearPreset();
                        state[key] = clamp(value);
                    }
                    number.value = Number(state[key]).toFixed(2);
                    updateAll();
                });
                number.addEventListener("keydown", (event) => {
                    if (event.key === "Enter") {
                        event.preventDefault();
                        const value = Number(number.value);
                        if (Number.isFinite(value)) {
                            clearPreset();
                            state[key] = clamp(value);
                        }
                        number.value = Number(state[key]).toFixed(2);
                        updateAll();
                    } else if (event.key === "Escape") {
                        event.preventDefault();
                        number.value = Number(state[key]).toFixed(2);
                    } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                        event.preventDefault();
                        clearPreset();
                        const step = event.shiftKey ? 0.1 : 0.01;
                        state[key] = clamp(state[key] + (event.key === "ArrowUp" ? step : -step));
                        number.value = Number(state[key]).toFixed(2);
                        updateAll();
                    }
                });
                axisControls[key] = { range, number };
                row.append(title, range, number);
                return row;
            }
            root.append(
                createAxis("좌우 (X)", "pos_x"),
                createAxis("상하 (Y)", "pos_y"),
                createAxis("거리 (Z)", "pos_z"),
                createAxis("롤 (R)", "roll"),
                createAxis("세로 프레이밍", "frame_y"),
            );
            root.appendChild(presetIndexHelp);
            root.appendChild(element("div", "kr-camera-help", "숫자 칸의 화살표로 0.01씩 조절할 수 있습니다. Enter로 적용, Esc로 취소, Shift+↑↓로 0.10씩 조절할 수 있습니다."));

            function details(title, open = false) {
                const container = element("details");
                container.open = open;
                container.appendChild(element("summary", "", title));
                const content = element("div", "kr-camera-details");
                container.appendChild(content);
                return { container, content };
            }

            const weights = details("가중치 설정");
            const prompts = details("사용자 프롬프트");
            root.append(weights.container, prompts.container);

            function numberSetting(parent, label, path, min, max, step) {
                const row = element("div", "kr-camera-setting");
                const input = element("input");
                input.type = "range";
                input.min = String(min);
                input.max = String(max);
                input.step = String(step);
                input.value = String(getPath(config, path));
                const number = element("input");
                number.type = "number";
                number.min = String(min);
                number.max = String(max);
                number.step = String(step);
                number.value = String(getPath(config, path));
                const apply = (value) => {
                    const next = clamp(value, min, max);
                    setPath(config, path, next);
                    input.value = next;
                    number.value = next;
                    updateAll();
                };
                input.addEventListener("input", () => apply(input.value));
                number.addEventListener("input", () => apply(number.value));
                row.append(element("label", "", label), input, number);
                parent.appendChild(row);
            }

            function booleanSetting(parent, label, path) {
                const row = element("div", "kr-camera-setting wide");
                const input = element("input");
                input.type = "checkbox";
                input.checked = Boolean(getPath(config, path));
                input.addEventListener("change", () => {
                    setPath(config, path, input.checked);
                    updateAll();
                });
                row.append(element("label", "", label), input, element("span", "kr-camera-help", input.checked ? "사용" : "사용 안 함"));
                input.addEventListener("change", () => row.lastChild.textContent = input.checked ? "사용" : "사용 안 함");
                parent.appendChild(row);
            }

            function textSetting(parent, label, path, withToggle = true) {
                const row = element("div", "kr-camera-setting wide");
                const enabledPath = path.replace(/\.(tag|value)$/, ".enabled");
                const checkbox = element("input");
                checkbox.type = "checkbox";
                checkbox.checked = withToggle ? getPath(config, enabledPath) !== false : true;
                checkbox.style.visibility = withToggle ? "visible" : "hidden";
                const input = element("input");
                input.type = "text";
                input.value = String(getPath(config, path) || "");
                if (withToggle) checkbox.addEventListener("change", () => {
                    setPath(config, enabledPath, checkbox.checked);
                    updateAll(false);
                });
                input.addEventListener("input", () => {
                    setPath(config, path, input.value);
                    updateAll(false);
                });
                row.append(element("label", "", label), checkbox, input);
                parent.appendChild(row);
            }

            function group(parent, title) {
                parent.appendChild(element("div", "kr-camera-group-title", title));
            }

            function rebuildSettings() {
                weights.content.replaceChildren();
                prompts.content.replaceChildren();

                booleanSetting(weights.content, "가중치 제거", "no_weight");
                numberSetting(weights.content, "방위 총 가중치", "azimuth.weight", 0.1, 10, 0.1);
                booleanSetting(weights.content, "방위 사용", "azimuth.enabled");
                numberSetting(weights.content, "방위 데드존", "azimuth.deadzone_ratio", 0, 1, 0.01);
                numberSetting(weights.content, "높이 총 가중치", "elevation.weight", 0.1, 10, 0.1);
                booleanSetting(weights.content, "높이 사용", "elevation.enabled");
                numberSetting(weights.content, "거리 총 가중치", "distance.weight", 0.1, 10, 0.1);
                booleanSetting(weights.content, "거리 사용", "distance.enabled");
                booleanSetting(weights.content, "롤 사용", "tilt.enabled");
                numberSetting(weights.content, "롤 데드존", "tilt.deadzone", 0, 1, 0.01);

                group(prompts.content, "방위");
                textSetting(prompts.content, "정면", "azimuth.directions.front.tag");
                textSetting(prompts.content, "뒤", "azimuth.directions.back.tag");
                textSetting(prompts.content, "카메라 왼쪽", "azimuth.directions.left.tag");
                textSetting(prompts.content, "카메라 오른쪽", "azimuth.directions.right.tag");
                group(prompts.content, "높이");
                textSetting(prompts.content, "직부감", "elevation.categories.bird.tag");
                textSetting(prompts.content, "하이 앵글", "elevation.categories.high.tag");
                textSetting(prompts.content, "눈높이", "elevation.categories.eye.tag");
                textSetting(prompts.content, "로우 앵글", "elevation.categories.low.tag");
                textSetting(prompts.content, "직앙", "elevation.categories.worm.tag");
                group(prompts.content, "거리");
                textSetting(prompts.content, "극단적 클로즈업", "distance.categories.ecu.tag");
                textSetting(prompts.content, "클로즈업", "distance.categories.cu.tag");
                textSetting(prompts.content, "미디엄 샷", "distance.categories.medium.tag");
                textSetting(prompts.content, "풀 바디", "distance.categories.full.tag");
                textSetting(prompts.content, "와이드 샷", "distance.categories.wide.tag");
                group(prompts.content, "롤·렌즈·연출");
                textSetting(prompts.content, "더치 앵글", "tilt.dutch_tag", false);
                textSetting(prompts.content, "렌즈", "extras.lens.value");
                textSetting(prompts.content, "심도", "extras.dof.value");
                textSetting(prompts.content, "카메라 무빙", "extras.movement.value");
                textSetting(prompts.content, "구도", "extras.composition.value");
                textSetting(prompts.content, "스타일", "extras.style.value");
            }

            rebuildSettings();
            root.appendChild(promptOutput);
            root.appendChild(presetPromptRow);
            root.appendChild(presetLockNotice);
            root.appendChild(element("div", "kr-camera-help", "노드 출력은 STRING입니다. CLIP Text Encode나 다른 프롬프트 병합 노드에 연결하세요."));

            const domWidget = node.addDOMWidget("camera_ui", "camera_ui", root, { serialize: false, hideOnZoom: false });
            domWidget.computeSize = (width) => [width, Math.max(520, root.scrollHeight + 8)];

            let resizeFrame = 0;
            const resize = () => {
                cancelAnimationFrame(resizeFrame);
                resizeFrame = requestAnimationFrame(() => {
                    const width = Math.max(620, node.size?.[0] || 620);
                    const height = Math.max(520, root.scrollHeight + 22);
                    if (!node.size || Math.abs(node.size[0] - width) > 1 || Math.abs(node.size[1] - height) > 1) node.setSize([width, height]);
                    node.graph?.setDirtyCanvas(true, true);
                });
            };
            const observer = new ResizeObserver(resize);
            observer.observe(root);
            root.querySelectorAll("details").forEach((item) => item.addEventListener("toggle", resize));

            const originalRemoved = node.onRemoved;
            node.onRemoved = function () {
                observer.disconnect();
                cancelAnimationFrame(resizeFrame);
                return originalRemoved?.apply(this, arguments);
            };

            node._krCameraResync = () => {
                config = loadConfig(widget.config?.value);
                loadPreviewView();
                for (const key of ["pos_x", "pos_y", "pos_z", "roll", "frame_y"]) state[key] = clamp(widget[key]?.value);
                rebuildSettings();
                activePresetIndex = null;
                refreshPresets();
                updateAll();
                resize();
            };
            node._krCameraSyncForSerialize = syncWidgets;
            node._krCameraSnapshot = snapshot;
            node._krCameraApplySnapshot = applySnapshot;
            node._krCameraApplyPreset = applyPreset;
            node._krCameraSavePreset = savePreset;

            updateAll();
            resize();
            return result;
        };
    },
});
