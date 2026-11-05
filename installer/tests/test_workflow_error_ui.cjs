const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8");
const clickStart = source.indexOf('workflowMenu.addEventListener("click", async event => {');
const clickEnd = source.indexOf("let latestSystemStatus", clickStart);
const errorStart = source.indexOf("function showGenerationError(");
const errorEnd = source.indexOf("function compactDiagnosticValue(", errorStart);
assert.ok(clickStart >= 0 && clickEnd > clickStart && errorStart >= 0 && errorEnd > errorStart);
const script = source.slice(errorStart, errorEnd) + "\n" + source.slice(clickStart, clickEnd);
const message = "MOSS 공식 워크플로를 읽지 못했어요. 업데이트·복구 후 다시 실행해 주세요.";

async function clickWorkflow(engine, result, networkError = null) {
  let click;
  const requests = [], dialogs = [], redirects = [];
  const popup = {
    closed: 0,
    close() { this.closed++; },
    location: { replace(url) { redirects.push(url); } },
  };
  const context = {
    workflowMenu: { addEventListener(name, listener) { assert.equal(name, "click"); click = listener; } },
    closeWorkflowMenu() {},
    currentGenerationEngine: () => engine,
    window: { open(url) { assert.equal(url, "about:blank"); return popup; } },
    async fetch(url, options) {
      requests.push({ url, options });
      if (networkError) throw networkError;
      return { ok: result.ok, status: result.ok ? 200 : 500, json: async () => result };
    },
    continuousRun: null,
    continuousAdvance: false,
    setContinuousProgress() {},
    resetGenerationButton() {},
    lastErrorReport: null,
    clientGenerationDiagnostics: value => value,
    generateButton: {},
    showDevModal: options => dialogs.push(options),
  };
  vm.runInNewContext(script, context);
  await click({ target: { closest: () => ({ dataset: { workflowKind: "editable" } }) } });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/open-workflow");
  assert.equal(requests[0].options.method, "POST");
  assert.deepEqual(JSON.parse(requests[0].options.body), { kind: "editable", engine });
  return { context, dialogs, popup, redirects };
}

(async () => {
  const moss = await clickWorkflow("moss", { ok: false, code: "LKS-MOSS-1010", error: message });
  assert.equal(moss.popup.closed, 1);
  assert.deepEqual(moss.redirects, []);
  assert.equal(moss.dialogs.length, 1);
  assert.equal(moss.dialogs[0].message, `${message}\n\n오류 코드: LKS-MOSS-1010`);
  assert.equal(moss.dialogs[0].copyError, true);
  assert.equal(moss.context.lastErrorReport.error_code, "LKS-MOSS-1010");
  assert.equal(moss.context.lastErrorReport.message, message);

  const generic = await clickWorkflow("anima", { ok: false, error: "기존 오류 안내" });
  assert.equal(generic.popup.closed, 1);
  assert.equal(generic.dialogs[0].message, "기존 오류 안내");
  assert.equal(generic.context.lastErrorReport.error_code, "LKS-GEN-1001");

  const network = await clickWorkflow("moss", null, new TypeError("Failed to fetch"));
  assert.equal(network.popup.closed, 1);
  assert.deepEqual(network.redirects, []);
  assert.equal(network.dialogs[0].message, "Failed to fetch");

  for (const engine of ["anima", "moss"]) {
    const success = await clickWorkflow(engine, { ok: true, comfy_url: "http://127.0.0.1:19000/" });
    assert.equal(success.popup.closed, 0);
    assert.deepEqual(success.dialogs, []);
    assert.deepEqual(success.redirects, ["http://127.0.0.1:19000/"]);
    assert.equal(success.context.lastErrorReport, null);
  }
  console.log("PASS workflow error dialog/copy code, generic/network failures, ANIMA/MOSS success and single request");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
