from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src" / "external_ui"))

import serve_ui  # noqa: E402


class LegalDocumentTests(unittest.TestCase):
    def test_inpaint_license_opens_the_bundled_official_document(self):
        relative = serve_ui.LLLITE_INPAINT_LICENSE_PATH.relative_to(serve_ui.INSTALL_ROOT)
        actual_document = REPOSITORY_ROOT / relative
        expected_document = (
            REPOSITORY_ROOT / "third_party_licenses"
            / "CircleStone-Labs-Non-Commercial-License-v1.0.txt"
        )
        original = expected_document.read_bytes()
        self.assertTrue(original.startswith(b"CircleStone Labs Non-Commercial License v1.0"))
        with mock.patch.object(serve_ui, "INSTALL_ROOT", REPOSITORY_ROOT), \
                mock.patch.object(serve_ui, "LLLITE_INPAINT_LICENSE_PATH", actual_document), \
                mock.patch.object(serve_ui.os, "startfile") as open_file:
            result = serve_ui.open_legal_document("lllite-inpaint")
        self.assertEqual(result, {"ok": True, "document": "lllite-inpaint"})
        open_file.assert_called_once_with(str(expected_document))
        self.assertEqual(original, expected_document.read_bytes())

    def test_unknown_document_is_not_opened(self):
        with mock.patch.object(serve_ui.os, "startfile") as open_file:
            with self.assertRaises(FileNotFoundError):
                serve_ui.open_legal_document("../LICENSE.md")
        open_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
