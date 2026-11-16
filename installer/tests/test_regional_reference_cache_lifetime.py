"""SnapRef cache-record lifetime tests using definitions from the installed source."""
import ast
import builtins
from contextlib import nullcontext
import gc
import importlib.util
import logging
import math
import os
from pathlib import Path
import sys
import types
import unittest
import weakref
from types import FunctionType, SimpleNamespace
from unittest.mock import patch

import torch


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src/custom_nodes/ComfyUI-LAKIS-Regional-Reference"


class _UnexpectedSnapRefGlobal:
    def __init__(self, name):
        self.name = name

    def __call__(self, *args, **kwargs):
        raise AssertionError(f"Unexpected SnapRef dependency used by test: {self.name}")

    def __getattr__(self, name):
        raise AssertionError(
            f"Unexpected SnapRef dependency used by test: {self.name}.{name}")


def _nested_code_names(code):
    names = set(code.co_names)
    for item in code.co_consts:
        if isinstance(item, types.CodeType):
            names.update(_nested_code_names(item))
    return names


def _extract_snapref_definitions(source, names, namespace):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    if {node.name for node in functions} != names:
        raise AssertionError(f"{source} is missing one of {sorted(names)}")
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    referenced = set()
    for name in names:
        referenced.update(_nested_code_names(namespace[name].__code__))
    for name in referenced - namespace.keys() - set(dir(builtins)):
        namespace[name] = _UnexpectedSnapRefGlobal(name)


def _tensor_leaves(value):
    if isinstance(value, torch.Tensor):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _tensor_leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _tensor_leaves(item)


def _tree_signature(value):
    if isinstance(value, torch.Tensor):
        return ("tensor", tuple(value.shape), value.dtype)
    if isinstance(value, dict):
        return ("dict", type(value), tuple(
            (key, _tree_signature(item)) for key, item in value.items()))
    if isinstance(value, tuple):
        return ("tuple", type(value), tuple(_tree_signature(item) for item in value))
    if isinstance(value, list):
        return ("list", tuple(_tree_signature(item) for item in value))
    return ("value", value)


def _make_records(device, sizes):
    records = []
    source_refs = []
    for index, size in enumerate(sizes):
        key = torch.arange(
            size * 2, device=device, dtype=torch.float32
        ).reshape(1, size, 1, 2) + index * 10
        value = key + 100
        pair = (key, value)
        records.append([pair])
        source_refs.extend((weakref.ref(key), weakref.ref(value)))
    signatures = tuple(_tree_signature(record) for record in records)
    return records, source_refs, signatures


class RegionalReferenceCacheLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        comfy_root = Path(os.environ["LAKIS_COMFY_ROOT"])
        snapref_source = comfy_root / "custom_nodes/snapref/__init__.py"
        namespace = {
            "torch": torch,
            "weakref": weakref,
            "math": math,
            "logging": logging,
            "logger": logging.getLogger(__name__),
            "_Adapter": SimpleNamespace,
            "_STATE": {"adapter": None, "stream": None},
            "NO_REF_KEY": "snapref_off",
        }

        def set_attn_state(model, state):
            for block in model.blocks:
                block.self_attn._ref_kv_state = state

        def get_attn_state(model):
            return model.blocks[0].self_attn._ref_kv_state

        namespace["_set_attn_state"] = set_attn_state
        namespace["_get_attn_state"] = get_attn_state
        namespace["_ref_digest"] = lambda *args, **kwargs: "reference"
        namespace["_model_token"] = lambda *args, **kwargs: "model"
        _extract_snapref_definitions(
            snapref_source, {"_make_wrapper", "_concat_kv"}, namespace)
        cls.native_globals = namespace
        cls.make_wrapper = staticmethod(namespace["_make_wrapper"])
        cls.native_concat = staticmethod(namespace["_concat_kv"])

        module_name = "regional_reference_cache_lifetime_test"
        module_spec = importlib.util.spec_from_file_location(
            module_name, PACKAGE / "cache_lifetime.py")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        cls.release_encoding_records = staticmethod(module.release_encoding_records)

    def _fixture(self, sizes, device="cpu", dtype=torch.float32, reference_device="cpu"):
        latent = torch.zeros((1, 4, 1, 2, 4), device=device, dtype=dtype)
        key = ("reference", "model", tuple(latent.shape[-2:]), latent.dtype, latent.device)
        adapter = SimpleNamespace(cache={}, install=lambda model: None)
        references = [torch.full((1, 4, 1, 1, 1), float(index + 1),
                                 device=reference_device, dtype=dtype)
                      for index in range(len(sizes))]
        native = self.make_wrapper(
            adapter, references, (torch.zeros(1, 3, 4), {}), "char", False)
        attn = SimpleNamespace(_ref_kv_state=None)
        model = SimpleNamespace(
            blocks=[SimpleNamespace(self_attn=attn)], patch_temporal=1,
            preprocess_text_embeds=lambda cross, *args: cross)
        return adapter, native, model, attn, latent, key

    def _attach_lora_streams(self, adapter, device, dtype=torch.float32):
        slots = []
        lora = {}
        for index in range(2):
            ref_scale = float(index + 0.125)
            target_scale = float(index + 0.625)
            ref = [
                torch.tensor([[1.0 + index, 2.0 + index],
                              [3.0 + index, 4.0 + index]], device=device, dtype=dtype),
                torch.tensor([[5.0 + index, 6.0 + index],
                              [7.0 + index, 8.0 + index]], device=device, dtype=dtype),
                ref_scale,
            ]
            target = [
                torch.tensor([[9.0 + index, 10.0 + index],
                              [11.0 + index, 12.0 + index]], device=device, dtype=dtype),
                torch.tensor([[13.0 + index, 14.0 + index],
                              [15.0 + index, 16.0 + index]], device=device, dtype=dtype),
                target_scale,
            ]
            streams = {"ref": ref, "tgt": target}
            name = f"layer-{index}"
            lora[name] = streams
            slots.append({
                "name": name,
                "streams": streams,
                "ref": ref,
                "target": target,
                "ref_scale": ref_scale,
                "target_scale": target_scale,
                "target_tensors": tuple(target[:2]),
                "target_values": tuple(tensor.detach().clone() for tensor in target[:2]),
            })
        adapter.lora = lora
        return lora, slots

    def _assert_bitwise_equal(self, actual, expected):
        actual_cpu = actual.detach().to(device="cpu").contiguous()
        expected_cpu = expected.detach().to(device="cpu").contiguous()
        self.assertEqual(actual_cpu.shape, expected_cpu.shape)
        self.assertEqual(actual_cpu.dtype, expected_cpu.dtype)
        self.assertTrue(torch.equal(
            actual_cpu.view(torch.uint8), expected_cpu.view(torch.uint8)))

    def _assert_streams_and_targets_unchanged(self, adapter, lora, slots, device):
        self.assertIs(adapter.lora, lora)
        for slot in slots:
            streams = slot["streams"]
            ref, target = slot["ref"], slot["target"]
            self.assertIs(adapter.lora[slot["name"]], streams)
            self.assertIs(streams["ref"], ref)
            self.assertIs(streams["tgt"], target)
            self.assertIs(ref[2], slot["ref_scale"])
            self.assertIs(target[2], slot["target_scale"])
            for tensor, original, snapshot in zip(
                    target[:2], slot["target_tensors"], slot["target_values"]):
                self.assertIs(tensor, original)
                self.assertEqual(tensor.device, torch.device(device))
                self._assert_bitwise_equal(tensor, snapshot)

    def _reference_weight_snapshots(self, slots):
        return tuple(
            tensor.detach().to(device="cpu").contiguous().clone()
            for slot in slots for tensor in slot["ref"][:2])

    def _exercise_reference_offload_and_reload(self, device):
        sizes = [2, 3]
        runtime_dtype = torch.float16
        adapter, native, model, attn, latent, cache_key = self._fixture(
            sizes, device, runtime_dtype, reference_device=device)
        lora, slots = self._attach_lora_streams(adapter, device)
        events = []
        encode_calls = []
        encoded_weights = []
        encoded_weight_refs = []
        concat_calls = []

        def encode(current_adapter, _model, reference, *_args):
            self.assertIs(current_adapter, adapter)
            self.assertEqual(reference.device, torch.device(device))
            self.assertEqual(reference.dtype, runtime_dtype)
            for slot in slots:
                weights = slot["ref"]
                for index in (0, 1):
                    # Model the native adapter hook's device/dtype reload before encoding.
                    weights[index] = weights[index].to(
                        device=reference.device, dtype=reference.dtype)
                    self.assertEqual(weights[index].device, torch.device(device))
                    self.assertEqual(weights[index].dtype, runtime_dtype)
            events.append("reload")
            encoded_weights.append(self._reference_weight_snapshots(slots))
            encoded_weight_refs.append(tuple(
                weakref.ref(tensor) for slot in slots for tensor in slot["ref"][:2]))
            reference_index = int(reference.flatten()[0].item()) - 1
            size = sizes[reference_index]
            key = torch.arange(
                size * 2, device=device, dtype=runtime_dtype
            ).reshape(1, size, 1, 2) + reference_index * 10
            value = key + 100
            encode_calls.append(reference_index)
            events.append("encode")
            return [(key, value)]

        def concat(records):
            self.assertEqual(
                len(encode_calls), (len(concat_calls) + 1) * len(sizes))
            for slot in slots:
                for weight in slot["ref"][:2]:
                    self.assertEqual(weight.device, torch.device(device))
                    self.assertEqual(weight.dtype, runtime_dtype)
            concat_calls.append(records)
            result = self.native_concat(records)
            events.append("concat")
            return result

        def executor(x, *_args, **_kwargs):
            events.append("target")
            for slot in slots:
                for weight in slot["ref"][:2]:
                    self.assertEqual(weight.device, torch.device("cpu"))
                    self.assertEqual(weight.dtype, runtime_dtype)
            state = attn._ref_kv_state
            self.assertIsNotNone(state)
            self.assertEqual(state["sizes"], sizes)
            return x + 0.25

        executor.class_obj = model
        sigma = torch.ones(1, device=device, dtype=runtime_dtype)
        conditioning = torch.zeros((1, 3, 4), device=device, dtype=runtime_dtype)

        def assert_offloaded_weights_match_last_encoding():
            self._assert_streams_and_targets_unchanged(adapter, lora, slots, device)
            expected = encoded_weights[-1]
            actual = tuple(
                tensor for slot in slots for tensor in slot["ref"][:2])
            for tensor, snapshot in zip(actual, expected):
                self.assertEqual(tensor.device, torch.device("cpu"))
                self._assert_bitwise_equal(tensor, snapshot)

        with patch.dict(self.native_globals, {
            "_encode_reference": encode,
            "_reference_context": lambda _model: nullcontext(),
        }):
            wrapped = self.release_encoding_records(
                native, concat, offload_reference_weights=True)
            first = wrapped(executor, latent, sigma, conditioning)
            self.assertEqual(
                events, ["reload", "encode", "reload", "encode", "concat", "target"])
            self.assertEqual(encode_calls, [0, 1])
            self.assertEqual(len(concat_calls), 1)
            assert_offloaded_weights_match_last_encoding()
            if latent.is_cuda:
                self.assertTrue(all(reference() is None
                                    for reference in encoded_weight_refs[-1]))
            first_weights = tuple(
                id(tensor) for slot in slots for tensor in slot["ref"][:2])
            first_cache = adapter.cache[cache_key]
            first_kv = tuple(tensor.detach().cpu().contiguous().clone()
                             for tensor in _tensor_leaves(first_cache[0]))

            cache_hit = wrapped(executor, latent, sigma, conditioning)
            self.assertEqual(len(encode_calls), 2, "cache hits must not re-encode references")
            self.assertEqual(len(concat_calls), 1, "cache hits must not concatenate again")
            self.assertEqual(
                tuple(events[-1:]), ("target",),
                "a cache hit must not reload reference weights")
            self.assertEqual(
                tuple(id(tensor) for slot in slots for tensor in slot["ref"][:2]),
                first_weights)
            self.assertIs(adapter.cache[cache_key], first_cache)

            adapter.cache.pop(cache_key)
            second = wrapped(executor, latent, sigma, conditioning)
            self.assertEqual(encode_calls, [0, 1, 0, 1])
            self.assertEqual(len(concat_calls), 2)
            self.assertEqual(events[-6:], [
                "reload", "encode", "reload", "encode", "concat", "target"])
            assert_offloaded_weights_match_last_encoding()
            second_cache = adapter.cache[cache_key]
            second_kv = tuple(tensor.detach().cpu().contiguous().clone()
                              for tensor in _tensor_leaves(second_cache[0]))
            self.assertEqual(len(first_kv), len(second_kv))
            for actual, expected in zip(second_kv, first_kv):
                self._assert_bitwise_equal(actual, expected)

        expected_output = torch.full_like(latent, 0.25)
        self._assert_bitwise_equal(first, expected_output)
        self._assert_bitwise_equal(cache_hit, expected_output)
        self._assert_bitwise_equal(second, expected_output)
        self._assert_streams_and_targets_unchanged(adapter, lora, slots, device)
        self.assertIsNone(attn._ref_kv_state)

    def test_forecast_offloads_reference_weights_after_encode_and_reloads_on_miss(self):
        devices = ["cpu"]
        if torch.cuda.is_available():
            devices.append("cuda:0")
        for device in devices:
            with self.subTest(device=device):
                self._exercise_reference_offload_and_reload(device)

    def test_default_and_false_forecast_leave_reference_weights_on_device(self):
        devices = ["cpu"]
        if torch.cuda.is_available():
            devices.append("cuda:0")
        for device in devices:
            for explicit_false in (False, True):
                with self.subTest(device=device, explicit_false=explicit_false):
                    adapter, native, model, attn, latent, _cache_key = self._fixture(
                        [2], device, reference_device=device)
                    lora, slots = self._attach_lora_streams(adapter, device)
                    original_reference_ids = tuple(
                        id(tensor) for slot in slots for tensor in slot["ref"][:2])
                    original_reference_values = self._reference_weight_snapshots(slots)

                    def encode(current_adapter, _model, reference, *_args):
                        self.assertIs(current_adapter, adapter)
                        for slot in slots:
                            for index in (0, 1):
                                slot["ref"][index] = slot["ref"][index].to(
                                    device=reference.device, dtype=reference.dtype)
                        return [(torch.ones((1, 2, 1, 2), device=device),
                                 torch.full((1, 2, 1, 2), 2.0, device=device))]

                    def executor(x, *_args, **_kwargs):
                        for slot in slots:
                            for weight in slot["ref"][:2]:
                                self.assertEqual(weight.device, torch.device(device))
                        return x + 0.25

                    executor.class_obj = model
                    with patch.dict(self.native_globals, {
                        "_encode_reference": encode,
                        "_reference_context": lambda _model: nullcontext(),
                    }):
                        if explicit_false:
                            wrapped = self.release_encoding_records(
                                native, self.native_concat, offload_reference_weights=False)
                        else:
                            wrapped = self.release_encoding_records(native, self.native_concat)
                        output = wrapped(
                            executor, latent, torch.ones(1, device=device),
                            torch.zeros((1, 3, 4), device=device))

                    self.assertEqual(
                        tuple(id(tensor) for slot in slots for tensor in slot["ref"][:2]),
                        original_reference_ids)
                    self._assert_streams_and_targets_unchanged(adapter, lora, slots, device)
                    for tensor, snapshot in zip(
                            (tensor for slot in slots for tensor in slot["ref"][:2]),
                            original_reference_values):
                        self._assert_bitwise_equal(tensor, snapshot)
                    self._assert_bitwise_equal(output, torch.full_like(latent, 0.25))
                    self.assertIsNone(attn._ref_kv_state)

    def test_encoding_and_concat_cancellation_preserve_native_state_and_weights(self):
        for device in (["cpu", "cuda:0"] if torch.cuda.is_available() else ["cpu"]):
            for cancelled_phase in ("encode", "concat"):
                with self.subTest(device=device, cancelled_phase=cancelled_phase):
                    adapter, native, model, attn, latent, _cache_key = self._fixture(
                        [2], device, reference_device=device)
                    lora, slots = self._attach_lora_streams(adapter, device)
                    original_reference_ids = tuple(
                        id(tensor) for slot in slots for tensor in slot["ref"][:2])
                    original_reference_values = self._reference_weight_snapshots(slots)
                    cancellation = InterruptedError(f"{cancelled_phase} cancelled")

                    def encode(_adapter, _model, reference, *_args):
                        for slot in slots:
                            for index in (0, 1):
                                slot["ref"][index] = slot["ref"][index].to(
                                    device=reference.device, dtype=reference.dtype)
                        if cancelled_phase == "encode":
                            raise cancellation
                        return [(torch.ones((1, 2, 1, 2), device=device),
                                 torch.full((1, 2, 1, 2), 2.0, device=device))]

                    def concat(_records):
                        if cancelled_phase == "concat":
                            raise cancellation
                        return self.native_concat(_records)

                    def executor(*_args, **_kwargs):
                        self.fail("target execution must not follow cancellation")

                    executor.class_obj = model
                    with patch.dict(self.native_globals, {
                        "_encode_reference": encode,
                        "_reference_context": lambda _model: nullcontext(),
                    }):
                        wrapped = self.release_encoding_records(
                            native, concat, offload_reference_weights=True)
                        with self.assertRaises(InterruptedError) as raised:
                            wrapped(
                                executor, latent, torch.ones(1, device=device),
                                torch.zeros((1, 3, 4), device=device))

                    self.assertIs(raised.exception, cancellation)
                    self.assertEqual(adapter.cache, {})
                    self.assertIsNone(attn._ref_kv_state)
                    self.assertEqual(
                        self.native_globals["_STATE"], {"adapter": None, "stream": None})
                    self.assertEqual(
                        tuple(id(tensor) for slot in slots for tensor in slot["ref"][:2]),
                        original_reference_ids)
                    self._assert_streams_and_targets_unchanged(adapter, lora, slots, device)
                    for tensor, snapshot in zip(
                            (tensor for slot in slots for tensor in slot["ref"][:2]),
                            original_reference_values):
                        self._assert_bitwise_equal(tensor, snapshot)

    def test_native_linear_hooks_reload_offloaded_weights_and_preserve_target(self):
        source = Path(os.environ["LAKIS_COMFY_ROOT"]) / "custom_nodes/snapref/__init__.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        adapter_class = next(node for node in tree.body
                             if isinstance(node, ast.ClassDef) and node.name == "_Adapter")
        install_method = next(node for node in adapter_class.body
                              if isinstance(node, ast.FunctionDef) and node.name == "install")
        namespace = {
            "torch": torch, "F": torch.nn.functional,
            "_STATE": {"adapter": None, "stream": None},
        }
        _extract_snapref_definitions(source, {"_adapter_block_map"}, namespace)
        exec(compile(ast.Module(body=[install_method], type_ignores=[]), str(source), "exec"),
             namespace)

        class Attention(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.q_proj = torch.nn.Linear(2, 2, bias=False)
                with torch.no_grad():
                    self.q_proj.weight.copy_(torch.eye(2))

            def compute_qkv(self, x, context=None, rope_emb=None, transformer_options=None):
                q = self.q_proj(x)
                return q, q, q

            def compute_attention(self, q, k, v, transformer_options=None):
                return q

            def forward(self, x, context=None, rope_emb=None, transformer_options=None):
                return self.compute_attention(*self.compute_qkv(x))

        class Block(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.self_attn = Attention()

        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.blocks = torch.nn.ModuleList([Block()])

            def forward(self, x):
                return self.blocks[0].self_attn(x)

        devices = ["cpu", "cuda:0"] if torch.cuda.is_available() else ["cpu"]
        for device in devices:
            for dtype in (torch.float32, torch.float16, torch.bfloat16):
                with self.subTest(device=device, dtype=dtype), torch.no_grad():
                    model = Model().to(device=device, dtype=dtype).requires_grad_(False)
                    x = torch.tensor([[[1., 2.], [3., 4.]]], device=device, dtype=dtype)
                    reference = [
                        torch.diag(torch.tensor([2., 3.], device=device)),
                        torch.diag(torch.tensor([4., 5.], device=device)), .25]
                    target = [
                        torch.diag(torch.tensor([1., 2.], device=device)),
                        torch.diag(torch.tensor([2., 3.], device=device)), .5]
                    adapter = SimpleNamespace(
                        lora={"blocks.0.self_attn.q_proj": {"ref": reference, "tgt": target}},
                        block_indices={0}, hooked=weakref.WeakSet())
                    namespace["install"](adapter, model)
                    attn = model.blocks[0].self_attn
                    attn._ref_kv_state = {"record": [None]}
                    namespace["_STATE"].update(adapter=adapter, stream="ref")
                    before = model(x)
                    self._assert_bitwise_equal(
                        before, x * torch.tensor([3., 4.75], device=device, dtype=dtype))
                    records = [attn._ref_kv_state["record"]]
                    old_reference = tuple(weakref.ref(weight) for weight in reference[:2])

                    attn._ref_kv_state = None
                    namespace["_STATE"].update(stream="tgt")
                    target_before = model(x)
                    self._assert_bitwise_equal(
                        target_before, x * torch.tensor([2., 4.], device=device, dtype=dtype))
                    target_tensors = tuple(target[:2])
                    namespace["_STATE"].update(adapter=None, stream=None)

                    native = self.make_wrapper(adapter, [None], (None, {}), "char", False)
                    wrapped = self.release_encoding_records(
                        native, self.native_concat, offload_reference_weights=True)
                    cache = wrapped.__globals__["_concat_kv"](records)
                    for weight in reference[:2]:
                        self.assertEqual(weight.device.type, "cpu")
                        self.assertEqual(weight.dtype, dtype)
                    if x.is_cuda:
                        self.assertTrue(all(weight() is None for weight in old_reference))
                    for actual, original in zip(target[:2], target_tensors):
                        self.assertIs(actual, original)
                    self._assert_bitwise_equal(cache[0][0], before)

                    namespace["_STATE"].update(adapter=adapter, stream="tgt")
                    self._assert_bitwise_equal(model(x), target_before)
                    attn._ref_kv_state = {"record": [None]}
                    namespace["_STATE"].update(stream="ref")
                    self._assert_bitwise_equal(model(x), before)
                    for weight in reference[:2]:
                        self.assertEqual(weight.device, x.device)
                        self.assertEqual(weight.dtype, x.dtype)
                    namespace["_STATE"].update(adapter=None, stream=None)
                    attn._ref_kv_state = None
                    self._assert_bitwise_equal(model(x), x)

    def _copy_and_assert_isolated(self, native, unrelated):
        original_globals = native.__globals__
        globals_before = dict(original_globals)
        metadata_before = dict(native.__dict__)
        copied = self.release_encoding_records(native, self.native_concat)

        self.assertIsInstance(copied, FunctionType)
        self.assertIsNot(copied, native)
        self.assertIs(copied.__code__, native.__code__)
        self.assertIs(copied.__closure__, native.__closure__)
        self.assertIs(copied.__defaults__, native.__defaults__)
        self.assertEqual(copied.__kwdefaults__, native.__kwdefaults__)
        self.assertEqual(copied.__name__, native.__name__)
        self.assertEqual(copied.__qualname__, native.__qualname__)
        self.assertEqual(copied.__module__, native.__module__)
        self.assertEqual(copied.__doc__, native.__doc__)
        self.assertEqual(copied.__annotations__, native.__annotations__)
        self.assertEqual(copied.__dict__, {**metadata_before, "__wrapped__": native})

        self.assertIsNot(copied.__globals__, original_globals)
        self.assertEqual(set(copied.__globals__), set(original_globals))
        for name, value in globals_before.items():
            if name == "_concat_kv":
                self.assertIsNot(copied.__globals__[name], value)
            else:
                self.assertIs(copied.__globals__[name], value)
        self.assertIs(native.__globals__, original_globals)
        self.assertIs(native.__globals__["_concat_kv"], self.native_concat)
        self.assertIs(unrelated.__globals__, original_globals)
        self.assertIs(unrelated.__globals__["_concat_kv"], self.native_concat)
        for name, value in globals_before.items():
            self.assertIs(original_globals[name], value)
        return copied

    def _exercise_multiple_reference_records(self, device):
        sizes = [2, 3]
        adapter, native, model, attn, latent, cache_key = self._fixture(sizes, device)
        unrelated_adapter = SimpleNamespace(cache={}, install=lambda model: None)
        unrelated = self.make_wrapper(
            unrelated_adapter, [None], (None, {}), "other", False)
        copied = self._copy_and_assert_isolated(native, unrelated)

        records, source_refs, source_signatures = _make_records(device, sizes)
        expected_cache = self.native_concat(records)
        delegated = []
        concat_calls = []
        original_record_ids = tuple(id(record) for record in records)

        def delegate(current_records):
            self.assertIs(current_records, records)
            self.assertEqual(
                tuple(id(record) for record in current_records), original_record_ids)
            concat_calls.append(current_records)
            result = self.native_concat(current_records)
            delegated.append(result)
            return result

        copied = self.release_encoding_records(native, delegate)
        concatenated = copied.__globals__["_concat_kv"](records)
        self.assertEqual(len(concat_calls), 1)
        self.assertIs(concat_calls[0], records)
        self.assertIs(concatenated, delegated[0])
        self.assertEqual(_tree_signature(concatenated), _tree_signature(expected_cache))
        for actual, expected in zip(_tensor_leaves(concatenated), _tensor_leaves(expected_cache)):
            torch.testing.assert_close(actual, expected, atol=0, rtol=0)

        self.assertEqual(len(records), len(source_signatures))
        self.assertEqual(
            tuple(_tree_signature(record) for record in records), source_signatures)
        self.assertTrue(all(tensor.device.type == "meta" for tensor in _tensor_leaves(records)))
        gc.collect()
        self.assertTrue(all(reference() is None for reference in source_refs))

        adapter.cache[cache_key] = (concatenated, sizes)
        cache_snapshot = adapter.cache[cache_key]
        seen = []

        def executor(x, *args, **kwargs):
            self.assertTrue(all(reference() is None for reference in source_refs))
            state = attn._ref_kv_state
            self.assertIs(state["cache"], concatenated)
            self.assertEqual(state["sizes"], sizes)
            seen.append(state)
            return x + 0.25

        executor.class_obj = model
        sigma = torch.ones(1, device=device)
        conditioning = torch.zeros((1, 3, 4), device=device)
        original_output = native(executor, latent, sigma, conditioning)
        copied_output = copied(executor, latent, sigma, conditioning)
        torch.testing.assert_close(original_output, copied_output, atol=0, rtol=0)
        torch.testing.assert_close(copied_output, latent + 0.25, atol=0, rtol=0)
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(concat_calls), 1, "cache hits must not concatenate records again")
        self.assertIs(adapter.cache[cache_key], cache_snapshot)

    def test_multiple_reference_records_release_before_native_cache_hit_forward(self):
        devices = ["cpu"]
        if torch.cuda.is_available():
            devices.append("cuda")
        for device in devices:
            with self.subTest(device=device):
                self._exercise_multiple_reference_records(device)

    def test_native_cache_miss_releases_duplicates_before_prediction(self):
        devices = ["cpu", "cuda"] if torch.cuda.is_available() else ["cpu"]
        sizes = [2, 3]
        for device in devices:
            with self.subTest(device=device):
                source_refs = {}

                def encode(adapter, _model, reference, *_args):
                    index = int(reference.flatten()[0].item()) - 1
                    key = torch.full((1, sizes[index], 1, 2), float(index + 1), device=device)
                    value = key + 10
                    source_refs.setdefault(id(adapter), []).extend(
                        (weakref.ref(key), weakref.ref(value)))
                    return [(key, value)]

                outputs = []
                with patch.dict(self.native_globals, {
                    "_encode_reference": encode,
                    "_reference_context": lambda model: nullcontext(),
                }):
                    for compact in (False, True):
                        adapter, native, model, attn, latent, cache_key = self._fixture(sizes, device)
                        run = self.release_encoding_records(native, self.native_concat) if compact else native
                        seen = []

                        def executor(x, *_args, **_kwargs):
                            references = source_refs[id(adapter)]
                            self.assertEqual(len(references), 4)
                            if compact or seen:
                                self.assertTrue(all(reference() is None for reference in references))
                            else:
                                self.assertTrue(all(reference() is not None for reference in references))
                            state = attn._ref_kv_state
                            self.assertEqual(state["sizes"], sizes)
                            keys, values = state["cache"][0]
                            expected = torch.cat([
                                torch.full((1, size, 1, 2), float(index + 1), device=device)
                                for index, size in enumerate(sizes)], dim=1)
                            torch.testing.assert_close(keys, expected, atol=0, rtol=0)
                            torch.testing.assert_close(values, expected + 10, atol=0, rtol=0)
                            seen.append(True)
                            return x + 0.25

                        executor.class_obj = model
                        sigma, context = torch.ones(1, device=device), torch.zeros(1, 3, 4, device=device)
                        first = run(executor, latent, sigma, context)
                        cached = adapter.cache[cache_key]
                        second = run(executor, latent, sigma, context)
                        self.assertIs(adapter.cache[cache_key], cached)
                        self.assertEqual(len(source_refs[id(adapter)]), 4)
                        self.assertIsNone(attn._ref_kv_state)
                        torch.testing.assert_close(first, second, atol=0, rtol=0)
                        outputs.append(first)
                torch.testing.assert_close(outputs[0], outputs[1], atol=0, rtol=0)

    def _exercise_single_reference_alias(self, device):
        adapter, native, _model, _attn, _latent, _cache_key = self._fixture([3], device)
        unrelated = self.make_wrapper(
            SimpleNamespace(cache={}, install=lambda model: None),
            [None], (None, {}), "other", False)
        copied = self._copy_and_assert_isolated(native, unrelated)
        records, source_refs, source_signatures = _make_records(device, [3])
        delegated = []

        def delegate(current_records):
            self.assertIs(current_records, records)
            result = self.native_concat(current_records)
            delegated.append(result)
            return result

        copied = self.release_encoding_records(native, delegate)
        result = copied.__globals__["_concat_kv"](records)
        self.assertIs(result, delegated[0])
        self.assertEqual(
            tuple(_tree_signature(record) for record in records), source_signatures)
        self.assertTrue(all(tensor.device.type == "meta" for tensor in _tensor_leaves(records)))
        result_tensors = list(_tensor_leaves(result))
        self.assertEqual(len(result_tensors), len(source_refs))
        for reference, tensor in zip(source_refs, result_tensors):
            self.assertIs(reference(), tensor)
            self.assertTrue(torch.isfinite(tensor).all())
        gc.collect()
        self.assertTrue(all(reference() is not None for reference in source_refs))

    def test_single_reference_concat_aliases_keep_source_tensors_alive(self):
        devices = ["cpu"]
        if torch.cuda.is_available():
            devices.append("cuda")
        for device in devices:
            with self.subTest(device=device):
                self._exercise_single_reference_alias(device)

    def test_cache_hit_cancellation_propagates_unchanged(self):
        sizes = [2]
        adapter, native, model, attn, latent, cache_key = self._fixture(sizes)
        records, _source_refs, _signatures = _make_records("cpu", sizes)
        cache = self.native_concat(records)
        adapter.cache[cache_key] = (cache, sizes)
        unrelated = self.make_wrapper(
            SimpleNamespace(cache={}, install=lambda model: None),
            [None], (None, {}), "other", False)
        copied = self._copy_and_assert_isolated(native, unrelated)
        cancellation = InterruptedError("native executor cancelled")

        def executor(x, *args, **kwargs):
            self.assertIsNotNone(attn._ref_kv_state)
            raise cancellation

        executor.class_obj = model
        with self.assertRaises(InterruptedError) as raised:
            copied(executor, latent, torch.ones(1), torch.zeros((1, 3, 4)))
        self.assertIs(raised.exception, cancellation)
        self.assertIsNone(attn._ref_kv_state)
        self.assertEqual(self.native_globals["_STATE"], {"adapter": None, "stream": None})


if __name__ == "__main__":
    unittest.main()
