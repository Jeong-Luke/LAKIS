// Node-only regression checks for the narrowly scoped LAKIS adapters.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ROOT = path.resolve(__dirname, "../..");

async function nativeSerialization() {
    let extension;
    let callbacks = 0;
    const canvas = { id: 3001, type: "LAKIS_Canvas",
        widgets: [{ name: "width", value: 736 }, { name: "height", value: 1008 }] };
    const decoyCanvas = { id: 3009, type: "LAKIS_Canvas",
        widgets: [{ name: "width", value: 2048 }, { name: "height", value: 2048 }] };
    const fields = [
        { id: "positive_trigger_mqktckx0", text: "keep trigger text" },
        { id: "positive_artist_mtm1mn6a", text: "keep artist text" },
    ];
    const fieldNames = fields.map(field => `field_${field.id}`);
    const fieldsValue = JSON.stringify(fields);
    const studio = { id: 2133, type: "EasyUseAnimaPromptStudioAdvanced",
        properties: { lakis_source_id: "2133", lakis_canvas_node_id: 3001,
            lakis_widget_names: ["resolution_custom_width", "resolution_custom_height", "advanced_fields"] },
        inputs: [],
        widgets: [{ name: "resolution_custom_width", value: 1024 },
                  { name: "resolution_custom_height", value: 1536 },
                  { name: "resolution_bucket", value: "Custom" },
                  { name: "resolution_size", value: "1024 * 1536 (custom)" },
                  { name: "advanced_fields", value: fieldsValue }],
        // Prompt Studio owns/rebuilds these dynamic field slots. Loaded
        // positional links would be assigned to the rebuilt prompt fields.
        onSerialize(serialized) {
            const previous = this.inputs;
            this.inputs = fieldNames.map((name, index) => ({
                name, type: "STRING", link: previous[index]?.link ?? null }));
            serialized.inputs = this.inputs;
        } };
    const pose = { id: 3030, type: "ToyxyzPose3DEditor", properties: { lakis_source_id: "3030" },
        inputs: [{ name: "width", link: 1 }, { name: "height", link: 2 }],
        widgets: [{ name: "width", value: 768, callback: () => callbacks++ },
                  { name: "height", value: 1024, callback: () => callbacks++ }] };
    const painter = { id: 3032, type: "ComfyCoupleRegionPainter", properties: { lakis_source_id: "3032" },
        inputs: [{ name: "width", link: 3 }, { name: "height", link: 4 }],
        widgets: [{ name: "width", value: 768, callback: () => callbacks++ },
                  { name: "height", value: 1024, callback: () => callbacks++ }] };
    const unreferencedStudio = { id: 999, type: "EasyUseAnimaPromptStudioAdvanced",
        properties: { lakis_source_id: "unreferenced" }, inputs: [],
        widgets: [{ name: "resolution_custom_width", value: 333 }] };
    const graphNodes = [decoyCanvas, canvas, studio, pose, painter, unreferencedStudio];
    const app = { graph: { _nodes: graphNodes,
        serialize: () => ({ nodes: [], links: [] }),
        links: { 1: { origin_id: 3001, origin_slot: 0 }, 2: { origin_id: 3001, origin_slot: 1 },
                 3: { origin_id: 3001, origin_slot: 0 }, 4: { origin_id: 3001, origin_slot: 1 },
                 5: { origin_id: 9000, origin_slot: 0 } },
        getNodeById: id => graphNodes.find(node => node.id === id) },
        graphToPrompt: async () => {
            studio.onSerialize({ properties: { ...studio.properties } });
            const inputs = Object.fromEntries(studio.widgets.map(w => [w.name, w.value]));
            for (const input of studio.inputs) {
                const link = app.graph.links[input.link];
                if (link) inputs[input.name] = [String(link.origin_id), link.origin_slot];
            }
            return { output: { "2133": { inputs } } };
        },
        registerExtension: x => extension = x };
    const source = fs.readFileSync(path.join(ROOT, "src/custom_nodes/ComfyUI-LAKIS-Detail/web/native_workflow.js"), "utf8")
        .replace(/^import .*;\r?$/gm, "");
    vm.runInNewContext(source, { app, api: {} });
    extension.setup();
    extension.nodeCreated(canvas);
    extension.afterConfigureGraph();
    const serialized = { properties: { ...studio.properties } };
    studio.onSerialize(serialized);
    assert.deepEqual(studio.inputs.map(input => input.name), fieldNames);
    assert.ok(studio.inputs.every(input => input.link == null), "Canvas links must not enter rebuilt prompt slots");
    assert.equal(serialized.properties.lakis_canvas_node_id, 3001);
    assert.deepEqual(JSON.parse(JSON.stringify(serialized.properties.lakis_widget_values)),
        { resolution_custom_width: 736, resolution_custom_height: 1008, advanced_fields: fieldsValue });
    assert.equal(callbacks, 4, "pose and painter must run their real dimension callbacks");
    assert.equal(unreferencedStudio.widgets[0].value, 333, "never infer another Studio's Canvas");
    // A real prompt string connection survives dynamic rebuilds and size edits.
    studio.inputs[1].link = 5;
    canvas.widgets[0].value = 1280;
    canvas.widgets[1].value = 768;
    canvas.onWidgetChanged("width", 1280);
    assert.equal(studio.widgets[0].value, 1280);
    assert.equal(studio.widgets[1].value, 768);
    assert.equal(callbacks, 8);
    // Direct native serialization also refreshes stale display copies.
    studio.widgets[0].value = 256;
    studio.onSerialize(serialized);
    assert.equal(studio.widgets[0].value, 1280);
    assert.equal(serialized.properties.lakis_widget_values.resolution_custom_width, 1280);
    const { output } = await app.graphToPrompt();
    assert.equal(output["2133"].inputs.resolution_custom_width, 1280);
    assert.equal(output["2133"].inputs.resolution_custom_height, 768);
    assert.equal(output["2133"].inputs.advanced_fields, fieldsValue);
    assert.equal(output["2133"].inputs[fieldNames[0]], undefined);
    assert.deepEqual(JSON.parse(JSON.stringify(output["2133"].inputs[fieldNames[1]])), ["9000", 0]);
    assert.ok(fieldNames.every(name => !JSON.stringify(output["2133"].inputs[name] || "").includes("3001")),
        "no Canvas value may be routed into a prompt field");
    assert.equal(callbacks, 8, "unchanged editor sizes must not rerun callbacks");
    // Unmarked workflows are deliberately untouched.
    studio.properties = {};
    studio.widgets[0].value = 256;
    await app.graphToPrompt();
    assert.equal(studio.widgets[0].value, 256);
}

async function nativeApiClone() {
    let extension;
    const choices = new Proxy(["normal", "karras"], {});
    const links = [[27, "3001", 0, "3000", 1, choices, "keep extra tuple fields"]];
    const extra = { unknown: "preserve" };
    let nodes = [{ id: "3000", type: "LAKIS_GenerationControls" }];
    const app = {
        graph: { serialize: () => ({ nodes, links, extra }) },
        graphToPrompt: async () => ({ output: {} }),
        registerExtension: value => extension = value,
    };
    assert.throws(() => structuredClone(app.graph.serialize()), /could not be cloned/);
    const source = fs.readFileSync(path.join(ROOT, "src/custom_nodes/ComfyUI-LAKIS-Detail/web/native_workflow.js"), "utf8")
        .replace(/^import .*;\r?$/gm, "");
    vm.runInNewContext(source, { app, api: {} });
    extension.setup();
    const serialized = app.graph.serialize();
    const cloned = structuredClone(serialized);
    assert.deepEqual(cloned.links, [[27, "3001", 0, "3000", 1, "COMBO", "keep extra tuple fields"]]);
    assert.equal(serialized.extra, extra);
    assert.equal(links[0][5], choices, "normalization must not mutate live link types");
    nodes = [{ id: 1, type: "KSampler" }];
    const unrelated = app.graph.serialize();
    assert.equal(unrelated.links, links, "unrelated workflows must remain untouched");
    assert.throws(() => structuredClone(unrelated), /could not be cloned/);
}

async function nativeApiCamera() {
    let extension, resyncs = 0;
    const names = ["pos_x", "pos_y", "pos_z", "roll", "config", "frame_y"];
    const inputs = { pos_x: .2, pos_y: -.1, pos_z: -1, roll: .5, config: '{"weight_max":10}', frame_y: .8 };
    let state = Object.fromEntries(names.map(name => [name, 0]));
    const camera = {
        type: "KR_CameraControl",
        properties: {},
        widgets: names.map(name => ({ name, value: inputs[name] })),
        _krCameraResync() {
            state = Object.fromEntries(this.widgets.map(field => [field.name, field.value]));
            resyncs++;
        },
        onSerialize() {
            for (const field of this.widgets) field.value = state[field.name];
        },
    };
    const app = {
        graph: {
            _nodes: [{ type: "LAKIS_GenerationControls" }, camera],
            serialize: () => ({ nodes: [], links: [] }),
        },
        graphToPrompt: async () => ({ output: {} }),
        registerExtension: value => extension = value,
    };
    const source = fs.readFileSync(path.join(ROOT, "src/custom_nodes/ComfyUI-LAKIS-Detail/web/native_workflow.js"), "utf8")
        .replace(/^import .*;\r?$/gm, "");
    vm.runInNewContext(source, { app, api: {} });
    extension.setup();
    // The real API loader invokes this hook before serializing its activation
    // snapshot, while the camera widgets contain the imported API values.
    extension.afterConfigureGraph();
    camera.onSerialize();
    assert.deepEqual(Object.fromEntries(camera.widgets.map(field => [field.name, field.value])), inputs);
    assert.equal(resyncs, 1);
    app.graph._nodes = [camera];
    state = Object.fromEntries(names.map(name => [name, 0]));
    extension.afterConfigureGraph();
    camera.onSerialize();
    assert.equal(resyncs, 1, "legacy API loads must remain untouched");
    assert.ok(camera.widgets.every(field => field.value === 0));
}

async function retainedPreview() {
    const listeners = {};
    let extension, NodeClass, current;
    let warnings = 0;
    const app = { graph: { setDirtyCanvas() {}, getNodeById: () => null },
        registerExtension: x => extension = x };
    const api = { addEventListener: (name, fn) => listeners[name] = fn };
    const source = fs.readFileSync(path.join(ROOT, "src/custom_nodes/ComfyUI-PreviewMonitor/web/js/preview_monitor.js"), "utf8");
    const sandbox = { window: { comfyAPI: { app: { app }, api: { api } } },
        LiteGraph: { LGraphNode: class { constructor() { this.flags = {}; } },
            registerNodeType: (_, cls) => NodeClass = cls },
        createImageBitmap: async value => { if (value.error) throw new Error("bad image"); return value; },
        console: { warn: () => warnings++ } };
    vm.runInNewContext(source, sandbox);
    await extension.registerCustomNodes();
    const first = { width: 128, height: 64, closed: false, close() { this.closed = true; } };
    await listeners.b_preview({ detail: first });
    listeners.execution_success();
    const ctx = new Proxy({ drawImage: image => current = image,
        measureText: text => ({ width: text.length * 4 }) },
        { get: (target, name) => name in target ? target[name] : () => {} });
    const node = new NodeClass();
    node.onDrawBackground(ctx);
    assert.equal(current, first);
    assert.equal(first.closed, false, "completion must retain the preview bitmap");
    listeners.execution_interrupted();
    node.onDrawBackground(ctx);
    assert.equal(current, first);
    await listeners.b_preview({ detail: { error: true } });
    assert.equal(warnings, 1);
    const next = { width: 64, height: 128, close() {} };
    await listeners.b_preview({ detail: next });
    assert.equal(first.closed, true);
    node.onDrawBackground(ctx);
    assert.equal(current, next, "a decode failure must not freeze subsequent previews");
}

Promise.resolve().then(nativeSerialization).then(nativeApiClone).then(nativeApiCamera).then(retainedPreview).then(() => {
    console.log("PASS Canvas display sync, native API cloning/camera restoration, scoped behavior, 3D/painter callbacks and retained preview");
}).catch(error => { console.error(error); process.exitCode = 1; });
