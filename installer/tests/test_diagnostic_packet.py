import base64
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.decode_diagnostic import decode_report


ROOT = Path(__file__).resolve().parents[2]
DECODER = ROOT / "tools" / "decode_diagnostic.py"
MAX_RAW_BYTES = 4 * 1024 * 1024
MAX_COMPRESSED_BYTES = 1024 * 1024


def make_packet(raw, compressed=None, length=None, hash_input=None, version="LKS1G"):
    if compressed is None:
        compressed = gzip.compress(raw, mtime=0)
    if length is None:
        length = len(raw)
    if hash_input is None:
        hash_input = raw
    digest = hashlib.sha256(hash_input).hexdigest()
    encoded = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii")
    return f"{version}:{length}:{digest}:{encoded}"


class DiagnosticPacketTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "report_schema": 1,
            "error_code": "NETWORK_DIAGNOSTIC",
            "message": "연결을 확인하세요 🚀",
            "details": {
                "retries": 0,
                "cancelled": False,
                "nested": {
                    "note": "한글과 이모지 😀",
                    "values": [False, 0, None, {"explanation": "상세 진단"}],
                },
            },
        }
        self.raw = json.dumps(
            self.report, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.compressed = gzip.compress(self.raw, mtime=0)
        self.packet = make_packet(self.raw, self.compressed)

    def test_semantic_round_trip_and_independent_gzip_hash(self):
        self.assertEqual(decode_report(self.packet), self.report)
        encoded = self.packet.split(":")[3]
        independent_raw = gzip.decompress(
            base64.urlsafe_b64decode(
                encoded + "=" * ((4 - len(encoded) % 4) % 4)
            )
        )
        self.assertEqual(len(independent_raw), len(self.raw))
        self.assertEqual(hashlib.sha256(independent_raw).hexdigest(), self.packet.split(":")[2])
        self.assertEqual(json.loads(independent_raw.decode("utf-8")), self.report)

    def test_copied_report_and_duplicate_tokens(self):
        self.assertEqual(
            decode_report(f"Copied diagnostic report:\n{self.packet}\nEnd of report."),
            self.report,
        )
        self.assertEqual(decode_report(f"Copied report ({self.packet})."), self.report)
        self.assertEqual(decode_report(
            f"LAKIS 8.0.1 | LKS-GEN-1012 | 연결 실패\n진단: {self.packet}"), self.report)
        for suffix in ("=", "!"):
            with self.assertRaises(ValueError):
                decode_report(f"LAKIS | LKS-GEN-1012\n진단: {self.packet}{suffix}")
        with self.assertRaises(ValueError):
            decode_report(f"{self.packet}\n{self.packet}")

    def test_corrupt_truncated_hash_length_version_and_base64(self):
        damaged = bytearray(self.compressed)
        damaged[-1] ^= 1
        malformed = [
            make_packet(self.raw, bytes(damaged)),
            make_packet(self.raw, self.compressed[:-2]),
            make_packet(self.raw, self.compressed, hash_input=b"wrong"),
            make_packet(self.raw, self.compressed, length=len(self.raw) + 1),
            make_packet(self.raw, self.compressed, version="LKS2G"),
            self.packet[:-1] + "!",
            self.packet + "=",
        ]
        for packet in malformed:
            with self.subTest(packet=packet[:12]):
                with self.assertRaises(ValueError):
                    decode_report(packet)

    def test_size_limits_and_oversized_gzip_expansion(self):
        oversized_compressed = b"x" * (MAX_COMPRESSED_BYTES + 1)
        encoded = base64.urlsafe_b64encode(oversized_compressed).rstrip(b"=").decode("ascii")
        with self.assertRaises(ValueError):
            decode_report(f"LKS1G:1:{'0' * 64}:{encoded}")

        with self.assertRaises(ValueError):
            decode_report(
                f"LKS1G:{MAX_RAW_BYTES + 1}:{'0' * 64}:"
                f"{base64.urlsafe_b64encode(self.compressed).rstrip(b'=').decode('ascii')}"
            )

        expansion = b"A" * (MAX_RAW_BYTES + 1)
        expansion_packet = make_packet(
            expansion,
            gzip.compress(expansion, mtime=0),
            length=MAX_RAW_BYTES,
        )
        with self.assertRaises(ValueError):
            decode_report(expansion_packet)

    def test_schema_utf8_and_concatenated_gzip_are_rejected(self):
        invalid_reports = [
            b'{"report_schema":2,"error_code":"X"}',
            b'{"report_schema":1,"error_code":""}',
            b'{"report_schema":1,"error_code":"X","extra":NaN}',
            b'{"report_schema":1,"error_code":"X","extra":1e999}',
            b"\xff",
        ]
        for raw in invalid_reports:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    decode_report(make_packet(raw))

        concatenated = self.compressed + gzip.compress(self.raw, mtime=0)
        with self.assertRaises(ValueError):
            decode_report(make_packet(self.raw, concatenated))
        with self.assertRaises(ValueError):
            decode_report(make_packet(self.raw, self.compressed + gzip.compress(b"", mtime=0)))

    def test_cli_stdin_and_file_and_concise_invalid_input(self):
        stdin_result = subprocess.run(
            [sys.executable, str(DECODER)],
            input=self.packet,
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(stdin_result.returncode, 0, stdin_result.stderr)
        self.assertEqual(json.loads(stdin_result.stdout), self.report)
        self.assertIn("연결을 확인하세요 🚀", stdin_result.stdout)

        with tempfile.TemporaryDirectory() as temporary_directory:
            packet_file = Path(temporary_directory) / "packet.txt"
            packet_file.write_text(self.packet, encoding="utf-8")
            file_result = subprocess.run(
                [sys.executable, str(DECODER), str(packet_file)],
                text=True,
                capture_output=True,
                cwd=ROOT,
                check=False,
            )
        self.assertEqual(file_result.returncode, 0, file_result.stderr)
        self.assertEqual(json.loads(file_result.stdout), self.report)

        invalid_result = subprocess.run(
            [sys.executable, str(DECODER)],
            input=self.packet + "=",
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        self.assertNotEqual(invalid_result.returncode, 0)
        self.assertNotIn("Traceback", invalid_result.stderr)
        self.assertNotIn(self.packet, invalid_result.stdout + invalid_result.stderr)


if __name__ == "__main__":
    unittest.main()
