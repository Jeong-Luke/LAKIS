import hashlib
import importlib.util
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "installer" / "lakis_cmd_installer.py"
MANIFEST = ROOT / "installer" / "cmd-installer-manifest.json"
CMD = ROOT / "installer" / "LAKIS_CMD_Install.cmd"
spec = importlib.util.spec_from_file_location("lakis_cmd_installer", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


class CmdInstallerTests(unittest.TestCase):
    @staticmethod
    def _zip_tree(archive, root_name, files):
        with zipfile.ZipFile(archive, "w") as bundle:
            for relative, content in files.items():
                bundle.writestr(f"{root_name}/{relative}", content)

    def test_manifest_is_pinned_and_matches_cmd_bootstrap(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cmd = CMD.read_text(encoding="cp949")
        self.assertEqual(data["version"], "7.5.1")
        self.assertEqual(data["base"]["sha256"], "7C380D4309BBDA395366C49564EDF8996181FD45E61B6F353EA417F32BC3B970")
        self.assertIn(data["base"]["url"], cmd)
        self.assertIn(data["base"]["sha256"], cmd)
        self.assertEqual(len(data["nodes"]), 14)
        self.assertEqual(len(data["models"]), 7)
        self.assertEqual(data["source"]["sha256"], "D6D8BC920C7A74BE4728C0F7703744469E62E80502F297E582EE1A1406FA052D")

    def test_manifest_dependency_contract_matches_setup(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        setup = (ROOT / "installer" / "Setup_LAKIS_Safe.cs").read_text(encoding="utf-8")
        records = [data["base"], *(
            {"url": row[1], "sha256": row[2]} for row in data["nodes"]
        ), {"url": data["nested_node"][1], "sha256": data["nested_node"][2]}, *(
            {"url": row[1], "sha256": row[2]} for row in data["models"]
        )]
        for record in records:
            self.assertIn(record["url"], setup)
            self.assertIn(record["sha256"], setup)

    def test_cmd_has_no_powershell_or_defender_bypass(self):
        cmd = CMD.read_text(encoding="cp949").casefold()
        for forbidden in ("powershell", "pwsh", "add-mppreference", "set-mppreference", "-executionpolicy", "iex "):
            self.assertNotIn(forbidden, cmd)
        self.assertIn("certutil.exe -hashfile", cmd)
        self.assertIn("curl.exe --fail", cmd)
        self.assertIn("--retry 5 --retry-all-errors", cmd)
        self.assertIn("--continue-at -", cmd)
        self.assertNotIn("--insecure", cmd)
        self.assertIn('if /i "%~1"=="--spinner" goto :spinner', cmd)
        self.assertIn('set "spinner=%~f0"', cmd)
        self.assertIn("ping.exe", cmd)
        self.assertIn('for %%p in ("%target%") do set "stage=%%~dpp.lakis-cmd-stage-', cmd)
        self.assertIn('if exist "%stage%" goto :failed', cmd)
        self.assertNotIn('rmdir /s /q "%stage%"', cmd)

    def test_safe_relative_rejects_escape_and_absolute(self):
        for value in ("../escape", "a/../../escape", "C:/Windows/file", "C:escape", "\\rooted", "file:stream"):
            with self.assertRaises(ValueError):
                module.safe_relative(value)
        self.assertEqual(module.safe_relative("ComfyUI/LAKIS"), Path("ComfyUI") / "LAKIS")

    def test_desktop_shortcut_targets_installed_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "LAKIS"
            target.mkdir()
            (target / "LAKIS.exe").write_bytes(b"launcher")
            desktop = root / "Desktop"
            observed = {}

            def fake_runner(command, **kwargs):
                observed["command"] = command
                observed["kwargs"] = kwargs
                Path(command[3]).write_bytes(b"shortcut")

            shortcut = module.create_desktop_shortcut(target, desktop, fake_runner)
            self.assertEqual(shortcut, desktop / "LAKIS.lnk")
            self.assertEqual(observed["command"][4], str(target / "LAKIS.exe"))
            self.assertEqual(observed["command"][5], str(target))
            self.assertTrue(observed["kwargs"]["check"])

    def test_default_input_image_is_valid_png_with_expected_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            image = module.create_default_input_image(Path(folder))
            content = image.read_bytes()
            self.assertEqual(content[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", content[16:24]), (1536, 1024))
            self.assertEqual(image.name, "LAKIS_1_2026-09-01-221228.webp")

    def test_download_retries_and_resumes_after_interrupted_tls_stream(self):
        payload = b"0123456789"

        class Response:
            def __init__(self, body, status, fail=False):
                self.body = body
                self.status = status
                self.headers = {"Content-Length": str(len(body))}
                self.fail = fail
                self.reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                self.reads += 1
                if self.fail and self.reads == 2:
                    raise OSError("simulated TLS interruption")
                if self.reads == 1:
                    return self.body
                return b""

        responses = [Response(payload[:4], 200, fail=True), Response(payload[4:], 206)]
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return responses.pop(0)

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(module.urllib.request, "urlopen", side_effect=fake_urlopen), \
                mock.patch.object(module.time, "sleep"), \
                mock.patch("sys.stdout", output):
            target = Path(folder) / "model.bin"
            result = module.download(
                "https://example.invalid/model.bin",
                target,
                hashlib.sha256(payload).hexdigest().upper(),
                len(payload),
            )
            self.assertEqual(result.read_bytes(), payload)
            self.assertIsNone(requests[0].get_header("Range"))
            self.assertEqual(requests[1].get_header("Range"), "bytes=4-")
            self.assertIn("\r        model.bin", output.getvalue())
            self.assertIn("%  /", output.getvalue())

    def test_complete_partial_is_verified_without_requesting_past_eof(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(module.urllib.request, "urlopen") as request:
            target = Path(folder) / "model.bin"
            partial = target.with_suffix(".bin.part")
            partial.write_bytes(b"complete")
            result = module.download("https://example.invalid/model.bin", target,
                                     hashlib.sha256(b"complete").hexdigest().upper(), 8)
            self.assertEqual(result.read_bytes(), b"complete")
            self.assertFalse(partial.exists())
            request.assert_not_called()

    def test_corrupt_prefix_fails_hash_then_next_run_can_recover(self):
        class Response(io.BytesIO):
            status = 206
            headers = {'Content-Length': '10'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'model.bin'
            target.with_suffix('.bin.part').write_bytes(b'bad')
            payload = b'correct bytes'
            digest = hashlib.sha256(payload).hexdigest().upper()
            with mock.patch.object(module.urllib.request, 'urlopen', return_value=Response(payload[3:])):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                    module.download('https://example.invalid/model', target, digest, len(payload))
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.bin.part').exists())
            source = root / 'source.bin'
            source.write_bytes(payload)
            module.download(source.as_uri(), target, digest, len(payload))
            self.assertEqual(target.read_bytes(), payload)

    def test_corrupt_complete_partial_is_replaced_by_a_fresh_download(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.bin"
            source.write_bytes(b"correct")
            target = Path(folder) / "model.bin"
            target.with_suffix(".bin.part").write_bytes(b"invalid")
            result = module.download(source.as_uri(), target, module.sha256(source), 7)
            self.assertEqual(result.read_bytes(), b"correct")

    def test_unknown_size_partial_recovers_from_http_416(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(module.time, "sleep"):
            source = Path(folder) / "source.zip"
            source.write_bytes(b"correct bytes")
            target = Path(folder) / "repair.zip"
            target.with_suffix(".zip.part").write_bytes(b"corrupt oversized partial content")
            opener = module.urllib.request.urlopen
            requests = []
            def response(request, timeout):
                requests.append(request)
                if len(requests) == 1:
                    raise module.urllib.error.HTTPError(request.full_url, 416, "past EOF", {}, None)
                return opener(request, timeout=timeout)
            with mock.patch.object(module.urllib.request, "urlopen", side_effect=response):
                result = module.download(source.as_uri(), target, module.sha256(source))
            self.assertEqual(result.read_bytes(), source.read_bytes())
            self.assertIsNotNone(requests[0].get_header("Range"))
            self.assertIsNone(requests[1].get_header("Range"))

    def test_zip_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escape.txt", "bad")
            with self.assertRaises(RuntimeError):
                module.extract_zip(archive, root / "out")
            self.assertFalse((root / "escape.txt").exists())

    def test_layout_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = root / "payload.txt"
            payload.write_bytes(b"exact")
            digest = hashlib.sha256(b"exact").hexdigest().upper()
            layout = root / "layout.json"
            layout.write_text(json.dumps({"files": [{"path": "payload.txt", "size": 5, "sha256": digest}]}), encoding="utf-8")
            self.assertEqual(module.validate_layout(root, layout), (1, []))
            payload.write_bytes(b"other")
            self.assertEqual(module.validate_layout(root, layout)[1], ["hash:payload.txt"])
            payload.write_bytes(b"longer")
            self.assertEqual(module.validate_layout(root, layout)[1], ["size:payload.txt"])

    def test_layout_validation_supports_public_size_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "payload.txt").write_bytes(b"exact")
            layout = root / "layout.json"
            layout.write_text(json.dumps({"files": [{"path": "payload.txt", "size": 5}]}), encoding="utf-8")
            self.assertEqual(module.validate_layout(root, layout), (1, []))

    def test_safe_requirements_uses_pinned_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "requirements.txt"
            source.write_text(
                "git+https://github.com/ltdrdata/img2texture.git\n"
                "git+https://github.com/ltdrdata/ffmpy.git\n",
                encoding="utf-8",
            )
            output = module.safe_requirements(source)
            self.assertIn("img2texture/zip/d6159abea44a0b2cf77454d3d46962c8b21eb9d3", output.read_text(encoding="utf-8"))
            text = output.read_text(encoding="utf-8")
            self.assertIn("codeload.github.com/ltdrdata/ffmpy/zip/f000737", text)
            self.assertNotIn("git+https://", text)

    def test_synthetic_fresh_install_promotes_only_after_exact_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            portable = root / "stage" / "ComfyUI_windows_portable"
            (portable / "python_embeded").mkdir(parents=True)
            (portable / "python_embeded" / "python.exe").write_bytes(b"stub")
            sibling = portable.parent / "keep-unrelated-user-file.txt"
            sibling.write_bytes(b"must survive promotion")
            (portable / "ComfyUI" / "custom_nodes").mkdir(parents=True)
            assets = root / "assets"
            assets.mkdir()
            node = assets / "node.zip"
            nested = assets / "nested.zip"
            self._zip_tree(node, "node-root", {"__init__.py": "NODE = True\n"})
            self._zip_tree(nested, "nested-root", {"marker.txt": "nested\n"})
            model = assets / "model.bin"
            model.write_bytes(b"model")
            source = assets / "source.zip"
            self._zip_tree(source, "source-root", {
                "resources/PRODUCTION_NODE_PACKAGES.txt": "LAKIS-Demo\n",
                "resources/STOP_AUTOMATION": "stop\n",
                "src/custom_nodes/LAKIS-Demo/__init__.py": "NODE = True\n",
                "src/external_ui/index.html": "ui\n",
                "src/runtime/sync_runtime_workflow.py": "SYNC = True\n",
                "workflows/LAKIS_runtime_api_v7.4.json": "{}\n",
                "workflows/LAKIS_runtime_visual_v7.4.json": "{}\n",
                "workflows/LAKIS_custom_v7.4_editable.json": "{}\n",
                "LICENSE.md": "license\n",
                "THIRD_PARTY_NOTICES.md": "notices\n",
                "third_party_licenses/demo.txt": "license\n",
                "patches/ComfyUI-Spectrum-KSampler/files/nodes.py": "patched\n",
                "patches/ComfyUI-Spectrum-KSampler/files/spectrum.py": "patched\n",
            })
            repair = assets / "LAKIS_RepairPack.zip"
            with zipfile.ZipFile(repair, "w") as bundle:
                bundle.writestr("LAKIS.exe", b"launcher")
                bundle.writestr("VERSION", b"7.5.0")
            layout = assets / "release-layout.json"
            files = []
            for name, content in (("LAKIS.exe", b"launcher"), ("VERSION", b"7.5.0")):
                files.append({"path": name, "sha256": hashlib.sha256(content).hexdigest().upper()})
            layout.write_text(json.dumps({"files": files}), encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schema": 1,
                "version": "7.5.0",
                "release_base": assets.as_uri(),
                "base": {},
                "source": {
                    "name": source.name,
                    "url": source.as_uri(),
                    "sha256": module.sha256(source),
                    "bytes": source.stat().st_size,
                },
                "repair_pack": {"name": repair.name, "sha256": module.sha256(repair)},
                "release_layout": {"name": layout.name, "sha256": module.sha256(layout)},
                "nodes": [[node.name, node.as_uri(), module.sha256(node), "demo-node"]],
                "nested_node": [nested.name, nested.as_uri(), module.sha256(nested), "demo-node/repositories/nested"],
                "models": [[model.name, model.as_uri(), module.sha256(model), "demo-models", model.stat().st_size]],
            }), encoding="utf-8")
            target = root / "installed"
            with mock.patch.object(
                module,
                "create_desktop_shortcut",
                return_value=root / "Desktop" / "LAKIS.lnk",
            ), mock.patch.object(module, "ensure_webview2_runtime") as webview:
                module.install(manifest, portable, target, root / "cache", False)
                webview.assert_called_once()
            self.assertEqual((target / "VERSION").read_text(encoding="utf-8"), "7.5.0")
            completed_at = (target / "install.complete").read_text(encoding="utf-8")
            self.assertEqual(datetime.fromisoformat(completed_at).utcoffset(), timedelta(0))
            self.assertEqual((target / "LAKIS.exe").read_bytes(), b"launcher")
            self.assertTrue((target / "ComfyUI" / "custom_nodes" / "demo-node" / "__init__.py").is_file())
            self.assertTrue((target / "ComfyUI" / "custom_nodes" / "LAKIS-Demo" / "__init__.py").is_file())
            self.assertTrue((target / "ComfyUI" / "LAKIS" / "workflows" / "LAKIS_custom_v7.4_editable.json").is_file())
            self.assertTrue((target / "ComfyUI" / "input" / "LAKIS_1_2026-09-01-221228.webp").is_file())
            self.assertTrue((target / "ComfyUI" / "models" / "demo-models" / "model.bin").is_file())
            self.assertEqual((target / ".lakis" / "install-method.txt").read_text(encoding="ascii"), "cmd\n")
            self.assertEqual(sibling.read_bytes(), b"must survive promotion")

    def test_existing_webview_runtime_skips_download_and_install(self):
        with mock.patch.object(module, 'has_webview2_runtime', return_value=True), \
                mock.patch.object(module, 'download') as fetch, \
                mock.patch.object(module.subprocess, 'run') as run:
            module.ensure_webview2_runtime({}, Path('unused'))
            fetch.assert_not_called()
            run.assert_not_called()

    def test_missing_webview_uses_verified_download_then_rechecks(self):
        record = {'url': 'https://example.invalid/pinned', 'sha256': 'A' * 64, 'bytes': 99}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(module, 'has_webview2_runtime', side_effect=[False, True]), \
                mock.patch.object(module, 'download', return_value=Path(folder) / 'runtime.exe') as fetch, \
                mock.patch.object(module.subprocess, 'run') as run:
            module.ensure_webview2_runtime({'webview2': record}, Path(folder))
            fetch.assert_called_once_with(record['url'], Path(folder) / 'MicrosoftEdgeWebview2Setup.exe', record['sha256'], 99)
            self.assertEqual(run.call_args.args[0][1:], ['/silent', '/install'])
            self.assertTrue(run.call_args.kwargs['check'])

    def test_missing_webview_after_install_blocks_completion(self):
        record = {'url': 'https://example.invalid/pinned', 'sha256': 'A' * 64, 'bytes': 99}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(module, 'has_webview2_runtime', return_value=False), \
                mock.patch.object(module, 'download', return_value=Path(folder) / 'runtime.exe'), \
                mock.patch.object(module.subprocess, 'run'):
            with self.assertRaisesRegex(RuntimeError, 'WebView2'):
                module.ensure_webview2_runtime({'webview2': record}, Path(folder))

    def test_webview_registry_detection_rejects_missing_or_invalid_versions(self):
        import winreg
        with mock.patch.object(winreg, 'OpenKey') as open_key, \
                mock.patch.object(winreg, 'QueryValueEx') as query:
            open_key.return_value.__enter__.return_value = 'fixture-key'
            for version in ('', '0.0.0.0', ' 0.0.0.0 ', 'not-a-version'):
                query.return_value = (version, winreg.REG_SZ)
                self.assertFalse(module.has_webview2_runtime())
            query.return_value = ('160.0.4430.69', winreg.REG_SZ)
            self.assertTrue(module.has_webview2_runtime())
            open_key.side_effect = FileNotFoundError()
            self.assertFalse(module.has_webview2_runtime())


if __name__ == "__main__":
    unittest.main()
