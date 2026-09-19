// SPDX-FileCopyrightText: 2026 Luke Jeong
// SPDX-License-Identifier: MIT
// LAKIS AutoPatch Bridge
// Loads the workflow marker once after ComfyUI has finished starting.

import { app } from "../../scripts/app.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function tryLoadPatchedWorkflow() {
  // Give the workflow persistence/restoration layer time to finish first.
  await sleep(1800);

  let response;
  try {
    response = await fetch("/lakis/autopatch/startup-workflow", {
      cache: "no-store",
    });
  } catch {
    return;
  }

  if (!response || response.status === 204 || !response.ok) return;

  let payload;
  try {
    payload = await response.json();
  } catch (e) {
    console.error("[LAKIS AutoPatch] invalid workflow payload", e);
    return;
  }
  const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  if (!isObject(payload)) return;
  const enveloped = Object.prototype.hasOwnProperty.call(payload, "workflow") &&
    Object.prototype.hasOwnProperty.call(payload, "lakis_autopatch");
  const metadata = enveloped && isObject(payload.lakis_autopatch) ? payload.lakis_autopatch : {};
  const workflow = enveloped ? payload.workflow : payload;
  if (!isObject(workflow)) return;
  const format = metadata.format || (Array.isArray(workflow.nodes) ? "workflow" : "api");
  const valid = format === "workflow" ? Array.isArray(workflow.nodes) :
    format === "api" && Object.keys(workflow).length > 0 &&
    Object.values(workflow).every((node) => isObject(node) && typeof node.class_type === "string" && isObject(node.inputs));
  if (!valid) {
    console.error("[LAKIS AutoPatch] unsupported workflow format", format);
    return;
  }
  const displayName = typeof metadata.display_name === "string" && metadata.display_name
    ? metadata.display_name : "LAKIS_custom_v7.4.json";
  try {
    if (format === "api") {
      if (typeof app.loadApiJson !== "function") throw new Error("ComfyUI API workflow loader is unavailable");
      await app.loadApiJson(workflow, displayName);
    } else {
      await app.loadGraphData(workflow, true, true, displayName);
    }
    // Acknowledge only after the selected loader succeeds. The marker digest
    // lets the server reject known-stale acknowledgements (optimistic check).
    const markerId = response.headers?.get("X-LAKIS-Marker-SHA256");
    const consume = await fetch("/lakis/autopatch/consume-startup-workflow", {
      method: "POST", cache: "no-store",
      headers: markerId ? { "X-LAKIS-Marker-SHA256": markerId } : {},
    });
    if (!consume.ok) {
      console.warn("[LAKIS AutoPatch] workflow loaded; acknowledgement was not accepted", consume.status);
      return;
    }
    console.log("[LAKIS AutoPatch] patched workflow opened");
  } catch (e) {
    console.error("[LAKIS AutoPatch] workflow auto-open failed", e);
  }
}

app.registerExtension({
  name: "LAKIS.AutoPatch",
  async setup() {
    // A second small delay also handles slower frontend/workflow restoration.
    setTimeout(() => {
      tryLoadPatchedWorkflow();
    }, 600);
  },
});
