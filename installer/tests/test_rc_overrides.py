from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RcOverrideContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = (ROOT / "installer" / "LAKIS_Launcher.cs").read_text(encoding="utf-8")
        cls.updater = (ROOT / "installer" / "LAKIS_Updater.cs").read_text(encoding="utf-8")

    def test_public_defaults_are_unchanged(self):
        for source in (self.launcher, self.updater):
            self.assertIn("https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-latest.json", source)
            self.assertIn("https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-latest.json", source)
            self.assertIn("String.IsNullOrWhiteSpace(overrideUrl)", source)
        self.assertIn("https://github.com/Jeong-Luke/LAKIS/releases/download/v", self.launcher)

    def test_overrides_are_loopback_only_and_block_unsafe_forms(self):
        for source in (self.launcher, self.updater):
            self.assertIn('Uri.UriSchemeHttp', source)
            self.assertIn(r'^(127\\.0\\.0\\.1|localhost):[0-9]+$', source)
            self.assertIn('!String.IsNullOrEmpty(uri.UserInfo)', source)
            self.assertIn('!String.IsNullOrEmpty(uri.Fragment)', source)
            self.assertIn('!String.IsNullOrEmpty(uri.Query)', source)
            self.assertIn('part == "." || part == ".."', source)
            self.assertIn("value.IndexOf('\\\\')", source)
            self.assertIn('"(^|/)\\\\.{1,2}(/|$)|%2e|%2f|%5c"', source)
        self.assertNotIn("Uri.UriSchemeHttps", self.launcher)
        self.assertNotIn("Uri.UriSchemeHttps", self.updater)

    def test_release_assets_share_one_rc_base(self):
        self.assertIn("LAKIS_RC_RELEASE_BASE_URL", self.launcher)
        self.assertIn('ReleaseAssetUrl(version, "release-layout.json")', self.launcher)
        self.assertIn('ReleaseAssetUrl(layout.version, "LAKIS_RepairPack.zip")', self.launcher)

    def test_manifest_and_restart_environment_contract(self):
        for source in (self.launcher, self.updater):
            self.assertIn("LAKIS_RC_MANIFEST_URL", source)
            self.assertIn("CopyRcEnvironment", source)
        self.assertIn("CopyRcEnvironment(updaterInfo)", self.launcher)
        self.assertIn("CopyRcEnvironment(helperInfo)", self.updater)
        self.assertIn("CopyRcEnvironment(launcherInfo)", self.updater)
        self.assertIn("UseShellExecute = false", self.launcher)
        self.assertIn("UseShellExecute = false", self.updater)


if __name__ == "__main__":
    unittest.main(verbosity=2)
