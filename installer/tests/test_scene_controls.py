from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src" / "external_ui"))

import scene_controls
import serve_ui


class Request:
    def __init__(self, path="/api/scene-controls", data=None):
        self.path = path
        self.data = data
        self.status = None
        self.response = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def _read_json(self, max_size):
        return self.data

    def _send_json(self, status, response):
        self.status, self.response = status, response

    def send_error(self, status):
        self.status = status

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


class SceneControlsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.prompt = {
            "1634:1721": {"class_type": "DiTSpectrumPatch", "inputs": {"model": ["base", 0], "enabled": True}},
            "1634:1622": {"class_type": "KSampler", "inputs": {
                "model": ["1634:1721", 0], "seed": 42, "steps": 30, "cfg": 4.0,
                "sampler_name": "euler", "scheduler": "normal",
                "positive": ["positive", 0], "negative": ["negative", 0],
            }},
            "1633:1612": {"class_type": "KSampler", "inputs": {
                "model": ["turbo", 0], "latent_image": ["1634:1622", 0],
                "positive": ["positive", 0], "negative": ["negative", 0],
            }},
            "890:1281": {"class_type": "easy loraStackApply", "inputs": {"lora_stack": ["global", 1]}},
            "775": {"class_type": "Image Saver", "inputs": {"images": ["decode", 0]}},
        }
        self.info = {name: {"input": {"required": {}}} for name in scene_controls.REQUIRED_NODES}
        self.info["AnimaLLLiteApply_sdscripts"]["input"]["required"]["lllite_name"] = [list(scene_controls.MODELS)]
        self.info["ComfyCoupleMask"]["input"]["required"] = {
            "cross_region_attention": ["FLOAT", {"default": 0.0}],
            "cross_region_mode": [["self_exclusion", "global_average"]],
            "feather_mask": ["INT", {"default": 0}],
            "model_type": [["auto", "anima"]],
            "skip_positive_conditioning": ["BOOLEAN", {"default": True}],
        }
        self.config = {
            "enabled": True, "toyxyz_enabled": True,
            "pose_data": json.dumps({"version": 1}),
            "toyxyz_render_data": json.dumps({
                "version": 1, "region_painter": {"width": 768, "height": 512},
            }),
            "toyxyz_paint_data": json.dumps({
                "version": 1, "width": 768, "height": 512, "layers": [],
            }),
        }

    def apply(self, **application):
        return scene_controls.apply_scene_controls(
            self.prompt, application, self.info, self.root, 768, 512,
        )

    def test_default_off_keeps_existing_graph_identical(self):
        before = copy.deepcopy(self.prompt)
        with patch.object(scene_controls, "model_status") as status:
            result = self.apply()
        self.assertFalse(result["scene_controls_enabled"])
        self.assertEqual(before, self.prompt)
        status.assert_not_called()

    def test_pose_and_regions_keep_spectrum_highrez_loras_and_final_saver(self):
        before = copy.deepcopy(self.prompt)
        with patch.object(scene_controls, "model_status", return_value={"valid": True}):
            result = self.apply(scene_controls=self.config)
        self.assertTrue(result["scene_controls_enabled"])
        self.assertTrue(all(result["scene_prompt_contract"].values()))
        for node in ("775", "890:1281"):
            self.assertEqual(before[node], self.prompt[node])
        self.assertTrue(self.prompt["1634:1721"]["inputs"]["enabled"])
        self.assertEqual(["1634:1721", 0], self.prompt["1634:1622"]["inputs"]["model"])
        self.assertEqual(["1634:1622", 0], self.prompt["1633:1612"]["inputs"]["latent_image"])
        self.assertEqual(42, self.prompt["1634:1622"]["inputs"]["seed"])
        painter = self.prompt["lakis:toyxyz_painter"]["inputs"]
        self.assertEqual(["lakis:toyxyz_pose", 5], painter["region_painter"])
        self.assertEqual(["lakis:toyxyz_base", 0], painter["region"])
        self.assertEqual(["890:2012", 0], self.prompt["lakis:toyxyz_base"]["inputs"]["base_prompt_text"])
        for stage, owner, sampler in (
            ("initial", "1634:1721", "1634:1622"), ("highrez", "1633:1612", "1633:1612"),
        ):
            mask = self.prompt[f"lakis:toyxyz_{stage}"]["inputs"]
            self.assertEqual([f"lakis:toyxyz_{stage}", 0], self.prompt[owner]["inputs"]["model"])
            self.assertEqual([f"lakis:region_{stage}", 0], mask["model"])
            self.assertEqual(["negative", 0], mask["negative"])
            self.assertEqual("self_exclusion", mask["cross_region_mode"])
            self.assertEqual([f"lakis:toyxyz_{stage}", 1], self.prompt[sampler]["inputs"]["positive"])
            self.assertEqual([f"lakis:toyxyz_{stage}", 2], self.prompt[sampler]["inputs"]["negative"])
            for kind, image, end in (
                ("pose", "lakis:toyxyz_pose", 1.0), ("region", "lakis:toyxyz_painter", 0.3),
            ):
                inputs = self.prompt[f"lakis:{kind}_{stage}"]["inputs"]
                self.assertEqual([image, 0], inputs["image"])
                self.assertEqual(end, inputs["end_percent"])
                self.assertTrue(inputs["preserve_wrapper"])
            self.assertEqual([f"lakis:pose_{stage}", 0], self.prompt[f"lakis:region_{stage}"]["inputs"]["model"])

    def test_conflicting_modes_reject_before_graph_changes(self):
        before = copy.deepcopy(self.prompt)
        for mode in ("i2i", "inpaint", "composition_enabled"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.apply(scene_controls=self.config, **{mode: True if mode == "composition_enabled" else {"enabled": True}})
            self.assertEqual(before, self.prompt)

    def test_incomplete_or_stale_editor_capture_rejects_before_graph_changes(self):
        before = copy.deepcopy(self.prompt)
        for change in (
            {"toyxyz_render_data": ""},
            {"toyxyz_render_data": json.dumps({"version": 1, "region_painter": []})},
            {"pose_data": json.dumps({"version": True})},
            {"toyxyz_paint_data": json.dumps({"version": 1, "width": 512, "height": 768})},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.apply(scene_controls={**self.config, **change})
            self.assertEqual(before, self.prompt)

    def test_missing_nodes_and_models_do_not_change_graph(self):
        before = copy.deepcopy(self.prompt)
        with patch.dict(self.info, {}, clear=True), self.assertRaisesRegex(ValueError, "노드"):
            self.apply(scene_controls=self.config)
        for valid in (False, True):
            with self.subTest(valid=valid):
                inventory = self.info["AnimaLLLiteApply_sdscripts"]["input"]["required"]
                with patch.dict(inventory, {"lllite_name": [[]] if valid else [list(scene_controls.MODELS)]}), \
                        patch.object(scene_controls, "model_status", return_value={"valid": valid}), \
                        self.assertRaisesRegex(ValueError, "설치기·업데이터"):
                    self.apply(scene_controls=self.config)
                self.assertEqual(before, self.prompt)

    def test_nonfinite_strength_and_suspended_boxes_are_rejected(self):
        for change in ({"pose_strength": float("nan")}, {"region_strength": float("inf")},
                       {"pose_strength": -1}, {"region_strength": 2.01},
                       {"pose_strength": None}, {"multicharacter": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                scene_controls.normalize_state({**self.config, **change})

    def test_state_roundtrip_preserves_unknown_fields_and_is_install_scoped(self):
        root = self.root / "installation-a"
        config = {**self.config, "future": {"kept": True}}
        request = Request(data=config)
        self.assertTrue(scene_controls.handle_post(request, root))
        self.assertEqual(200, request.status)
        self.assertEqual(scene_controls.normalize_state(config), scene_controls.load_state(root))
        self.assertFalse(scene_controls.load_state(self.root / "installation-b")["enabled"])
        (self.root / "scene-controls-v7.6.json").write_text(json.dumps(config), encoding="utf-8")
        self.assertFalse(scene_controls.load_state(self.root)["enabled"])

    def test_failed_state_replace_preserves_saved_state(self):
        original = scene_controls.normalize_state({})
        target = self.root / scene_controls.STATE_FILENAME
        target.write_text(json.dumps(original), encoding="utf-8")
        request = Request(data=self.config)
        with patch.object(scene_controls.os, "replace", side_effect=OSError("locked")):
            scene_controls.handle_post(request, self.root)
        self.assertEqual(400, request.status)
        self.assertEqual(original, scene_controls.load_state(self.root))

    def test_invalid_saved_state_is_reported_not_reset(self):
        target = self.root / scene_controls.STATE_FILENAME
        target.write_bytes(b"{broken")
        request = Request()
        scene_controls.handle_get(request, self.root, self.root)
        self.assertEqual(503, request.status)
        self.assertEqual(b"{broken", target.read_bytes())

    def test_missing_and_corrupt_models_fail_hash_check_without_writes(self):
        for name in scene_controls.MODELS:
            missing = scene_controls.model_status(name, self.root)
            self.assertFalse(missing["valid"])
            self.assertFalse(missing["installed"])
            self.assertFalse(missing["manual_install_only"])
            self.assertEqual("installer_updater_official_download", missing["installation_method"])
            self.assertIn("비상업·비프로덕션", missing["notice"])
            self.assertIn("원본 데이터 이용 조건", missing["notice"])
            self.assertIn("설치기·업데이터", missing["notice"])
            target = self.root / "models" / "controlnet" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"corrupt fixture")
            result = scene_controls.model_status(name, self.root)
            self.assertTrue(result["installed"])
            self.assertFalse(result["valid"])
            self.assertEqual(hashlib.sha256(b"corrupt fixture").hexdigest(), result["actual_sha256"])
            self.assertEqual(b"corrupt fixture", target.read_bytes())
        with self.assertRaises(ValueError):
            scene_controls.model_status("../other.safetensors", self.root)

    def test_vendor_files_are_limited_to_node_web_directory(self):
        web = self.root / "custom_nodes" / "ComfyUI_toyxyz_test_nodes" / "web"
        web.mkdir(parents=True)
        (web / "editor.js").write_bytes(b"export {};")
        (web / "private.py").write_bytes(b"private")
        (web.parent / "outside.txt").write_bytes(b"outside")
        request = Request("/vendor/toyxyz/editor.js")
        self.assertTrue(scene_controls.handle_get(request, self.root, self.root))
        self.assertEqual(200, request.status)
        self.assertEqual(b"export {};", request.wfile.getvalue())
        for path in ("../outside.txt", "%2e%2e/outside.txt", "private.py", "missing.js"):
            with self.subTest(path=path):
                denied = Request("/vendor/toyxyz/" + path)
                scene_controls.handle_get(denied, self.root, self.root)
                self.assertEqual(404, denied.status)
                self.assertEqual(b"", denied.wfile.getvalue())

    def test_scene_api_retains_existing_origin_authorization(self):
        for method in (serve_ui.Handler.do_GET, serve_ui.Handler.do_POST):
            with self.subTest(method=method.__name__):
                request = Request(data=self.config)
                request._authorize_api_request = lambda: False
                with patch.object(scene_controls, "handle_get") as get, \
                        patch.object(scene_controls, "handle_post") as post:
                    method(request)
                get.assert_not_called()
                post.assert_not_called()

    def test_scene_api_is_connected_without_development_mode(self):
        root = self.root / "installation"
        request = Request(data=self.config)
        request._authorize_api_request = lambda: True
        with patch.object(serve_ui, "DEVELOPMENT", False), \
                patch.object(serve_ui, "UI_STATE_PATH", root / "state.json"), \
                patch.object(serve_ui, "COMFY_ROOT", self.root):
            serve_ui.Handler.do_POST(request)
            self.assertEqual(200, request.status)
            restored = Request()
            restored._authorize_api_request = lambda: True
            serve_ui.Handler.do_GET(restored)
        self.assertEqual(200, restored.status)
        self.assertTrue(restored.response["state"]["toyxyz_enabled"])
        self.assertEqual(
            (REPOSITORY_ROOT / "VERSION").read_text(encoding="utf-8-sig").strip(),
            restored.response["version"],
        )


if __name__ == "__main__":
    unittest.main()
