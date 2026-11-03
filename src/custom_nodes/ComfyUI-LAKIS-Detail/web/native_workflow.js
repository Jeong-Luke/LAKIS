// SPDX-License-Identifier: GPL-3.0-only
// Only graphs carrying LAKIS native metadata are affected. Upstream nodes and
// their UI editors are not patched or replaced.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const widget = (node, name) => node.widgets?.find(w => w.name === name);
const isNative = node => node.properties?.lakis_source_id != null;

function canvasValue(source, name) {
    if (source?.type !== "LAKIS_Canvas") return null;
    const raw = Number(widget(source, name)?.value);
    return Number.isFinite(raw) ? Math.max(256, Math.min(4096, Math.round(raw / 16) * 16)) : null;
}

function synchronizeStudioResolution(node) {
    const canvas = app.graph.getNodeById(node.properties.lakis_canvas_node_id);
    const w = canvasValue(canvas, "width");
    const h = canvasValue(canvas, "height");
    if (w == null || h == null) return;
    for (const [name, value] of [["resolution_custom_width", w], ["resolution_custom_height", h]]) {
        const target = widget(node, name);
        if (target) target.value = value;
    }
    const bucket = widget(node, "resolution_bucket");
    const size = widget(node, "resolution_size");
    if (bucket) bucket.value = "Custom";
    if (size) size.value = `${w} * ${h} (custom)`;
}

function synchronizeDimensions() {
    for (const node of app.graph._nodes) {
        if (!isNative(node)) continue;
        if (node.type === "EasyUseAnimaPromptStudioAdvanced") {
            synchronizeStudioResolution(node);
            continue;
        }
        if (!["ToyxyzPose3DEditor", "ComfyCoupleRegionPainter"].includes(node.type)) continue;
        for (const input of node.inputs || []) {
            if (!["width", "height"].includes(input.name)) continue;
            const link = app.graph.links[input.link];
            const canvas = link && app.graph.getNodeById(link.origin_id);
            const value = canvasValue(canvas, link?.origin_slot === 0 ? "width" : "height");
            const target = widget(node, input.name);
            if (value == null || !target || target.value === value) continue;
            target.value = value;
            // Editor callbacks resize their real render canvas, not just the
            // LiteGraph node box. This runs before editor capture/serialization.
            target.callback?.(value);
        }
    }
}

function normalizeNativeLinks(serialized) {
    if (!serialized.nodes.some(node => node.type === "LAKIS_GenerationControls")) return serialized;
    // The API loader can put reactive enum choices into link types. Native
    // snapshots use COMBO, not those arrays, and must be structured-cloneable.
    serialized.links = serialized.links.map(link => {
        const values = Array.from(link);
        if (Array.isArray(values[5])) values[5] = "COMBO";
        return values;
    });
    return serialized;
}

function installSerialization(node) {
    if (!isNative(node) || node.__lakisNativeSerialization) return;
    node.__lakisNativeSerialization = true;
    const original = node.onSerialize;
    node.onSerialize = function (serialized) {
        if (this.type === "EasyUseAnimaPromptStudioAdvanced") synchronizeStudioResolution(this);
        const result = original?.apply(this, arguments);
        const names = this.properties.lakis_widget_names || [];
        const named = {};
        for (const name of names) {
            const field = widget(this, name);
            if (field) named[name] = field.value;
        }
        serialized.properties ||= {};
        serialized.properties.lakis_widget_values = named;
        return result;
    };
    if (node.type === "LAKIS_OptionalImage") {
        node.addWidget("button", "Upload source / mask", null, () => {
            const picker = document.createElement("input");
            picker.type = "file";
            picker.accept = "image/*";
            picker.onchange = async () => {
                const file = picker.files?.[0];
                if (!file) return;
                const body = new FormData();
                body.append("image", file);
                body.append("type", "input");
                const response = await api.fetchApi("/upload/image", { method: "POST", body });
                if (!response.ok) throw new Error(`Image upload failed: ${response.status}`);
                const uploaded = await response.json();
                widget(node, "image").value = uploaded.subfolder
                    ? `${uploaded.subfolder}/${uploaded.name}` : uploaded.name;
                node.setDirtyCanvas(true, true);
            };
            picker.click();
        }, { serialize: false });
    }
}

app.registerExtension({
    name: "LAKIS.StandaloneWorkflow",
    setup() {
        const serialize = app.graph.serialize;
        app.graph.serialize = function () {
            return normalizeNativeLinks(serialize.apply(this, arguments));
        };
        const original = app.graphToPrompt;
        app.graphToPrompt = async function () {
            synchronizeDimensions();
            return original.apply(this, arguments);
        };
    },
    loadedGraphNode(node) {
        installSerialization(node);
    },
    afterConfigureGraph() {
        const native = app.graph._nodes.some(node => node.type === "LAKIS_GenerationControls");
        for (const node of app.graph._nodes) {
            installSerialization(node);
            // API loading assigns widgets without the camera's onConfigure.
            // Hydrate its UI before ComfyUI snapshots the activated workflow.
            if (native && node.type === "KR_CameraControl") node._krCameraResync();
        }
        synchronizeDimensions();
    },
    nodeCreated(node) {
        if (node.type !== "LAKIS_Canvas") return;
        const original = node.onWidgetChanged;
        node.onWidgetChanged = function () {
            original?.apply(this, arguments);
            synchronizeDimensions();
        };
    },
});
