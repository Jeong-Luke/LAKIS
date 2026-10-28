import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { webcrypto } from "node:crypto";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../../src/external_ui/generation-diagnostics.js", import.meta.url), "utf8");
const packetSource = await readFile(new URL("../../src/external_ui/diagnostic-packet.js", import.meta.url), "utf8");
const appSource = await readFile(new URL("../../src/external_ui/app.js", import.meta.url), "utf8");
Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
vm.runInThisContext(source);
vm.runInThisContext(packetSource);
const diagnostics = globalThis.LAKISGenerationDiagnostics;
const packet = globalThis.LAKISDiagnosticPacket;
const payload = () => ({
  prompt: { general: "PRIVATE_PROMPT" },
  generation: { mode: "detail", lakis_mode: false, upscale_engine: "ultimate" },
  model: { checkpoint: "C:/Users/private/models/model.safetensors", sampler: "euler", steps: 30, cfg: 4 },
  output: { width: 1536, height: 1536, seed: 123, seed_mode: "random", aspect_locked: true },
  loras: [{ name: "C:/Users/private/lora/style.safetensors", enabled: true, strength: 0 }],
  i2i: { enabled: false, image: "data:image/png;PRIVATE_IMAGE" },
  inpaint: { enabled: false, prompt: "PRIVATE_INPAINT", mask_image: "PRIVATE_MASK" },
  advanced_node_settings: { "123": { text: "PRIVATE_OVERRIDE", steps: 0, enabled: false } },
  scene_controls: {
    enabled: false, toyxyz_enabled: false, pose_data: "한글",
    toyxyz_render_data: "PRIVATE_RENDER", toyxyz_paint_data: "PRIVATE_PAINT",
  },
  authorization: "PRIVATE_AUTH",
});
const response = (body, status = 202) => new Response(body, {
  status, headers: { "Content-Type": "application/json" },
});

test("transport failures retain byte/scene/correlation evidence without resubmitting", async () => {
  let calls = 0;
  const input = payload();
  await assert.rejects(diagnostics.submit(input, async (url, options) => {
    calls++;
    assert.equal(url, "/api/generate");
    assert.match(options.headers["X-LAKIS-Client-Request-ID"], /^[a-f0-9]{32}$/);
    assert.deepEqual(JSON.parse(options.body), input);
    throw new TypeError("Failed to fetch");
  }), error => {
    const info = error.lakis;
    assert.equal(info.error_code, "LKS-GEN-1012");
    assert.equal(info.failure_step, "request_send");
    assert.equal(info.error_exception_type, "TypeError");
    assert.equal(info.submission_diagnostic.acceptance, "unknown");
    assert.equal(info.submission_diagnostic.request_bytes, new Blob([JSON.stringify(input)]).size);
    assert.equal(info.submission_diagnostic.scene.pose_data_bytes, new Blob(["한글"]).size);
    assert.equal(info.submission_diagnostic.scene.enabled, false);
    assert.doesNotMatch(JSON.stringify(info), /PRIVATE_PROMPT|PRIVATE_IMAGE|PRIVATE_AUTH|PRIVATE_RENDER/);
    return true;
  });
  assert.equal(calls, 1);
});

test("response body, JSON, HTTP, schema and cancellation failures have distinct locations", async () => {
  const cases = [
    [async () => ({ status: 202, headers: new Headers(), text: async () => { throw new TypeError("terminated"); } }),
      "LKS-GEN-1026", "response_body", "unknown"],
    [async () => response("<html>PRIVATE_RESPONSE</html>", 503),
      "LKS-GEN-1011", "response_json", "unknown"],
    [async () => response('{"ok":false,"error":"Server error"}', 500),
      "LKS-GEN-1027", "response_validation", "rejected"],
    [async () => response("null"),
      "LKS-GEN-1028", "response_validation", "unknown"],
    [async () => response('{"ok":true}'),
      "LKS-GEN-1028", "response_validation", "unknown"],
    [async () => { throw new DOMException("Aborted", "AbortError"); },
      "LKS-GEN-1029", "request_send", "unknown"],
  ];
  for (const [request, code, phase, acceptance] of cases) {
    await assert.rejects(diagnostics.submit(payload(), request), error => {
      assert.equal(error.lakis.error_code, code);
      assert.equal(error.lakis.failure_step, phase);
      assert.equal(error.lakis.submission_diagnostic.acceptance, acceptance);
      assert.doesNotMatch(JSON.stringify(error.lakis), /PRIVATE_RESPONSE/);
      return true;
    });
  }
});

test("backend codes and confirmed acceptance are preserved separately from transport errors", async () => {
  await assert.rejects(diagnostics.submit(payload(), async () => response(JSON.stringify({
    ok: false, error_code: "LKS-MOD-1101", error: "모델을 찾을 수 없어요.",
    error_stage: "요청 검증", error_exception_type: "ValueError",
    error_detail: "PRIVATE_EXCEPTION C:/Users/private/model.safetensors",
    request_diagnostic: { acceptance: "rejected", server_step: "prompt_preparation" },
  }), 409)), error => {
    assert.equal(error.lakis.error_code, "LKS-MOD-1101");
    assert.equal(error.lakis.failure_component, "ui_server");
    assert.equal(error.lakis.error_exception_type, "ValueError");
    assert.equal(error.lakis.submission_diagnostic.server.server_step, "prompt_preparation");
    assert.doesNotMatch(JSON.stringify(error.lakis), /PRIVATE_EXCEPTION/);
    return true;
  });
  const accepted = await diagnostics.submit(payload(), async () => response(
    '{"ok":true,"request_id":"bridge-123","request_diagnostic":{"acceptance":"accepted"}}'));
  assert.equal(accepted.submission_diagnostic.acceptance, "accepted");
  assert.equal(accepted.submission_diagnostic.bridge_request_id, "bridge-123");
});

test("each preparation stage is distinct and serialization/oversize failure never sends POST", async () => {
  for (const [phase, code] of [
    ["payload_snapshot", "LKS-GEN-1020"], ["prompt_prepare", "LKS-GEN-1021"],
    ["wildcard_resolve", "LKS-GEN-1022"], ["prompt_translate", "LKS-GEN-1023"],
    ["inpaint_translate", "LKS-GEN-1024"], ["scene_prepare", "LKS-GEN-1025"],
  ]) {
    const context = diagnostics.createContext();
    diagnostics.mark(context, phase);
    const error = diagnostics.preparationFailure(new TypeError("PRIVATE_PROMPT"), context);
    assert.equal(error.lakis.error_code, code);
    assert.equal(error.lakis.failure_step, phase);
    assert.equal(error.lakis.submission_diagnostic.acceptance, "not_submitted");
    assert.doesNotMatch(JSON.stringify(error.lakis), /PRIVATE_PROMPT/);
  }
  const cyclic = {}; cyclic.self = cyclic;
  let calls = 0;
  await assert.rejects(diagnostics.submit(cyclic, async () => { calls++; }), error =>
    error.lakis.error_code === "LKS-GEN-1020");
  await assert.rejects(diagnostics.submit({ data: "x".repeat(45_000_000) },
    async () => { calls++; }), error => error.lakis.error_code === "LKS-CFG-1003"
      && error.lakis.submission_diagnostic.acceptance === "not_submitted");
  assert.equal(calls, 0);
});

let copied = [];
globalThis.window = {
  LAKISDiagnosticPacket: packet,
  LAKISGenerationDiagnostics: diagnostics,
};
Object.assign(globalThis, {
  continuousRun: null, continuousAdvance: false,
  setContinuousProgress() {}, resetGenerationButton() {}, generateButton: {},
  lastErrorReport: null, showDevModal() {},
});
const reportBegin = appSource.indexOf("function showGenerationError(");
const reportEnd = appSource.indexOf("function closeGenerationError(", reportBegin);
vm.runInThisContext(appSource.slice(reportBegin, reportEnd));

test("one copy contains summary and reversible detail while excluding sensitive input", async () => {
  let failure;
  try { await diagnostics.submit(payload(), async () => { throw new TypeError("Failed to fetch"); }); }
  catch (error) { failure = error.lakis; }
  globalThis.showGenerationError(failure.error, failure.error_code, {
    stage: failure.error_stage, failureStep: failure.failure_step,
    failureComponent: failure.failure_component, exceptionType: failure.error_exception_type,
    clientRequestId: failure.client_request_id, submissionDiagnostic: failure.submission_diagnostic,
    diagnostics: payload(), errorDetail: failure.error_detail,
  });
  const report = globalThis.lastErrorReport;
  const expectedTime = report.occurred_at;
  let click;
  copied = [];
  globalThis.errorDialogCopy = { addEventListener: (event, listener) => { click = listener; } };
  globalThis.fetch = async () => {
    globalThis.lastErrorReport = { error_code: "OTHER_JOB_MUST_NOT_REPLACE_SNAPSHOT" };
    return response('{"version":"8.0.1"}', 200);
  };
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
    clipboard: { writeText: async text => { copied.push(text); } },
  } });
  globalThis.setTimeout = callback => { callback(); return 0; };
  const begin = appSource.indexOf('errorDialogCopy.addEventListener("click",');
  const end = appSource.indexOf('errorDialog.addEventListener("click",', begin);
  vm.runInThisContext(appSource.slice(begin, end));
  await click({ currentTarget: {} });
  assert.equal(copied.length, 1);
  const text = copied[0];
  assert.match(text, /^LAKIS 8\.0\.1 \| LKS-GEN-1012/);
  assert.match(text, /서버 접수 여부 미확인/);
  assert.match(text, /위치: request_send/);
  const decoded = await packet.decode(text);
  assert.equal(decoded.report_schema, 1);
  assert.equal(decoded.error_code, "LKS-GEN-1012");
  assert.equal(decoded.occurred_at, expectedTime);
  assert.equal(decoded.submission.acceptance, "unknown");
  assert.equal(decoded.submission.scene.enabled, false);
  assert.equal(decoded.settings.loras[0].strength, 0);
  assert.equal(decoded.settings.model.checkpoint, "model.safetensors");
  assert.equal(decoded.settings.loras[0].name, "style.safetensors");
  assert.equal(decoded.settings.advanced_node_settings["123"].steps, 0);
  assert.equal(decoded.settings.advanced_node_settings["123"].enabled, false);
  const json = JSON.stringify(decoded);
  assert.doesNotMatch(json, /PRIVATE_|data:image|C:\/Users|"seed":|OTHER_JOB/);
  assert.ok(text.length < JSON.stringify(report, null, 2).length);
});

test("compression failure keeps the entire allowed report in the same copy", async () => {
  const report = {
    report_schema: 1, error_code: "LKS-GEN-1026", failure_stage: "응답 본문 수신",
    submission: { acceptance: "unknown", request_bytes: 0, http_status: 202 },
    runtime_trace: { last_node_id: "775", last_node_type: "Image Saver" },
  };
  globalThis.window.LAKISDiagnosticPacket = { encode: async () => { throw new Error("fixture"); } };
  const text = await globalThis.formatGenerationErrorReport(report, "8.0.1");
  const raw = JSON.parse(text.slice(text.lastIndexOf("): ") + 3));
  assert.equal(raw.runtime_trace.last_node_id, "775");
  assert.equal(raw.submission.request_bytes, 0);
  assert.equal(raw.packet_error.error_code, "LKS-UI-1020");
  globalThis.window.LAKISDiagnosticPacket = packet;
});
