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

  const envelope = payload?.lakis_autopatch && payload?.workflow;
  const workflow = envelope ? payload.workflow : payload;
  const workflowFormat = envelope ? payload.lakis_autopatch.format : "workflow";
  if (!workflow || typeof workflow !== "object") {
    console.error("[LAKIS AutoPatch] workflow payload is not a ComfyUI workflow");
    return;
  }

  try {
    const displayName = payload?.lakis_autopatch?.display_name
      || workflow?.extra?.lakis_autopatch_display_name
      || "LAKIS_DETAIL_runtime_api_v7.3.json";
    if (workflowFormat === "api") {
      await app.loadApiJson(workflow, displayName);
    } else {
      await app.loadGraphData(workflow, true, true, displayName);
    }
    await fetch("/lakis/autopatch/consume-startup-workflow", {
      method: "POST",
      cache: "no-store",
    });
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
