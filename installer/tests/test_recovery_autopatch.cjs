/* Execute the actual product JS in a VM with only fetch, timers, and ComfyUI
 * app mocked. These are loader-call/ack contracts, not browser rendering. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.env.LAKIS_TEST_SOURCE_ROOT || path.resolve(__dirname, '../..');
const filename = path.join(root, 'src/custom_nodes/ComfyUI-LAKIS-AutoPatch/web/lakis_autopatch.js');
const source = fs.readFileSync(filename, 'utf8').replace(/^import\s+\{\s*app\s*\}\s+from\s+[^;]+;\s*$/m, '');
const api = JSON.parse(fs.readFileSync(path.join(root, 'workflows/LAKIS_runtime_api_v7.4.json'), 'utf8'));
const editable = JSON.parse(fs.readFileSync(path.join(root, 'workflows/LAKIS_custom_v7.4_editable.json'), 'utf8'));
const envelope = (workflow, format) => ({ lakis_autopatch: {format, display_name:'expected.json'}, workflow });
async function exercise(payload, opts={}) {
  const calls=[], requests=[], logs=[];
  const app={registerExtension() {}, async loadApiJson(...a) {calls.push(['api',...a]); if(opts.loaderFails) throw Error('injected');},
    async loadGraphData(...a) {calls.push(['workflow',...a]);if(opts.loaderFails)throw Error('injected');}};
  if(opts.noApiLoader) delete app.loadApiJson;
  const fetch=async (url, options={})=>{
    requests.push({url,options});
    if(!url.includes('consume-')) {
      if(opts.transportFails)throw Error('offline');
      const status=opts.getStatus||200;
      return {status,ok:status>=200&&status<300,headers:{get:()=>opts.noDigest?null:'hash-A'},
        async json(){if(opts.badJson)throw Error('parse');return payload;}};
    }
    const status=opts.ackStatus||200;
    return {status,ok:status>=200&&status<300,async json(){return {ok:status===200}}};
  };
  const ctx=vm.createContext({app,fetch,setTimeout:fn=>{queueMicrotask(fn);return 1;},
    console:{log:(...a)=>logs.push(['log',...a]),error:(...a)=>logs.push(['error',...a]),warn:(...a)=>logs.push(['warn',...a])}});
  vm.runInContext(source,ctx,{filename});
  await vm.runInContext('tryLoadPatchedWorkflow()',ctx);
  return {calls,requests,logs};
}
const tests=[];
function test(name,fn){tests.push([name,fn]);}
function acknowledged(result, kind, display) {
  assert.equal(result.calls.length,1);assert.equal(result.calls[0][0],kind);
  assert.equal(result.requests.filter(r=>r.options.method==='POST').length,1);
  assert.equal(result.requests[1].options.headers['X-LAKIS-Marker-SHA256'],'hash-A');
  if(display)assert.equal(result.calls[0].at(-1),display);
}
test('actual_runtime_api_envelope_loads_api_once',async()=>{
  const r=await exercise(envelope(api,'api'));acknowledged(r,'api','expected.json');assert.equal(r.calls[0][1],api);
});
test('actual_editable_envelope_loads_graph_once',async()=>{
  const r=await exercise(envelope(editable,'workflow'));acknowledged(r,'workflow','expected.json');assert.equal(r.calls[0][1],editable);
});
test('legacy_bare_api_is_supported',async()=>{acknowledged(await exercise(api),'api');});
test('legacy_bare_workflow_is_supported',async()=>{acknowledged(await exercise(editable),'workflow');});
test('empty_marker_204_is_noop',async()=>{const r=await exercise(null,{getStatus:204});assert.equal(r.calls.length,0);assert.equal(r.requests.length,1);});
test('get_failure_is_noop',async()=>{const r=await exercise(api,{transportFails:true});assert.equal(r.calls.length,0);assert.equal(r.requests.length,1);});
test('invalid_json_is_not_acknowledged',async()=>{const r=await exercise(api,{badJson:true});assert.equal(r.calls.length,0);assert.equal(r.requests.length,1);});
test('malformed_api_is_not_loaded_or_acknowledged',async()=>{const r=await exercise(envelope({'1':null},'api'));assert.equal(r.calls.length,0);assert.equal(r.requests.length,1);});
test('wrong_declared_format_is_not_silently_reinterpreted',async()=>{const r=await exercise(envelope(api,'workflow'));assert.equal(r.calls.length,0);assert.equal(r.requests.length,1);});
test('unknown_format_is_rejected',async()=>{const r=await exercise(envelope(editable,'other'));assert.equal(r.calls.length,0);assert.equal(r.requests.length,1);});
test('missing_api_loader_preserves_marker',async()=>{const r=await exercise(envelope(api,'api'),{noApiLoader:true});assert.equal(r.calls.length,0);assert.equal(r.requests.length,1);});
test('loader_failure_never_acknowledges',async()=>{const r=await exercise(envelope(editable,'workflow'),{loaderFails:true});assert.equal(r.calls.length,1);assert.equal(r.requests.length,1);});
test('stale_ack_is_not_reported_as_open_success',async()=>{
  const r=await exercise(envelope(editable,'workflow'),{ackStatus:409});assert.equal(r.calls.length,1);
  assert.equal(r.requests.length,2);assert.equal(r.logs.filter(x=>x[0]==='log').length,0);
});
test('new_client_can_load_old_server_without_digest',async()=>{
  const r=await exercise(envelope(api,'api'),{noDigest:true});assert.equal(r.calls.length,1);assert.equal(r.requests.length,2);
  assert.equal(Object.keys(r.requests[1].options.headers).length,0);
});
(async()=>{
  const results=[];
  for(const [name,fn] of tests){try{await fn();results.push({name,status:'PASS'});}catch(e){results.push({name,status:'FAIL',error:String(e)});}}
  const report={source:filename,sha256:require('node:crypto').createHash('sha256').update(fs.readFileSync(filename)).digest('hex'),
    scope:'actual JS and workflow files; VM fetch/timers/app mocked; no browser',
    total:results.length,passed:results.filter(x=>x.status==='PASS').length,results};
  console.log(JSON.stringify(report,null,2));process.exitCode=report.passed===report.total?0:1;
})().catch(e=>{console.error(e);process.exitCode=2;});
