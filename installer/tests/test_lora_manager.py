"""LoRA profile, routing and inventory regressions without model inference."""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "external_ui"))
import lora_manager as lm
import moss_mode
import serve_ui
import workflow_bridge as bridge
from installer.tests.test_moss_mode import schema, state


class ManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lakis-lora-split-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.loras = self.root / "models" / "loras"
        self.pool = lm.ManagerPool(self.root, [self.loras])
        self.addCleanup(self.pool.close)

    def test_engine_roots_settings_downloads_and_databases_are_separate(self):
        profiles = {}
        for engine in lm.ENGINES:
            directory = self.pool.prepare_profile(engine)
            data = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
            expected = str((self.loras / engine).resolve())
            self.assertEqual(data["folder_paths"]["loras"], [expected])
            self.assertEqual(data["default_lora_root"], expected)
            self.assertEqual(data["active_library"], engine.upper())
            self.assertTrue(Path(data["recipes_path"]).is_relative_to(directory))
            self.assertTrue(Path(data["example_images_path"]).is_relative_to(directory))
            for library in (data, data["libraries"][engine.upper()]):
                if engine == "moss":
                    unet_root = self.root / "models" / "diffusion_models" / "moss"
                    self.assertEqual(library["folder_paths"]["unet"], [str(unet_root)])
                    self.assertEqual(library["default_unet_root"], str(unet_root))
                    self.assertTrue(unet_root.is_dir())
                else:
                    self.assertEqual(library["folder_paths"]["unet"], [])
                    self.assertNotIn("default_unet_root", library)
            profiles[engine] = directory
        self.assertNotEqual(profiles["anima"], profiles["moss"])
        moss = json.loads((profiles["moss"] / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(moss["extra_folder_paths"]["loras"], [])

    def test_existing_moss_profile_adds_only_missing_model_paths(self):
        directory = self.pool.prepare_profile("moss")
        file = directory / "settings.json"
        settings = json.loads(file.read_text(encoding="utf-8"))
        unet_root = self.root / "models" / "diffusion_models" / "moss"
        for library in (settings, settings["libraries"]["MOSS"]):
            library["folder_paths"]["unet"] = [str(self.root / "custom-models")]
            library["folder_paths"]["checkpoints"] = [str(self.root / "custom-checkpoints")]
            library["extra_folder_paths"]["unet"] = [str(self.root / "shared-models")]
            library.pop("default_unet_root")
        settings["libraries"]["MOSS"]["default_unet_root"] = ""
        settings["libraries"]["inactive"] = {
            "folder_paths": {"unet": [str(self.root / "inactive-models")]},
            "default_unet_root": str(self.root / "inactive-models"),
        }
        settings["civitai_api_key"] = "test-only-preserve-auth"
        settings["future_preference"] = {"layout": "compact"}
        expected = deepcopy(settings)
        for library in (expected, expected["libraries"]["MOSS"]):
            library["folder_paths"]["unet"].append(str(unet_root))
            library["default_unet_root"] = str(unet_root)
        file.write_text(json.dumps(settings), encoding="utf-8")

        self.pool.prepare_profile("moss")

        self.assertEqual(json.loads(file.read_text(encoding="utf-8")), expected)
        before = file.read_bytes()
        self.pool.prepare_profile("moss")
        self.assertEqual(file.read_bytes(), before)

    def test_existing_moss_custom_defaults_and_equivalent_paths_are_preserved(self):
        directory = self.pool.prepare_profile("moss")
        file = directory / "settings.json"
        settings = json.loads(file.read_text(encoding="utf-8"))
        unet_root = self.root / "models" / "diffusion_models" / "moss"
        for library in (settings, settings["libraries"]["MOSS"]):
            library["folder_paths"]["unet"] = [str(unet_root) + os.sep + "."]
            library["default_unet_root"] = str(self.root / "custom-models")
        file.write_text(json.dumps(settings), encoding="utf-8")
        before = file.read_bytes()

        self.pool.prepare_profile("moss")

        self.assertEqual(file.read_bytes(), before)

    def test_existing_moss_profile_with_no_unet_key_is_completed(self):
        directory = self.pool.prepare_profile("moss")
        file = directory / "settings.json"
        settings = json.loads(file.read_text(encoding="utf-8"))
        for library in (settings, settings["libraries"]["MOSS"]):
            library["folder_paths"].pop("unet")
            library.pop("default_unet_root")
        file.write_text(json.dumps(settings), encoding="utf-8")

        self.pool.prepare_profile("moss")

        settings = json.loads(file.read_text(encoding="utf-8"))
        expected = str(self.root / "models" / "diffusion_models" / "moss")
        for library in (settings, settings["libraries"]["MOSS"]):
            self.assertEqual(library["folder_paths"]["unet"], [expected])
            self.assertEqual(library["default_unet_root"], expected)

    def test_existing_moss_profile_fills_only_missing_lora_roots(self):
        shared_root = self.root / "shared-models" / "loras"
        pool = lm.ManagerPool(self.root, [self.loras, shared_root])
        self.addCleanup(pool.close)
        directory = pool.prepare_profile("moss")
        file = directory / "settings.json"
        settings = json.loads(file.read_text(encoding="utf-8"))
        for library in (settings, settings["libraries"]["MOSS"]):
            library["folder_paths"].pop("loras")
            library["extra_folder_paths"].pop("loras")
            library.pop("default_lora_root")
        settings["civitai_api_key"] = "test-only-preserve-auth"
        settings["future_preference"] = {"layout": "compact"}
        expected = deepcopy(settings)
        model_root = self.loras / "moss"
        for library in (expected, expected["libraries"]["MOSS"]):
            library["folder_paths"]["loras"] = [str(model_root)]
            library["extra_folder_paths"]["loras"] = [str(shared_root / "moss")]
            library["default_lora_root"] = str(model_root)
        model_root.rmdir()
        file.write_text(json.dumps(settings), encoding="utf-8")

        pool.prepare_profile("moss")

        self.assertEqual(json.loads(file.read_text(encoding="utf-8")), expected)
        self.assertTrue(model_root.is_dir())
        before = file.read_bytes()
        pool.prepare_profile("moss")
        self.assertEqual(file.read_bytes(), before)

    def test_additional_moss_model_reaches_generation_inventory_and_graph(self):
        directory = self.pool.prepare_profile("moss")
        settings = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
        model = Path(settings["default_unet_root"]) / "additional.safetensors"
        model.write_bytes(b"path-only-fixture")
        expected = "moss/additional.safetensors"
        with patch.object(bridge, "COMFY_ROOT", self.root), \
                patch.dict(os.environ, {"LAKIS_SHARED_MODELS_ROOT": ""}):
            names = [name.replace("\\", "/") for name in bridge._model_files("diffusion_models")]
        self.assertEqual(names, [expected])
        info = schema()
        info["UNet loader with Name (Image Saver)"]["input"]["required"]["unet_name"][0] = names
        with patch.object(bridge, "_comfy_object_info", return_value=info):
            self.assertEqual(bridge.model_inventory()["moss"]["inventory"]["checkpoint"], [expected])
        value = state()
        value["model"]["checkpoint"] = expected
        graph, _ = moss_mode.build_prompt(value, info, Path("fixture-output"), 2**53 - 1)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], expected)
        moss_mode.validate_models(graph, info)

    def test_legacy_anima_preferences_and_files_are_not_overwritten_or_moved(self):
        legacy = self.pool.state_root / "settings.json"
        legacy.parent.mkdir(parents=True)
        content = '{"future_preference":{"keep":true},"active_library":"comfyui"}'
        legacy.write_text(content, encoding="utf-8")
        self.loras.mkdir(parents=True)
        model = self.loras / "existing.safetensors"
        model.write_bytes(b"existing-user-file")
        directory = self.pool.prepare_profile("anima")
        settings = directory / "settings.json"
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["future_preference"], {"keep": True})
        before = settings.read_bytes()
        self.pool.prepare_profile("anima")
        self.pool.prepare_profile("moss")
        self.assertEqual(settings.read_bytes(), before)
        self.assertEqual(legacy.read_text(encoding="utf-8"), content)
        self.assertEqual(model.read_bytes(), b"existing-user-file")
        self.assertTrue(lm.file_matches_engine(model, "anima", [self.loras]))
        self.assertFalse(lm.file_matches_engine(model, "moss", [self.loras]))

    def test_legacy_moss_files_cannot_enter_the_anima_scanner(self):
        calls = []

        class Scanner:
            async def _process_model_file(self, path, root, **kwargs):
                calls.append(path)
                return {"file_path": path}

        lm.scope_scanner(Scanner, "anima", [self.loras])
        scanner = Scanner()
        moss = str(self.loras / "MOSS" / "style.safetensors")
        anima = str(self.loras / "legacy.safetensors")
        self.assertIsNone(asyncio.run(scanner._process_model_file(moss, str(self.loras))))
        self.assertEqual(asyncio.run(scanner._process_model_file(anima, str(self.loras))), {"file_path": anima})
        self.assertEqual(calls, [anima])

    def test_scanner_scope_ignores_overlapping_root_order(self):
        nested_root = self.loras / "moss"
        moss_file = nested_root / "style.safetensors"
        roots = [nested_root, self.loras]

        self.assertTrue(lm.file_matches_engine(moss_file, "moss", roots))
        self.assertFalse(lm.file_matches_engine(moss_file, "anima", roots))

    def test_cross_engine_settings_are_rejected_without_rewriting(self):
        directory = self.pool.prepare_profile("moss")
        file = directory / "settings.json"
        data = json.loads(file.read_text(encoding="utf-8"))
        data["default_lora_root"] = str(self.loras / "anima")
        file.write_text(json.dumps(data), encoding="utf-8")
        before = file.read_bytes()
        with self.assertRaises(RuntimeError):
            self.pool.prepare_profile("moss")
        self.assertEqual(file.read_bytes(), before)

    def test_invalid_engine_creates_no_profile(self):
        with self.assertRaises(ValueError):
            self.pool.prepare_profile("../moss")
        self.assertFalse(self.pool.state_root.exists())

    def test_database_environment_overrides_are_not_shared(self):
        with patch.dict(os.environ, {"LORA_MANAGER_CACHE_DB": "foreign.db",
                                    "LORA_MANAGER_RECIPE_FTS_DB": "foreign-fts.db"}):
            env = lm.manager_environment(self.root)
        self.assertNotIn("LORA_MANAGER_CACHE_DB", env)
        self.assertNotIn("LORA_MANAGER_RECIPE_FTS_DB", env)
        self.assertEqual(env["LORA_MANAGER_SETTINGS_DIR"], str(self.root))

    def test_missing_manager_is_reported_instead_of_opening_the_anima_manager(self):
        with self.assertRaisesRegex(RuntimeError, "LoRA Manager"):
            self.pool.manager_url("moss")
        self.assertEqual(self.pool.instances, {})


class MossDownloadRoutingTests(unittest.TestCase):
    setUp = ManagerTests.setUp

    def test_backend_moss_classification_preserves_other_model_families(self):
        from types import SimpleNamespace

        module = self.root / "static" / "js" / "managers" / "DownloadManager.js"
        module.parent.mkdir(parents=True)
        module.write_text(
            "            const _isDiffusionModel = this.selectedFile\n"
            "        return (file.type === 'UNet' || file.type === 'Diffusion Model') ? 'diffusion' : 'model';",
            encoding="utf-8",
        )
        backend = SimpleNamespace(DIFFUSION_MODEL_BASE_MODELS=frozenset({"Anima", "Flux.1 D"}))
        with patch.dict(sys.modules, {"py.services": SimpleNamespace(download_manager=backend)}):
            lm.install_moss_download_routing(Mock(), self.root / "standalone.py")
        self.assertEqual(backend.DIFFUSION_MODEL_BASE_MODELS, {"Anima", "Flux.1 D", "MOSS Image"})

    @unittest.skipUnless(os.environ.get("LAKIS_LORA_MANAGER_TEST_SOURCE"), "Set the bundled standalone.py path for offline UI regression")
    def test_bundled_moss_download_dialog_routes_by_model_type_without_starting_a_manager(self):
        bundled_source = Path(os.environ["LAKIS_LORA_MANAGER_TEST_SOURCE"])
        bundled_module = bundled_source.parent / "static" / "js" / "managers" / "DownloadManager.js"
        module = self.root / "static" / "js" / "managers" / "DownloadManager.js"
        module.parent.mkdir(parents=True)
        module.write_text(bundled_module.read_text(encoding="utf-8"), encoding="utf-8")

        class Router:
            def add_get(self, path, handler):
                self.path = path
                self.handler = handler

        class Response:
            def __init__(self, *, text, content_type, headers):
                self.text = text
                self.content_type = content_type
                self.headers = headers

        router = Router()
        server = type("Server", (), {"app": type("App", (), {"router": router})()})()
        backend = type("Backend", (), {"DIFFUSION_MODEL_BASE_MODELS": frozenset({"Anima", "Flux.1 D"})})()
        web = type("Web", (), {"Response": Response})()
        with patch.dict(sys.modules, {
            "aiohttp": type("Aiohttp", (), {"web": web})(),
            "py.services": type("Services", (), {"download_manager": backend})(),
        }):
            lm.install_moss_download_routing(server, self.root / "standalone.py")
            response = asyncio.run(router.handler(Mock()))

        self.assertEqual(router.path, "/loras_static/js/managers/DownloadManager.js")
        self.assertEqual(backend.DIFFUSION_MODEL_BASE_MODELS,
                         {"Anima", "Flux.1 D", "MOSS Image"})
        module.write_text(response.text, encoding="utf-8")
        env = os.environ.copy()
        env["LAKIS_MOSS_MANAGER_MODULE"] = str(module)
        env["LAKIS_MOSS_TEST_ROOT"] = str(self.root / "models" / "diffusion_models" / "moss")
        env["LAKIS_MOSS_LORA_TEST_ROOT"] = str(self.loras / "moss")
        subprocess.run(
            [
                "node", "--test",
                str(Path(__file__).with_name("test_moss_download_routing.cjs")),
                str(Path(__file__).with_name("test_advanced_settings_commit.cjs")),
            ],
            env=env, check=True,
        )


class RoutingAndInventoryTests(unittest.TestCase):
    def handler(self, path):
        handler = Mock()
        handler.path = path
        handler._authorize_api_request.return_value = True
        return handler

    def test_mode_is_explicit_and_routes_to_its_own_manager(self):
        for engine, port in (("anima", 55111), ("moss", 55112)):
            handler = self.handler(f"/api/lora-manager?engine={engine}")
            target = f"http://127.0.0.1:{port}/loras"
            with patch.object(serve_ui, "lora_manager_url", return_value=target) as manager:
                serve_ui.Handler.do_GET(handler)
            manager.assert_called_once_with(engine)
            handler.send_response.assert_called_once_with(302)
            handler.send_header.assert_any_call("Location", target)
        for query in ("", "?engine=other", "?engine=moss&engine=anima"):
            handler = self.handler("/api/lora-manager" + query)
            with patch.object(serve_ui, "lora_manager_url") as manager:
                serve_ui.Handler.do_GET(handler)
            manager.assert_not_called()
            self.assertEqual(handler._send_json.call_args.args[0], 400)

    def test_denied_origin_does_not_start_a_manager(self):
        handler = self.handler("/api/lora-manager?engine=moss")
        handler._authorize_api_request.return_value = False
        with patch.object(serve_ui, "lora_manager_url") as manager:
            serve_ui.Handler.do_GET(handler)
        manager.assert_not_called()

    def test_moss_download_is_visible_immediately_despite_a_fresh_schema_cache(self):
        old = schema()
        new = schema()
        new["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0].append("moss/downloaded.safetensors")
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(new).encode("utf-8")
        with patch.object(bridge, "_OBJECT_INFO_CACHE", old), \
                patch.object(bridge, "_OBJECT_INFO_CACHE_AT", time.time()), \
                patch.object(bridge, "urlopen", return_value=response) as fetch:
            inventory = bridge.lora_inventory("moss")
        self.assertIn("moss/downloaded.safetensors", inventory["options"])
        fetch.assert_called_once()

    def test_uppercase_windows_moss_folder_remains_isolated_and_applies_to_graph(self):
        info = schema()
        name = "MOSS\\style.safetensors"
        info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0].append(name)
        info["LoraLoader"]["input"]["required"]["lora_name"][0].append(name)
        value = state()
        value["loras"] = [{"name": name, "enabled": True, "strength": 0.7}]
        with patch.object(bridge, "_comfy_object_info", return_value=info):
            self.assertIn(name, bridge.lora_inventory("moss")["options"])
            self.assertNotIn(name, bridge.lora_inventory("anima")["options"])
        graph, _ = moss_mode.build_prompt(value, info, Path("fixture-output"), 2**53 - 1)
        self.assertTrue(any(node.get("inputs", {}).get("lora_name") == name for node in graph.values()))
        moss_mode.validate_models(graph, info)


@unittest.skipUnless(os.environ.get("LAKIS_LORA_MANAGER_TEST_SOURCE"), "Set the bundled standalone.py path for isolated integration")
class BundledManagerTests(unittest.TestCase):
    setUp = ManagerTests.setUp

    def test_real_bundled_pages_ports_and_download_roots_are_separate(self):
        self.pool.source = Path(os.environ["LAKIS_LORA_MANAGER_TEST_SOURCE"])
        urls = {engine: self.pool.manager_url(engine) for engine in lm.ENGINES}
        self.assertNotEqual(urls["anima"], urls["moss"])
        for engine, url in urls.items():
            with urlopen(url, timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers["Content-Type"])
            with urlopen(url.replace("/loras", "/api/lm/loras/roots"), timeout=10) as response:
                roots = json.load(response)
            self.assertIn(str((self.loras / engine).resolve()).replace("\\", "/"),
                          json.dumps(roots).replace("\\\\", "/"))
            self.assertEqual(self.pool.manager_url(engine), url)
        processes = [instance["process"] for instance in self.pool.instances.values()]
        self.pool.close()
        self.assertTrue(all(process.poll() is not None for process in processes))


if __name__ == "__main__":
    unittest.main()
