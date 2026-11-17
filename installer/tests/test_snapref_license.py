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
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "snapref_experiment_license", ROOT / "installer/install_snapref_experiment.py"
)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class SnapRefTermsTests(unittest.TestCase):
    def test_official_hosts_only(self):
        for source, target in [
                ("huggingface.co", "https://cas-bridge.xethub.hf.co/data"),
                ("raw.githubusercontent.com", "https://raw.githubusercontent.com/pinned")]:
            INSTALLER.check_origin(source, target)
        for url in ("https://example.invalid/model", "http://huggingface.co/model",
                    "https://user@huggingface.co/model", "https://huggingface.co:444/model",
                    "https://hf.co.example.invalid/model"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                INSTALLER.check_origin("huggingface.co", url)

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

class SnapRefProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="snapref-provision-test-")))
        self.node = self.root / "ComfyUI/custom_nodes/snapref"
        self.model = self.root / "ComfyUI/models/loras" / INSTALLER.WEIGHT_NAME
        for relative in ("ComfyUI/main.py", "python_embeded/python.exe"):
            path = self.root / relative
            path.parent.mkdir(exist_ok=True)
            path.touch()
        (self.root / "VERSION").write_text("8.1.3", encoding="ascii")
        self.files = {
            "__init__.py": b"# fixture inference code\n",
            "simple.py": b"# fixture implementation\n",
            "web/snapref.js": b"// fixture web extension\n",
            "LICENSE": b"fixture code license\n",
            "WEIGHTS_LICENSE.md": b"fixture publisher terms\n",
            "WEIGHTS_NOTICE.txt": b"fixture publisher attribution\n",
        }
        self.weight = b"tiny weight fixture"
        sources, notices, self.publisher = {}, {}, {INSTALLER.WEIGHT_URL: self.weight}
        for name, (source, _) in INSTALLER.SOURCE_FILES.items():
            data = self.files[name]
            git_blob = b"blob %d\0" % len(data) + data
            sources[name] = (source, hashlib.sha1(git_blob).hexdigest())
            self.publisher[f"https://raw.githubusercontent.com/ArcAnima/SnapRef/{INSTALLER.SOURCE_REVISION}/{source}"] = data
        for name, (source, _) in INSTALLER.WEIGHT_NOTICES.items():
            data = self.files[name]
            notices[name] = (source, hashlib.sha256(data).hexdigest())
            self.publisher[f"https://huggingface.co/0ppxnhximxr/snapref-v2a/raw/{INSTALLER.WEIGHT_REVISION}/{source}"] = data
        self.enterContext(patch.multiple(INSTALLER, SOURCE_FILES=sources, WEIGHT_NOTICES=notices,
                                         WEIGHT_SIZE=len(self.weight), WEIGHT_SHA256=hashlib.sha256(self.weight).hexdigest()))
        self.stream = self.enterContext(patch.object(
            INSTALLER, "publisher_stream", side_effect=lambda url, timeout: io.BytesIO(self.publisher[url])))

    def provision(self):
        output = io.StringIO()
        with redirect_stdout(output):
            INSTALLER.main(["--install-root", str(self.root), "--provision-for-update"])
        return json.loads(output.getvalue())

    def test_normal_update_installs_exact_pins_without_manual_ack_or_saved_consent(self):
        with patch.object(INSTALLER, "install") as manual:
            result = self.provision()
        manual.assert_not_called()
        self.assertEqual(Path(result["model"]), self.model)
        expected = {self.node / name: data for name, data in self.files.items()}
        expected.update({
            self.model: self.weight,
            self.root / "VERSION": b"8.1.3",
            self.root / "ComfyUI/main.py": b"",
            self.root / "python_embeded/python.exe": b"",
        })
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}, expected)

    def test_verified_local_files_need_no_network_or_rewrites(self):
        self.provision()
        unrelated = self.node / "user-notes.txt"
        unrelated.write_bytes(b"keep")
        with patch.object(INSTALLER, "publisher_stream", side_effect=AssertionError("unexpected network")), \
             patch.object(INSTALLER.tempfile, "TemporaryDirectory", side_effect=AssertionError("unexpected staging")):
            self.provision()
            INSTALLER.install(self.root, acknowledge_terms=True)
            with self.assertRaises(ValueError):
                INSTALLER.install(self.root)
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_fetches_only_missing_component(self):
        self.provision()
        self.model.unlink()
        self.stream.reset_mock()
        self.provision()
        self.stream.assert_called_once_with(INSTALLER.WEIGHT_URL, timeout=90)
        for name in self.files:
            (self.node / name).unlink()
        (self.node / "web").rmdir()
        self.node.rmdir()
        self.stream.reset_mock()
        self.provision()
        self.assertEqual({call.args[0] for call in self.stream.call_args_list},
                         self.publisher.keys() - {INSTALLER.WEIGHT_URL})

    def test_modified_notice_and_weight_are_preserved_without_network(self):
        self.provision()
        notice = self.node / "WEIGHTS_NOTICE.txt"
        for existing in (notice, self.model):
            with self.subTest(existing=existing):
                original = existing.read_bytes()
                modified = b"x" * len(original)
                existing.write_bytes(modified)
                self.stream.reset_mock()
                error = io.StringIO()
                with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                    self.provision()
                self.assertEqual(caught.exception.code, 1)
                self.assertIn("was not overwritten", error.getvalue())
                self.assertEqual(existing.read_bytes(), modified)
                self.stream.assert_not_called()
                existing.write_bytes(original)

    def test_http_and_hash_failures_report_error_and_clean_staging(self):
        def unavailable(url, timeout):
            if url == INSTALLER.WEIGHT_URL:
                raise HTTPError(url, 503, "Service Unavailable", None, None)
            return io.BytesIO(self.publisher[url])

        for side_effect, message in (
            (unavailable, "HTTP Error 503"),
            (lambda url, timeout: io.BytesIO(
                b"x" * len(self.weight) if url == INSTALLER.WEIGHT_URL else self.publisher[url]),
             "size/SHA-256 verification failed"),
        ):
            with self.subTest(message=message):
                error = io.StringIO()
                with patch.object(INSTALLER, "publisher_stream", side_effect=side_effect), \
                     redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                    self.provision()
                self.assertEqual(caught.exception.code, 1)
                self.assertIn(message, error.getvalue())
                self.assertFalse(self.node.exists())
                self.assertFalse(self.model.exists())
                self.assertEqual(list(self.root.rglob(".lakis-snapref-*")), [])
        self.provision()

    def test_update_mode_requires_correct_source_and_cannot_be_combined_with_ack(self):
        (self.root / "VERSION").write_text("8.1.2", encoding="ascii")
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            self.provision()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("requires a LAKIS 8.1.3 installation", error.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            INSTALLER.main(["--install-root", str(self.root), "--provision-for-update", "--acknowledge-snapref-terms"])
        self.assertEqual(caught.exception.code, 2)
        self.stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
