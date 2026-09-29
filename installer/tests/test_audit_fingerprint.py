"""Execute fingerprinting against clean and runtime-dirty repository fixtures."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'New-ReleaseAuditFingerprint.ps1'

class AuditFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'installer').mkdir()
        (self.root / 'src').mkdir()
        shutil.copyfile(SCRIPT, self.root / 'installer' / SCRIPT.name)
        shutil.copyfile(SCRIPT.parent.parent / '.gitignore', self.root / '.gitignore')
        (self.root / 'VERSION').write_text('7.5.0\n', encoding='utf-8')
        (self.root / 'src/app.py').write_text('value = 1\n', encoding='utf-8')
        for args in [('init', '--quiet'), ('add', '.'), ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost', 'commit', '--quiet', '-m', 'fixture')]:
            subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def git_status(self):
        return subprocess.check_output(['git','status','--porcelain'],cwd=self.root).decode('utf-8')

    def fingerprint(self):
        p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.root/'installer'/SCRIPT.name)],
                           cwd=self.root, capture_output=True, encoding='utf-8', errors='strict', check=True)
        return json.loads(p.stdout)

    def test_runtime_log_creation_mutation_and_rotation_do_not_change_identity(self):
        clean = self.fingerprint()
        log = self.root/'src/external_ui_bridge_audit.jsonl'
        log.write_text('{"event":"first"}\n', encoding='utf-8')
        self.assertEqual(clean, self.fingerprint())
        log.write_text('{"event":"second"}\n', encoding='utf-8')
        (self.root/'src/external_ui_bridge_audit.jsonl.1').write_bytes(b'old runtime output')
        (self.root/'src/external_ui_bridge_audit.jsonl.2.gz').write_bytes(b'compressed rotation')
        self.assertEqual(clean, self.fingerprint())
        self.assertEqual('', self.git_status())
        checkout=self.root/'clean-checkout'
        subprocess.run(['git','clone','--quiet',str(self.root),str(checkout)],check=True,capture_output=True)
        p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(checkout/'installer'/SCRIPT.name)],cwd=checkout,capture_output=True,encoding='utf-8',check=True)
        self.assertEqual(clean,json.loads(p.stdout))

    def test_actual_source_change_still_changes_identity(self):
        old = self.fingerprint()
        (self.root/'src/app.py').write_text('value = 2\n', encoding='utf-8')
        self.assertNotEqual(old['fingerprint_sha256'], self.fingerprint()['fingerprint_sha256'])

    def test_other_jsonl_data_is_not_silently_excluded(self):
        old = self.fingerprint()
        data = self.root/'src/other_audit.jsonl'
        data.write_bytes(b'{"value":1}\n')
        current = self.fingerprint()
        self.assertEqual(old['file_count'] + 1, current['file_count'])
        self.assertNotEqual(old['fingerprint_sha256'], current['fingerprint_sha256'])
        self.assertIn('src/other_audit.jsonl',self.git_status())
        data.write_bytes(b'{"value":2}\n')
        self.assertNotEqual(current['fingerprint_sha256'], self.fingerprint()['fingerprint_sha256'])

if __name__ == '__main__':
    unittest.main()
