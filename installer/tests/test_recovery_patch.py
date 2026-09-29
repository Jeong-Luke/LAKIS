"""Regression contracts for the offline recovery candidate.

Full workflow_bridge module, isolated paths, synthetic requests/images. No GPU
or external server is used. LAKIS_TEST_SOURCE_ROOT selects an unmodified source
for the same before/after assertions; no expected-failure inversion is used.
"""
from __future__ import annotations
import ast
import asyncio
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(os.environ.get('LAKIS_TEST_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'src' / 'external_ui'))
import workflow_bridge as m
import serve_ui as http_ui
import aiohttp
from PIL import Image
from PIL.PngImagePlugin import PngInfo


class Reply:
    def __init__(self, data, status=200): self.data, self.status = data, status
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def json(self):
        if isinstance(self.data, Exception): raise self.data
        return self.data


class FakeSession:
    def __init__(self, history=None, queue=None):
        self.history = history or {}
        self.queue = queue or {'queue_running': [], 'queue_pending': []}
        self.gets = []
    def get(self, url, **_):
        self.gets.append(url)
        return Reply(self.queue if url.endswith('/queue') else self.history)


class DormantWorker:
    def __init__(self, *_, **kwargs): self.target = kwargs['target']; self.args = kwargs['args']; self.started = False
    def start(self): self.started = True
    def is_alive(self): return self.started


class IsolatedBridge(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lakis-patch-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root/'runtime'; self.runtime.mkdir()
        self.output = self.root/'output'; self.output.mkdir()
        overrides = dict(DEV_ROOT=self.runtime, OUTPUT_ROOT=self.output,
            OUTPUT_LOCATION_PATH=self.runtime/'output-location.json',
            LEGACY_OUTPUT_LOCATION_PATH=self.runtime/'legacy-output-location.json',
            STOP_FILE=self.runtime/'STOP_AUTOMATION', ALLOW_FILE=self.runtime/'ALLOW_ONE_GENERATION',
            UI_STATE_PATH=self.root/'state'/'ui.json', LEGACY_UI_STATE_PATH=self.root/'legacy.json',
            UNSCOPED_UI_STATE_PATH=self.root/'unscoped.json', GENERATION_JOURNAL_PATH=self.root/'journal.json')
        p = patch.multiple(m, **overrides); p.start(); self.addCleanup(p.stop)
        p = patch.object(m, '_audit'); p.start(); self.addCleanup(p.stop)
        p = patch.object(m, '_enum_options', side_effect=lambda _c,_n,f=(),**kw:f); p.start(); self.addCleanup(p.stop)
        p = patch.object(m, '_clean_advanced_node_overrides', side_effect=lambda v,**kw:deepcopy(v or {})); p.start(); self.addCleanup(p.stop)
        m.STOP_FILE.write_text('safety enabled')
        self.bridge = m.WorkflowBridge()
        self.bridge._request_runtime_reset = lambda: None
        self.graph = {'775': {'class_type':'Image Saver', 'inputs': {}, '_meta':{'title':'Final'}}}
        p = patch.object(m,'build_prompt',side_effect=lambda state:(deepcopy(self.graph),{})); p.start(); self.addCleanup(p.stop)
        self.state = {'output':{'seed':1},'generation':{'mode':'detail'},'prompt':{'general':'test'}}

    def start_dormant(self):
        with patch.object(m.threading,'Thread',DormantWorker):
            info = self.bridge.start(deepcopy(self.state))
        return info, self.bridge._worker.args

    def output_url(self, final):
        session = FakeSession({'P':{'outputs':{'775':final}}})
        with patch.object(m.asyncio,'sleep',new=AsyncMock()):
            return asyncio.run(self.bridge._find_output(session,'P'))

    def image(self, name, request=None, webp=False):
        path = self.output / name
        image = Image.new('RGB',(8,8),(128,140,160))
        graph = {'775': {'_meta': {'lakis_request_id':request}}}
        if webp:
            exif = Image.Exif(); exif[272] = 'prompt:' + json.dumps(graph)
            image.save(path, exif=exif)
        else:
            metadata = PngInfo()
            if request: metadata.add_text('prompt',json.dumps(graph))
            image.save(path,pnginfo=metadata)
        return path

    def test_empty_output_config_never_scans_cwd(self):
        for value in ({},[],{'path':None},{'path':''},{'path':' '},{'path':'.'},{'path':12}):
            with self.subTest(value=value):
                m.OUTPUT_LOCATION_PATH.write_text(json.dumps(value))
                self.assertEqual(self.output.resolve(),m.configured_output_root())

    def test_valid_output_config_and_bom_are_preserved(self):
        custom=self.root/'custom';custom.mkdir()
        m.OUTPUT_LOCATION_PATH.write_text(json.dumps({'path':str(custom)}),encoding='utf-8-sig')
        self.assertEqual(custom.resolve(),m.configured_output_root())

    def test_per_user_output_config_overrides_legacy_install_record(self):
        current=self.root/'current';current.mkdir()
        legacy=self.root/'legacy';legacy.mkdir()
        m.LEGACY_OUTPUT_LOCATION_PATH.write_text(json.dumps({'path':str(legacy)}),encoding='utf-8')
        m.OUTPUT_LOCATION_PATH.write_text(json.dumps({'path':str(current)}),encoding='utf-8')
        self.assertEqual(current.resolve(),m.configured_output_root())

    def test_http_history_root_obeys_same_empty_config_contract(self):
        text=(ROOT/'src/external_ui/serve_ui.py').read_text(encoding='utf-8-sig')
        node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='configured_output_root')
        module=ast.Module(body=[node],type_ignores=[])
        env={'Path':Path,'json':json,'OUTPUT_ROOT':self.output,'OUTPUT_LOCATION_PATH':m.OUTPUT_LOCATION_PATH,
             'LEGACY_OUTPUT_LOCATION_PATH':m.LEGACY_OUTPUT_LOCATION_PATH}
        exec(compile(ast.fix_missing_locations(module),'serve_ui.py','exec'),env)
        m.OUTPUT_LOCATION_PATH.write_text('{}')
        self.assertEqual(self.output,env['configured_output_root']())

    def test_direct_history_image_is_compatible(self):
        self.assertIn('owned.webp',self.output_url({'images':[{'filename':'owned.webp','type':'output','subfolder':''}]}))

    def test_nested_history_image_is_compatible(self):
        self.assertIn('owned.webp',self.output_url({'ui':{'images':[{'filename':'owned.webp'}]}}))

    def test_malformed_history_array_has_typed_diagnostic(self):
        with self.assertRaises(m.FinalOutputNotFoundError):
            self.output_url({'images':[None,3,False]})

    def test_history_ignores_bad_descriptors_but_keeps_valid_image(self):
        self.assertIn('good.png',self.output_url({'images':[{'filename':'good.png'},None]}))

    def test_history_does_not_accept_path_traversal(self):
        with self.assertRaises(m.FinalOutputNotFoundError):
            self.output_url({'images':[{'filename':'outside.png','subfolder':'../secret'}]})

    def test_recent_unrelated_image_is_not_a_result(self):
        self.bridge.status.update(started_at=time.time()-1,request_id='R')
        self.image('foreign.png')
        with self.assertRaises(m.FinalOutputNotFoundError): self.output_url({})

    def test_old_image_is_not_a_result(self):
        now=time.time();self.bridge.status.update(started_at=now,request_id='R')
        path=self.image('old.png');os.utime(path,(now-1,now-1))
        with self.assertRaises(m.FinalOutputNotFoundError): self.output_url({})

    def test_png_request_metadata_selects_own_output_over_newer_foreign_image(self):
        self.bridge.status.update(started_at=time.time()-1,request_id='R')
        self.image('owned.png','R'); self.image('newer_foreign.png','Other')
        self.assertIn('owned.png',self.output_url({}))

    def test_webp_exif_request_metadata_fallback(self):
        self.bridge.status.update(started_at=time.time()-1,request_id='R')
        self.image('owned.webp','R',webp=True)
        self.assertIn('owned.webp',self.output_url({}))

    def test_corrupt_image_never_accepted_by_timestamp(self):
        self.bridge.status.update(started_at=time.time()-1,request_id='R')
        (self.output/'bad.png').write_bytes(b'not an image')
        with self.assertRaises(m.FinalOutputNotFoundError): self.output_url({})

    def test_disjoint_state_saves_preserve_both_writers(self):
        m._write_external_ui_payload({'version':5,'prompt':{'general':'OLD'},'model':{'checkpoint':'OLD_MODEL'}})
        writer=m._write_external_ui_payload
        at_write=threading.Event();release=threading.Event();prompt_done=threading.Event();errors=[]
        def gated(payload):
            if threading.current_thread().name=='state-generation':
                at_write.set()
                if not release.wait(3): raise RuntimeError('fixture timed out')
            writer(payload)
        def save_model():
            try: m.save_external_generation_state({'checkpoint':'NEW_MODEL'}, {})
            except Exception as error: errors.append(str(error))
        def save_prompt():
            try: m.save_external_prompt_state({'general':'NEW'})
            except Exception as error: errors.append(str(error))
            finally: prompt_done.set()
        with patch.object(m,'_write_external_ui_payload',side_effect=gated):
            g=threading.Thread(target=save_model,name='state-generation');p=threading.Thread(target=save_prompt)
            g.start(); self.assertTrue(at_write.wait(2));p.start()
            # In the original implementation prompt can commit before G. In
            # the candidate it waits for G's complete read/merge/write lock.
            prompt_done.wait(.08);release.set();g.join(3);p.join(3)
        self.assertFalse(g.is_alive() or p.is_alive());self.assertEqual([],errors)
        value=json.loads(m.UI_STATE_PATH.read_text());self.assertEqual('NEW',value['prompt']['general'])
        self.assertEqual('NEW_MODEL',value['model']['checkpoint'])

    def test_save_failure_keeps_previous_json(self):
        m._write_external_ui_payload({'prompt':{'general':'KEEP'}})
        with patch.object(m.os,'replace',side_effect=OSError('injected')):
            with self.assertRaises(OSError):m.save_external_prompt_state({'general':'NEW'})
        self.assertEqual('KEEP',json.loads(m.UI_STATE_PATH.read_text())['prompt']['general'])
        self.assertEqual([],list(m.UI_STATE_PATH.parent.glob('*.tmp')))

    def test_start_adds_request_identity_without_changing_saver_inputs(self):
        info,args=self.start_dormant()
        self.assertEqual(info['request_id'],args[0]['775']['_meta'].get('lakis_request_id'))
        self.assertEqual({},args[0]['775']['inputs'])
        self.assertNotIn('lakis_request_id',self.graph['775']['_meta'])

    def test_two_concurrent_start_attempts_have_one_winner(self):
        barrier=threading.Barrier(3);ok=[];errors=[]
        def go():
            barrier.wait()
            try:ok.append(self.bridge.start(deepcopy(self.state)))
            except (RuntimeError,FileExistsError) as e:errors.append(type(e).__name__)
        # Mock only product worker creation, keep our two real caller threads.
        original_thread=threading.Thread
        with patch.object(m.threading,'Thread',DormantWorker):
            a=original_thread(target=go);b=original_thread(target=go)
            a.start();b.start();barrier.wait();a.join(3);b.join(3)
        self.assertEqual(1,len(ok));self.assertEqual(1,len(errors))

    def test_journal_write_failure_rolls_back_start(self):
        with patch.object(self.bridge,'_write_generation_journal',side_effect=OSError('injected journal')):
            with self.assertRaises(OSError):self.start_dormant()
        self.assertFalse(m.ALLOW_FILE.exists());self.assertIsNone(self.bridge._worker)
        self.assertNotEqual('preparing',self.bridge.status.state)
        self.assertTrue(self.start_dormant()[0]['ok'])

    def test_worker_start_failure_rolls_back_allowance_and_journal(self):
        with patch.object(DormantWorker,'start',side_effect=RuntimeError('thread failure')):
            with self.assertRaises(RuntimeError):self.start_dormant()
        self.assertFalse(m.ALLOW_FILE.exists());self.assertFalse(m.GENERATION_JOURNAL_PATH.exists())
        self.assertTrue(self.start_dormant()[0]['ok'])

    def test_old_finally_cannot_accept_then_delete_next_request(self):
        _,args=self.start_dormant(); accepted=[]
        async def run(*_):
            self.bridge.status.update(state='complete')
            try:accepted.append(self.bridge.start(deepcopy(self.state)))
            except RuntimeError:pass
        with patch.object(self.bridge,'_run',new=run),patch.object(m.threading,'Thread',DormantWorker):
            self.bridge._thread_main(*args)
        self.assertEqual([],accepted)
        self.assertFalse(m.ALLOW_FILE.exists());self.assertFalse(m.GENERATION_JOURNAL_PATH.exists())
        self.assertTrue(self.start_dormant()[0]['ok'])

    def test_cleanup_preserves_foreign_owned_allowance(self):
        _,args=self.start_dormant()
        m.ALLOW_FILE.write_text(json.dumps({'request_id':'FOREIGN'}))
        async def run(*_):self.bridge.status.update(state='complete')
        with patch.object(self.bridge,'_run',new=run):self.bridge._thread_main(*args)
        self.assertTrue(m.ALLOW_FILE.exists())
        self.assertEqual('FOREIGN',json.loads(m.ALLOW_FILE.read_text())['request_id'])
        with self.assertRaises(RuntimeError):self.start_dormant()

    def test_cleanup_permission_failure_does_not_release_execution_slot(self):
        _,args=self.start_dormant()
        async def run(*_):self.bridge.status.update(state='complete')
        unlink=Path.unlink
        def guarded(path,*a,**kw):
            if path==m.ALLOW_FILE:raise PermissionError('locked')
            return unlink(path,*a,**kw)
        with patch.object(self.bridge,'_run',new=run),patch.object(Path,'unlink',new=guarded):
            self.bridge._thread_main(*args)
        with self.assertRaises(RuntimeError):self.start_dormant()

    def test_uncertain_submission_preserves_slot_and_never_resets_backend(self):
        self.assertTrue(hasattr(m,'SubmissionOutcomeUnknownError'))
        _,args=self.start_dormant();resets=[]
        async def run(*_):
            self.bridge.status.update(prompt_requests=1)
            raise m.SubmissionOutcomeUnknownError('unknown')
        with patch.object(self.bridge,'_run',new=run),patch.object(self.bridge,'_request_runtime_reset',side_effect=lambda:resets.append(1)):
            self.bridge._thread_main(*args)
        self.assertEqual([],resets);self.assertEqual('LKS-GEN-1011',self.bridge.status.error_code)
        self.assertTrue(self.bridge.status.submission_unresolved)
        self.assertTrue(m.GENERATION_JOURNAL_PATH.exists())
        with self.assertRaises(RuntimeError):self.start_dormant()

    def test_closed_websocket_recovers_same_prompt_without_re_read(self):
        calls=[]
        class Socket:
            async def receive(inner,**_):
                calls.append(1)
                if len(calls)>2:raise RuntimeError('fixture receive cap')
                return types.SimpleNamespace(type=aiohttp.WSMsgType.CLOSED,data=None)
        with patch.object(self.bridge,'_probe_prompt_state',new=AsyncMock(return_value='complete')) as probe:
            result=asyncio.run(self.bridge._observe(FakeSession(),Socket(),'P',self.graph))
        self.assertTrue(result);self.assertEqual(1,len(calls));probe.assert_awaited_once()

    def test_monitor_recovery_is_bounded_and_does_not_resubmit(self):
        self.assertTrue(hasattr(m,'SubmissionOutcomeUnknownError'))
        class Socket:
            async def receive(inner,**_):return types.SimpleNamespace(type=aiohttp.WSMsgType.CLOSED,data=None)
        with patch.object(self.bridge,'_probe_prompt_state',new=AsyncMock(return_value='running')) as probe,patch.object(m.asyncio,'sleep',new=AsyncMock()):
            with self.assertRaises(m.SubmissionOutcomeUnknownError):
                asyncio.run(self.bridge._observe(FakeSession(),Socket(),'P',self.graph))
        self.assertEqual(12,probe.await_count)

    def test_partial_history_is_not_completion(self):
        session=FakeSession({'P':{'outputs':{},'status':{'completed':False}}},
                            {'queue_running':[[0,'P']], 'queue_pending':[]})
        self.assertEqual('running',asyncio.run(self.bridge._probe_prompt_state(session,'P')))

    def test_history_execution_failure_preserves_node(self):
        record={'P':{'outputs':{},'status':{'status_str':'error','messages':[
            ['execution_error',{'node_id':'775','node_type':'Image Saver','exception_message':'disk full'}]]}}}
        with self.assertRaises(m.GenerationExecutionError) as caught:
            asyncio.run(self.bridge._probe_prompt_state(FakeSession(record),'P'))
        self.assertEqual('775',caught.exception.node_id)

    def test_progress_journal_failure_does_not_abort_running_prompt(self):
        queue=[{'type':'executing','data':{'prompt_id':'P','node':'775'}},
               {'type':'execution_success','data':{'prompt_id':'P'}}]
        class Socket:
            async def receive(inner,**_):return types.SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data=json.dumps(queue.pop(0)))
        with patch.object(self.bridge,'_write_generation_journal',side_effect=OSError('disk full')):
            self.assertTrue(asyncio.run(self.bridge._observe(FakeSession(),Socket(),'P',self.graph)))

    def test_prompt_rejection_preserves_structured_node_errors(self):
        self.assertTrue(hasattr(m,'PromptRejectedError'))
        body={'error':{'type':'prompt_outputs_failed_validation'},'node_errors':{'775':{'class_type':'Image Saver','errors':[{'message':'bad input'}]}}}
        err=m.PromptRejectedError(400,body)
        self.assertEqual(body,err.payload);self.assertEqual('775',err.node_id)
        self.assertEqual('LKS-CFG-1104',self.bridge._public_error(err)[0])


    def test_png_prompt_literal_does_not_break_request_metadata(self):
        self.bridge.status.update(started_at=time.time()-1,request_id='R')
        graph={'775':{'_meta':{'lakis_request_id':'R'}},'2':{'inputs':{'text':'literal prompt: in text'}}}
        image=Image.new('RGB',(8,8));meta=PngInfo();meta.add_text('prompt',json.dumps(graph))
        image.save(self.output/'literal.png',pnginfo=meta)
        self.assertIn('literal.png',self.output_url({}))

    def test_malformed_history_error_messages_still_typed(self):
        session=FakeSession({'P':{'status':{'status_str':'error','messages':7}}})
        with self.assertRaises(m.GenerationExecutionError):
            asyncio.run(self.bridge._probe_prompt_state(session,'P'))

    def test_worker_rejection_keeps_structured_payload_in_status(self):
        self.assertTrue(hasattr(m,'PromptRejectedError'))
        _,args=self.start_dormant()
        body={'node_errors':{'775':{'class_type':'Image Saver','errors':[{'type':'bad_input'}]}}}
        async def run(*_):raise m.PromptRejectedError(400,body)
        with patch.object(self.bridge,'_run',new=run):self.bridge._thread_main(*args)
        self.assertEqual(body,self.bridge.status.snapshot()['setting_diagnostic']['comfy_error'])
        self.assertEqual('775',self.bridge.status.error_node_id)


class LibraryDeleteContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lakis-library-delete-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.custom = self.root/'custom'; self.custom.mkdir()
        self.default = self.root/'default'; self.default.mkdir()
        roots = patch.object(http_ui, 'configured_output_root', return_value=self.custom)
        roots.start(); self.addCleanup(roots.stop)
        output = patch.object(http_ui, 'OUTPUT_ROOT', self.default)
        output.start(); self.addCleanup(output.stop)

    def test_delete_uses_validated_custom_history_target(self):
        image = self.custom/'nested'/'sample.webp'
        image.parent.mkdir(); image.write_bytes(b'image')
        with patch.object(http_ui, '_send_to_recycle_bin', side_effect=lambda path: path.unlink()) as recycle:
            result = http_ui.delete_history_image('configured:nested/sample.webp')
        self.assertTrue(result['recycled'])
        recycle.assert_called_once_with(image.resolve())
        self.assertFalse(image.exists())

    def test_delete_rejects_path_traversal_before_recycle(self):
        outside = self.root/'outside.webp'; outside.write_bytes(b'image')
        with patch.object(http_ui, '_send_to_recycle_bin') as recycle:
            with self.assertRaises(ValueError):
                http_ui.delete_history_image('configured:../outside.webp')
        recycle.assert_not_called()

    def test_library_delete_does_not_launch_powershell(self):
        source = (ROOT/'src/external_ui/serve_ui.py').read_text(encoding='utf-8-sig')
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'delete_history_image')
        self.assertNotIn('subprocess', ast.unparse(node))


if __name__=='__main__':unittest.main(verbosity=2)
