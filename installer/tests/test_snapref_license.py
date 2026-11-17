"""Offline tests of the experimental installer's terms boundary; no real models."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "snapref_experiment_license", ROOT / "installer/install_snapref_experiment.py"
)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class SnapRefTermsTests(unittest.TestCase):
    def test_missing_acknowledgement_fails_before_paths_or_network(self):
        with patch.object(INSTALLER, "inference_files") as files, \
             patch.object(INSTALLER, "download_weight") as download, \
             patch.object(INSTALLER.Path, "resolve") as resolve:
            with self.assertRaisesRegex(ValueError, "Non-Commercial License v1.2"):
                INSTALLER.install("not-an-installation")
            files.assert_not_called()
            download.assert_not_called()
            resolve.assert_not_called()

    def test_truthy_values_do_not_substitute_for_explicit_acknowledgement(self):
        with patch.object(INSTALLER, "inference_files") as files:
            for value in (None, 1, "true", "accepted"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    INSTALLER.install("not-an-installation", acknowledge_terms=value)
            files.assert_not_called()

    def test_cli_without_acknowledgement_displays_terms_and_does_not_install(self):
        error = io.StringIO()
        with patch.object(INSTALLER, "install") as install, redirect_stderr(error):
            with self.assertRaises(SystemExit) as caught:
                INSTALLER.main(["--install-root", "unused"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn(INSTALLER.WEIGHT_LICENSE_URL, error.getvalue())
        self.assertIn(INSTALLER.WEIGHT_NOTICE_URL, error.getvalue())
        self.assertIn("non-production", error.getvalue())
        self.assertIn("do not grant commercial/product-integration rights", error.getvalue())
        install.assert_not_called()

    def test_help_discloses_restrictions_without_installing(self):
        output = io.StringIO()
        with patch.object(INSTALLER, "install") as install, redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                INSTALLER.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        compact = "".join(output.getvalue().split())
        self.assertIn("CircleStoneLabsNon-CommercialLicensev1.2", compact)
        self.assertIn("non-productionrestrictions", compact)
        self.assertIn("--acknowledge-snapref-terms", compact)
        install.assert_not_called()

    def test_cli_passes_explicit_acknowledgement_to_install(self):
        output = io.StringIO()
        with patch.object(INSTALLER, "install", return_value={"ok": True}) as install, \
             redirect_stdout(output):
            INSTALLER.main(["--install-root", "fixture", "--acknowledge-snapref-terms"])
        install.assert_called_once_with(Path("fixture"), acknowledge_terms=True)
        self.assertEqual(json.loads(output.getvalue()), {"ok": True})

    def test_acknowledged_install_preserves_both_weight_notices(self):
        # Tiny fixtures exercise publication only, not model or licence validity.
        files = {
            "__init__.py": b"# fixture inference code\n",
            "LICENSE": b"fixture code license\n",
            "WEIGHTS_LICENSE.md": b"fixture publisher terms\n",
            "WEIGHTS_NOTICE.txt": b"fixture publisher attribution\n",
        }
        weight = b"tiny weight fixture"
        with tempfile.TemporaryDirectory(prefix="snapref-terms-test-") as temporary:
            root = Path(temporary)
            for relative in ("ComfyUI/custom_nodes", "ComfyUI/models/loras", "python_embeded"):
                (root / relative).mkdir(parents=True)
            (root / "ComfyUI/main.py").write_bytes(b"")
            (root / "python_embeded/python.exe").write_bytes(b"")
            with patch.object(INSTALLER, "inference_files", return_value=files), \
                 patch.object(INSTALLER, "WEIGHT_SIZE", len(weight)), \
                 patch.object(INSTALLER, "WEIGHT_SHA256", hashlib.sha256(weight).hexdigest()), \
                 patch.object(INSTALLER, "download_weight", side_effect=lambda target: target.write_bytes(weight)):
                result = INSTALLER.install(root, acknowledge_terms=True)
                package = root / "ComfyUI/custom_nodes/snapref"
                for name, expected in files.items():
                    self.assertEqual((package / name).read_bytes(), expected)
                self.assertEqual(Path(result["model"]).read_bytes(), weight)
                # Reusing an existing adapter must still require confirmation.
                with self.assertRaises(ValueError):
                    INSTALLER.install(root)
                (package / "WEIGHTS_NOTICE.txt").write_bytes(b"user-modified notice")
                with self.assertRaisesRegex(ValueError, "was not overwritten"):
                    INSTALLER.install(root, acknowledge_terms=True)
                self.assertEqual((package / "WEIGHTS_NOTICE.txt").read_bytes(), b"user-modified notice")


if __name__ == "__main__":
    unittest.main()
