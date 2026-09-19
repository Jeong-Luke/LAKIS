"""Provider registration/schema and CPU-tensor checks; no model inference."""
from __future__ import annotations
import ast
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import torch

ROOT=Path(os.environ.get('LAKIS_TEST_SOURCE_ROOT') or Path(__file__).resolve().parents[2])

def load_node(name):
    path=ROOT/'src/custom_nodes'/name/'__init__.py'
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),path)
    node=importlib.util.module_from_spec(spec)
    comfy=types.ModuleType('comfy'); comfy.__path__=[]
    samplers=types.ModuleType('comfy.samplers')
    samplers.CFGGuider=type('CFGGuider',(),{})
    samplers.KSampler=types.SimpleNamespace(SAMPLERS=['euler','euler_ancestral'],SCHEDULERS=['normal'])
    sample=types.ModuleType('comfy.sample');comfy.samplers=samplers;comfy.sample=sample
    with patch.dict(sys.modules,{'comfy':comfy,'comfy.samplers':samplers,'comfy.sample':sample}):
        spec.loader.exec_module(node)
    return node

class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.local=load_node('ComfyUI-LAKIS-Local-Inpaint')
    def color(self):
        self.assertIn('LAKIS_INPAINT_COLOR_MATCH',self.local.NODE_CLASS_MAPPINGS)
        return self.local.NODE_CLASS_MAPPINGS['LAKIS_INPAINT_COLOR_MATCH']()
    def fixture(self):
        generated=torch.full((2,16,16,3),.3);original=torch.full_like(generated,.5)
        mask=torch.zeros((2,16,16));mask[:,4:12,4:12]=1
        return generated,original,mask
    def test_color_contract_matches_bridge(self):
        node=self.color();req=node.INPUT_TYPES()['required']
        self.assertEqual({'generated','original','mask','radius','strength','max_shift'},set(req))
        self.assertEqual(('IMAGE',),node.RETURN_TYPES)
    def test_color_changes_only_mask_and_is_bounded(self):
        g,o,mask=self.fixture();result=self.color().match(g,o,mask,4,1,.1)[0]
        self.assertTrue(torch.equal(result[mask==0],g[mask==0]))
        self.assertTrue(torch.allclose(result[mask==1],torch.full_like(result[mask==1],.4)))
        self.assertTrue(torch.allclose(g,torch.full_like(g,.3)))
    def test_color_zero_strength_is_exact_noop(self):
        g,o,mask=self.fixture();self.assertIs(g,self.color().match(g,o,mask,4,0,.18)[0])
    def test_color_full_mask_without_context_is_unchanged(self):
        g,o,mask=self.fixture();mask.fill_(1)
        self.assertTrue(torch.equal(g,self.color().match(g,o,mask,4,1,.18)[0]))
    def test_color_empty_mask_is_unchanged(self):
        g,o,mask=self.fixture();mask.zero_()
        self.assertTrue(torch.equal(g,self.color().match(g,o,mask,4,1,.18)[0]))
    def test_color_single_reference_and_mask_broadcast(self):
        g,o,mask=self.fixture();result=self.color().match(g,o[:1],mask[0],4,.5,.18)[0]
        self.assertEqual(g.shape,result.shape);self.assertTrue(torch.isfinite(result).all())
    def test_color_invalid_batch_is_rejected(self):
        g,o,mask=self.fixture()
        with self.assertRaises(ValueError):self.color().match(g,torch.ones((3,16,16,3)),mask,4,1,.18)
    def test_color_nan_setting_is_rejected(self):
        g,o,mask=self.fixture()
        with self.assertRaises(ValueError):self.color().match(g,o,mask,4,float('nan'),.18)
    def test_color_preserves_alpha_channel(self):
        g,o,mask=self.fixture();g=torch.cat((g,torch.ones((2,16,16,1))*.8),dim=-1)
        self.assertTrue(torch.equal(g[...,3],self.color().match(g,o,mask,4,.85,.18)[0][...,3]))
    def test_current_v2_mask_empty_and_batch_behavior_preserved(self):
        node=self.local.LAKISSafeMasksCombineBatch()
        result=node.combine_masks(torch.zeros((0,8,8)))[0]
        self.assertEqual((1,8,8),tuple(result.shape));self.assertEqual(0,result.sum().item())
    def test_restored_providers_register_all_required_types(self):
        d=load_node('ComfyUI-LAKIS-Detail');f=load_node('ComfyUI-LAKIS-Fast-Refiner')
        self.assertTrue({'LAKIS_DETAIL','LAKIS_VRAM_GATE'}<=set(d.NODE_CLASS_MAPPINGS))
        self.assertIn('LAKIS_SCOPE',f.NODE_CLASS_MAPPINGS)
    def test_restored_provider_inputs_match_bridge_injected_keys(self):
        d=load_node('ComfyUI-LAKIS-Detail');f=load_node('ComfyUI-LAKIS-Fast-Refiner')
        mappings={**d.NODE_CLASS_MAPPINGS,**f.NODE_CLASS_MAPPINGS,**self.local.NODE_CLASS_MAPPINGS}
        tree=ast.parse((ROOT/'src/external_ui/workflow_bridge.py').read_text(encoding='utf-8'))
        checked=set()
        for expr in ast.walk(tree):
            if not isinstance(expr,ast.Dict):continue
            pairs={k.value:v for k,v in zip(expr.keys,expr.values) if isinstance(k,ast.Constant) and isinstance(k.value,str)}
            ct=pairs.get('class_type');inputs=pairs.get('inputs')
            if not isinstance(ct,ast.Constant) or ct.value not in {'LAKIS_DETAIL','LAKIS_SCOPE','LAKIS_VRAM_GATE','LAKIS_INPAINT_COLOR_MATCH'} or not isinstance(inputs,ast.Dict):continue
            node=mappings[ct.value];spec=node.INPUT_TYPES();keys={k.value for k in inputs.keys if isinstance(k,ast.Constant)}
            required=set(spec.get('required',{}));allowed=required|set(spec.get('optional',{}))
            self.assertTrue(required<=keys,(ct.value,required-keys));self.assertTrue(keys<=allowed,(ct.value,keys-allowed))
            params=set(inspect.signature(getattr(node,node.FUNCTION)).parameters)
            self.assertTrue(keys<=params,(ct.value,keys-params));checked.add(ct.value)
        self.assertEqual({'LAKIS_DETAIL','LAKIS_SCOPE','LAKIS_VRAM_GATE','LAKIS_INPAINT_COLOR_MATCH'},checked)
    def test_no_duplicate_mask_registration(self):
        f=load_node('ComfyUI-LAKIS-Fast-Refiner')
        self.assertNotIn('LAKIS_SafeMasksCombineBatch',f.NODE_CLASS_MAPPINGS)
        self.assertIn('LAKIS_SafeMasksCombineBatch',self.local.NODE_CLASS_MAPPINGS)
    def test_restored_scope_resize_and_tile_positions(self):
        f=load_node('ComfyUI-LAKIS-Fast-Refiner')
        positions=f._positions(100,32,8);self.assertEqual(0,positions[0]);self.assertEqual(68,positions[-1])
        result=f._resize_bhwc(torch.zeros((1,8,8,3)),16,24)
        self.assertEqual((1,16,24,3),tuple(result.shape))
    def test_restored_detail_vram_gate_does_not_unload_models(self):
        d=load_node('ComfyUI-LAKIS-Detail');mm=types.ModuleType('comfy.model_management')
        mm.get_free_memory=lambda:2*1024**3
        comfy=types.ModuleType('comfy');comfy.__path__=[];comfy.model_management=mm
        image=torch.zeros((1,8,8,3))
        with patch.dict(sys.modules,{'comfy':comfy,'comfy.model_management':mm}):
            result,info=d.LAKISVRAMGate().run(image,1.5,True)
        self.assertIs(image,result);self.assertEqual('deferred_until_prompt_complete',json.loads(info)['cleanup'])

if __name__=='__main__':unittest.main(verbosity=2)
