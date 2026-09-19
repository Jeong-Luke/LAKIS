"""Actual aiohttp client/loopback protocol tests. Fake backend, never a GPU job.

The full product _run/observer/output code talks to an ephemeral 127.0.0.1
server. External host, ComfyUI process and model execution are not involved.
A test-only 100-receive budget prevents an old closed-socket busy loop from
blocking asyncio cancellation. It does not fabricate messages or backend state.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch, AsyncMock
from aiohttp import web
import aiohttp

ROOT=Path(os.environ.get('LAKIS_TEST_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'src/external_ui'))
import workflow_bridge as m


class LoopbackGeneration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='lakis-http-test-');self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.runtime=root/'runtime';self.runtime.mkdir();output=root/'output';output.mkdir()
        p=patch.multiple(m,DEV_ROOT=self.runtime,OUTPUT_ROOT=output,
            OUTPUT_LOCATION_PATH=self.runtime/'output-location.json',STOP_FILE=self.runtime/'STOP_AUTOMATION',
            ALLOW_FILE=self.runtime/'ALLOW_ONE_GENERATION',GENERATION_JOURNAL_PATH=root/'journal.json')
        p.start();self.addCleanup(p.stop)
        p=patch.object(m,'_audit');p.start();self.addCleanup(p.stop)
        self.mode='success';self.posts=[];self.gets=[];self.resets=0;self.ws=[];self.tasks=[]
        self.receive_count=0
        original_receive=aiohttp.ClientWebSocketResponse.receive
        async def bounded_receive(ws,*args,**kwargs):
            self.receive_count+=1
            if self.receive_count>100:
                raise RuntimeError('test-only WebSocket receive budget exceeded')
            return await original_receive(ws,*args,**kwargs)
        p=patch.object(aiohttp.ClientWebSocketResponse,'receive',new=bounded_receive)
        p.start();self.addCleanup(p.stop)
        self.history={};self.queue={'queue_running':[],'queue_pending':[]}
        app=web.Application()
        app.router.add_get('/queue',self.queue_get)
        app.router.add_get('/object_info',self.nodes_get)
        app.router.add_get('/history/{pid}',self.history_get)
        app.router.add_get('/ws',self.websocket)
        app.router.add_post('/prompt',self.submit)
        app.router.add_post('/free',self.free)
        self.runner=web.AppRunner(app);await self.runner.setup()
        site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        p=patch.multiple(m,COMFY_PORT=port,COMFY_SERVER=f'http://127.0.0.1:{port}')
        p.start();self.addCleanup(p.stop)
        self.bridge=m.WorkflowBridge()
        self.token={'request_id':'request-http-test','created_at':time.time(),'source':'external_ui_click'}
        m.ALLOW_FILE.write_text(json.dumps(self.token))
        m.STOP_FILE.write_text('guard')
        self.bridge.status.update(state='preparing',request_id=self.token['request_id'],started_at=time.time())
        self.graph={'775':{'class_type':'Image Saver','inputs':{},'_meta':{'lakis_request_id':self.token['request_id']}}}

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():task.cancel()
        if self.tasks:await asyncio.gather(*self.tasks,return_exceptions=True)
        for ws in self.ws:
            if not ws.closed:await ws.close()
        await self.runner.cleanup()

    async def queue_get(self,request):
        self.gets.append(request.path)
        return web.json_response(self.queue)
    async def nodes_get(self,request):
        self.gets.append(request.path)
        if self.mode=='missing_nodes':return web.json_response({})
        nodes={'Image Saver':{}}
        if self.mode=='invalid_model':
            nodes['DiffusionModelLoaderKJ']={'input':{'required':{'model_name':[['anima_baseV10.safetensors'],{}]}}}
        return web.json_response(nodes)
    async def history_get(self,request):
        self.gets.append(request.path)
        return web.json_response(self.history)
    async def websocket(self,request):
        ws=web.WebSocketResponse();await ws.prepare(request);self.ws.append(ws)
        async for message in ws:pass
        return ws
    async def free(self,request):
        self.resets+=1;return web.json_response({'ok':True})
    async def emit(self):
        await asyncio.sleep(.01)
        if self.mode in ('closed','malformed_progress','malformed_json'):
            if self.mode=='closed':await self.ws[-1].close()
            elif self.mode=='malformed_json':await self.ws[-1].send_str('not-json')
            else:
                await self.ws[-1].send_json({'type':'executing','data':{'prompt_id':'P','node':'775'}})
                await self.ws[-1].send_json({'type':'progress','data':{'prompt_id':'P','value':'bad','max':3}})
        elif self.mode=='execution_error':
            await self.ws[-1].send_json({'type':'execution_error','data':{'prompt_id':'P','node_id':'775',
                'node_type':'Image Saver','exception_type':'OSError','exception_message':'disk full'}})
        else:
            # An event for another prompt must not terminate this one.
            await self.ws[-1].send_json({'type':'execution_success','data':{'prompt_id':'OTHER'}})
            await self.ws[-1].send_json({'type':'execution_success','data':{'prompt_id':'P'}})
    async def submit(self,request):
        self.posts.append(await request.json())
        if self.mode=='reject':
            return web.json_response({'error':{'type':'prompt_outputs_failed_validation'},
                'node_errors':{'775':{'class_type':'Image Saver','errors':[{'message':'bad image'}]}}},status=400)
        if self.mode=='server_error':return web.json_response({'error':'injected server error'},status=500)
        if self.mode=='missing_id':return web.json_response({'number':0})
        if self.mode=='non_json':return web.Response(text='accepted?')
        if self.mode=='lost_response':
            # The fake backend accepts the payload, but drops the reply.
            self.queue={'queue_running':[[0,'P']],'queue_pending':[]}
            request.transport.close()
            return web.json_response({'prompt_id':'P'})
        self.history={'P':{'status':{'completed':True,'status_str':'success'},
            'outputs':{'775':{'ui':{'images':[{'filename':'owned.png','type':'output','subfolder':''}]}}}}}
        self.tasks.append(asyncio.create_task(self.emit()))
        return web.json_response({'prompt_id':'P','number':0})
    async def execute(self):
        return await asyncio.wait_for(self.bridge._run(deepcopy(self.graph),{},self.token),8)
    def single_submission(self):
        self.assertEqual(1,len(self.posts));self.assertEqual(1,self.bridge.status.prompt_requests)
        self.assertEqual(0,self.resets)
        self.assertEqual(['775'],self.posts[0]['partial_execution_targets'])
        self.assertEqual(self.graph,self.posts[0]['prompt'])

    async def test_success_with_real_http_ws_and_history(self):
        await self.execute();self.single_submission()
        self.assertEqual('complete',self.bridge.status.state)
        self.assertIn('owned.png',self.bridge.status.output_url)
    async def test_closed_ws_uses_same_history_and_no_second_prompt(self):
        self.mode='closed';await self.execute();self.single_submission()
        self.assertEqual('complete',self.bridge.status.state)
        self.assertGreaterEqual(self.gets.count('/history/P'),2)
    async def test_malformed_ws_json_recovers_by_existing_prompt(self):
        self.mode='malformed_json';await self.execute();self.single_submission()
        self.assertEqual('complete',self.bridge.status.state)
    async def test_bad_progress_value_does_not_abort_accepted_request(self):
        self.mode='malformed_progress';await self.execute();self.single_submission()
        self.assertEqual('complete',self.bridge.status.state)
    async def test_rejected_prompt_preserves_response_body(self):
        self.mode='reject'
        with self.assertRaises(m.PromptRejectedError) as caught:await self.execute()
        self.single_submission();self.assertEqual('775',caught.exception.node_id)
        self.assertEqual('prompt_outputs_failed_validation',caught.exception.payload['error']['type'])
    async def test_server_500_is_unknown_not_retried(self):
        self.mode='server_error'
        with self.assertRaises(m.SubmissionOutcomeUnknownError):await self.execute()
        self.single_submission()
    async def test_accepted_response_missing_id_is_unknown(self):
        self.mode='missing_id'
        with self.assertRaises(m.SubmissionOutcomeUnknownError):await self.execute()
        self.single_submission()
    async def test_non_json_accepted_response_is_unknown(self):
        self.mode='non_json'
        with self.assertRaises(m.SubmissionOutcomeUnknownError):await self.execute()
        self.single_submission()
    async def test_lost_accepted_response_never_submits_twice(self):
        self.mode='lost_response'
        with self.assertRaises(m.SubmissionOutcomeUnknownError):await self.execute()
        self.single_submission();self.assertTrue(self.queue['queue_running'])
    async def test_preflight_missing_node_submits_nothing(self):
        self.mode='missing_nodes'
        with self.assertRaises(m.MissingRuntimeNodesError):await self.execute()
        self.assertEqual([],self.posts);self.assertEqual([],self.ws);self.assertTrue(m.ALLOW_FILE.exists())
    async def test_queue_busy_submits_nothing(self):
        self.queue={'queue_running':[[0,'Other']],'queue_pending':[]}
        with self.assertRaises(RuntimeError):await self.execute()
        self.assertEqual([],self.posts);self.assertTrue(m.ALLOW_FILE.exists())
    async def test_stale_model_is_rejected_before_prompt_submission(self):
        self.mode='invalid_model'
        self.graph['890:1365']={'class_type':'DiffusionModelLoaderKJ','inputs':{'model_name':'foreign.safetensors'}}
        with self.assertRaisesRegex(ValueError,'Unknown diffusion model'):await self.execute()
        self.assertEqual([],self.posts);self.assertTrue(m.ALLOW_FILE.exists())
    async def test_execution_error_preserves_node_and_does_not_resubmit(self):
        self.mode='execution_error'
        with self.assertRaises(m.GenerationExecutionError) as caught:await self.execute()
        self.single_submission();self.assertEqual('775',caught.exception.node_id)
        self.assertEqual('disk full',caught.exception.payload['exception_message'])


class AutoPatchRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='autopatch-http-');self.addCleanup(self.tmp.cleanup)
        routes=web.RouteTableDef()
        server=types.ModuleType('server');server.PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes))
        path=ROOT/'src/custom_nodes/ComfyUI-LAKIS-AutoPatch/__init__.py'
        spec=importlib.util.spec_from_file_location('autopatch_routes_under_test',path)
        self.module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'server':server}):spec.loader.exec_module(self.module)
        self.marker=Path(self.tmp.name)/'startup_workflow.json';self.module._marker=self.marker
        app=web.Application();app.add_routes(routes)
        self.runner=web.AppRunner(app);await self.runner.setup();site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        self.url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/lakis/autopatch/'
        self.session=aiohttp.ClientSession()
    async def asyncTearDown(self):
        await self.session.close();await self.runner.cleanup()
    async def get(self):
        async with self.session.get(self.url+'startup-workflow') as response:
            return response.status,dict(response.headers),await response.text()
    async def consume(self,digest=None):
        headers={'X-LAKIS-Marker-SHA256':digest} if digest else {}
        async with self.session.post(self.url+'consume-startup-workflow',headers=headers) as response:
            return response.status,await response.json()
    async def test_no_marker_is_no_content(self):
        self.assertEqual(204,(await self.get())[0])
    async def test_matching_digest_acknowledges_loaded_marker(self):
        self.marker.write_text('{"nodes":[]}',encoding='utf-8-sig')
        status,headers,text=await self.get();self.assertEqual(200,status)
        self.assertEqual({'nodes':[]},json.loads(text))
        digest=headers.get('X-LAKIS-Marker-SHA256');self.assertTrue(digest)
        self.assertEqual(200,(await self.consume(digest))[0]);self.assertFalse(self.marker.exists())
    async def test_stale_digest_cannot_delete_replacement_marker(self):
        self.marker.write_text('{"nodes":[]}');_,headers,_=await self.get()
        self.marker.write_text('{"nodes":[{"id":2}]}')
        self.assertEqual(409,(await self.consume(headers.get('X-LAKIS-Marker-SHA256')))[0])
        self.assertEqual({'nodes':[{'id':2}]},json.loads(self.marker.read_text()))
    async def test_legacy_ack_without_identity_does_not_delete_work(self):
        self.marker.write_text('{"nodes":[]}')
        self.assertEqual(409,(await self.consume())[0]);self.assertTrue(self.marker.exists())
    async def test_malformed_marker_reports_error_without_deletion(self):
        self.marker.write_text('{bad json')
        self.assertEqual(500,(await self.get())[0]);self.assertTrue(self.marker.exists())

if __name__=='__main__':unittest.main(verbosity=2)
