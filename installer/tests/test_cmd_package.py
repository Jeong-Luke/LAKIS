import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'installer'))
import build_runtime_installer_manifest as manifest_builder
spec = importlib.util.spec_from_file_location('builder', ROOT / 'installer/build_cmd_installer.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CmdPackageTests(unittest.TestCase):
    def assert_cmd_payload(self, cmd, source):
        self.assertNotIn(b'\n', cmd.replace(b'\r\n', b''))
        expected = source.decode('cp949').replace(
            'https://www.7-zip.org/a/7zr.exe',
            'https://github.com/ip7z/7zip/releases/download/26.03/7zr.exe',
        )
        self.assertEqual(cmd.decode('cp949').splitlines(), expected.splitlines())

    def fixture(self, root, *, git_line_endings=False):
        repo = root / 'repo'
        dist = root / 'dist'
        installer = repo / 'installer'
        installer.mkdir(parents=True)
        dist.mkdir()
        (repo / 'VERSION').write_text('8.0.0\n')
        for name in (*builder.PACKAGE_FILES, 'cmd-installer-manifest.json', 'Setup_LAKIS_Safe.cs'):
            shutil.copyfile(ROOT / 'installer' / name, installer / name)
        archive = root / 'source.zip'
        revision = 'a' * 40
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr(f'LAKIS-{revision}/VERSION', '8.0.0\n')
            for name in builder.PACKAGE_FILES:
                data = (installer / name).read_bytes()
                if git_line_endings:
                    data = data.replace(b'\r\n', b'\n')
                z.writestr(f'LAKIS-{revision}/installer/{name}', data)
        digest = builder.sha256(archive)
        contract = root / 'source-contract.json'
        contract.write_text(json.dumps({'schema': 1, 'revision': revision, 'sha256': digest, 'bytes': archive.stat().st_size}))
        pinned = root / 'pinned.cs'
        pinned.write_text(f'private const string Revision = "{revision}";\nprivate const string SourceArchiveSha256 = "{digest}";\n')
        webview = root / 'MicrosoftEdgeWebview2Setup.exe'
        webview.write_bytes(b'fixture-only Microsoft bootstrapper')
        webview_record = {
            'name': webview.name, 'url': 'https://example.invalid/pinned-webview',
            'sha256': builder.sha256(webview), 'bytes': webview.stat().st_size,
        }
        (root / 'webview2-bootstrapper.json').write_text(json.dumps(webview_record))
        with pinned.open('a') as stream:
            stream.write(f'private const string WebView2BootstrapperUrl = "{webview_record["url"]}";\n')
            stream.write(f'private const string WebView2BootstrapperSha256 = "{webview_record["sha256"]}";\n')
            stream.write(f'private const long WebView2BootstrapperBytes = {webview_record["bytes"]};\n')
        bundle_path = root / 'runtime-bundle.json'
        bundle_path.write_text(json.dumps({
            'schema': 2, 'product': 'LAKIS', 'version': '8.0.0',
            'comfyui_version': '0.42.0', 'name': 'LAKIS_Runtime_8.0.0.zip',
            'bytes': 10, 'files': 1, 'sha256': 'A' * 64, 'manifest_sha256': 'B' * 64,
            'parts': [{
                'name': 'LAKIS_Runtime_8.0.0.zip.part001', 'bytes': 10, 'sha256': 'C' * 64,
                'url': 'https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/LAKIS_Runtime_8.0.0.zip.part001',
            }],
        }))
        manifest_path = root / 'runtime-installer-manifest.json'
        manifest_builder.build(repo, bundle_path, root / 'webview2-bootstrapper.json', manifest_path)
        setup = dist / 'LAKIS_Setup.exe'
        setup.write_bytes(b'fixture setup with pinned runtime manifest')
        (root / 'runtime-installer-contract.json').write_text(json.dumps({
            'schema': 1, 'version': '8.0.0',
            'manifest_sha256': builder.sha256(manifest_path),
            'setup_sha256': builder.sha256(setup),
        }))
        return repo, dist, archive, contract, pinned

    def test_exact_source_and_release_assets_generate_reproducible_package(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            package = builder.build(*args)
            first = package.read_bytes()
            self.assertEqual(builder.build(*args).read_bytes(), first)
            with zipfile.ZipFile(package) as z:
                self.assertEqual(set(z.namelist()), {*builder.PACKAGE_FILES, 'cmd-installer-manifest.json'})
                manifest = json.loads(z.read('cmd-installer-manifest.json'))
                self.assertEqual(z.read('cmd-installer-manifest.json'),
                                 (args[3].parent / 'runtime-installer-manifest.json').read_bytes())
                self.assertEqual(manifest['runtime_bundle']['version'], '8.0.0')
                self.assertEqual(manifest['webview2']['sha256'], builder.sha256(args[3].parent / 'MicrosoftEdgeWebview2Setup.exe'))
                for key in ('nodes', 'source', 'repair_pack', 'release_layout'):
                    self.assertNotIn(key, manifest)
                for name in builder.PACKAGE_FILES:
                    if name != 'LAKIS_CMD_Install.cmd':
                        self.assertEqual(z.read(name), (args[0] / 'installer' / name).read_bytes())
                cmd = z.read('LAKIS_CMD_Install.cmd')
                self.assert_cmd_payload(cmd, (args[0] / 'installer/LAKIS_CMD_Install.cmd').read_bytes())

    def test_git_archive_lf_matches_windows_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory), git_line_endings=True)
            self.assertTrue(builder.build(*args).is_file())

    def test_lf_checkout_still_packages_a_crlf_cmd(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory), git_line_endings=True)
            path = args[0] / 'installer/LAKIS_CMD_Install.cmd'
            path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
            package = builder.build(*args)
            with zipfile.ZipFile(package) as z:
                cmd = z.read(path.name)
            self.assert_cmd_payload(cmd, path.read_bytes())

    def test_stale_source_contract_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            args[2].write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError, 'source archive does not match'):
                builder.build(*args)

    def test_github_api_archive_root_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            args = list(self.fixture(Path(directory)))
            revision = 'a' * 40
            with zipfile.ZipFile(args[2], 'w') as z:
                z.writestr('Jeong-Luke-LAKIS-a1b2c3d/VERSION', '8.0.0\n')
                for name in builder.PACKAGE_FILES:
                    z.writestr('Jeong-Luke-LAKIS-a1b2c3d/installer/' + name,
                               (args[0] / 'installer' / name).read_bytes())
            digest = builder.sha256(args[2])
            args[3].write_text(json.dumps({'schema': 1, 'revision': revision, 'sha256': digest, 'bytes': args[2].stat().st_size}))
            args[4].write_text(args[4].read_text().replace(
                next(line.split('"')[1] for line in args[4].read_text().splitlines() if 'SourceArchiveSha256' in line),
                digest,
            ))
            self.assertTrue(builder.build(*args).is_file())

    def test_setup_cmd_pin_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            args[4].write_text('wrong pin')
            with self.assertRaisesRegex(ValueError, 'Setup and CMD source pins differ'):
                builder.build(*args)

    def test_stale_dependency_template_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            template = args[0] / 'installer/cmd-installer-manifest.json'
            manifest = json.loads(template.read_text())
            manifest['models'][0][2] = '0' * 64
            template.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'dependency template is stale'):
                builder.build(*args)

    def test_runtime_manifest_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            path = args[3].parent / 'runtime-installer-manifest.json'
            path.write_bytes(path.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'runtime installer contracts differ'):
                builder.build(*args)

    def test_modified_cmd_helper_is_not_packaged_under_an_old_source_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            path = args[0] / 'installer/runtime_install.py'
            path.write_bytes(path.read_bytes() + b'\n# changed after source freeze\n')
            with self.assertRaisesRegex(ValueError, 'source changed after the frozen source archive'):
                builder.build(*args)

    def test_different_gui_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            (args[1] / 'LAKIS_Setup.exe').write_bytes(b'a different GUI installer')
            with self.assertRaisesRegex(ValueError, 'runtime installer contracts differ'):
                builder.build(*args)

    def test_webview_build_pin_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            (args[3].parent / 'MicrosoftEdgeWebview2Setup.exe').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'WebView2 bootstrapper build contract mismatch'):
                builder.build(*args)

    def test_setup_cmd_webview_pin_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            args[4].write_text(args[4].read_text().replace('https://example.invalid/pinned-webview', 'https://example.invalid/wrong'))
            with self.assertRaisesRegex(ValueError, 'Setup and CMD WebView2 pins differ'):
                builder.build(*args)


if __name__ == '__main__':
    unittest.main(verbosity=2)
