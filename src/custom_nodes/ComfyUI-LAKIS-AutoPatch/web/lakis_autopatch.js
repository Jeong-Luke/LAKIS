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

  let workflow;
  try {
    workflow = await response.json();
  } catch (e) {
    console.error("[LAKIS AutoPatch] invalid workflow payload", e);
    return;
  }

  if (!workflow || typeof workflow !== "object" || !Array.isArray(workflow.nodes)) {
    console.error("[LAKIS AutoPatch] workflow payload is not a ComfyUI workflow");
    return;
  }

  try {
    await app.loadGraphData(workflow, true, true, "LAKIS_custom_v7.1.json");
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
