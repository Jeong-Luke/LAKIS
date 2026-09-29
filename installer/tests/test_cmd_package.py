import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('builder', ROOT / 'installer/build_cmd_installer.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CmdPackageTests(unittest.TestCase):
    def fixture(self, root):
        repo = root / 'repo'
        dist = root / 'dist'
        installer = repo / 'installer'
        installer.mkdir(parents=True)
        dist.mkdir()
        (repo / 'VERSION').write_text('7.5.0\n')
        for name in (*builder.PACKAGE_FILES, 'cmd-installer-manifest.json', 'Setup_LAKIS_Safe.cs'):
            shutil.copyfile(ROOT / 'installer' / name, installer / name)
        archive = root / 'source.zip'
        revision = 'a' * 40
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr(f'LAKIS-{revision}/VERSION', '7.5.0\n')
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
        (dist / 'release-layout.json').write_text(json.dumps({'version': '7.5.0', 'files': [{'path': 'VERSION', 'size': 5}]}))
        (dist / 'LAKIS_RepairPack.zip').write_bytes(b'fixture repair bytes')
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
                self.assertEqual(manifest['source']['sha256'], builder.sha256(args[2]))
                self.assertIn('a' * 40, manifest['source']['url'])
                self.assertEqual(manifest['webview2']['sha256'], builder.sha256(args[3].parent / 'MicrosoftEdgeWebview2Setup.exe'))
                for key in ('repair_pack', 'release_layout'):
                    asset = args[1] / manifest[key]['name']
                    self.assertEqual(manifest[key]['sha256'], builder.sha256(asset))
                    self.assertEqual(manifest[key]['bytes'], asset.stat().st_size)
                self.assertEqual(z.read('LAKIS_CMD_Install.cmd'), (args[0] / 'installer/LAKIS_CMD_Install.cmd').read_bytes())

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
                z.writestr('Jeong-Luke-LAKIS-a1b2c3d/VERSION', '7.5.0\n')
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
            manifest['nodes'][0][2] = '0' * 64
            template.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'dependency template is stale'):
                builder.build(*args)

    def test_required_setup_dependency_missing_from_cmd_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            template = args[0] / 'installer/cmd-installer-manifest.json'
            manifest = json.loads(template.read_text())
            manifest['nodes'].pop()
            template.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'dependency template is stale'):
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
