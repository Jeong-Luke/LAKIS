const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const sourcePath = path.join(__dirname, "../../src/external_ui/generation-clock.js");
const source = fs.readFileSync(sourcePath, "utf8");

function createHarness(initialNowMs) {
  let fakeNow = initialNowMs;
  const intervals = new Map();
  const delays = [];
  let nextId = 1;
  let createCount = 0;
  const element = {
    textContent: "",
    style: { display: "" },
    hidden: false,
  };
  const document = {
    getElementById(id) {
      assert.equal(id, "generateElapsed");
      return element;
    },
  };
  function backendSpy(name) {
    return function () {
      assert.fail(`generation clock must not call ${name}`);
    };
  }
  const sandbox = {
    window: {},
    document,
    Date: { now: () => fakeNow },
    Math,
    Number,
    String,
    Object,
    setInterval(fn, ms) {
      delays.push(ms);
      const id = nextId;
      nextId += 1;
      intervals.set(id, fn);
      createCount += 1;
      return id;
    },
    clearInterval(id) {
      intervals.delete(id);
    },
    fetch: backendSpy("fetch"),
    XMLHttpRequest: backendSpy("XMLHttpRequest"),
    WebSocket: backendSpy("WebSocket"),
    EventSource: backendSpy("EventSource"),
    navigator: { sendBeacon: backendSpy("sendBeacon") },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: "generation-clock.js" });
  const clock = sandbox.window.LAKISGenerationClock;
  assert.ok(clock, "window.LAKISGenerationClock must be exported");
  return {
    clock,
    element,
    intervals,
    delays,
    get now() {
      return fakeNow;
    },
    setNow(value) {
      fakeNow = value;
    },
    advance(ms) {
      fakeNow += ms;
      for (const fn of Array.from(intervals.values())) {
        fn();
      }
    },
    tick() {
      for (const fn of Array.from(intervals.values())) {
        fn();
      }
    },
    get createCount() {
      return createCount;
    },
  };
}

function toUnixSeconds(ms) {
  return ms / 1000;
}

test("clock exposes the four-method API without backend calls on a one-second interval", () => {
  const h = createHarness(1_700_000_000_000);
  for (const name of ["begin", "sync", "stop", "reset"]) {
    assert.equal(typeof h.clock[name], "function", `${name} must be a function`);
  }
  h.clock.begin();
  h.clock.sync({
    state: "running",
    request_id: "api-check",
    started_at: toUnixSeconds(1_700_000_000_000 - 2000),
  });
  h.clock.stop();
  h.clock.sync({
    state: "running",
    request_id: "api-check-2",
    started_at: toUnixSeconds(1_700_000_000_000 - 1000),
  });
  h.clock.reset();
  assert.ok(h.delays.length > 0, "clock must schedule an interval");
  for (const delay of h.delays) {
    assert.equal(delay, 1000, "interval delay must be one second");
  }
  h.clock.sync({
    state: "running",
    request_id: "fmt-check",
    started_at: toUnixSeconds(1_700_000_000_000 - 65000),
  });
  assert.match(h.element.textContent, /^(?:\d{2}:\d{2}|\d+:\d{2}:\d{2})$/);
  assert.ok(!h.element.textContent.includes("%"), "display must not contain percentages");
  assert.ok(!h.element.textContent.includes(" "), "display must be time only");
});

test("formatting shows MM:SS below one hour and H:MM:SS after", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  const cases = [
    [0, "00:00"],
    [5, "00:05"],
    [59, "00:59"],
    [60, "01:00"],
    [65, "01:05"],
    [599, "09:59"],
    [600, "10:00"],
    [3599, "59:59"],
    [3600, "1:00:00"],
    [3661, "1:01:01"],
    [7322, "2:02:02"],
  ];
  for (const [elapsedSec, expected] of cases) {
    h.clock.sync({
      state: "running",
      request_id: "fmt",
      started_at: toUnixSeconds(base - elapsedSec * 1000),
    });
    assert.equal(h.element.textContent, expected, `elapsed ${elapsedSec}s`);
    assert.match(h.element.textContent, /^(?:\d{2}:\d{2}|\d+:\d{2}:\d{2})$/);
  }
});

test("begin starts a provisional 00:00 clock and never restarts an active clock", () => {
  const h = createHarness(1_700_000_000_000);
  h.clock.begin();
  assert.equal(h.element.textContent, "00:00");
  assert.equal(h.intervals.size, 1);
  const firstCount = h.createCount;
  h.advance(7000);
  assert.equal(h.element.textContent, "00:07");
  h.clock.begin();
  assert.equal(h.element.textContent, "00:07", "second begin must not restart");
  assert.equal(h.createCount, firstCount, "second begin must not recreate the interval");
  h.advance(3000);
  assert.equal(h.element.textContent, "00:10");
});

test("one-second ticks advance a running job", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  h.clock.sync({ state: "running", request_id: "tick-1", started_at: toUnixSeconds(base - 2 * 1000) });
  assert.equal(h.element.textContent, "00:02");
  h.advance(1000);
  assert.equal(h.element.textContent, "00:03");
  h.advance(57000);
  assert.equal(h.element.textContent, "01:00");
});

test("repeated active polls reuse the interval and negative elapsed clamps to zero", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  h.clock.sync({ state: "running", request_id: "same", started_at: toUnixSeconds(base - 4 * 1000) });
  assert.equal(h.createCount, 1);
  h.clock.sync({ state: "running", request_id: "same", started_at: toUnixSeconds(base - 4 * 1000) });
  h.clock.sync({ state: "preparing", request_id: "same", started_at: toUnixSeconds(base - 4 * 1000) });
  h.clock.sync({ state: "cancelling", request_id: "same", started_at: toUnixSeconds(base - 4 * 1000) });
  h.clock.sync({ state: "unknown", request_id: "same", started_at: toUnixSeconds(base - 4 * 1000) });
  assert.equal(h.createCount, 1, "repeated active polls must not recreate the interval");
  assert.equal(h.intervals.size, 1);
  for (const delay of h.delays) {
    assert.equal(delay, 1000);
  }
  h.clock.sync({ state: "running", request_id: "future", started_at: toUnixSeconds(base + 30 * 1000) });
  assert.equal(h.element.textContent, "00:00", "future started_at must clamp to zero");
});

test("reload anchoring uses server started_at without a prior begin", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  h.clock.sync({ state: "running", request_id: "reloaded", started_at: toUnixSeconds(base - 90 * 1000) });
  assert.equal(h.element.textContent, "01:30");
  assert.equal(h.intervals.size, 1);
  h.advance(30000);
  assert.equal(h.element.textContent, "02:00");
});

test("a different request_id resets the job clock on the same interval", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  h.clock.sync({ state: "running", request_id: "job-a", started_at: toUnixSeconds(base - 50 * 1000) });
  assert.equal(h.element.textContent, "00:50");
  const created = h.createCount;
  h.setNow(base + 20 * 1000);
  h.clock.sync({ state: "running", request_id: "job-a", started_at: toUnixSeconds(base - 50 * 1000) });
  assert.equal(h.element.textContent, "01:10");
  h.clock.sync({ state: "running", request_id: "job-b", started_at: toUnixSeconds(base + 20 * 1000 - 3 * 1000) });
  assert.equal(h.element.textContent, "00:03", "new request must reset to its own start");
  assert.equal(h.createCount, created, "request change must not recreate the interval");
  assert.equal(h.intervals.size, 1);
});

test("terminal states freeze at finished_at and keep timers stopped", () => {
  const base = 1_700_000_000_000;
  for (const terminal of ["complete", "cancelled", "error"]) {
    const h = createHarness(base);
    h.clock.sync({ state: "running", request_id: `job-${terminal}`, started_at: toUnixSeconds(base - 10 * 1000) });
    assert.equal(h.intervals.size, 1);
    h.clock.sync({
      state: terminal,
      request_id: `job-${terminal}`,
      started_at: toUnixSeconds(base - 10 * 1000),
      finished_at: toUnixSeconds(base + 25 * 1000),
    });
    assert.equal(h.element.textContent, "00:35", `${terminal} must freeze at finish minus start`);
    assert.equal(h.intervals.size, 0, `${terminal} must stop the timer`);
    h.setNow(base + 120 * 1000);
    h.tick();
    assert.equal(h.element.textContent, "00:35", `${terminal} display must stay frozen`);
  }
});

test("terminal states without finished_at freeze at now and clamp negatives", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base + 40 * 1000);
  h.clock.sync({ state: "running", request_id: "no-finish", started_at: toUnixSeconds(base) });
  assert.equal(h.element.textContent, "00:40");
  h.clock.sync({ state: "error", request_id: "no-finish", started_at: toUnixSeconds(base) });
  assert.equal(h.element.textContent, "00:40");
  assert.equal(h.intervals.size, 0);
  const neg = createHarness(base);
  neg.clock.sync({
    state: "complete",
    request_id: "negative",
    started_at: toUnixSeconds(base),
    finished_at: toUnixSeconds(base - 5 * 1000),
  });
  assert.equal(neg.element.textContent, "00:00");
  assert.equal(neg.intervals.size, 0);
});

test("repeated terminal sync without finished_at remains frozen", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base + 40 * 1000);
  h.clock.sync({ state: "running", request_id: "frozen", started_at: toUnixSeconds(base) });
  h.clock.sync({ state: "error", request_id: "frozen", started_at: toUnixSeconds(base) });
  const frozen = h.element.textContent;
  assert.equal(frozen, "00:40");
  h.setNow(base + 90 * 1000);
  h.clock.sync({ state: "error", request_id: "frozen", started_at: toUnixSeconds(base) });
  assert.equal(h.element.textContent, frozen, "repeated terminal without finish must stay frozen");
  h.clock.sync({ state: "error", request_id: "frozen", started_at: toUnixSeconds(base) });
  assert.equal(h.element.textContent, frozen);
  assert.equal(h.intervals.size, 0);
});

test("stop renders the final second but preserves a frozen terminal", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  h.clock.sync({ state: "running", request_id: "stop-live", started_at: toUnixSeconds(base - 12 * 1000) });
  assert.equal(h.element.textContent, "00:12");
  h.setNow(base + 1500);
  h.clock.stop();
  assert.equal(h.element.textContent, "00:13", "stop must render the current final second");
  assert.equal(h.intervals.size, 0);
  const t = createHarness(base + 40 * 1000);
  t.clock.sync({ state: "running", request_id: "stop-frozen", started_at: toUnixSeconds(base) });
  t.clock.sync({ state: "complete", request_id: "stop-frozen", started_at: toUnixSeconds(base) });
  const frozen = t.element.textContent;
  assert.equal(frozen, "00:40");
  t.setNow(base + 200 * 1000);
  t.clock.stop();
  assert.equal(t.element.textContent, frozen, "stop must preserve an already frozen terminal");
  assert.equal(t.intervals.size, 0);
});

test("stop freezes the display while reset clears and hides", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  h.clock.sync({ state: "running", request_id: "s1", started_at: toUnixSeconds(base - 12 * 1000) });
  assert.equal(h.element.textContent, "00:12");
  h.clock.stop();
  assert.equal(h.intervals.size, 0, "stop must clear the interval");
  assert.equal(h.element.textContent, "00:12", "stop must leave the frozen value visible");
  h.clock.reset();
  assert.equal(h.intervals.size, 0);
  assert.equal(h.element.textContent, "");
  assert.equal(h.element.style.display, "none");
  assert.equal(h.element.hidden, true);
  h.setNow(base + 5 * 1000);
  h.clock.begin();
  assert.equal(h.element.textContent, "00:00", "begin after reset starts a fresh clock");
  assert.equal(h.element.style.display, "");
});

test("idle sync resets the clock", () => {
  const base = 1_700_000_000_000;
  const h = createHarness(base);
  h.clock.sync({ state: "running", request_id: "active", started_at: toUnixSeconds(base - 9 * 1000) });
  assert.equal(h.element.textContent, "00:09");
  h.clock.sync({ state: "idle" });
  assert.equal(h.element.textContent, "");
  assert.equal(h.element.style.display, "none");
  assert.equal(h.intervals.size, 0);
});
