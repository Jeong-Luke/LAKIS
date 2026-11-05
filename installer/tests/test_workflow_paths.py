"""Focused path, API routing, and marker tests for sidebar workflow opening."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_MISSING = object()


def _make_workflow_bridge_stub() -> types.ModuleType:
    """Stub only the unrelated bridge while importing this test's serve_ui."""
    bridge_stub = types.ModuleType("workflow_bridge")

    class _WorkflowBridge:
        def __init__(self) -> None:
            self.status = types.SimpleNamespace(snapshot=lambda: {})

    def unused_bridge_api(*args, **kwargs):
        return None

    bridge_stub.InvalidGenerationRequestError = type("InvalidGenerationRequestError", (Exception,), {})
    bridge_stub.LOCAL_INPAINT_V2 = "test-inpaint-model"
    bridge_stub.WorkflowBridge = _WorkflowBridge
    for name in (
        "lora_inventory",
        "model_inventory",
        "remove_persisted_upscaler_override",
        "save_external_generation_state",
        "save_external_prompt_state",
        "load_external_prompt_bundle",
        "upscaler_choice_status",
        "workflow_configuration",
    ):
        setattr(bridge_stub, name, unused_bridge_api)
    bridge_stub.UI_STATE_PATH = Path(tempfile.gettempdir()) / "lakis-workflow-path-test-state.json"
    return bridge_stub


def _restore_module(name: str, previous: object) -> None:
    if previous is _MISSING:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = previous


def _import_test_serve_ui():
    """Import the target module with a temporary bridge stub, restoring caches."""
    previous_bridge = sys.modules.get("workflow_bridge", _MISSING)
    previous_serve_ui = sys.modules.get("serve_ui", _MISSING)
    external_ui_path = str(ROOT / "src" / "external_ui")
    add_path = external_ui_path not in sys.path
    try:
        if add_path:
            sys.path.insert(0, external_ui_path)
        sys.modules["workflow_bridge"] = _make_workflow_bridge_stub()
        sys.modules.pop("serve_ui", None)
        return importlib.import_module("serve_ui")
    finally:
        _restore_module("workflow_bridge", previous_bridge)
        _restore_module("serve_ui", previous_serve_ui)
        if add_path:
            sys.path.remove(external_ui_path)


def _import_test_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(__file__).resolve())
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load test module from {__file__}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name, _MISSING)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        _restore_module(module_name, previous)


serve_ui = _import_test_serve_ui()


SOURCE_API_NAME = serve_ui.RUNTIME_LAKIS_WORKFLOW.name
SOURCE_EDITABLE_NAME = serve_ui.EDITABLE_LAKIS_WORKFLOW.name
SOURCE_PREFERRED_NAME = serve_ui.PREFERRED_LAKIS_WORKFLOW.name
CANONICAL_WORKFLOW_ROOT = ROOT / "workflows"


def api_fixture() -> dict:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "fixture.safetensors"},
        }
    }


def editable_fixture() -> dict:
    return {
        "last_node_id": 1,
        "nodes": [{"id": 1, "type": "CheckpointLoaderSimple"}],
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorkflowPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package_root = self.root / "packaged"
        self.personal_root = self.root / "personal"
        self.package_root.mkdir()
        self.personal_root.mkdir()
        self.api_path = self.package_root / "LAKIS_runtime_api_v8.0.json"
        self.editable_path = self.package_root / "LAKIS_custom_v8.0_editable.json"
        self.marker_path = (
            self.root / "custom_nodes" / "ComfyUI-LAKIS-AutoPatch" / "startup_workflow.json"
        )

        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(serve_ui, "PACKAGED_WORKFLOW_ROOT", self.package_root))
        self.patches.enter_context(patch.object(serve_ui, "WORKFLOW_ROOT", self.personal_root))
        self.patches.enter_context(patch.object(serve_ui, "PREFERRED_LAKIS_WORKFLOW", self.api_path))
        self.patches.enter_context(patch.object(serve_ui, "RUNTIME_LAKIS_WORKFLOW", self.api_path))
        self.patches.enter_context(patch.object(serve_ui, "RUNTIME_LAKIS_SOURCE_NAME", self.api_path.name))
        self.patches.enter_context(patch.object(serve_ui, "EDITABLE_LAKIS_WORKFLOW", self.editable_path))
        self.patches.enter_context(patch.object(serve_ui, "AUTOPATCH_MARKER", self.marker_path))
        self.patches.enter_context(patch.object(serve_ui, "upscaler_choice_status", return_value={"choice": None}))
        self.patches.enter_context(patch.object(serve_ui, "audit"))

    def write_templates(self) -> None:
        self.api_path.write_text(json.dumps(api_fixture()), encoding="utf-8")
        self.editable_path.write_text(json.dumps(editable_fixture()), encoding="utf-8")

    @staticmethod
    def handler() -> serve_ui.Handler:
        return serve_ui.Handler.__new__(serve_ui.Handler)

    def test_packaged_constants_name_v80_templates(self) -> None:
        self.assertEqual(SOURCE_API_NAME, "LAKIS_runtime_api_v8.0.json")
        self.assertEqual(SOURCE_PREFERRED_NAME, "LAKIS_runtime_api_v8.0.json")
        self.assertEqual(SOURCE_EDITABLE_NAME, "LAKIS_custom_v8.0_editable.json")

    def test_installed_resource_bundle_imports_without_source_checkout(self) -> None:
        install = self.root / "installed"
        ui = install / "ComfyUI" / "LAKIS" / "external_ui"
        shutil.copytree(ROOT / "src" / "external_ui", ui,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (ui / "runtime").mkdir()
        shutil.copy2(ROOT / "src" / "runtime" / "native_workflow.py",
                     ui / "runtime" / "native_workflow.py")
        legacy_helper = ui.parent / "runtime"
        legacy_helper.mkdir()
        (legacy_helper / "native_workflow.py").write_text(
            'raise RuntimeError("Unmanaged helper must not override packaged resources")',
            encoding="utf-8")
        bundled = ui / "workflows"
        bundled.mkdir()
        for name in (SOURCE_API_NAME, SOURCE_EDITABLE_NAME, "LAKIS_runtime_visual_v8.0.json"):
            shutil.copy2(CANONICAL_WORKFLOW_ROOT / name, bundled / name)
        personal = install / "ComfyUI" / "user" / "default" / "workflows"
        personal.mkdir(parents=True)
        saved = personal / "LAKIS_custom_v7.4_editable.json"
        saved.write_text("personal workflow sentinel", encoding="utf-8")
        before = sha256(saved)
        code = """
import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import serve_ui,workflow_bridge,native_workflow
api,_ = serve_ui.resolve_lakis_workflow("api")
editable,_ = serve_ui.resolve_lakis_workflow("editable")
print(json.dumps({"api":str(api),"editable":str(editable),
    "template":str(workflow_bridge.TEMPLATE),"helper":native_workflow.__file__}))
"""
        environment = dict(os.environ, LOCALAPPDATA=str(self.root / "state"))
        result = subprocess.run([sys.executable, "-c", code, str(ui)], env=environment,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(bundled / SOURCE_API_NAME, Path(observed["api"]))
        self.assertEqual(bundled / SOURCE_EDITABLE_NAME, Path(observed["editable"]))
        self.assertEqual(bundled / SOURCE_API_NAME, Path(observed["template"]))
        self.assertEqual(ui / "runtime" / "native_workflow.py", Path(observed["helper"]))
        self.assertEqual(before, sha256(saved))

    def test_import_isolation_preserves_and_allows_real_workflow_bridge(self) -> None:
        real_bridge_path = ROOT / "src" / "external_ui" / "workflow_bridge.py"
        external_ui_path = str(real_bridge_path.parent)

        # Run discovery-style imports in the same process with no prior bridge
        # module, then verify Python imports the real source rather than a stub.
        with patch.dict(sys.modules):
            sys.modules.pop("workflow_bridge", None)
            sys.modules.pop("serve_ui", None)
            sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
            discovered_test = _import_test_module("_isolated_workflow_paths_import")
            self.assertNotIn("workflow_bridge", sys.modules)
            self.assertNotIn("serve_ui", sys.modules)

            add_path = external_ui_path not in sys.path
            if add_path:
                sys.path.insert(0, external_ui_path)
            try:
                real_bridge = importlib.import_module("workflow_bridge")
            finally:
                if add_path:
                    sys.path.remove(external_ui_path)
            self.assertEqual(Path(real_bridge.__file__).resolve(), real_bridge_path.resolve())
            self.assertIs(importlib.import_module("workflow_bridge"), real_bridge)

            # Existing module objects must also survive importing the test.
            existing_serve_ui = types.ModuleType("serve_ui")
            sys.modules["serve_ui"] = existing_serve_ui
            repeated_test = _import_test_module("_isolated_workflow_paths_import_again")
            self.assertIs(sys.modules["workflow_bridge"], real_bridge)
            self.assertIs(sys.modules["serve_ui"], existing_serve_ui)
            self.assertIs(importlib.import_module("workflow_bridge"), real_bridge)
            self.assertIsNot(discovered_test.serve_ui, existing_serve_ui)
            self.assertIsNot(repeated_test.serve_ui, existing_serve_ui)

    def test_api_and_editable_select_separate_templates_and_marker_formats(self) -> None:
        self.write_templates()
        handler = self.handler()

        api_result = handler._prepare_lakis_workflow("api")
        self.assertEqual(api_result["workflow_kind"], "api")
        self.assertEqual(api_result["workflow_name"], self.api_path.name)
        api_marker = json.loads(self.marker_path.read_text(encoding="utf-8"))
        self.assertEqual(api_marker["lakis_autopatch"]["format"], "api")
        self.assertEqual(api_marker["lakis_autopatch"]["display_name"], self.api_path.name)
        self.assertEqual(api_marker["workflow"], api_fixture())

        editable_result = handler._prepare_lakis_workflow("editable")
        self.assertEqual(editable_result["workflow_kind"], "editable")
        self.assertEqual(editable_result["workflow_name"], self.editable_path.name)
        editable_marker = json.loads(self.marker_path.read_text(encoding="utf-8"))
        self.assertEqual(editable_marker["lakis_autopatch"]["format"], "workflow")
        self.assertEqual(editable_marker["lakis_autopatch"]["display_name"], self.editable_path.name)
        self.assertEqual(editable_marker["workflow"], editable_fixture())

    def test_default_and_runtime_alias_normalize_to_api(self) -> None:
        self.write_templates()
        self.assertEqual(serve_ui.resolve_lakis_workflow()[0], self.api_path)
        self.assertEqual(serve_ui.resolve_lakis_workflow("runtime")[0], self.api_path)

        result = self.handler()._prepare_lakis_workflow("runtime")
        marker = json.loads(self.marker_path.read_text(encoding="utf-8"))
        self.assertEqual(result["workflow_kind"], "api")
        self.assertEqual(marker["lakis_autopatch"]["format"], "api")
        self.assertEqual(marker["lakis_autopatch"]["display_name"], self.api_path.name)

        default_result = self.handler()._prepare_lakis_workflow()
        self.assertEqual(default_result["workflow_kind"], "api")

    def test_moss_templates_and_metadata_are_separate_from_anima_and_personal_files(self) -> None:
        self.write_templates()
        before_anima = (self.api_path.read_bytes(), self.editable_path.read_bytes())
        for kind, name in (
            ("api", serve_ui.moss_workflows.API_NAME),
            ("editable", serve_ui.moss_workflows.EDITABLE_NAME),
        ):
            source = CANONICAL_WORKFLOW_ROOT / name
            packaged = self.package_root / name
            shutil.copyfile(source, packaged)
            personal = self.personal_root / name
            personal.write_bytes(b"owner's edited workflow")
            before = packaged.read_bytes()
            with patch.object(serve_ui, "upscaler_choice_status") as anima_settings:
                result = self.handler()._prepare_lakis_workflow(kind, "moss")
            anima_settings.assert_not_called()
            marker = json.loads(self.marker_path.read_bytes())
            self.assertEqual(marker["workflow"], json.loads(before))
            self.assertEqual(result["workflow_name"], name)
            self.assertEqual(result["generation_engine"], "moss")
            self.assertIn("engine=moss", result["download_url"])
            self.assertEqual(packaged.read_bytes(), before)
            self.assertEqual(personal.read_bytes(), b"owner's edited workflow")
        self.assertEqual((self.api_path.read_bytes(), self.editable_path.read_bytes()), before_anima)

    def test_moss_history_reads_shared_controls_instead_of_link_identifiers(self) -> None:
        graph = serve_ui.moss_mode.base_graph(
            seed=872, positive="a ceramic cup", negative="blur")
        metadata = serve_ui._prompt_graph_metadata(graph)
        self.assertEqual(metadata["engine"], "moss")
        self.assertEqual(metadata["checkpoint"], "moss_image_sft_int8_convrot.safetensors")
        self.assertEqual(metadata["seed"], 872)
        self.assertEqual(metadata["prompt"], "a ceramic cup")
        self.assertEqual(metadata["negative_prompt"], "blur")

    def test_actual_http_download_and_open_route_keep_engine_and_format(self) -> None:
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        self.write_templates()
        for name in (serve_ui.moss_workflows.API_NAME, serve_ui.moss_workflows.EDITABLE_NAME):
            shutil.copyfile(CANONICAL_WORKFLOW_ROOT / name, self.package_root / name)
        server = serve_ui.ThreadingHTTPServer(("127.0.0.1", 0), serve_ui.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            for engine in ("anima", "moss"):
                for kind in ("api", "editable"):
                    expected_path, expected = serve_ui.resolve_lakis_workflow(kind, engine)
                    with urlopen(base + f"/api/workflow-download?engine={engine}&kind={kind}", timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(expected_path.name, response.headers["Content-Disposition"])
                        self.assertEqual(json.load(response), expected)
                    request = Request(base + "/api/open-workflow",
                        data=json.dumps({"engine": engine, "kind": kind}).encode(),
                        headers={"Content-Type": "application/json"})
                    with patch.object(serve_ui.scene_controls, "handle_post", return_value=False), \
                            urlopen(request, timeout=5) as response:
                        opened = json.load(response)
                    self.assertEqual(opened["workflow_name"], expected_path.name)
                    self.assertEqual(opened["generation_engine"], engine)
                    self.assertEqual(json.loads(self.marker_path.read_bytes())["workflow"], expected)
            before = self.marker_path.read_bytes()
            (self.package_root / serve_ui.moss_workflows.API_NAME).unlink()
            with self.assertRaises(HTTPError) as raised:
                urlopen(base + "/api/workflow-download?engine=moss&kind=api", timeout=5)
            self.assertEqual(raised.exception.code, 500)
            self.assertEqual(json.load(raised.exception)["code"], "LKS-MOSS-1010")
            with self.assertRaises(HTTPError) as raised:
                urlopen(base + "/api/workflow-download?engine=../anima&kind=api", timeout=5)
            self.assertEqual(raised.exception.code, 400)
            self.assertEqual(self.marker_path.read_bytes(), before)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

    def test_missing_or_invalid_api_never_falls_back_and_preserves_marker(self) -> None:
        self.editable_path.write_text(json.dumps(editable_fixture()), encoding="utf-8")
        (self.package_root / "LAKIS_runtime_visual_v8.0.json").write_text(
            json.dumps({"nodes": []}), encoding="utf-8"
        )
        (self.package_root / "LAKIS_runtime_api_v7.4.json").write_text(
            json.dumps(api_fixture()), encoding="utf-8"
        )
        self.marker_path.parent.mkdir(parents=True)
        previous_marker = b'{"previous":"marker"}'
        self.marker_path.write_bytes(previous_marker)

        with self.assertRaises(FileNotFoundError):
            self.handler()._prepare_lakis_workflow("api")
        self.assertEqual(self.marker_path.read_bytes(), previous_marker)
        self.assertFalse(self.marker_path.with_suffix(".tmp").exists())

        self.api_path.write_text(
            json.dumps({"nodes": [{"id": 1, "type": "KSampler"}]}), encoding="utf-8"
        )
        with self.assertRaises(FileNotFoundError):
            self.handler()._prepare_lakis_workflow()
        self.assertEqual(self.marker_path.read_bytes(), previous_marker)

    def test_unknown_and_malformed_workflow_kinds_are_rejected(self) -> None:
        self.write_templates()
        for kind in ("visual", "unknown", ["api"]):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    serve_ui.resolve_lakis_workflow(kind)  # type: ignore[arg-type]

    def test_allowed_root_validation_is_preserved(self) -> None:
        self.write_templates()
        outside = self.root / "outside" / self.api_path.name
        outside.parent.mkdir()
        outside.write_text(json.dumps(api_fixture()), encoding="utf-8")
        with patch.object(serve_ui, "RUNTIME_LAKIS_WORKFLOW", outside):
            with self.assertRaises(FileNotFoundError):
                serve_ui.resolve_lakis_workflow("api")

    def test_explicit_legacy_editable_fallback_remains_available(self) -> None:
        legacy = self.personal_root / "LAKIS_custom_v7.1_fullsync_review.json"
        legacy.write_text(json.dumps(editable_fixture()), encoding="utf-8")

        resolved_path, resolved_workflow = serve_ui.resolve_lakis_workflow("editable")
        self.assertEqual(resolved_path, legacy)
        self.assertEqual(resolved_workflow, editable_fixture())

    def test_actual_post_route_defaults_aliases_and_rejects_unknown_kind(self) -> None:
        self.write_templates()
        handler = self.handler()

        def post(incoming: dict):
            responses = []
            request = type(
                "WorkflowRequest",
                (),
                {
                    "path": "/api/open-workflow",
                    "_authorize_api_request": lambda self: True,
                    "_read_json": lambda self: incoming,
                    "_prepare_lakis_workflow": lambda self, kind, engine: handler._prepare_lakis_workflow(kind, engine),
                    "_send_json": lambda self, status, body: responses.append((status, body)),
                },
            )()
            with patch.object(serve_ui.scene_controls, "handle_post", return_value=False):
                serve_ui.Handler.do_POST(request)
            return responses

        status, body = post({})[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["workflow_kind"], "api")
        self.assertEqual(body["workflow_name"], self.api_path.name)

        status, body = post({"kind": "runtime"})[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["workflow_kind"], "api")

        status, body = post({"kind": "editable"})[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["workflow_kind"], "editable")

        previous_marker = self.marker_path.read_bytes()
        status, body = post({"kind": "not-a-kind"})[0]
        self.assertEqual(status, 500)
        self.assertFalse(body["ok"])
        self.assertEqual(self.marker_path.read_bytes(), previous_marker)

    def test_existing_v74_workflow_files_are_not_modified(self) -> None:
        legacy_paths = (
            CANONICAL_WORKFLOW_ROOT / "LAKIS_runtime_api_v7.4.json",
            CANONICAL_WORKFLOW_ROOT / "LAKIS_runtime_visual_v7.4.json",
            CANONICAL_WORKFLOW_ROOT / "LAKIS_custom_v7.4_editable.json",
        )
        before = {
            path: (path.exists(), sha256(path) if path.is_file() else None)
            for path in legacy_paths
        }
        self.write_templates()
        self.handler()._prepare_lakis_workflow("api")
        self.handler()._prepare_lakis_workflow("editable")
        after = {
            path: (path.exists(), sha256(path) if path.is_file() else None)
            for path in legacy_paths
        }
        self.assertEqual(after, before)
        self.assertTrue(all(existed for existed, _ in before.values()))

    def test_real_canonical_api_template_when_present(self) -> None:
        path = CANONICAL_WORKFLOW_ROOT / "LAKIS_runtime_api_v8.0.json"
        if not path.is_file():
            self.skipTest("workflow agent has not produced the canonical v8.0 API template")
        with (
            patch.object(serve_ui, "PACKAGED_WORKFLOW_ROOT", CANONICAL_WORKFLOW_ROOT),
            patch.object(serve_ui, "RUNTIME_LAKIS_WORKFLOW", path),
        ):
            resolved_path, workflow = serve_ui.resolve_lakis_workflow("api")
        self.assertEqual(resolved_path, path)
        self.assertTrue(workflow)
        self.assertTrue(all(isinstance(node.get("class_type"), str) for node in workflow.values()))

    def test_real_canonical_editable_template_when_present(self) -> None:
        path = CANONICAL_WORKFLOW_ROOT / "LAKIS_custom_v8.0_editable.json"
        if not path.is_file():
            self.skipTest("workflow agent has not produced the canonical v8.0 editable template")
        with (
            patch.object(serve_ui, "PACKAGED_WORKFLOW_ROOT", CANONICAL_WORKFLOW_ROOT),
            patch.object(serve_ui, "EDITABLE_LAKIS_WORKFLOW", path),
        ):
            resolved_path, workflow = serve_ui.resolve_lakis_workflow("editable")
        self.assertEqual(resolved_path, path)
        self.assertIsInstance(workflow.get("nodes"), list)


if __name__ == "__main__":
    unittest.main()
