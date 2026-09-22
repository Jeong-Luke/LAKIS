import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "installer"
VERSION = (REPO / "VERSION").read_text(encoding="utf-8").strip()
AUDITORS = ("gpt", "deepseek", "codex")
ASSETS = (
    "LAKIS_Setup.exe",
    "LAKIS.exe",
    "LAKIS_Patcher.exe",
    "LAKIS_Updater.exe",
    "LAKIS_Desktop.exe",
    "LAKIS_Model_Importer.exe",
    "Uninstall_LAKIS.exe",
    "Microsoft.Web.WebView2.Core.dll",
    "Microsoft.Web.WebView2.WinForms.dll",
    "WebView2Loader.dll",
    "release-layout.json",
    "LAKIS_RepairPack.zip",
    f"LAKIS_CMD_Installer_{VERSION}.zip",
    "private-rc-build.json",
)


def run_ps(script, *args):
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *map(str, args)],
        cwd=REPO, text=True, encoding="utf-8", errors="replace", capture_output=True,
    )
    return result.returncode, result.stdout + result.stderr
def current_fingerprint(temp_root):
    output = temp_root / "fingerprint.json"
    code, log = run_ps(INSTALLER / "New-ReleaseAuditFingerprint.ps1", "-OutputPath", output)
    if code:
        raise AssertionError(log)
    return json.loads(output.read_text(encoding="utf-8-sig"))["fingerprint_sha256"]


def audit_record(auditor, fingerprint, status="PASS"):
    return {
        "schema": 1,
        "auditor": auditor,
        "version": VERSION,
        "fingerprint_sha256": fingerprint,
        "status": status,
        "blockers": [],
        "findings": [],
    }


def outage_exception(fingerprint):
    return {
        "schema": 1,
        "type": "owner_approved_two_party_exception",
        "version": VERSION,
        "fingerprint_sha256": fingerprint,
        "owner_approved": True,
        "reason": "GPT_SERVICE_UNAVAILABLE",
        "required_auditors": ["deepseek", "codex"],
    }


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class ThreePartyAuditGateTests(unittest.TestCase):
    def test_fingerprint_covers_private_rc_verification_tools(self):
        source = (INSTALLER / "New-ReleaseAuditFingerprint.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('"tools\\rc_patcher"', source)

    def make_evidence(self, root, fingerprint):
        evidence = root / "audit"
        evidence.mkdir()
        for auditor in AUDITORS:
            write_json(evidence / f"{auditor}.json", audit_record(auditor, fingerprint))
        return evidence

    def run_gate(self, evidence):
        return run_ps(
            INSTALLER / "Test-ThreePartyAuditGate.ps1",
            "-Version", VERSION, "-EvidenceDirectory", evidence,
        )
    def test_pass_requires_clean_three_party_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.make_evidence(root, current_fingerprint(root))
            code, log = self.run_gate(evidence)
            self.assertEqual(0, code, log)
            self.assertIn("THREE_PARTY_AUDIT_GATE_OK", log)

    def test_pass_with_findings_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            record = audit_record("gpt", fingerprint)
            record["findings"] = [{"severity": "medium", "claim": "open"}]
            write_json(evidence / "gpt.json", record)
            code, log = self.run_gate(evidence)
            self.assertNotEqual(0, code)
            self.assertIn("THREE_PARTY_AUDIT_BLOCKED", log)

    def test_stale_fingerprint_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.make_evidence(root, current_fingerprint(root))
            record = json.loads((evidence / "codex.json").read_text(encoding="utf-8"))
            record["fingerprint_sha256"] = "0" * 64
            write_json(evidence / "codex.json", record)
            code, log = self.run_gate(evidence)
            self.assertNotEqual(0, code)
            self.assertIn("THREE_PARTY_AUDIT_STALE", log)
    def test_token_limited_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            write_json(evidence / "deepseek.json", audit_record("deepseek", fingerprint, "TOKEN_LIMITED"))
            code, log = self.run_gate(evidence)
            self.assertNotEqual(0, code)
            self.assertIn("THREE_PARTY_AUDIT_INCOMPLETE", log)

    def test_missing_primary_auditor_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self.make_evidence(root, current_fingerprint(root))
            (evidence / "codex.json").unlink()
            code, log = self.run_gate(evidence)
            self.assertNotEqual(0, code)
            self.assertIn("THREE_PARTY_AUDIT_MISSING", log)

    def test_owner_approved_two_party_exception_passes_without_gpt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            (evidence / "gpt.json").unlink()
            write_json(evidence / "owner-two-party-exception.json", {
                "schema": 1,
                "type": "owner_approved_two_party_exception",
                "version": VERSION,
                "fingerprint_sha256": fingerprint,
                "owner_approved": True,
                "reason": "GPT_SERVICE_UNAVAILABLE",
                "required_auditors": ["deepseek", "codex"],
            })
            code, log = self.run_gate(evidence)
            self.assertEqual(0, code, log)
            self.assertIn("OWNER_APPROVED_TWO_PARTY_AUDIT_GATE_OK", log)

    def test_two_party_exception_requires_exact_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            (evidence / "gpt.json").unlink()
            write_json(evidence / "owner-two-party-exception.json", {
                "schema": 1,
                "type": "owner_approved_two_party_exception",
                "version": VERSION,
                "fingerprint_sha256": "0" * 64,
                "owner_approved": True,
                "reason": "GPT_SERVICE_UNAVAILABLE",
                "required_auditors": ["deepseek", "codex"],
            })
            code, log = self.run_gate(evidence)
            self.assertNotEqual(0, code)
            self.assertIn("TWO_PARTY_AUDIT_EXCEPTION_INVALID", log)

    def test_two_party_preserves_stale_gpt_but_blocks_current_known_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            write_json(evidence / "owner-two-party-exception.json", outage_exception(fingerprint))
            write_json(evidence / "gpt.json", audit_record("gpt", "0" * 64, "FAIL"))
            code, log = self.run_gate(evidence)
            self.assertEqual(code, 0, log)
            write_json(evidence / "gpt.json", audit_record("gpt", fingerprint, "FAIL"))
            code, log = self.run_gate(evidence)
            self.assertNotEqual(code, 0)
            self.assertIn("TWO_PARTY_AUDIT_KNOWN_GPT_FAILURE", log)

    def test_two_party_exception_rejects_coerced_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            (evidence / "gpt.json").unlink()
            for field, value in (
                ("schema", "1"), ("schema", True),
                ("owner_approved", 1), ("owner_approved", "true"),
                ("owner_approved", False), ("owner_approved", None),
                ("reason", "gpt_service_unavailable"),
                ("reason", ["GPT_SERVICE_UNAVAILABLE"]),
                ("required_auditors", ["deepseek", "deepseek"]),
                ("required_auditors", ["DeepSeek", "codex"]),
                ("version", "0.0.0"),
            ):
                with self.subTest(field=field, value=value):
                    record = outage_exception(fingerprint)
                    record[field] = value
                    write_json(evidence / "owner-two-party-exception.json", record)
                    code, log = self.run_gate(evidence)
                    self.assertNotEqual(0, code)
                    self.assertIn("TWO_PARTY_AUDIT_EXCEPTION_INVALID", log)

    def test_pass_rejects_non_array_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            for field in ("blockers", "findings"):
                for value in (None, 0, False, {}, ""):
                    with self.subTest(field=field, value=value):
                        record = audit_record("deepseek", fingerprint)
                        record[field] = value
                        write_json(evidence / "deepseek.json", record)
                        code, log = self.run_gate(evidence)
                        self.assertNotEqual(0, code)
                        self.assertIn("THREE_PARTY_AUDIT_INVALID_RECORD", log)

    def test_two_party_does_not_waive_remaining_auditors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            (evidence / "gpt.json").unlink()
            write_json(evidence / "owner-two-party-exception.json", outage_exception(fingerprint))
            for auditor in ("deepseek", "codex"):
                with self.subTest(auditor=auditor):
                    (evidence / f"{auditor}.json").unlink()
                    code, log = self.run_gate(evidence)
                    self.assertNotEqual(0, code)
                    self.assertIn("THREE_PARTY_AUDIT_MISSING", log)
                    write_json(evidence / f"{auditor}.json", audit_record(auditor, fingerprint, "TOKEN_LIMITED"))
                    code, log = self.run_gate(evidence)
                    self.assertNotEqual(0, code)
                    self.assertIn("THREE_PARTY_AUDIT_INCOMPLETE", log)
                    write_json(evidence / f"{auditor}.json", audit_record(auditor, fingerprint))

    def test_false_valued_findings_are_still_open_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            for field in ("blockers", "findings"):
                for value in ([False], [None], [0]):
                    with self.subTest(field=field, value=value):
                        record = audit_record("deepseek", fingerprint)
                        record[field] = value
                        write_json(evidence / "deepseek.json", record)
                        code, log = self.run_gate(evidence)
                        self.assertNotEqual(0, code)
                        self.assertIn("THREE_PARTY_AUDIT_BLOCKED", log)

    def test_auditor_fields_reject_type_coercion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = current_fingerprint(root)
            evidence = self.make_evidence(root, fingerprint)
            for field, value in (("schema", "1"), ("schema", True), ("status", ["PASS"]), ("auditor", ["deepseek"])):
                with self.subTest(field=field, value=value):
                    record = audit_record("deepseek", fingerprint)
                    record[field] = value
                    write_json(evidence / "deepseek.json", record)
                    code, log = self.run_gate(evidence)
                    self.assertNotEqual(0, code)
                    self.assertIn("THREE_PARTY_AUDIT_INVALID_RECORD", log)


class ReleaseApprovalGateTests(unittest.TestCase):
    REQUIRED_CHECKS = (
        "fresh_setup", "update_745_to_750", "updater_self_update",
        "updater_interruption_recovery", "automatic_restart", "second_restart",
        "repair", "runtime_identity", "release_layout_consistency",
        "automatic_repair_mixed_version", "network_consistency_bypass", "runtime_capability",
        "desktop_visual", "basic_generation", "inpaint",
        "two_consecutive_generations", "one_prompt_per_click", "final_saver_775",
        "actual_output_file", "ui_return", "user_data_preservation",
    )
    def prepare(self, root):
        fingerprint = current_fingerprint(root)
        dist = root / "dist"
        evidence = root / "approval"
        dist.mkdir()
        evidence.mkdir()
        hashes = {}
        for index, name in enumerate(ASSETS):
            payload = f"test-artifact-{index}-{name}".encode()
            (dist / name).write_bytes(payload)
            hashes[name] = hashlib.sha256(payload).hexdigest().upper()
        canonical = "\n".join(f"{name}\t{hashes[name]}" for name in ASSETS)
        artifact_set = hashlib.sha256(canonical.encode()).hexdigest().upper()
        private_rc = {
            "schema": 1, "version": VERSION, "fingerprint_sha256": fingerprint,
            "status": "PASS", "artifact_set_sha256": artifact_set,
            "checks": {name: True for name in self.REQUIRED_CHECKS},
            "artifacts": hashes,
        }
        owner = {
            "schema": 1, "version": VERSION, "fingerprint_sha256": fingerprint,
            "status": "APPROVED", "artifact_set_sha256": artifact_set,
            "approved_by": "release-gate-test",
        }
        write_json(evidence / "private_rc.json", private_rc)
        write_json(evidence / "owner.json", owner)
        return evidence, dist

    def run_gate(self, evidence, dist):
        return run_ps(
            INSTALLER / "Test-ReleaseApprovalGate.ps1",
            "-Version", VERSION, "-EvidenceDirectory", evidence, "-DistDirectory", dist,
        )
    def test_valid_exact_artifact_approval_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, dist = self.prepare(Path(directory))
            code, log = self.run_gate(evidence, dist)
            self.assertEqual(0, code, log)
            self.assertIn("RELEASE_APPROVAL_GATE_OK", log)

    def test_missing_private_rc_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, dist = self.prepare(Path(directory))
            (evidence / "private_rc.json").unlink()
            code, log = self.run_gate(evidence, dist)
            self.assertNotEqual(0, code)
            self.assertIn("RELEASE_APPROVAL_MISSING", log)

    def test_missing_owner_approval_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, dist = self.prepare(Path(directory))
            (evidence / "owner.json").unlink()
            code, log = self.run_gate(evidence, dist)
            self.assertNotEqual(0, code)
            self.assertIn("RELEASE_APPROVAL_MISSING", log)

    def test_artifact_hash_mismatch_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, dist = self.prepare(Path(directory))
            (dist / "LAKIS.exe").write_bytes(b"tampered")
            code, log = self.run_gate(evidence, dist)
            self.assertNotEqual(0, code)
            self.assertIn("RELEASE_APPROVAL_ARTIFACT_MISMATCH", log)

    def test_cmd_asset_missing_or_changed_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, dist = self.prepare(Path(directory))
            asset = dist / f"LAKIS_CMD_Installer_{VERSION}.zip"
            asset.unlink()
            code, log = self.run_gate(evidence, dist)
            self.assertNotEqual(0, code)
            self.assertIn("RELEASE_APPROVAL_ARTIFACT_MISSING", log)
            asset.write_bytes(b"unapproved CMD installer")
            code, log = self.run_gate(evidence, dist)
            self.assertNotEqual(0, code)
            self.assertIn("RELEASE_APPROVAL_ARTIFACT_MISMATCH", log)

    def test_rc_build_identity_file_is_bound_to_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, dist = self.prepare(Path(directory))
            (dist / "private-rc-build.json").write_text('{"source_commit":"different"}')
            code, log = self.run_gate(evidence, dist)
            self.assertNotEqual(code, 0)
            self.assertIn("RELEASE_APPROVAL_ARTIFACT_MISMATCH", log)

    def test_release_approval_rejects_type_coercion(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, dist = self.prepare(Path(directory))
            rc_path = evidence / "private_rc.json"
            original = rc_path.read_text()
            for field, value in (("schema", "1"), ("schema", True), ("status", ["PASS"]),
                                 ("status", "pass"), ("fingerprint_sha256", ["0" * 64])):
                with self.subTest(field=field, value=value):
                    record = json.loads(original)
                    record[field] = value
                    write_json(rc_path, record)
                    code, log = self.run_gate(evidence, dist)
                    self.assertNotEqual(code, 0, log)
            for value in (1, "true", "false", None, [True]):
                with self.subTest(check=value):
                    record = json.loads(original)
                    record["checks"]["fresh_setup"] = value
                    write_json(rc_path, record)
                    code, log = self.run_gate(evidence, dist)
                    self.assertNotEqual(code, 0, log)
                    self.assertIn("RELEASE_APPROVAL_RC_CHECK_FAILED", log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
