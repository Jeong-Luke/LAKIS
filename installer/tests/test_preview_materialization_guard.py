from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PREVIEW_SCRIPT = ROOT / "installer" / "tests" / "prepare_integrated_preview.py"


class PreviewMaterializationGuardTests(unittest.TestCase):
    def _preview_arguments(self, workspace_parent: Path) -> list[str]:
        return [
            "--baseline", str(workspace_parent / "missing-baseline"),
            "--baseline-manifest-sha256", "0" * 64,
            "--source-revision", "a" * 40,
            "--source-diff", str(workspace_parent / "missing-source.diff"),
            "--workspace-parent", str(workspace_parent),
            "--moss-models", str(workspace_parent / "missing-moss-models"),
            "--anima-models", str(workspace_parent / "missing-anima-models"),
        ]

    def _run_preview(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PREVIEW_SCRIPT), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    def test_refuses_without_switch_before_reading_inputs_or_allocating_workspace(self):
        with tempfile.TemporaryDirectory(prefix="preview-guard-test-") as directory:
            workspace_parent = Path(directory)
            sibling = workspace_parent / "preexisting-sibling"
            sibling.mkdir()
            sentinel = sibling / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            before_entries = set(workspace_parent.iterdir())

            result = self._run_preview(self._preview_arguments(workspace_parent))

            self.assertEqual(2, result.returncode)
            self.assertIn("installer/run_installed_tests.py", result.stderr)
            self.assertIn("--materialize-runtime", result.stderr)
            self.assertNotIn("No such file or directory", result.stderr)
            self.assertEqual(before_entries, set(workspace_parent.iterdir()))
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_materialization_switch_retains_required_build_inputs(self):
        result = self._run_preview(["--materialize-runtime"])

        self.assertEqual(2, result.returncode)
        self.assertIn("required with --materialize-runtime", result.stderr)
        self.assertNotIn("For ordinary checks", result.stderr)
        self.assertNotIn("PRIVATE_PREVIEW_WORKSPACE=", result.stdout)


if __name__ == "__main__":
    unittest.main()
