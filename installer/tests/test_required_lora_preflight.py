"""Required ANIMA LoRA checks without inference, submissions or live user state."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/external_ui"))
import workflow_bridge as bridge
from installer.tests.test_moss_mode import schema as moss_schema, state as moss_state
from installer.tests.test_recovery_patch import Reply


TURBO = "anima-turbo-lora-v0.2.safetensors"


class RequiredLoRAPreflightTests(unittest.TestCase):
    def setUp(self):
        self.template = ROOT / "workflows/LAKIS_runtime_api_v8.0.json"
        self.graph = json.loads(self.template.read_text(encoding="utf-8"))
        aliases = bridge._native_alias_view(self.graph)
        self.info = {
            node["class_type"]: {"input": {"required": {}}}
            for node in self.graph.values()
        }
        for node_id, kind, field in (
            ("890:1365", "DiffusionModelLoaderKJ", "model_name"),
            ("890:159", "VAELoader", "vae_name"),
            ("890:164", "CLIPLoader", "clip_name"),
        ):
            self.info[kind] = {"input": {"required": {
                field: [[aliases[node_id]["inputs"][field]]],
            }}}
        self.info["LoraLoaderModelOnly"] = {"input": {"required": {
            "lora_name": [[TURBO]],
        }}}

    def missing_info(self):
        info = deepcopy(self.info)
        info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0] = []
        return info

    def test_missing_turbo_rejects_native_build_even_with_user_loras_disabled(self):
        for mode in ("fast", "detail", "lakis_detail"):
            with (
                self.subTest(mode=mode),
                patch.object(bridge, "TEMPLATE", self.template),
                patch.object(bridge, "_wait_for_comfy_object_info", return_value=self.missing_info()),
            ):
                with self.assertRaises(bridge.MissingRuntimeLoRAError) as raised:
                    bridge.build_prompt({
                        "generation": {"engine": "anima", "mode": mode},
                        "loras": [], "lora_enabled": False, "output": {"seed": 42},
                    })
                self.assertEqual(TURBO, raised.exception.lora_name)
                self.assertEqual("3005", raised.exception.node_id)
                self.assertEqual("LoraLoaderModelOnly", raised.exception.node_type)

    def test_present_turbo_passes_without_mutating_graph_or_inventory(self):
        for mode in ("FAST", "DETAIL", "LAKIS DETAIL"):
            with self.subTest(mode=mode):
                self.graph["3000"]["inputs"]["mode"] = mode
                before_graph, before_info = deepcopy(self.graph), deepcopy(self.info)
                bridge._validate_live_prompt_models(self.graph, self.info)
                self.assertEqual(before_graph, self.graph)
                self.assertEqual(before_info, self.info)

    def test_restored_inventory_is_used_without_a_stale_missing_result(self):
        info = self.missing_info()
        with self.assertRaises(bridge.MissingRuntimeLoRAError):
            bridge._validate_live_prompt_models(self.graph, info)
        info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0].append(TURBO)
        bridge._validate_live_prompt_models(self.graph, info)

    def test_different_registered_relative_path_does_not_silently_rewrite_the_graph(self):
        info = self.missing_info()
        info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0].append("anima/" + TURBO)
        before = deepcopy(self.graph)
        with self.assertRaises(bridge.MissingRuntimeLoRAError):
            bridge._validate_live_prompt_models(self.graph, info)
        self.assertEqual(before, self.graph)

    def test_runtime_adapter_resolves_only_the_registered_anima_namespaces(self):
        for registered, expected in (
            ([TURBO], TURBO),
            (["anima/" + TURBO], "anima/" + TURBO),
            (["ANIMA\\" + TURBO], "ANIMA\\" + TURBO),
            (["anima/" + TURBO, TURBO], TURBO),
            (["moss/" + TURBO], TURBO),
            (["other/" + TURBO], TURBO),
            ([], TURBO),
        ):
            with self.subTest(registered=registered):
                info = self.missing_info()
                info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0] = registered
                before = deepcopy(info)
                self.assertEqual(expected, bridge._runtime_anima_lora_name(TURBO, info))
                self.assertEqual(before, info)

    def test_moss_then_anima_build_uses_registered_turbo_path_in_all_quality_modes(self):
        original = self.template.read_bytes()
        for separator in ("/", "\\"):
            for mode in ("fast", "detail", "lakis_detail"):
                with self.subTest(separator=separator, mode=mode), \
                     tempfile.TemporaryDirectory(prefix="lakis-turbo-path-") as temporary:
                    root = Path(temporary)
                    info = deepcopy(self.info)
                    selected = "anima" + separator + TURBO
                    info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0] = [
                        selected, "moss/style.safetensors",
                    ]
                    with (
                        patch.multiple(
                            bridge, TEMPLATE=self.template, COMFY_ROOT=root,
                            OUTPUT_ROOT=root / "output",
                            OUTPUT_LOCATION_PATH=root / "location.json",
                            LEGACY_OUTPUT_LOCATION_PATH=root / "legacy-location.json",
                        ),
                        patch.object(bridge, "_wait_for_comfy_object_info", return_value=moss_schema()),
                    ):
                        moss_graph, _ = bridge.build_prompt(moss_state())
                    self.assertEqual("moss", moss_graph["775"]["_meta"]["generation_engine"])
                    with (
                        patch.multiple(
                            bridge, TEMPLATE=self.template, COMFY_ROOT=root,
                            OUTPUT_ROOT=root / "output",
                            OUTPUT_LOCATION_PATH=root / "location.json",
                            LEGACY_OUTPUT_LOCATION_PATH=root / "legacy-location.json",
                        ),
                        patch.object(bridge, "_wait_for_comfy_object_info", return_value=info),
                        patch.object(bridge, "_comfy_object_info", return_value=info),
                        patch.object(bridge, "_live_lora_inventory", return_value=[]),
                        patch.object(bridge, "_preferred_upscaler", return_value=None),
                    ):
                        graph, _ = bridge.build_prompt({
                            "generation": {"engine": "anima", "mode": mode},
                            "loras": [], "lora_enabled": False,
                            "composition_enabled": False, "output": {"seed": 42},
                        })
                    self.assertEqual(selected, graph["3005"]["inputs"]["lora_name"])
                    self.assertEqual(["3003", 0], graph["775"]["inputs"]["images"])
                    bridge._validate_live_prompt_models(graph, info)
                    self.assertEqual(original, self.template.read_bytes())

    def test_graph_without_a_model_only_lora_does_not_require_turbo(self):
        graph = {"775": {"class_type": "Image Saver", "inputs": {}}}
        bridge._validate_live_prompt_models(graph, self.missing_info())

    def test_moss_keeps_its_existing_model_validation_without_anima_turbo(self):
        info = moss_schema()
        graph, _ = bridge.moss_mode.build_prompt(
            moss_state(), info, Path("fixture-output"), 2**53 - 1,
        )
        bridge._validate_live_prompt_models(graph, info)

    def test_public_error_identifies_the_missing_file_and_node(self):
        with self.assertRaises(bridge.MissingRuntimeLoRAError) as raised:
            bridge._validate_live_prompt_models(self.graph, self.missing_info())
        error = raised.exception
        code, message = bridge.WorkflowBridge._public_error(error, engine="anima")
        self.assertEqual("LKS-MOD-1201", code)
        self.assertIn(TURBO, message)
        self.assertEqual("모델 파일 확인", error.failure_stage)
        self.assertEqual({"missing_lora": TURBO, "input_name": "lora_name"}, error.diagnostic())

    def test_changed_inventory_blocks_allowance_consumption_socket_and_prompt_submission(self):
        bridge._validate_live_prompt_models(self.graph, self.info)
        session = MagicMock()
        session.get.side_effect = [
            Reply({"queue_running": [], "queue_pending": []}),
            Reply(self.missing_info()),
        ]
        client = MagicMock()
        client.__aenter__.return_value = session
        worker = Mock()
        worker.status.cancel_requested = False
        with (
            patch.object(bridge.aiohttp, "ClientSession", return_value=client),
            patch.object(bridge.os, "replace") as consume_allowance,
        ):
            with self.assertRaises(bridge.MissingRuntimeLoRAError):
                asyncio.run(bridge.WorkflowBridge._run(
                    worker, self.graph, {}, {"request_id": "missing-turbo-preflight"},
                ))
        consume_allowance.assert_not_called()
        session.ws_connect.assert_not_called()
        session.post.assert_not_called()
        worker.status.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
