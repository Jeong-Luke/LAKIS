from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "installer" / "run_installed_tests.py"
CHILD_PROBE = "installer.tests.test_installed_test_runner._InstalledRunnerChildProbe."
SOURCE_FILES = (
    RUNNER,
    ROOT / "installer" / "tests" / "prepare_integrated_preview.py",
    Path(__file__).resolve(),
)
ENVIRONMENT_KEYS = ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP")
CHILD_MODE_ENV = "LAKIS_INSTALLED_TEST_RUNNER_CHILD_MODE"
PROBE_FILE_ENV = "LAKIS_INSTALLED_TEST_RUNNER_PROBE_FILE"


def _embedded_install_root() -> Path | None:
    executable = Path(sys.executable).resolve()
    if executable.name.casefold() != "python.exe":
        return None
    if executable.parent.name.casefold() != "python_embeded":
        return None
    return executable.parent.parent


def _source_snapshot() -> dict[Path, tuple[bytes, int]]:
    return {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in SOURCE_FILES
    }


class _InstalledRunnerChildProbe(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get(CHILD_MODE_ENV) == "success",
        "child-runner probe only",
    )
    def test_reports_isolated_environment_and_visible_output(self):
        environment_paths = {
            key: Path(os.environ[key]).resolve() for key in ENVIRONMENT_KEYS
        }
        temporary_root = environment_paths["LOCALAPPDATA"].parent
        contents = {
            entry.name: sorted(child.name for child in entry.iterdir())
            for entry in temporary_root.iterdir()
        }
        repository_root = Path(__file__).resolve().parents[2]
        report = {
            "environment": {key: str(path) for key, path in environment_paths.items()},
            "temporary_root": str(temporary_root),
            "temporary_contents": contents,
            "dont_write_bytecode": os.environ.get("PYTHONDONTWRITEBYTECODE"),
            "cwd": str(Path.cwd().resolve()),
            "repository_root": str(repository_root.resolve()),
            "repository_root_in_sys_path": str(repository_root.resolve())
            in {str(Path(value).resolve()) for value in sys.path if value},
            "test_module": str(Path(__file__).resolve()),
        }
        Path(os.environ[PROBE_FILE_ENV]).write_text(
            json.dumps(report), encoding="utf-8"
        )
        print("RUNNER_CHILD_STDOUT_MARKER", flush=True)
        print("RUNNER_CHILD_STDERR_MARKER", file=sys.stderr, flush=True)

        self.assertEqual("1", report["dont_write_bytecode"])
        self.assertTrue(report["repository_root_in_sys_path"])

    @unittest.skipUnless(
        os.environ.get(CHILD_MODE_ENV) == "failure",
        "child-runner failure probe only",
    )
    def test_intentional_child_failure(self):
        self._write_workspace_report()
        self.fail("intentional child failure marker")

    @unittest.skipUnless(
        os.environ.get(CHILD_MODE_ENV) == "nonzero-exit",
        "child-runner exit probe only",
    )
    def test_nonstandard_child_exit(self):
        self._write_workspace_report()
        os._exit(23)

    def _write_workspace_report(self):
        temporary_root = Path(os.environ["LOCALAPPDATA"]).resolve().parent
        Path(os.environ[PROBE_FILE_ENV]).write_text(
            json.dumps({"temporary_root": str(temporary_root)}), encoding="utf-8"
        )


@unittest.skipUnless(
    _embedded_install_root() is not None,
    "run focused runner checks with the installed LAKIS embedded Python",
)
class InstalledTestRunnerTests(unittest.TestCase):
    def _invoke_runner(self, target: str, mode: str, temp_parent: Path, marker: Path):
        env = os.environ.copy()
        env.update({
            "LOCALAPPDATA": str(temp_parent / "ambient-local"),
            "APPDATA": str(temp_parent / "ambient-roaming"),
            "TEMP": str(temp_parent),
            "TMP": str(temp_parent),
            "PYTHONDONTWRITEBYTECODE": "0",
            CHILD_MODE_ENV: mode,
            PROBE_FILE_ENV: str(marker),
        })
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--install-root",
                str(_embedded_install_root()),
                target,
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    def _preserved_sibling(self, parent: Path) -> tuple[Path, bytes]:
        sibling = parent / "preexisting-sibling"
        sibling.mkdir()
        sentinel = sibling / "keep.txt"
        sentinel.write_bytes(b"keep this sibling")
        return sentinel, sentinel.read_bytes()

    def test_success_isolates_and_cleans_only_its_workspace(self):
        before_sources = _source_snapshot()
        with tempfile.TemporaryDirectory(prefix="runner-success-test-") as directory:
            temp_parent = Path(directory)
            sentinel, sentinel_bytes = self._preserved_sibling(temp_parent)

            reports = []
            for number in (1, 2):
                marker = temp_parent / f"probe-{number}.json"
                result = self._invoke_runner(
                    CHILD_PROBE
                    + "test_reports_isolated_environment_and_visible_output",
                    "success",
                    temp_parent,
                    marker,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("RUNNER_CHILD_STDOUT_MARKER", result.stdout)
                self.assertIn("RUNNER_CHILD_STDERR_MARKER", result.stderr)
                report = json.loads(marker.read_text(encoding="utf-8"))
                reports.append(report)

                isolated_root = Path(report["temporary_root"])
                self.assertEqual(temp_parent, isolated_root.parent)
                self.assertFalse(isolated_root.exists())
                self.assertEqual(
                    {Path(report["environment"][key]).name for key in ENVIRONMENT_KEYS},
                    set(report["temporary_contents"]),
                )
                isolated_paths = {
                    Path(report["environment"][key]).resolve()
                    for key in ENVIRONMENT_KEYS
                }
                self.assertEqual(len(ENVIRONMENT_KEYS), len(isolated_paths))
                ambient_paths = {
                    "LOCALAPPDATA": temp_parent / "ambient-local",
                    "APPDATA": temp_parent / "ambient-roaming",
                    "TEMP": temp_parent,
                    "TMP": temp_parent,
                }
                for key in ENVIRONMENT_KEYS:
                    isolated_path = Path(report["environment"][key])
                    self.assertEqual(isolated_root, isolated_path.parent)
                    self.assertNotEqual(
                        ambient_paths[key].resolve(),
                        isolated_path,
                    )
                self.assertTrue(
                    all(not children for children in report["temporary_contents"].values()),
                    "the runner workspace must not contain runtime or model copies",
                )
                self.assertEqual("1", report["dont_write_bytecode"])
                self.assertEqual(str(ROOT.resolve()), report["cwd"])
                self.assertEqual(str(ROOT.resolve()), report["repository_root"])
                self.assertEqual(
                    "test_installed_test_runner.py",
                    Path(report["test_module"]).name,
                )
                self.assertTrue(report["repository_root_in_sys_path"])
                self.assertTrue(Path(report["test_module"]).is_relative_to(ROOT))
                self.assertTrue(sentinel.exists())
                self.assertEqual(sentinel_bytes, sentinel.read_bytes())

            self.assertNotEqual(
                reports[0]["temporary_root"],
                reports[1]["temporary_root"],
                "each invocation must receive a unique workspace",
            )
            self.assertEqual(before_sources, _source_snapshot())

    def test_failure_and_nonstandard_exit_clean_up_and_preserve_status(self):
        before_sources = _source_snapshot()
        with tempfile.TemporaryDirectory(prefix="runner-failure-test-") as directory:
            temp_parent = Path(directory)
            sentinel, sentinel_bytes = self._preserved_sibling(temp_parent)

            failure_marker = temp_parent / "failure-probe.json"
            failure = self._invoke_runner(
                CHILD_PROBE + "test_intentional_child_failure",
                "failure",
                temp_parent,
                failure_marker,
            )
            self.assertEqual(1, failure.returncode, failure.stderr)
            self.assertIn("intentional child failure marker", failure.stderr)
            failed_workspace = Path(
                json.loads(failure_marker.read_text(encoding="utf-8"))["temporary_root"]
            )
            self.assertFalse(failed_workspace.exists())
            self.assertTrue(sentinel.exists())
            self.assertEqual(sentinel_bytes, sentinel.read_bytes())

            exit_marker = temp_parent / "exit-probe.json"
            nonstandard_exit = self._invoke_runner(
                CHILD_PROBE + "test_nonstandard_child_exit",
                "nonzero-exit",
                temp_parent,
                exit_marker,
            )
            self.assertEqual(23, nonstandard_exit.returncode, nonstandard_exit.stderr)
            exited_workspace = Path(
                json.loads(exit_marker.read_text(encoding="utf-8"))["temporary_root"]
            )
            self.assertFalse(exited_workspace.exists())
            self.assertTrue(sentinel.exists())
            self.assertEqual(sentinel_bytes, sentinel.read_bytes())

        self.assertEqual(before_sources, _source_snapshot())


if __name__ == "__main__":
    unittest.main()
