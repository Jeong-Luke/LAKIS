const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/external_ui/app.js"), "utf8");
new vm.Script(source);
const start = source.indexOf("async function animateGenerationEngineSwitch(");
const end = source.indexOf("async function switchGenerationEngine(", start);
assert.ok(start >= 0 && end > start);
const script = source.slice(start, end);

function element() {
  const classes = new Set();
  return {
    dataset: {}, hidden: true, inert: false, offsetWidth: 100, textContent: "",
    classList: {
      add(...names) { names.forEach(name => classes.add(name)); },
      remove(...names) { names.forEach(name => classes.delete(name)); },
      contains(name) { return classes.has(name); },
    },
  };
}

function fixture({ reduced = false, initiallyInert = false } = {}) {
  const shell = element(), layer = element(), status = element();
  shell.inert = initiallyInert;
  const calls = { random: 0, prepare: 0, waits: [] };
  let roll = 0;
  const math = Object.create(Math);
  math.random = () => { calls.random++; return roll; };
  const context = {
    Math: math,
    window: {
      matchMedia(query) {
        assert.equal(query, "(prefers-reduced-motion: reduce)");
        return { matches: reduced };
      },
    },
    document: {
      querySelector(selector) {
        const result = {
          ".app-shell": shell,
          "#generationEngineTransition": layer,
          "#generationEngineTransitionStatus": status,
        }[selector];
        assert.ok(result, selector);
        return result;
      },
    },
    async waitForEngineTransition(ms) { calls.waits.push(ms); },
  };
  vm.createContext(context);
  vm.runInContext(script, context);
  return {
    shell, layer, status, calls,
    async run(next, randomValue, expectedSpecial, fail = false) {
      roll = randomValue;
      const countBefore = calls.random;
      const run = context.animateGenerationEngineSwitch(next, async () => {
        calls.prepare++;
        assert.equal(layer.dataset.engine, next);
        assert.equal(layer.dataset.easterEgg, String(expectedSpecial));
        assert.equal(layer.hidden, false);
        assert.equal(layer.classList.contains("is-active"), true);
        assert.equal(shell.inert, true);
        assert.match(status.textContent, new RegExp(next.toUpperCase()));
        if (fail) throw new Error("inventory unavailable");
      });
      if (fail) await assert.rejects(run, /inventory unavailable/);
      else await run;
      assert.equal(calls.random - countBefore, 1);
      assert.equal(layer.hidden, true);
      assert.equal(layer.dataset.easterEgg, undefined);
      assert.equal(layer.classList.contains("is-active"), false);
      assert.equal(layer.classList.contains("is-exiting"), false);
      assert.equal(shell.classList.contains("engine-transition-shell"), false);
      assert.equal(shell.classList.contains("is-engine-leaving"), false);
      assert.equal(shell.inert, initiallyInert);
    },
  };
}

(async () => {
  for (const next of ["anima", "moss"]) {
    const sample = fixture();
    for (let i = 0; i < 100; i++) {
      // Independent evenly spaced values: exactly five of 100 select special.
      await sample.run(next, i / 100, i < 5);
    }
    await sample.run(next, 0.049999, true);
    await sample.run(next, 0.05, false);
    await sample.run(next, 0.999999, false);
    assert.equal(sample.calls.prepare, 103);
    assert.equal(sample.calls.random, 103);
  }
  const sequence = fixture();
  await sequence.run("moss", 0, true);
  await sequence.run("anima", 0.5, false);
  assert.deepEqual(sequence.calls.waits, [220, 1800, 320, 220, 220, 1800, 320, 220]);

  for (const reduced of [false, true]) {
    for (const initiallyInert of [false, true]) {
      const sample = fixture({ reduced, initiallyInert });
      await sample.run("moss", 0, true, true);
      await sample.run("anima", 0.8, false);
      assert.equal(sample.calls.prepare, 2);
      if (reduced) {
        assert.deepEqual(sample.calls.waits, [80, 200, 80, 80, 80, 200, 80, 80]);
      }
    }
  }
  console.log("PASS: 5% boundaries, one roll/preparation per transition, both engines, reset, failure cleanup, reduced motion, existing inert state");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
