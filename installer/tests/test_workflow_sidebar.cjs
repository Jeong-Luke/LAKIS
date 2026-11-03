/* Connect the real sidebar choices to the actual workflow-open click handler. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const root = process.env.LAKIS_TEST_SOURCE_ROOT || path.resolve(__dirname, '../..');
const htmlPath = path.join(root, 'src/external_ui/index.html');
const jsPath = path.join(root, 'src/external_ui/app.js');
const html = fs.readFileSync(htmlPath, 'utf8').replace(/\r\n/g, '\n');
const js = fs.readFileSync(jsPath, 'utf8').replace(/\r\n/g, '\n');
const handlerMatch = js.match(/workflowMenu\.addEventListener\("click",\s*async event => \{\n[\s\S]*?\n\}\);/);
assert.ok(handlerMatch, 'workflow click handler should be extractable from app.js');

const menuStart = html.indexOf('<div id="workflowMenu"');
assert.notEqual(menuStart, -1, 'workflow menu should exist in index.html');
const menuEnd = html.indexOf('</div>', menuStart);
assert.notEqual(menuEnd, -1, 'workflow menu should be closed in index.html');
const menuHtml = html.slice(menuStart, menuEnd);
const choices = [...menuHtml.matchAll(/<button\b[^>]*data-workflow-kind="([^"]+)"[^>]*>/g)]
  .map(match => {
    const tag = match[0];
    const attr = name => {
      const result = tag.match(new RegExp(`\\b${name}="([^"]*)"`));
      return result && result[1];
    };
    return { kind: match[1], tooltip: attr('data-tooltip'), ariaLabel: attr('aria-label') };
  });

async function clickChoice(kind, options = {}) {
  let clickHandler;
  const requests = [];
  const errors = [];
  const openCalls = [];
  let popupClosed = 0;
  let replacedUrl = null;
  const popup = {
    location: { replace(url) { replacedUrl = url; } },
    close() { popupClosed += 1; },
  };
  const window = {
    open(...args) {
      openCalls.push(args);
      if (args[0] === 'about:blank') return options.popupBlocked ? null : popup;
      return null;
    },
  };
  const workflowMenu = {
    hidden: false,
    addEventListener(type, callback) {
      assert.equal(type, 'click');
      clickHandler = callback;
    },
  };
  const context = vm.createContext({
    workflowMenu,
    workflowButton: { setAttribute() {} },
    closeWorkflowMenu() { workflowMenu.hidden = true; },
    window,
    fetch: async (url, init) => {
      requests.push({ url, init });
      if (options.fetchFails) throw new Error('offline');
      return {
        ok: !options.responseFails,
        status: options.responseFails ? 500 : 200,
        async json() {
          return options.responseFails
            ? { ok: false, error: 'preparation failed' }
            : { ok: true, comfy_url: 'http://127.0.0.1:8189/' };
        },
      };
    },
    showGenerationError(message) { errors.push(message); },
  });

  vm.runInContext(handlerMatch[0], context, { filename: jsPath });
  assert.equal(typeof clickHandler, 'function');
  await clickHandler({
    target: {
      closest(selector) {
        assert.equal(selector, '[data-workflow-kind]');
        return { dataset: { workflowKind: kind } };
      },
    },
  });
  return { requests, errors, openCalls, popupClosed, replacedUrl };
}

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('HTML workflow choices have the required kinds and labels', () => {
  assert.equal(choices.length, 2);
  const byKind = Object.fromEntries(choices.map(choice => [choice.kind, choice]));
  assert.deepEqual(Object.keys(byKind).sort(), ['api', 'editable']);
  assert.equal(byKind.editable.tooltip, '사용자 편집용 워크플로');
  assert.equal(byKind.editable.ariaLabel, '사용자 편집용 워크플로');
  assert.equal(byKind.api.tooltip, 'API용 워크플로');
  assert.equal(byKind.api.ariaLabel, 'API용 워크플로');
});

test('real HTML choices route their kind to the open-workflow handler', async () => {
  for (const { kind } of choices) {
    const result = await clickChoice(kind);
    assert.equal(result.requests.length, 1);
    assert.equal(result.requests[0].url, '/api/open-workflow');
    assert.equal(result.requests[0].init.method, 'POST');
    assert.deepEqual(JSON.parse(result.requests[0].init.body), { kind });
    assert.deepEqual(result.openCalls[0], ['about:blank', '_blank']);
    assert.equal(result.replacedUrl, 'http://127.0.0.1:8189/');
  }
});

test('popup-blocked path opens the prepared ComfyUI URL as fallback', async () => {
  const result = await clickChoice('api', { popupBlocked: true });
  assert.deepEqual(result.openCalls, [
    ['about:blank', '_blank'],
    ['http://127.0.0.1:8189/', '_blank', 'noopener'],
  ]);
  assert.equal(result.errors.length, 0);
});

test('failed preparation closes the reserved popup and reports an error', async () => {
  const result = await clickChoice('editable', { responseFails: true });
  assert.equal(result.popupClosed, 1);
  assert.equal(result.openCalls.length, 1);
  assert.deepEqual(result.errors, ['preparation failed']);
});

(async () => {
  const results = [];
  for (const [name, fn] of tests) {
    try {
      await fn();
      results.push({ name, status: 'PASS' });
    } catch (error) {
      results.push({ name, status: 'FAIL', error: String(error) });
    }
  }
  const report = { source: [htmlPath, jsPath], total: results.length,
    passed: results.filter(result => result.status === 'PASS').length, results };
  console.log(JSON.stringify(report, null, 2));
  process.exitCode = report.passed === report.total ? 0 : 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 2;
});
