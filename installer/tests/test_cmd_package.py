import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'installer'))
import runtime_manifest

spec = importlib.util.spec_from_file_location('builder', ROOT / 'installer/build_cmd_installer.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CmdPackageTests(unittest.TestCase):
    @staticmethod
    def write_archive(archive, repo, prefix):
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.write(repo / 'VERSION', f'{prefix}/VERSION')
            for name in builder.PACKAGE_FILES:
                bundle.write(repo / 'installer' / name, f'{prefix}/installer/{name}')

    def fixture(self, root):
        repo = root / 'repo'
        dist = root / 'dist'
        installer = repo / 'installer'
        installer.mkdir(parents=True)
        dist.mkdir()
        version = (ROOT / 'VERSION').read_text(encoding='utf-8-sig').strip()
        (repo / 'VERSION').write_text(version + '\n')
        for name in (*builder.PACKAGE_FILES, 'cmd-installer-manifest.json', 'Setup_LAKIS_Safe.cs'):
            shutil.copyfile(ROOT / 'installer' / name, installer / name)
        archive = root / 'source.zip'
        revision = 'a' * 40
        self.write_archive(archive, repo, f'LAKIS-{revision}')
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
        setup = dist / 'LAKIS_Setup.exe'
        setup.write_bytes(b'fixture-only compiled Setup')
        template = json.loads((installer / 'cmd-installer-manifest.json').read_text())
        name = 'LAKIS_RuntimeBundle.zip'
        manifest = {
            'schema': 1, 'version': version, 'webview2': webview_record,
            **{key: template[key] for key in ('base', 'models', 'optional_animesharp')},
            'runtime_bundle': {
                'schema': 2, 'product': 'LAKIS', 'version': version,
                'comfyui_version': runtime_manifest.COMFY_VERSION,
                'name': name, 'sha256': 'A' * 64, 'manifest_sha256': 'B' * 64,
                'bytes': 1, 'files': 1,
                'parts': [{
                    'name': name + '.part001', 'sha256': 'C' * 64, 'bytes': 1,
                    'url': f'https://github.com/Jeong-Luke/LAKIS/releases/download/v{version}/{name}.part001',
                }],
            },
        }
        manifest_path = root / 'runtime-installer-manifest.json'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        (root / 'runtime-installer-contract.json').write_text(json.dumps({
            'schema': 1, 'version': version,
            'manifest_sha256': builder.sha256(manifest_path),
            'setup_sha256': builder.sha256(setup),
        }), encoding='utf-8')
        return repo, dist, archive, contract, pinned

    def test_exact_source_and_release_assets_generate_reproducible_package(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            package = builder.build(*args)
            first = package.read_bytes()
            self.assertEqual(builder.build(*args).read_bytes(), first)
            with zipfile.ZipFile(package) as z:
                self.assertEqual(set(z.namelist()), {*builder.PACKAGE_FILES, 'cmd-installer-manifest.json'})
                self.assertEqual(z.read('cmd-installer-manifest.json'),
                                 (args[3].parent / 'runtime-installer-manifest.json').read_bytes())
                for name in builder.PACKAGE_FILES:
                    if name != 'LAKIS_CMD_Install.cmd':
                        self.assertEqual(z.read(name), (args[0] / 'installer' / name).read_bytes())
                cmd = z.read('LAKIS_CMD_Install.cmd').decode('cp949')
                self.assertIn('set "SEVEN_URL=https://github.com/ip7z/7zip/releases/download/26.03/7zr.exe"', cmd)
                self.assertNotIn('set "SEVEN_URL=https://www.7-zip.org/a/7zr.exe"', cmd)

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
            self.write_archive(args[2], args[0], 'Jeong-Luke-LAKIS-a1b2c3d')
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

    def test_required_setup_dependency_missing_from_cmd_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            template = args[0] / 'installer/cmd-installer-manifest.json'
            manifest = json.loads(template.read_text())
            manifest['models'].pop()
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

    def test_changed_packaged_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            with (args[0] / 'installer/runtime_update.py').open('ab') as stream:
                stream.write(b'\n# changed after source freeze\n')
            with self.assertRaisesRegex(ValueError, 'CMD source changed after the frozen source archive'):
                builder.build(*args)

    def test_gui_cmd_contract_rejects_changed_setup_or_manifest(self):
        for name in ('LAKIS_Setup.exe', 'runtime-installer-manifest.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                args = self.fixture(Path(directory))
                path = args[1] / name if name.endswith('.exe') else args[3].parent / name
                with path.open('ab') as stream:
                    stream.write(b' ')
                with self.assertRaisesRegex(ValueError, 'GUI and CMD runtime installer contracts differ'):
                    builder.build(*args)


if __name__ == '__main__':
    unittest.main(verbosity=2)
