"""Engine-independent wildcard behavior, using disposable user files."""

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "external_ui"))
import wildcard_service as service


class WildcardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.builtin = self.root / "builtin"
        self.user = self.root / "user"
        self.builtin.mkdir()
        self.user.mkdir()
        (self.builtin / "outfit.txt").write_text("# comment\nred shirt\nblue shirt\n", encoding="utf-8")

    def test_deterministic_resolution_exclusions_and_same_token(self):
        items = service.inventory(self.builtin, self.user)["items"]
        payload = {"enabled": True, "seed": 42,
                   "prompt": {"general": "__outfit__, __outfit__", "negative": "__outfit__"},
                   "inpaint": {"enabled": False},
                   "excluded": {"outfit": ["blue shirt"]}}
        original = copy.deepcopy(payload)
        result = service.resolve(payload, items)
        self.assertEqual(result["prompt"]["general"], "red shirt, red shirt")
        self.assertEqual(result["prompt"]["negative"], "red shirt")
        self.assertEqual(result, service.resolve(payload, items))
        self.assertEqual(len(result["selections"]), 1)
        self.assertEqual(result["selections"][0]["file_sha256"],
                         hashlib.sha256((self.builtin / "outfit.txt").read_bytes()).hexdigest().upper())
        self.assertEqual(payload, original)

    def test_user_override_and_invalid_or_empty_choices(self):
        (self.user / "outfit.txt").write_text("green shirt\n", encoding="utf-8")
        items = service.inventory(self.builtin, self.user)["items"]
        payload = {"enabled": True, "seed": 7, "prompt": {"general": "__outfit__"}}
        result = service.resolve(payload, items)
        self.assertEqual(result["prompt"]["general"], "green shirt")
        self.assertEqual(result["selections"][0]["source"], "USER")
        for bad in (
            {**payload, "enabled": False},
            {**payload, "excluded": {"outfit": ["green shirt"]}},
            {**payload, "prompt": {"general": "__missing__"}},
            {**payload, "prompt": {"general": "__../outside__"}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                service.resolve(bad, items)

    def test_nested_token_is_rejected_and_remove_inpaint_is_unchanged(self):
        (self.user / "nested.txt").write_text("__outfit__\n", encoding="utf-8")
        items = service.inventory(self.builtin, self.user)["items"]
        with self.assertRaisesRegex(ValueError, "중첩"):
            service.resolve({"enabled": True, "prompt": {"general": "__nested__"}}, items)
        inpaint = {"operation": "remove", "prompt": "__missing__", "negative_prompt": ""}
        result = service.resolve({"prompt": {"general": "plain"}, "inpaint": inpaint}, items)
        self.assertEqual(result["inpaint"], inpaint)
        self.assertEqual(result["selections"], [])


if __name__ == "__main__":
    unittest.main()
