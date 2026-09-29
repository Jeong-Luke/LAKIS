"""Run the distributed CMD download subroutine against local-only fixtures."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

CMD = Path(__file__).resolve().parents[1] / 'LAKIS_CMD_Install.cmd'


@unittest.skipUnless(os.name == 'nt' and shutil.which('curl.exe') and shutil.which('certutil.exe'),
                     'Windows CMD bootstrap tools required')
class CmdBootstrapTests(unittest.TestCase):
    def run_download(self, root, url, payload, expect_success=True):
        target = root / 'archive.bin'
        script = CMD.read_bytes().decode('cp949')
        routine = script[script.index('\r\n:download\r\n'):script.index('\r\n:missing_files\r\n')]
        digest = hashlib.sha256(payload).hexdigest().upper()
        wrapper = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                   'call :download "' + url + '" "' + str(target) + '" "' + digest + '"\r\n'
                   'exit /b %ERRORLEVEL%\r\n' + routine)
        harness = root / 'download.cmd'
        harness.write_bytes(wrapper.encode('cp949'))
        result = subprocess.run(['cmd.exe', '/d', '/c', str(harness)], cwd=root,
                                capture_output=True, timeout=45)
        diagnostic = (result.stdout + result.stderr).decode('cp949', errors='replace')
        diagnostic += repr({p.name: p.read_bytes() for p in root.glob('archive.bin*')})
        if not expect_success:
            self.assertNotEqual(result.returncode, 0, diagnostic)
            self.assertNotEqual(target.read_bytes(), payload)
            return
        self.assertEqual(result.returncode, 0, diagnostic)
        self.assertEqual(target.read_bytes(), payload)
        self.assertFalse(target.with_suffix('.bin.part').exists())

    def test_complete_partial_is_promoted_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b'complete local bootstrap fixture'
            (root / 'archive.bin.part').write_bytes(payload)
            self.run_download(root, 'http://127.0.0.1:1/not-requested', payload)
            self.assertFalse((root / 'archive.bin.http').exists())

    def test_invalid_range_resets_partial_once_and_recovers(self):
        self.check_range_recovery(False)

    def test_server_ignoring_range_resets_partial_once_and_recovers(self):
        self.check_range_recovery(True)

    def test_corrupt_prefix_is_rejected_and_next_run_recovers(self):
        payload = b'correct bytes'
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                ranged = self.headers.get('Range')
                requests.append(ranged)
                self.send_response(206 if ranged else 200)
                data = payload[3:] if ranged else payload
                if ranged:
                    self.send_header('Content-Range', 'bytes 3-12/13')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'archive.bin.part').write_bytes(b'bad')
                url = f'http://127.0.0.1:{server.server_port}/fixture'
                self.run_download(root, url, payload, expect_success=False)
                self.run_download(root, url, payload)
                self.assertEqual(requests, ['bytes=3-', None])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def check_range_recovery(self, ignore_range):
        payload = b'correct bytes'
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                range_header = self.headers.get('Range')
                requests.append(range_header)
                if range_header and not ignore_range:
                    self.send_response(416)
                    self.send_header('Content-Length', '0')
                    self.send_header('Content-Range', 'bytes */' + str(len(payload)))
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'archive.bin.part').write_bytes(b'corrupt oversized partial content')
                self.run_download(root, f'http://127.0.0.1:{server.server_port}/fixture', payload)
                self.assertIsNotNone(requests[0])
                self.assertEqual(requests.count(None), 1)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
