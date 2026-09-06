from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_UI_ROOT = REPOSITORY_ROOT / "src" / "external_ui"
sys.path.insert(0, str(EXTERNAL_UI_ROOT))

# This unit test exercises only the state-path helpers. GitHub's clean Python
# runner does not include the runtime-only aiohttp dependency, so provide an
# inert import stub rather than downloading application dependencies in CI.
try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    sys.modules["aiohttp"] = types.ModuleType("aiohttp")

import workflow_bridge  # noqa: E402


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class ScopedUiStateMigrationTests(unittest.TestCase):
    def test_install_legacy_state_wins_over_unscoped_global_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scoped = root / "scoped" / "external_ui_user_state.json"
            legacy = root / "install" / "ComfyUI" / "LAKIS_DEV" / "external_ui_user_state.json"
            global_state = root / "localappdata" / "LAKIS Studio" / "external_ui_user_state.json"
            legacy_payload = {
                "prompt": {"general": "main-install-prompt"},
                "lora": {"current": [{"name": f"lora-{index}"} for index in range(7)]},
            }
            global_payload = {
                "prompt": {"general": "test-install-prompt"},
                "lora": {"current": []},
            }
            _write(legacy, legacy_payload)
            _write(global_state, global_payload)

            with (
                patch.object(workflow_bridge, "UI_STATE_PATH", scoped),
                patch.object(workflow_bridge, "LEGACY_UI_STATE_PATH", legacy),
                patch.object(workflow_bridge, "UNSCOPED_UI_STATE_PATH", global_state),
            ):
                migrated = workflow_bridge._load_external_ui_payload()

            self.assertEqual("main-install-prompt", migrated["prompt"]["general"])
            self.assertEqual(7, len(migrated["lora"]["current"]))
            self.assertEqual(legacy_payload, json.loads(scoped.read_text(encoding="utf-8")))

    def test_unscoped_global_is_fallback_when_install_has_no_legacy_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scoped = root / "scoped" / "external_ui_user_state.json"
            legacy = root / "missing-legacy.json"
            global_state = root / "global" / "external_ui_user_state.json"
            global_payload = {"prompt": {"general": "only-existing-state"}}
            _write(global_state, global_payload)

            with (
                patch.object(workflow_bridge, "UI_STATE_PATH", scoped),
                patch.object(workflow_bridge, "LEGACY_UI_STATE_PATH", legacy),
                patch.object(workflow_bridge, "UNSCOPED_UI_STATE_PATH", global_state),
            ):
                migrated = workflow_bridge._load_external_ui_payload()

            self.assertEqual(global_payload, migrated)
            self.assertEqual(global_payload, json.loads(scoped.read_text(encoding="utf-8")))

    def test_existing_scoped_state_remains_authoritative_after_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scoped = root / "scoped" / "external_ui_user_state.json"
            legacy = root / "legacy.json"
            global_state = root / "global.json"
            _write(scoped, {"prompt": {"general": "scoped"}})
            _write(legacy, {"prompt": {"general": "legacy-changed"}})
            _write(global_state, {"prompt": {"general": "global-changed"}})

            with (
                patch.object(workflow_bridge, "UI_STATE_PATH", scoped),
                patch.object(workflow_bridge, "LEGACY_UI_STATE_PATH", legacy),
                patch.object(workflow_bridge, "UNSCOPED_UI_STATE_PATH", global_state),
            ):
                loaded = workflow_bridge._load_external_ui_payload()

            self.assertEqual("scoped", loaded["prompt"]["general"])


class ScopedUiStateIsolationTests(unittest.TestCase):
    def test_install_paths_receive_distinct_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user_root = root / "localappdata" / "LAKIS Studio"
            path_a = workflow_bridge._ui_state_path_for_install(root / "main-install", user_root)
            path_b = workflow_bridge._ui_state_path_for_install(root / "test-install", user_root)

            self.assertNotEqual(path_a, path_b)
            self.assertEqual(path_a.name, "external_ui_user_state.json")
            self.assertEqual(path_b.name, "external_ui_user_state.json")
            self.assertEqual(path_a.parent.parent, user_root / "installations")
            self.assertEqual(path_b.parent.parent, user_root / "installations")

    def test_each_install_persists_and_reloads_its_own_loras_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user_root = root / "localappdata" / "LAKIS Studio"
            state_a = workflow_bridge._ui_state_path_for_install(root / "main-install", user_root)
            state_b = workflow_bridge._ui_state_path_for_install(root / "test-install", user_root)
            missing_legacy = root / "missing-legacy.json"
            missing_global = root / "missing-global.json"

            def save(path: Path, checkpoint: str, lora: str, width: int) -> None:
                with (
                    patch.object(workflow_bridge, "UI_STATE_PATH", path),
                    patch.object(workflow_bridge, "LEGACY_UI_STATE_PATH", missing_legacy),
                    patch.object(workflow_bridge, "UNSCOPED_UI_STATE_PATH", missing_global),
                    patch.object(workflow_bridge, "_enum_options", side_effect=lambda _c, _n, fallback=(), _o=None: list(fallback)),
                    patch.object(workflow_bridge, "_clean_advanced_node_overrides", return_value={}),
                ):
                    workflow_bridge.save_external_generation_state(
                        {
                            "checkpoint": checkpoint,
                            "sampler": "euler_ancestral",
                            "scheduler": "normal",
                            "steps": 30,
                            "cfg": 5.0,
                        },
                        {"width": width, "height": 1024, "seed": 1, "seed_mode": "fixed"},
                        [{"name": lora, "enabled": True, "strength": 0.75}],
                        True,
                        {},
                    )

            save(state_a, "main.safetensors", "main-lora.safetensors", 1536)
            save(state_b, "test.safetensors", "test-lora.safetensors", 1024)

            payload_a = json.loads(state_a.read_text(encoding="utf-8"))
            payload_b = json.loads(state_b.read_text(encoding="utf-8"))
            self.assertEqual("main.safetensors", payload_a["model"]["checkpoint"])
            self.assertEqual("main-lora.safetensors", payload_a["lora"]["current"][0]["name"])
            self.assertEqual(1536, payload_a["output"]["width"])
            self.assertEqual("test.safetensors", payload_b["model"]["checkpoint"])
            self.assertEqual("test-lora.safetensors", payload_b["lora"]["current"][0]["name"])
            self.assertEqual(1024, payload_b["output"]["width"])

            with (
                patch.object(workflow_bridge, "UI_STATE_PATH", state_a),
                patch.object(workflow_bridge, "LEGACY_UI_STATE_PATH", missing_legacy),
                patch.object(workflow_bridge, "UNSCOPED_UI_STATE_PATH", missing_global),
            ):
                reloaded_a = workflow_bridge._load_external_ui_payload()
            self.assertEqual(payload_a, reloaded_a)


if __name__ == "__main__":
    unittest.main()
