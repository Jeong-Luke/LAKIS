"""Run dotted unittest targets from this checkout with an installed LAKIS Python."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ISOLATED_ENVIRONMENT_KEYS = ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP")


def run_child(repository_root: Path, targets: list[str]) -> int:
    """Load tests from the checkout, not from the installed application's source."""
    sys.path.insert(0, str(repository_root.resolve()))
    suite = unittest.defaultTestLoader.loadTestsFromNames(targets)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def run_installed_tests(install_root: Path, targets: list[str]) -> int:
    python_executable = (install_root / "python_embeded" / "python.exe").resolve()
    child_environment = os.environ.copy()

    with tempfile.TemporaryDirectory(prefix="lakis-installed-tests-") as temporary_root:
        isolated_root = Path(temporary_root)
        for key in ISOLATED_ENVIRONMENT_KEYS:
            child_directory = isolated_root / key
            child_directory.mkdir()
            child_environment[key] = str(child_directory)
        child_environment["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [
                str(python_executable),
                str(Path(__file__).resolve()),
                "--child",
                "--repository-root",
                str(REPOSITORY_ROOT),
                *targets,
            ],
            cwd=str(REPOSITORY_ROOT),
            env=child_environment,
            check=False,
        )
        return result.returncode


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--child":
        child_parser = argparse.ArgumentParser(add_help=False)
        child_parser.add_argument("--repository-root", type=Path, required=True)
        child_parser.add_argument("targets", nargs="+")
        child_args = child_parser.parse_args(arguments[1:])
        return run_child(child_args.repository_root, child_args.targets)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install-root",
        type=Path,
        required=True,
        help="LAKIS installation containing python_embeded/python.exe",
    )
    parser.add_argument("targets", nargs="+", help="dotted unittest target(s)")
    args = parser.parse_args(arguments)
    return run_installed_tests(args.install_root, args.targets)


if __name__ == "__main__":
    raise SystemExit(main())
