"""Real build_prompt and packaged templates; mock only local inventory choices.

No tensor inference. Minimal fixture input files satisfy existence checks; they
are not decoded by build_prompt. Reported parity is graph parity, not quality.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(os.environ.get('LAKIS_TEST_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'src/external_ui'))
import workflow_bridge as m

class GraphContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='lakis-graph-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'input').mkdir()
        for n in ('LAKIS_i2i_input_fixture.png','LAKIS_inpaint_input_fixture.png','LAKIS_inpaint_mask_fixture.png'):
            (self.root/'input'/n).write_bytes(b'path-only fixture; builder does not decode')
        template=ROOT/'workflows/LAKIS_runtime_api_v7.4.json'
        data=json.loads(template.read_text(encoding='utf-8-sig'))
        checkpoint=data['890:1365']['inputs']['model_name'];vae=data['890:159']['inputs']['vae_name'];clip=data['890:164']['inputs']['clip_name']
        config={'checkpoint':{'current':checkpoint,'options':[checkpoint]},'vae':{'current':vae,'options':[vae]},
            'clip':{'current':clip,'options':[clip]},'sampler':{'options':list(m.SAMPLER_OPTIONS)},
            'scheduler':{'options':list(m.SCHEDULER_OPTIONS)},'lora':{'current':[]}}
        for p in (patch.multiple(m,COMFY_ROOT=self.root,TEMPLATE=template,DEVELOPMENT=False,
                                 FULL_TURBO_EXPERIMENT=False,HALF_RES_FAST_EXPERIMENT=False),
                  patch.object(m,'workflow_configuration',return_value=config),
                  patch.object(m,'_preferred_upscaler',return_value=None),
                  patch.object(m,'_comfy_object_info',return_value={}),
                  patch.object(m,'_model_files',return_value=[])):
            p.start();self.addCleanup(p.stop)
        self.base={'generation':{'mode':'fast'},'output':{'seed':123,'width':1024,'height':768},
            'prompt':{'general':'fixture landscape'},'loras':[],'lora_enabled':False,
            'composition_enabled':False,'camera':{},'node_overrides':{}}

    def graph(self,mode='fast',inpaint=None,v2=True,i2i=False):
        state=json.loads(json.dumps(self.base));state['generation']['mode']=mode
        if inpaint:state['inpaint']={'enabled':True,'operation':inpaint,'prompt':'replace object',
            'image_name':'LAKIS_inpaint_input_fixture.png','mask_name':'LAKIS_inpaint_mask_fixture.png',
            'image_width':1024,'image_height':768}
        if i2i:state['i2i']={'enabled':True,'image_name':'LAKIS_i2i_input_fixture.png','denoise':.5}
        with patch.object(m,'LOCAL_INPAINT_V2',v2):prompt,assertions=m.build_prompt(state)
        self.assertIn('775',prompt);self.assertEqual('Image Saver',prompt['775']['class_type'])
        self.assertEqual(set(prompt),set(m._final_only(prompt)))
        for node in prompt.values():
            self.assertNotIn(node['class_type'],['LAKIS_Relight','LAKIS_ExecutionSettings'])
            for v in node.get('inputs',{}).values():
                if isinstance(v,list) and len(v)==2 and isinstance(v[0],str) and isinstance(v[1],int):
                    self.assertIn(v[0],prompt,'dangling executable reference')
        key=f'{mode}:{inpaint or "off"}:{v2}:{i2i}'
        digest=hashlib.sha256(json.dumps(prompt,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        # Full builder parity fixture captured from original 744, not a second
        # implementation of the expected graph. Tests below also enforce mode contracts.
        fixture=Path(__file__).with_name('recovery_graph_baseline.json')
        if fixture.exists():self.assertEqual(json.loads(fixture.read_text())[key],digest)
        if os.environ.get('LAKIS_CAPTURE_GRAPH_HASHES'):
            out=Path(os.environ['LAKIS_CAPTURE_GRAPH_HASHES'])
            hashes=json.loads(out.read_text()) if out.exists() else {};hashes[key]=digest
            out.write_text(json.dumps(hashes,indent=2))
        return prompt,assertions
    def test_fast(self):
        p,a=self.graph();self.assertNotIn('lakis:face_scope',p);self.assertTrue(a['initial_spectrum'])
    def test_legacy_detail(self):
        p,a=self.graph('detail');self.assertNotIn('lakis:face_scope',p);self.assertIn('1541:1538',p)
    def test_lakis_detail(self):
        p,a=self.graph('lakis_detail');types={x['class_type'] for x in p.values()}
        self.assertTrue({'LAKIS_DETAIL','LAKIS_SCOPE','LAKIS_VRAM_GATE'}<=types)
    def test_i2i(self):
        p,a=self.graph('detail',i2i=True);self.assertTrue(a['i2i_enabled'])
    def test_inpaint_regenerate_v2(self):
        p,a=self.graph('detail','regenerate');self.assertIn('lakis:inpaint_v2_prepare',p);self.assertNotIn('lakis:inpaint_color_match',p)
    def test_inpaint_remove_v2(self):
        p,a=self.graph('detail','remove');self.assertIn('lakis:inpaint_v2_prepare',p);self.assertNotIn('lakis:inpaint_color_match',p)
    def test_inpaint_regenerate_legacy(self):
        p,a=self.graph('detail','regenerate',False);self.assertNotIn('lakis:inpaint_v2_prepare',p)
    def test_inpaint_remove_legacy(self):
        p,a=self.graph('detail','remove',False);self.assertEqual('LAKIS_INPAINT_COLOR_MATCH',p['lakis:inpaint_color_match']['class_type'])
if __name__=='__main__':unittest.main(verbosity=2)
