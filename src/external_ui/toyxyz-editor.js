// SPDX-License-Identifier: GPL-3.0-only
// Standalone adapter for the unchanged toyxyz editors and their live mask binding.
// LAKIS 8.0 modification: use the LAKIS host message namespace.
import { app } from "./scripts/app.js";
import { Pose3DEditorUI } from "./vendor/toyxyz/pose3d_editor.js";
import { CoupleRegionPainterUI } from "./vendor/toyxyz/util/couple_region_painter_ui.js";
import { bindPoseRegions } from "./vendor/toyxyz/util/pose_region_bridge.js";
import { PrecisionPoseControls } from "./precision-pose-controls.js";
import { findMissingPaintPrompt } from "./toyxyz-prompt-validation.js";

let loaded = false, handling = false, revision = 0;
const poseNode = {
  id: -76, properties: {}, setDirtyCanvas() {
    if (!loaded || handling) return;
    revision++;
    reply({
      type: "lakis:toyxyz-changed", revision,
      pose_data: poseNode.widgets.find(w => w.name === "pose_data").value,
    });
  },
  widgets: [
    { name: "width", value: 768 }, { name: "height", value: 1024 },
    { name: "pose_data", value: "{}" }, { name: "render_data", value: "" },
  ],
};
const paintNode = {
  id: -77, properties: {}, setDirtyCanvas() {},
  widgets: [
    { name: "width", value: 768 }, { name: "height", value: 1024 },
    { name: "paint_data", value: "" },
  ],
  inputs: [{ name: "region_painter", link: 1 }],
};
const graph = {
  getLink(id) { return id === 1 ? { origin_id: poseNode.id } : null; },
  getNodeById(id) { return id === poseNode.id ? poseNode : paintNode; },
};
poseNode.graph = paintNode.graph = graph;
const pose = poseNode._pose3d = new Pose3DEditorUI(poseNode, document.querySelector("#pose"));
const painter = new CoupleRegionPainterUI(paintNode, document.querySelector("#painter"), app);
let binding, simple, commands = Promise.resolve();
const errorOutput = document.querySelector("#error");
function reply(message) { parent.postMessage(message, location.origin); }
const ready = Promise.all([pose.ready, painter.ready]).then(() => {
  pose.getPoseButton.hidden = true;
  simple = new PrecisionPoseControls(pose);
  reply({ type: "lakis:toyxyz-ready" });
});
ready.catch(error => {
  errorOutput.hidden = false;
  errorOutput.textContent = error.message;
  reply({ type: "lakis:toyxyz-ready", error: error.message });
});
async function handle(message) {
  await ready;
  errorOutput.hidden = true;
  errorOutput.textContent = "";
  const { width, height } = message;
  if (![width, height].every(n => Number.isInteger(n) && n >= 64 && n <= 4096)) {
    throw Error("toyxyz 편집기는 가로·세로 64~4096 크기를 지원합니다.");
  }
  for (const node of [poseNode, paintNode]) {
    node.widgets.find(w => w.name === "width").value = width;
    node.widgets.find(w => w.name === "height").value = height;
  }
  if (message.type === "lakis:toyxyz-size") {
    pose.resize();
    reply({ type: "lakis:toyxyz-result", request_id: message.request_id, revision });
    return;
  }
  if (message.type === "lakis:toyxyz-load") {
    const paint = message.paint_data ? JSON.parse(message.paint_data) : null;
    if (paint?.pose_source) poseNode.properties.pose_region_source_id = paint.pose_source.source_id;
    await pose.load(message.pose_data ? JSON.parse(message.pose_data) : {});
    pose.getPoseButton.hidden = true;
    simple.refresh();
    pose.resize();
    await painter.load(message.paint_data || "");
    binding ??= bindPoseRegions(paintNode, painter);
    await binding.syncNow(true);
    loaded = true;
    reply({ type: "lakis:toyxyz-result", request_id: message.request_id, revision });
    return;
  }
  simple.beforeCapture();
  if (message.paint_data) await painter.load(message.paint_data);
  pose.resize();
  await binding.syncNow(true);
  const data_url = pose.capture();
  const paint_data = await painter.serialize();
  if (message.validate_prompts) {
    const missing = findMissingPaintPrompt(painter);
    if (missing) {
      throw Object.assign(Error(`${missing.index + 1}번 인물/영역의 프롬프트가 비어 있습니다. 메인 화면의 정밀 프롬프트에 외형·의상을 입력하거나 해당 레이어를 숨겨 주세요.`),
        { missing_layer_id: missing.layer.id });
    }
  }
  reply({
    type: "lakis:toyxyz-result", request_id: message.request_id, data_url,
    pose_data: poseNode.widgets.find(w => w.name === "pose_data").value,
    render_data: poseNode.widgets.find(w => w.name === "render_data").value,
    paint_data, revision,
  });
}
window.addEventListener("message", event => {
  if (event.origin !== location.origin || event.source !== parent ||
      !["lakis:toyxyz-load", "lakis:toyxyz-capture", "lakis:toyxyz-size"].includes(event.data?.type)) return;
  const message = event.data;
  commands = commands.then(async () => {
    handling = true;
    pose.root.inert = true;
    try { await handle(message); }
    finally { handling = false; pose.root.inert = false; }
  }).catch(error => {
    if (error.code !== "DEKIS_POSE_BUSY") {
      errorOutput.hidden = false;
      errorOutput.textContent = error.message;
    }
    reply({ type: "lakis:toyxyz-result", request_id: message.request_id, error: error.message,
      error_code: error.code,
      missing_layer_id: error.missing_layer_id });
  });
});
window.addEventListener("pagehide", () => {
  simple?.dispose(); painter.dispose(); pose.dispose();
});
