const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const expectedUnetRoot = process.env.LAKIS_MOSS_TEST_ROOT.replaceAll('\\', '/');
const expectedLoraRoot = process.env.LAKIS_MOSS_LORA_TEST_ROOT.replaceAll('\\', '/');
const source = fs.readFileSync(process.env.LAKIS_MOSS_MANAGER_MODULE, 'utf8')
  .replace(/^import .*;\r?$/gm, '')
  .replace(/^export /gm, '');

function harness(modelType, roots) {
  const elements = new Map();
  const requested = [];
  const context = {
    console: { log() {}, error() {} },
    LoadingManager: class {},
    FolderTreeManager: class {},
    state: {
      global: {
        settings: {
          default_unet_root: expectedUnetRoot,
          default_lora_root: expectedLoraRoot,
          default_checkpoint_root: 'checkpoint-root',
        },
      },
    },
    showToast(...args) { assert.fail(JSON.stringify(args)); },
    translate(_key, args) { return args.type; },
    document: {
      getElementById(id) {
        if (!elements.has(id)) {
          elements.set(id, { innerHTML: '', textContent: '', value: '', setAttribute() {} });
        }
        return elements.get(id);
      },
    },
  };
  const DownloadManager = vm.runInNewContext(`${source}\nDownloadManager;`, context);
  const manager = Object.create(DownloadManager.prototype);
  manager.apiClient = {
    modelType,
    apiConfig: { config: { displayName: modelType === 'loras' ? 'LoRA' : 'Checkpoint' } },
    async fetchModelRoots(kind) {
      requested.push(kind);
      return { roots: roots(kind) };
    },
  };
  manager.folderTreeManager = { init() {} };
  manager.initializeFolderTree = async () => {};
  manager.loadDefaultPathSetting = () => {};
  manager.updateTargetPath = () => {};
  context.document.getElementById('modelRoot').addEventListener = () => {};
  return { context, elements, manager, requested };
}

test('MOSS checkpoint files use the registered diffusion-model root', async () => {
  const h = harness('checkpoints', kind => kind === 'diffusion_model' ? [expectedUnetRoot] : ['checkpoint-root']);
  h.manager.currentVersion = { baseModel: 'MOSS Image', files: [{ type: 'Model' }] };
  h.manager.selectedFile = { type: 'Model' };
  await h.manager.proceedToLocationContent();

  assert.deepEqual(h.requested, ['diffusion_model']);
  assert.equal(h.manager._isDiffusionModel, true);
  assert.equal(h.elements.get('modelRoot').value, expectedUnetRoot);
  assert.equal(h.elements.get('modelRootLabel').textContent, 'Diffusion Model');
  assert.equal(h.manager._getFileRoutingGroup({ type: 'Model' }), 'diffusion');
});

test('MOSS LoRA files use the MOSS LoRA root, not the diffusion-model root', async () => {
  const h = harness('loras', () => [expectedLoraRoot]);
  h.manager.currentVersion = { baseModel: 'MOSS Image', files: [{ type: 'Model' }] };
  h.manager.selectedFile = { type: 'Model' };
  await h.manager.proceedToLocationContent();

  assert.deepEqual(h.requested, [undefined]);
  assert.equal(h.manager._isDiffusionModel, false);
  assert.equal(h.elements.get('modelRoot').value, expectedLoraRoot);
  assert.equal(h.elements.get('modelRootLabel').textContent, 'LoRA');
  assert.equal(h.manager._getFileRoutingGroup({ type: 'Model' }), 'model');
});

test('other checkpoint families keep their existing file-type routing', async () => {
  const h = harness('checkpoints', kind => kind === 'diffusion_model' ? [expectedUnetRoot] : ['checkpoint-root']);
  h.manager.currentVersion = { baseModel: 'Flux.1 D', files: [{ type: 'Model' }] };
  h.manager.selectedFile = { type: 'Model' };
  await h.manager.proceedToLocationContent();
  assert.deepEqual(h.requested, [undefined]);
  assert.equal(h.manager._isDiffusionModel, false);
  assert.equal(h.elements.get('modelRoot').value, 'checkpoint-root');
  assert.equal(h.manager._getFileRoutingGroup({ type: 'Model' }), 'model');

  h.manager.currentVersion = { baseModel: 'Flux.1 D', files: [{ type: 'UNet' }] };
  h.manager.selectedFile = { type: 'UNet' };
  await h.manager.proceedToLocationContent();
  assert.deepEqual(h.requested, [undefined, 'diffusion_model']);
  assert.equal(h.manager._isDiffusionModel, true);
  assert.equal(h.manager._getFileRoutingGroup({ type: 'UNet' }), 'diffusion');
});

test('MOSS advanced settings keeps the available model settings group accessible', () => {
  const advancedSource = fs.readFileSync(
    path.join(__dirname, '../../src/external_ui/advanced-node-settings.js'),
    'utf8',
  );
  const method = advancedSource.match(
    /    syncGenerationEngine\(\) \{([\s\S]*?)\r?\n    \},\r?\n  \};/,
  );
  assert.ok(method, 'advanced settings engine synchronizer is present');

  const state = { generation: { engine: 'moss' } };
  const configuration = { model: [{ id: 'anima-model-settings' }] };
  const configurationByEngine = {
    moss: { model: [{ id: 'moss-model-settings', fields: [{ name: 'shift' }] }] },
  };
  const buttons = ['model', 'lora', 'generation'].map(group => ({
    dataset: { advancedGroup: group },
    disabled: false,
  }));
  const context = {
    state,
    configuration,
    configurationByEngine,
    document: {
      querySelectorAll: () => buttons,
      querySelector: () => null,
    },
    closeOverlay() {},
  };
  const synchronize = vm.runInNewContext(
    `(function() {${method[1]}\n})`,
    context,
  );
  synchronize();

  assert.equal(buttons[0].disabled, false);
  assert.equal(buttons[1].disabled, false);
  assert.equal(buttons[2].disabled, true);
});
