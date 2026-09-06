from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_UI_ROOT = REPOSITORY_ROOT / "src" / "external_ui"
sys.path.insert(0, str(EXTERNAL_UI_ROOT))

import workflow_bridge  # noqa: E402
import serve_ui  # noqa: E402


def _record(choice: str, *, acknowledged: bool = False) -> dict:
    model = workflow_bridge.UPSCALER_MODELS[choice]
    return {
        "choice": choice,
        "model": model,
        "license": "CC-BY-NC-SA-4.0" if choice == "animesharp" else "BSD-3-Clause",
        "noncommercial_acknowledged": acknowledged,
    }


class UpscalerChoiceStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.comfy = self.root / "ComfyUI"
        self.user_choice = self.root / "user" / "upscaler-license-choice.json"
        self.legacy_choice = self.root / "install" / ".lakis" / "upscaler-license-choice.json"
        self.patches = (
            patch.object(workflow_bridge, "COMFY_ROOT", self.comfy),
            patch.object(workflow_bridge, "UPSCALER_CHOICE_PATH", self.user_choice),
            patch.object(workflow_bridge, "LEGACY_UPSCALER_CHOICE_PATH", self.legacy_choice),
        )
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temporary.cleanup()

    def _install_model(self, model: str) -> None:
        path = self.comfy / "models" / "upscale_models" / model
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test-model")

    def _write(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_valid_realesrgan_choice_requires_model_file(self) -> None:
        self._write(self.user_choice, _record("realesrgan"))
        missing = workflow_bridge.upscaler_choice_status()
        self.assertTrue(missing["required"])
        self.assertEqual("selected_model_missing", missing["reason"])

        self._install_model(workflow_bridge.REALESRGAN_MODEL)
        valid = workflow_bridge.upscaler_choice_status()
        self.assertFalse(valid["required"])
        self.assertEqual(workflow_bridge.REALESRGAN_MODEL, valid["model"])

    def test_animesharp_choice_requires_explicit_acknowledgement(self) -> None:
        self._install_model(workflow_bridge.ANIMESHARP_MODEL)
        self._write(self.user_choice, _record("animesharp", acknowledged=False))
        missing_ack = workflow_bridge.upscaler_choice_status()
        self.assertTrue(missing_ack["required"])
        self.assertEqual("licence_acknowledgement_required", missing_ack["reason"])

        self._write(self.user_choice, _record("animesharp", acknowledged=True))
        valid = workflow_bridge.upscaler_choice_status()
        self.assertFalse(valid["required"])
        self.assertEqual(workflow_bridge.ANIMESHARP_MODEL, valid["model"])

    def test_stale_user_record_never_falls_back_to_legacy_choice(self) -> None:
        self._install_model(workflow_bridge.ANIMESHARP_MODEL)
        self._write(self.user_choice, _record("realesrgan"))
        self._write(self.legacy_choice, _record("animesharp", acknowledged=True))

        status = workflow_bridge.upscaler_choice_status()
        self.assertTrue(status["required"])
        self.assertEqual("selected_model_missing", status["reason"])

    def test_record_model_must_match_choice(self) -> None:
        self._install_model(workflow_bridge.REALESRGAN_MODEL)
        mismatched = _record("realesrgan")
        mismatched["model"] = workflow_bridge.ANIMESHARP_MODEL
        self._write(self.user_choice, mismatched)
        status = workflow_bridge.upscaler_choice_status()
        self.assertTrue(status["required"])
        self.assertEqual("invalid_record", status["reason"])


class UpscalerOverrideTests(unittest.TestCase):
    def test_advanced_override_cannot_replace_licence_choice(self) -> None:
        prompt = {
            workflow_bridge.UPSCALER_NODE_ID: {
                "class_type": "UpscaleModelLoader",
                "inputs": {workflow_bridge.UPSCALER_FIELD_NAME: workflow_bridge.REALESRGAN_MODEL},
            }
        }
        requested = {
            workflow_bridge.UPSCALER_NODE_ID: {
                workflow_bridge.UPSCALER_FIELD_NAME: workflow_bridge.ANIMESHARP_MODEL,
            }
        }
        with patch.object(workflow_bridge, "_comfy_object_info", return_value={}):
            workflow_bridge._apply_advanced_node_overrides(prompt, requested)
        self.assertEqual(
            workflow_bridge.REALESRGAN_MODEL,
            prompt[workflow_bridge.UPSCALER_NODE_ID]["inputs"][workflow_bridge.UPSCALER_FIELD_NAME],
        )

    def test_upscaler_override_is_not_retained_for_restart(self) -> None:
        requested = {
            workflow_bridge.UPSCALER_NODE_ID: {
                workflow_bridge.UPSCALER_FIELD_NAME: workflow_bridge.ANIMESHARP_MODEL,
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            template = Path(temporary) / "template.json"
            template.write_text(json.dumps({
                workflow_bridge.UPSCALER_NODE_ID: {
                    "class_type": "UpscaleModelLoader",
                    "inputs": {workflow_bridge.UPSCALER_FIELD_NAME: workflow_bridge.REALESRGAN_MODEL},
                }
            }), encoding="utf-8")
            with (
                patch.object(workflow_bridge, "TEMPLATE", template),
                patch.object(workflow_bridge, "_comfy_object_info", return_value={}),
            ):
                self.assertEqual({}, workflow_bridge._clean_advanced_node_overrides(requested))

    def test_saving_choice_removes_existing_persisted_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            comfy = root / "ComfyUI"
            model_path = comfy / "models" / "upscale_models" / workflow_bridge.ANIMESHARP_MODEL
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(b"test-model")
            state_path = root / "user" / "external_ui_user_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({
                "version": 2,
                "node_overrides": {
                    workflow_bridge.UPSCALER_NODE_ID: {
                        workflow_bridge.UPSCALER_FIELD_NAME: workflow_bridge.REALESRGAN_MODEL,
                    },
                    "2138": {"value": True},
                },
            }), encoding="utf-8")
            choice_path = root / "user" / "upscaler-license-choice.json"
            with (
                patch.object(serve_ui, "COMFY_ROOT", comfy),
                patch.object(serve_ui, "UPSCALER_CHOICE_PATH", choice_path),
                patch.object(serve_ui, "PACKAGED_WORKFLOW_ROOT", root / "workflows"),
                patch.object(workflow_bridge, "UI_STATE_PATH", state_path),
                patch.object(workflow_bridge, "LEGACY_UI_STATE_PATH", root / "legacy-state.json"),
            ):
                result = serve_ui.save_upscaler_choice({"choice": "animesharp", "acknowledged": True})

            self.assertTrue(result["advanced_override_removed"])
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotIn(workflow_bridge.UPSCALER_NODE_ID, saved_state["node_overrides"])
            self.assertEqual({"value": True}, saved_state["node_overrides"]["2138"])
            saved_choice = json.loads(choice_path.read_text(encoding="utf-8"))
            self.assertTrue(saved_choice["noncommercial_acknowledged"])

    def test_serve_ui_uses_the_validated_bridge_status(self) -> None:
        self.assertIs(serve_ui.upscaler_choice_status, workflow_bridge.upscaler_choice_status)


if __name__ == "__main__":
    unittest.main()
