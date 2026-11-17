from __future__ import annotations

import asyncio
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import runpy
import types
import unittest
from unittest.mock import AsyncMock, patch

# Load the existing fixture module without exporting its TestCase class into
# this module's namespace: unittest discovery must not run its tests again.
_RECOVERY = runpy.run_path(str(Path(__file__).with_name("test_recovery_patch.py")))
_BRIDGE = _RECOVERY["m"]
_ROOT = _RECOVERY["ROOT"]


def _event(event_type: str, **data):
    return {"type": event_type, "data": {"prompt_id": "P", **data}}


class _ReplaySocket:
    """Finite WebSocket replay; captures status after each consumed event."""

    def __init__(self, bridge, events):
        self.bridge = bridge
        self.events = list(events)
        self.index = 0
        self.snapshots = {}

    async def receive(self, **_kwargs):
        if self.index:
            self.snapshots[self.index - 1] = (
                self.bridge.status.percent,
                self.bridge.status.stage,
            )
        if self.index >= len(self.events):
            raise AssertionError("observer consumed beyond the finite event replay")
        event = self.events[self.index]
        self.index += 1
        if isinstance(event, BaseException):
            raise event
        return types.SimpleNamespace(
            type=_RECOVERY["aiohttp"].WSMsgType.TEXT,
            data=json.dumps(event),
        )


class GenerationProgressTests(unittest.TestCase):
    def setUp(self):
        # Composition reuses isolated paths and FakeSession without inheriting
        # or rediscovering IsolatedBridge's existing test methods.
        self.fixture = _RECOVERY["IsolatedBridge"](
            "test_empty_output_config_never_scans_cwd"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.bridge = self.fixture.bridge
        self.native_template = json.loads(
            (_ROOT / "workflows" / "LAKIS_runtime_api_v8.0.json").read_text(
                encoding="utf-8"
            )
        )

    def _mode_prompt(self, mode: str):
        prompt = deepcopy(self.native_template)
        prompt["3000"]["inputs"]["mode"] = mode
        return prompt

    def _replay(self, prompt, events):
        socket = _ReplaySocket(self.bridge, events)
        result = asyncio.run(
            self.bridge._observe(
                _RECOVERY["FakeSession"](), socket, "P", prompt
            )
        )
        return result, socket

    def test_real_v8_mode_plans_map_weights_and_exclude_other_modes(self):
        common = {"4041", "4036", "4040", "4037", "4032", "4031", "775"}
        expected_mode_nodes = {
            "FAST": set(),
            "DETAIL": {"4007", "4061", "4024"},
            "LAKIS DETAIL": {"3040", "3051"},
        }
        expensive = {"4007", "4061", "4024", "3040", "3051"}
        mapped = {
            "4041": ("1634:1622", 25.0, "Initial"),
            "4032": ("1633:1612", 8.0, "HighRez"),
            "4007": ("1530:1826", 15.0, "Face Detail"),
            "4061": ("1836:2069", 12.0, "Eye Detail"),
            "4024": ("1541:1538", 24.0, "Upscale"),
        }

        for mode, mode_nodes in expected_mode_nodes.items():
            with self.subTest(mode=mode):
                prompt = self._mode_prompt(mode)
                prompt["orphan_progress_node"] = {
                    "class_type": "KSampler",
                    "inputs": {},
                    "_meta": {"lakis_source_id": "1633:1612"},
                }
                original = deepcopy(prompt)
                weights, labels = _BRIDGE._progress_node_plan(prompt)

                self.assertEqual(original, prompt)
                self.assertTrue(common.issubset(weights))
                self.assertTrue(mode_nodes.issubset(weights))
                self.assertFalse((expensive - mode_nodes).intersection(weights))
                self.assertNotIn("orphan_progress_node", weights)
                for node_id in common | mode_nodes:
                    if node_id in mapped:
                        source_id, weight, label = mapped[node_id]
                        self.assertEqual(source_id, prompt[node_id]["_meta"]["lakis_source_id"])
                        self.assertEqual(weight, weights[node_id])
                        self.assertEqual(label, labels[node_id])

                if mode == "LAKIS DETAIL":
                    self.assertEqual(27.0, weights["3040"])
                    self.assertEqual("Face · Eye Detail", labels["3040"])
                    self.assertEqual(24.0, weights["3051"])
                    self.assertEqual("SCOPE Upscale", labels["3051"])

    def test_generation_controls_static_outputs_match_native_resolver(self):
        controls_class = runpy.run_path(
            str(_ROOT / "src" / "custom_nodes" / "ComfyUI-LAKIS-Detail" / "native_controls.py")
        )["GenerationControls"]
        resolver = controls_class()

        for mode in ("FAST", "DETAIL", "LAKIS DETAIL"):
            for composition, i2i, inpaint, pose in product((False, True), repeat=4):
                with self.subTest(
                    mode=mode,
                    composition=composition,
                    i2i=i2i,
                    inpaint=inpaint,
                    pose=pose,
                ):
                    expected = resolver.resolve(
                        mode, composition, i2i, inpaint, pose, 0.37
                    )[:8]
                    prompt = {
                        "3000": {
                            "class_type": "LAKIS_GenerationControls",
                            "inputs": {
                                "mode": mode,
                                "composition": composition,
                                "i2i": i2i,
                                "inpaint": inpaint,
                                "pose": pose,
                                "i2i_denoise": 0.37,
                            },
                            "_meta": {"lakis_source_id": "3000"},
                        },
                        "775": {
                            "class_type": "Image Saver",
                            "inputs": {},
                            "_meta": {"lakis_source_id": "775"},
                        },
                    }
                    for output_index, expected_value in enumerate(expected):
                        primitive_id = f"primitive_{output_index}"
                        switch_id = f"switch_{output_index}"
                        false_id = f"false_{output_index}"
                        true_id = f"true_{output_index}"
                        prompt[primitive_id] = {
                            "class_type": "PrimitiveBoolean",
                            "inputs": {"value": ["3000", output_index]},
                            "_meta": {"lakis_source_id": primitive_id},
                        }
                        prompt[switch_id] = {
                            "class_type": "ComfySwitchNode",
                            "inputs": {
                                "switch": [primitive_id, 0],
                                "on_false": [false_id, 0],
                                "on_true": [true_id, 0],
                            },
                            "_meta": {"lakis_source_id": switch_id},
                        }
                        prompt[false_id] = {
                            "class_type": "PrimitiveInt",
                            "inputs": {"value": 0},
                            "_meta": {"lakis_source_id": false_id},
                        }
                        prompt[true_id] = {
                            "class_type": "PrimitiveInt",
                            "inputs": {"value": 1},
                            "_meta": {"lakis_source_id": true_id},
                        }
                        prompt["775"]["inputs"][switch_id] = [switch_id, 0]

                    weights, _labels = _BRIDGE._progress_node_plan(prompt)
                    for output_index, expected_value in enumerate(expected):
                        selected = (
                            f"true_{output_index}"
                            if expected_value
                            else f"false_{output_index}"
                        )
                        rejected = (
                            f"false_{output_index}"
                            if expected_value
                            else f"true_{output_index}"
                        )
                        self.assertIn(selected, weights)
                        self.assertNotIn(rejected, weights)

    def test_unknown_switch_selector_keeps_both_branches(self):
        prompt = {
            "775": {
                "class_type": "Image Saver",
                "inputs": {"images": ["switch", 0]},
                "_meta": {"lakis_source_id": "775"},
            },
            "switch": {
                "class_type": "ComfySwitchNode",
                "inputs": {
                    "switch": ["unknown_selector", 0],
                    "on_false": ["false_branch", 0],
                    "on_true": ["true_branch", 0],
                },
            },
            "unknown_selector": {"class_type": "UnknownSelector", "inputs": {}},
            "false_branch": {
                "class_type": "PrimitiveInt",
                "inputs": {"value": 0},
                "_meta": {"lakis_source_id": "false_branch"},
            },
            "true_branch": {
                "class_type": "PrimitiveInt",
                "inputs": {"value": 1},
                "_meta": {"lakis_source_id": "true_branch"},
            },
        }

        weights, _labels = _BRIDGE._progress_node_plan(prompt)

        self.assertIn("false_branch", weights)
        self.assertIn("true_branch", weights)

    def test_progress_is_per_step_monotonic_and_ignores_foreign_events(self):
        prompt = self._mode_prompt("FAST")
        events = [
            _event("executing", node="4041"),
            _event("progress", node="4041", value=1, max=10),
            {"type": "progress", "data": {"prompt_id": "OTHER", "node": "4041", "value": 10, "max": 10}},
            _event("progress", node="4032", value=10, max=10),
            _event("progress", node="4041", value=2, max=10),
            _event("execution_success"),
        ]

        result, socket = self._replay(prompt, events)

        self.assertTrue(result)
        after_one = socket.snapshots[1]
        after_foreign_prompt = socket.snapshots[2]
        after_foreign_node = socket.snapshots[3]
        after_two = socket.snapshots[4]
        self.assertGreater(after_two[0], after_one[0])
        self.assertEqual(after_one, after_foreign_prompt)
        self.assertEqual(after_one, after_foreign_node)
        self.assertIn("1/10", after_one[1])
        self.assertIn("2/10", after_two[1])

    def test_cached_and_executed_nodes_complete_weighted_work(self):
        prompt = self._mode_prompt("DETAIL")
        events = [
            _event("execution_cached", nodes=["4041"]),
            _event("executing", node="4032"),
            _event("executed", node="4032", output={}),
            _event("execution_success"),
        ]

        result, socket = self._replay(prompt, events)

        self.assertTrue(result)
        after_cached = socket.snapshots[0][0]
        after_execution = socket.snapshots[1][0]
        after_executed = socket.snapshots[2][0]
        self.assertGreater(after_cached, 0.0)
        self.assertEqual(after_cached, after_execution)
        self.assertGreater(after_executed, after_execution)

    def test_nested_progress_reset_updates_stage_without_regressing_percent(self):
        prompt = self._mode_prompt("LAKIS DETAIL")
        events = [
            _event("executing", node="3051"),
            _event("progress", node="3051", value=8, max=10),
            _event("progress", node="3051", value=2, max=10),
            _event("executing", node="775"),
            _event("progress", node="775", value=1, max=1),
            _event("execution_success"),
        ]

        result, socket = self._replay(prompt, events)

        self.assertTrue(result)
        after_eight = socket.snapshots[1]
        after_reset = socket.snapshots[2]
        after_save = socket.snapshots[4]
        self.assertGreaterEqual(after_reset[0], after_eight[0])
        self.assertIn("SCOPE Upscale", after_reset[1])
        self.assertIn("2/10", after_reset[1])
        self.assertIn("Final Save", after_save[1])
        self.assertIn("1/1", after_save[1])
        self.assertLess(after_save[0], 100.0)
        self.assertLess(self.bridge.status.percent, 100.0)

    def test_quiet_running_interval_does_not_advance_percent(self):
        prompt = self._mode_prompt("FAST")
        socket = _ReplaySocket(
            self.bridge,
            [
                _event("executing", node="4041"),
                asyncio.TimeoutError(),
                _event("execution_success"),
            ],
        )
        with patch.object(
            self.bridge,
            "_probe_prompt_state",
            new=AsyncMock(return_value="running"),
        ):
            result = asyncio.run(
                self.bridge._observe(
                    _RECOVERY["FakeSession"](), socket, "P", prompt
                )
            )

        self.assertTrue(result)
        self.assertEqual(socket.snapshots[0][0], socket.snapshots[1][0])

    def test_cancellation_preserves_progress_and_stays_below_completion(self):
        self.bridge.status.update(cancel_requested=True)
        prompt = self._mode_prompt("FAST")
        events = [
            _event("executing", node="4041"),
            _event("progress", node="4041", value=2, max=10),
            _event("execution_interrupted"),
        ]

        result, _socket = self._replay(prompt, events)

        self.assertFalse(result)
        self.assertEqual("cancelled", self.bridge.status.state)
        self.assertEqual("중지됨", self.bridge.status.stage)
        self.assertGreater(self.bridge.status.percent, 0.0)
        self.assertLess(self.bridge.status.percent, 100.0)

    def test_execution_error_preserves_node_stage_and_progress(self):
        prompt = self._mode_prompt("LAKIS DETAIL")
        events = [
            _event("executing", node="3040"),
            _event("progress", node="3040", value=2, max=8),
            _event(
                "execution_error",
                node_id="3040",
                node_type="LAKIS_DETAIL",
                exception_type="RuntimeError",
                exception_message="nested detail failure",
            ),
        ]

        with self.assertRaises(_BRIDGE.GenerationExecutionError) as caught:
            self._replay(prompt, events)

        self.assertEqual("3040", caught.exception.node_id)
        self.assertEqual("LAKIS_DETAIL", caught.exception.node_type)
        self.assertEqual("Face · Eye Detail", caught.exception.failure_stage)
        self.assertEqual("nested detail failure", caught.exception.payload["exception_message"])
        self.assertGreater(self.bridge.status.percent, 0.0)
        self.assertLess(self.bridge.status.percent, 100.0)
        self.assertIn("2/8", self.bridge.status.stage)


if __name__ == "__main__":
    unittest.main()
