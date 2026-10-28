(function (root) {
  "use strict";
  const contexts = new WeakMap();
  const limitBytes = 45_000_000;
  const preparation = {
    payload_snapshot: ["LKS-GEN-1020", "생성 설정 복사"],
    request_serialization: ["LKS-GEN-1020", "생성 요청 직렬화"],
    prompt_prepare: ["LKS-GEN-1021", "프롬프트 준비"],
    wildcard_resolve: ["LKS-GEN-1022", "와일드카드 치환"],
    prompt_translate: ["LKS-GEN-1023", "프롬프트 번역"],
    inpaint_translate: ["LKS-GEN-1024", "인페인트 프롬프트 번역"],
    scene_prepare: ["LKS-GEN-1025", "3D 장면 준비"],
  };
  const byteLength = value => new Blob([value]).size;

  function createContext() {
    return {
      client_request_id: root.crypto.randomUUID().replaceAll("-", ""),
      started_at: new Date().toISOString(),
      started_ms: root.performance.now(),
      phase: "payload_snapshot",
      acceptance: "not_submitted",
      method: "POST", endpoint: "/api/generate", timeline: [],
    };
  }

  function mark(context, phase) {
    context.phase = phase;
    context.timeline.push({
      phase, elapsed_ms: Math.round(root.performance.now() - context.started_ms),
    });
  }

  function snapshot(context) {
    const { started_ms, ...diagnostic } = context;
    return structuredClone(diagnostic);
  }

  function bind(payload, context) {
    contexts.set(payload, context);
  }

  function sceneSummary(payload) {
    const scene = payload.scene_controls || {};
    const result = {
      enabled: Boolean(scene.enabled), toyxyz_enabled: Boolean(scene.toyxyz_enabled),
    };
    for (const key of ["pose_data", "toyxyz_render_data", "toyxyz_paint_data"]) {
      result[`${key}_bytes`] = typeof scene[key] === "string" ? byteLength(scene[key]) : 0;
    }
    return result;
  }

  function failure(error, context, code, stage, message, server = null) {
    const result = new Error(message);
    result.lakis = {
      error: message, error_code: code, error_stage: stage,
      error_exception_type: error?.name || "Error",
      failure_component: server ? "ui_server" : "frontend",
      failure_step: context.phase,
      client_request_id: context.client_request_id,
      submission_diagnostic: snapshot(context),
    };
    if (server) {
      for (const key of [
        "error_node_id", "error_node_type", "request_id", "prompt_id",
        "setting_diagnostic", "diagnostic_context", "request_diagnostic",
      ]) {
        if (server[key] !== undefined) result.lakis[key] = server[key];
      }
      if (server.error_exception_type) {
        result.lakis.error_exception_type = server.error_exception_type;
      }
    } else {
      result.lakis.error_detail = `${error?.name || "Error"} at ${context.phase}`;
    }
    return result;
  }

  function preparationFailure(error, context) {
    const [code, stage] = preparation[context.phase] || preparation.payload_snapshot;
    return failure(error, context, code, stage, `${stage}에 실패했어요.`);
  }

  async function submit(payload, fetchRequest = root.fetch) {
    const context = contexts.get(payload) || createContext();
    contexts.set(payload, context);
    mark(context, "request_serialization");
    let body;
    try {
      body = JSON.stringify(payload);
      if (typeof body !== "string") throw new TypeError("Generation payload is not JSON");
      context.request_bytes = byteLength(body);
      context.request_limit_bytes = limitBytes;
      context.scene = sceneSummary(payload);
    } catch (error) {
      throw preparationFailure(error, context);
    }
    if (context.request_bytes > limitBytes) {
      mark(context, "request_size_check");
      const error = failure(new RangeError(), context, "LKS-CFG-1003",
        "생성 요청 크기 검사", "생성 요청 데이터가 허용 크기를 초과했어요.");
      error.lakis.setting_diagnostic = { request_validation_reason: "body_too_large" };
      throw error;
    }
    mark(context, "request_send");
    context.acceptance = "unknown";
    let response;
    try {
      response = await fetchRequest("/api/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-LAKIS-Client-Request-ID": context.client_request_id,
        },
        body,
      });
    } catch (error) {
      const aborted = error?.name === "AbortError";
      throw failure(error, context, aborted ? "LKS-GEN-1029" : "LKS-GEN-1012",
        "생성 요청 전송·응답 대기", aborted
          ? "브라우저에서 생성 요청이 중단됐어요. 서버 접수 여부는 확인되지 않았어요."
          : "생성 서버의 응답을 받지 못했어요. 서버 접수 여부는 확인되지 않았어요.");
    }
    context.http_status = response.status;
    context.response_content_type = response.headers.get("Content-Type") || "";
    mark(context, "response_body");
    let text;
    try {
      text = await response.text();
      context.response_bytes = byteLength(text);
    } catch (error) {
      throw failure(error, context, "LKS-GEN-1026", "생성 응답 본문 수신",
        "응답 헤더는 받았지만 생성 응답 내용을 끝까지 읽지 못했어요.");
    }
    mark(context, "response_json");
    let result;
    try {
      result = JSON.parse(text);
    } catch (error) {
      throw failure(error, context, "LKS-GEN-1011", "생성 응답 JSON 해석",
        `생성 서버 응답을 해석하지 못했어요. (HTTP ${response.status})`);
    }
    mark(context, "response_validation");
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw failure(new TypeError(), context, "LKS-GEN-1028", "생성 응답 구조 검사",
        "생성 서버 응답의 형식이 올바르지 않아요.");
    }
    if (result.request_diagnostic && typeof result.request_diagnostic === "object") {
      const diagnostic = result.request_diagnostic;
      context.server = {};
      for (const key of [
        "client_request_id", "request_bytes", "request_limit_bytes",
        "acceptance", "server_step", "elapsed_ms",
      ]) {
        if (diagnostic[key] !== undefined) context.server[key] = diagnostic[key];
      }
    }
    if (!response.ok || result.ok !== true) {
      context.acceptance = context.server?.acceptance
        || (result.ok === false ? "rejected" : "unknown");
      const code = typeof result.error_code === "string" && result.error_code
        ? result.error_code : "LKS-GEN-1027";
      throw failure(new Error(), context, code, result.error_stage || "생성 서버 HTTP 응답",
        result.error || `생성 요청이 정상 처리되지 않았어요. (HTTP ${response.status})`, result);
    }
    if (typeof result.request_id !== "string" || !result.request_id) {
      throw failure(new TypeError(), context, "LKS-GEN-1028", "생성 접수 ID 확인",
        "성공 응답에 생성 접수 ID가 없어 접수 여부를 확인하지 못했어요.");
    }
    context.acceptance = "accepted";
    context.bridge_request_id = result.request_id;
    mark(context, "accepted");
    return { ...result, submission_diagnostic: snapshot(context) };
  }

  root.LAKISGenerationDiagnostics = Object.freeze({
    createContext, bind, mark, preparationFailure, submit,
  });
})(globalThis);
