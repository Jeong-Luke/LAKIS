import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/external_ui"))
import anima_reference as ref


class SnapRefConsentTest(unittest.TestCase):
    def test_explicit_consent_is_scoped_and_survives_reload(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            state = base / "install-a" / "ui.json"
            other = base / "install-b" / "ui.json"
            request = {"anima_reference": {"enabled": True}}
            with self.assertRaises(ValueError):
                ref.require_consent(request, state)
            ref.require_consent({"anima_reference": {"enabled": False}}, state)
            ref.require_consent({}, state)
            policy = ref.consent_status(state)["policy_id"]
            for rejected in [None, {}, {"accepted": 1, "policy_id": policy},
                             {"accepted": True, "policy_id": "old"}]:
                with self.assertRaises(ValueError):
                    ref.accept_terms(state, rejected)
            self.assertFalse(state.parent.exists())
            ref.accept_terms(state, {"accepted": True, "policy_id": policy})
            ref.require_consent(request, state)
            with self.assertRaises(ValueError):
                ref.require_consent(request, other)
            self.assertFalse(state.exists())
            receipt = state.with_name("snapref-use-consent.json")
            for data in [b"invalid", b"\xff", b"[]", json.dumps(
                    {"accepted": True, "policy_id": "previous terms"}).encode()]:
                receipt.write_bytes(data)
                with self.assertRaises(ValueError):
                    ref.require_consent(request, state)

    def test_policy_matches_pinned_weight_and_publisher_license(self):
        import runpy
        pins = runpy.run_path(str(ROOT / "installer/install_snapref_experiment.py"))
        license_file = ROOT / "third_party_licenses/CircleStone-Labs-Non-Commercial-License-v1.2.md"
        self.assertEqual(ref.CONSENT_POLICY_ID, ":".join((
            pins["WEIGHT_NAME"], pins["WEIGHT_SHA256"],
            hashlib.sha256(license_file.read_bytes().replace(b"\r\n", b"\n").removesuffix(b"\n")).hexdigest())))


if __name__ == "__main__":
    unittest.main()
