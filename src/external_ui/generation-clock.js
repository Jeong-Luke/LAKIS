(function () {
  "use strict";

  var TICK_MS = 1000;

  var el = document.getElementById("generateElapsed");

  var activeRequestId = null;
  var startMs = null;
  var intervalId = null;
  var frozenState = null;
  var frozenRequestId = null;
  var frozenEndMs = null;

  function pad2(value) {
    return (value < 10 ? "0" : "") + String(value);
  }

  function formatElapsed(totalSeconds) {
    var total = Math.max(0, Math.floor(totalSeconds));
    var hours = Math.floor(total / 3600);
    var minutes = Math.floor((total % 3600) / 60);
    var seconds = total % 60;
    if (hours > 0) {
      return String(hours) + ":" + pad2(minutes) + ":" + pad2(seconds);
    }
    return pad2(minutes) + ":" + pad2(seconds);
  }

  function toUnixMs(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value * 1000;
    }
    return null;
  }

  function render(elapsedMs) {
    var safe = elapsedMs;
    if (!Number.isFinite(safe)) {
      safe = 0;
    }
    if (safe < 0) {
      safe = 0;
    }
    el.textContent = formatElapsed(safe / 1000);
    el.style.display = "";
    el.hidden = false;
  }

  function hideElement() {
    el.textContent = "";
    el.style.display = "none";
    el.hidden = true;
  }

  function tick() {
    if (startMs === null) {
      return;
    }
    render(Date.now() - startMs);
  }

  function ensureInterval() {
    if (intervalId !== null) {
      return;
    }
    intervalId = setInterval(tick, TICK_MS);
  }

  function clearTimer() {
    if (intervalId !== null) {
      clearInterval(intervalId);
    }
    intervalId = null;
  }

  function getState(status) {
    if (!status || typeof status !== "object") {
      return "unknown";
    }
    if (status.state === undefined || status.state === null) {
      return "unknown";
    }
    return String(status.state).toLowerCase();
  }

  function getRequestId(status) {
    if (!status || typeof status !== "object") {
      return null;
    }
    var value = status.request_id;
    if (value === null || value === undefined || value === "") {
      return null;
    }
    return value;
  }

  function isTerminal(state) {
    return state === "complete" || state === "cancelled" || state === "error";
  }

  function begin() {
    if (intervalId !== null) {
      return;
    }
    activeRequestId = null;
    startMs = Date.now();
    frozenState = null;
    frozenRequestId = null;
    frozenEndMs = null;
    ensureInterval();
    render(0);
  }

  function sync(status) {
    var state = getState(status);
    if (state === "idle") {
      reset();
      return;
    }
    if (isTerminal(state)) {
      var incomingTerminalId = getRequestId(status);
      if (frozenState === state && frozenRequestId === incomingTerminalId && frozenEndMs !== null) {
        var retryFinish = toUnixMs(status.finished_at);
        if (retryFinish === null) {
          clearTimer();
          return;
        }
      }
      var serverStart = toUnixMs(status.started_at);
      if (serverStart !== null) {
        startMs = serverStart;
      } else if (startMs === null) {
        startMs = Date.now();
      }
      var serverFinish = toUnixMs(status.finished_at);
      var endMs = serverFinish !== null ? serverFinish : Date.now();
      if (incomingTerminalId !== null) {
        activeRequestId = incomingTerminalId;
      }
      render(endMs - startMs);
      frozenState = state;
      frozenRequestId = incomingTerminalId;
      frozenEndMs = endMs;
      clearTimer();
      return;
    }
    frozenState = null;
    frozenRequestId = null;
    frozenEndMs = null;
    var incomingId = getRequestId(status);
    var serverStartMs = toUnixMs(status.started_at);
    if (incomingId !== null && incomingId !== activeRequestId) {
      activeRequestId = incomingId;
      startMs = serverStartMs !== null ? serverStartMs : Date.now();
    } else {
      if (incomingId !== null) {
        activeRequestId = incomingId;
      }
      if (serverStartMs !== null) {
        startMs = serverStartMs;
      } else if (startMs === null) {
        startMs = Date.now();
      }
    }
    ensureInterval();
    render(Date.now() - startMs);
  }

  function stop() {
    if (frozenEndMs !== null) {
      clearTimer();
      return;
    }
    if (startMs !== null) {
      render(Date.now() - startMs);
    }
    clearTimer();
  }

  function reset() {
    clearTimer();
    startMs = null;
    activeRequestId = null;
    frozenState = null;
    frozenRequestId = null;
    frozenEndMs = null;
    hideElement();
  }

  var api = {
    begin: begin,
    sync: sync,
    stop: stop,
    reset: reset
  };

  window.LAKISGenerationClock = api;
})();
