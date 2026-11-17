const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8");

function loadNormalizer() {
  const start = source.indexOf("function normalizeContinuousCount(");
  assert.ok(start >= 0, "missing normalizeContinuousCount");
  const end = source.indexOf("\n}", start) + 2;
  const context = { Number, Math };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  return context.normalizeContinuousCount;
}

test("positive safe-integer targets are limited to 1000 without restoring the old 20 cap", () => {
  const normalize = loadNormalizer();
  assert.equal(normalize(1, 1), 1);
  assert.equal(normalize(20, 1), 20);
  assert.equal(normalize(21, 1), 21, "count=20 cap must be removed");
  assert.equal(normalize(100, 1), 100);
  assert.equal(normalize(1000, 1), 1000);
  assert.equal(normalize(1001, 1), 1000);
  assert.equal(normalize(1000000, 1), 1000);
  assert.equal(normalize("7", 1), 7);
  assert.equal(normalize(2.9, 1), 2, "fractional counts truncate");
  assert.equal(normalize(Number.MAX_SAFE_INTEGER, 1), 1000);
});

test("non-finite, non-positive and unsafe counts fall back", () => {
  const normalize = loadNormalizer();
  for (const value of [0, -1, -20, NaN, Infinity, -Infinity, null, undefined, "nope", {}, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(normalize(value, 1), 1, `must fall back for ${String(value)}`);
  }
  assert.equal(normalize(0, 5), 5, "fallback parameter must be honored");
});

function loadNextCounter() {
  const normStart = source.indexOf("function normalizeContinuousCount(");
  const nextStart = source.indexOf("function nextContinuousCount(");
  assert.ok(normStart >= 0 && nextStart >= 0, "missing continuous helpers");
  let depth = 0;
  let end = nextStart;
  for (; end < source.length; end += 1) {
    if (source[end] === "{") depth += 1;
    else if (source[end] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  const context = { Number, Math };
  vm.createContext(context);
  vm.runInContext(`${source.slice(normStart, source.indexOf("\n}", normStart) + 2)};${source.slice(nextStart, end + 1)}`, context);
  return context.nextContinuousCount;
}

function controls() {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: "", attributes: {}, handlers: {},
      classList: { toggle() {} },
      setAttribute(key, value) { this.attributes[key] = value; },
      addEventListener(type, handler) { this.handlers[type] = handler; },
      blur() { this.handlers.blur(); },
    });
    return nodes.get(id);
  };
  let saves = 0;
  const context = {
    state: { continuous: { enabled: true, count: 1 } }, continuousRun: null,
    document: { querySelector: element },
    normalizeContinuousCount: loadNormalizer(), nextContinuousCount: loadNextCounter(),
    scheduleGenerationStateSave() { saves += 1; },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("const CONTINUOUS_DEFAULT_COUNT"), source.indexOf("const generateButton =")), context);
  return { state: context.state, input: element("#continuousCount"), element, saves: () => saves };
}

test("typed counts commit, persist once, retain +/- and never start generation", () => {
  const h = controls();
  h.input.value = "125";
  h.input.handlers.change();
  h.input.handlers.blur();
  assert.equal(h.state.continuous.count, 125);
  assert.equal(h.input.value, "125");
  assert.equal(h.saves(), 1);
  h.element("#continuousCountUp").handlers.click();
  assert.equal(h.state.continuous.count, 126);
  h.element("#continuousCountDown").handlers.click();
  assert.equal(h.state.continuous.count, 125);
  h.input.value = "30";
  let prevented = false;
  h.input.handlers.keydown({ key: "Enter", preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(h.state.continuous.count, 30);
  assert.equal(h.saves(), 4);
});

test("empty, negative and unsafe typed counts retain the prior target", () => {
  const h = controls();
  h.input.value = "27";
  h.input.handlers.change();
  for (const value of ["", "0", "-1", "invalid", String(Number.MAX_SAFE_INTEGER + 1)]) {
    h.input.value = value;
    h.input.handlers.blur();
    assert.equal(h.state.continuous.count, 27);
    assert.equal(h.input.value, "27");
  }
  assert.equal(h.saves(), 1);
});

test("increment stops at 1000 instead of overflowing or resetting to 1", () => {
  const next = loadNextCounter();
  assert.equal(next(1), 2);
  assert.equal(next(20), 21, "20 cap must be gone");
  assert.equal(next(999), 1000);
  assert.equal(next(1000), 1000, "boundary must hold instead of resetting");
  assert.equal(next(Number.MAX_SAFE_INTEGER - 1), 1000);
  assert.equal(next(Number.MAX_SAFE_INTEGER), 1000);
  assert.ok(Number.isSafeInteger(next(Number.MAX_SAFE_INTEGER)), "boundary result must stay a safe integer");
  assert.equal(next("41"), 42);
});

test("typing above 1000 and restoring oversized settings cannot exceed the cap", () => {
  const h = controls();
  h.input.value = "1001";
  h.input.handlers.change();
  assert.equal(h.state.continuous.count, 1000);
  assert.equal(h.input.value, "1000");
  h.element("#continuousCountUp").handlers.click();
  assert.equal(h.state.continuous.count, 1000);
  h.input.value = "1000000";
  h.input.handlers.blur();
  assert.equal(h.state.continuous.count, 1000);
  h.element("#continuousCountDown").handlers.click();
  assert.equal(h.state.continuous.count, 999);
});

function loadCompleteHandler() {
  const start = source.indexOf("function handleGenerationComplete()");
  assert.ok(start >= 0, "missing handleGenerationComplete");
  let depth = 0;
  let end = start;
  for (; end < source.length; end += 1) {
    if (source[end] === "{") depth += 1;
    else if (source[end] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  return source.slice(start, end + 1);
}

function runComplete(initial) {
  const timers = [];
  const calls = { progress: [], resets: 0, clicks: 0 };
  const context = {
    continuousRun: structuredClone(initial.run),
    continuousAdvance: false,
    generationCancelRequested: Boolean(initial.cancel),
    generationResetTimer: null,
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    setContinuousProgress: (...args) => { calls.progress.push(args); },
    resetGenerationButton: () => { calls.resets += 1; },
    generateButton: { click: () => { calls.clicks += 1; } },
    setGenerationProgress: () => {},
  };
  vm.createContext(context);
  vm.runInContext(`${loadCompleteHandler()}; handleGenerationComplete();`, context);
  for (const timer of timers.splice(0)) vm.runInContext("void 0;", context), timer();
  return { context, calls };
}

test("sequential execution advances, honors stop, and completes without retry", () => {
  let result = runComplete({ run: { index: 1, total: 3, stop: false } });
  assert.equal(result.context.continuousAdvance, true, "must advance to the next request");
  assert.equal(result.calls.clicks, 1, "must submit exactly one follow-up request");
  assert.equal(result.calls.resets, 1, "must reset the button before advancing");
  result = runComplete({ run: { index: 1, total: 3, stop: true } });
  assert.equal(result.context.continuousRun, null, "stop must clear the run");
  assert.equal(result.context.continuousAdvance, false, "stop must not advance");
  assert.equal(result.calls.clicks, 0, "stop must not submit another request");
  assert.ok(result.calls.progress.some(([, label]) => label === "중지됨"), "stop must report interruption");
  result = runComplete({ run: { index: 3, total: 3, stop: false } });
  assert.equal(result.context.continuousRun, null, "final completion must clear the run");
  assert.equal(result.calls.clicks, 0, "completion must not retry automatically");
  assert.ok(result.calls.progress.some(([, label]) => label === "완료"), "completion must report done");
});

test("error and cancel paths reset without resubmitting", () => {
  for (const name of ["lakis:generation-error", "lakis:generation-cancelled"]) {
    const marker = `window.addEventListener("${name}"`;
    const start = source.indexOf(marker);
    assert.ok(start >= 0, `missing ${name} handler`);
    const arrow = source.indexOf("=>", start);
    const end = source.indexOf("});", arrow);
    const body = source.slice(source.indexOf("{", arrow) + 1, end);
    assert.ok(!body.includes("generateButton.click"), `${name} must not retry`);
    assert.ok(!body.includes("lakis:generate"), `${name} must not resubmit`);
    const context = {
      continuousRun: { index: 2, total: 5, stop: false },
      setContinuousProgress: () => {},
      resetGenerationButton: () => {},
    };
    vm.createContext(context);
    vm.runInContext(`${body};`, context);
    assert.equal(context.continuousRun, null, `${name} must clear the run`);
  }
});
