"""Offline packaging checks; set LAKIS_8132_BASELINE and LAKIS_8132_STAGE for the native check."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage_8132_hotfix as hotfix
from build_813_file_patch import UPDATER_SOURCES, compiler, git


class HotfixPackaging(unittest.TestCase):
    def assert_package(self, stage, base_layout, baseline):
        manifest = json.loads((stage / hotfix.MANIFEST).read_bytes())
        report = json.loads((stage / hotfix.REPORT).read_bytes())
        layout = json.loads((stage / hotfix.LAYOUT).read_bytes())
        with zipfile.ZipFile(stage / hotfix.PACK) as archive:
            self.assertEqual(len(baseline), len(archive.infolist()))
            repaired = {entry.filename: archive.read(entry) for entry in archive.infolist()}
        ui = {
            f"ComfyUI/LAKIS/external_ui/{name}": f"src/external_ui/{name}"
            for name in ("index.html", "anima-reference.js", "anima-reference.css")
        }
        aliases = {"LAKIS_Updater.exe", "LAKIS_Patcher.exe"}
        helper = "ComfyUI/LAKIS/install_snapref.py"
        replacements = {path: hotfix.canonical_source(source) for path, source in ui.items()}
        replacements["COMPLIANCE.md"] = hotfix.canonical_source("COMPLIANCE.md")
        replacements.update({path: (stage / path).read_bytes() for path in aliases})
        self.assertEqual(replacements["LAKIS_Updater.exe"], replacements["LAKIS_Patcher.exe"])
        self.assertEqual({**baseline, **replacements, "VERSION": b"8.1.3.2"}, repaired)
        self.assertEqual(baseline[helper], (stage / "install_snapref.py").read_bytes())
        self.assertEqual(dict(base_layout, version="8.1.3.2", files=[
            {"path": path, "size": len(data)} for path, data in sorted(repaired.items())
        ]), layout)
        self.assertEqual({*aliases, *(Path(path).name for path in ui), "COMPLIANCE.md", "install_snapref.py",
                          hotfix.LAYOUT, hotfix.PACK, hotfix.MANIFEST, hotfix.REPORT},
                         {file.name for file in stage.iterdir()})
        self.assertEqual((2, "file-patch", "8.1.3.2", "8.1.0", "8.1.0", []), tuple(
            manifest[key] for key in ("schema", "kind", "version", "minimum_version", "minimum_updater_version", "delete")
        ))
        self.assertNotIn("runtime_bundle", manifest)
        release = "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.3.2"
        records = {row["path"]: row for row in manifest["files"]}
        self.assertEqual(set(ui) | aliases, set(records))
        self.assertEqual(len(records), len(manifest["files"]))
        for path, row in records.items():
            flat = stage / Path(path).name
            self.assertEqual(repaired[path], flat.read_bytes())
            self.assertEqual((f"{release}/{flat.name}", hotfix.sha256(repaired[path])), (row["url"], row["sha256"]))

        overlays = {row["path"]: row for row in report["required_finisher_overlays"]}
        self.assertEqual(set(ui) | {"COMPLIANCE.md"}, set(overlays))
        for path, row in overlays.items():
            versions = ["8.1.0", "8.1.1", "8.1.2"]
            if path == "COMPLIANCE.md":
                versions += ["8.1.3", "8.1.3.1"]
            flat = stage / Path(path).name
            self.assertEqual(repaired[path], flat.read_bytes())
            self.assertEqual((versions, f"{release}/{flat.name}", len(repaired[path]), hotfix.sha256(repaired[path])),
                             (row["source_versions"], row["url"], row["bytes"], row["sha256"]))
        self.assertEqual("private-draft-release-blocked", report["status"])
        self.assertEqual(hotfix.sha256(baseline[helper]), report["existing_finisher_work"]["helper"]["sha256"])
        descriptor = hotfix.canonical_source("installer/tests/fixtures/hotfix-public-813-runtime.json")
        self.assertEqual(hotfix.sha256(descriptor), report["runtime_replacement"]["descriptor_sha256"])
        return report

    def test_public_pins_reject_changed_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / hotfix.LAYOUT).write_bytes(b"x" * 20_944)
            with self.assertRaisesRegex(ValueError, "8\\.1\\.3\\.1 asset size or SHA-256 mismatch"):
                hotfix.load_baseline(site)

    def test_stages_only_the_expected_overlay_in_unique_directories(self):
        def compile_fixture(output, inputs):
            installer = inputs / "installer"
            installer.mkdir(parents=True)
            for name in ("LAKIS_Updater.cs", *hotfix.RUNTIME_HELPERS):
                shutil.copyfile(hotfix.ROOT / "installer" / name, installer / name)
            output.write_bytes(b"new updater fixture")

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            layout = {"schema": 1, "product": "LAKIS", "editable_template_policy": "preserve-v1",
                      "retired": ["ComfyUI/LAKIS/external_ui/light-control-prototype.css"]}
            baseline = {path: b"old bytes" for path in hotfix.ASSETS}
            baseline.update({
                hotfix.HELPER: hotfix.canonical_source(hotfix.SOURCE), "VERSION": b"8.1.3.1",
                "ComfyUI/LAKIS/external_ui/workflows/LAKIS_custom_v8.0_editable.json": b"retained template",
            })
            hotfix.write_repair(folder, layout, baseline, "8.1.3.1")
            pins = {}
            for name in ("LAKIS_RepairPack.zip", "release-layout.json"):
                data = (folder / name).read_bytes()
                pins[name] = (len(data), hotfix.sha256(data))
            with patch.object(hotfix, "BASELINE", pins), patch.object(hotfix, "compile_updater", compile_fixture):
                first = hotfix.stage_hotfix(folder, folder)
                second = hotfix.stage_hotfix(folder, folder)
            stage = Path(first["stage"])
            self.assertNotEqual(stage, Path(second["stage"]))
            self.assert_package(stage, json.loads((folder / hotfix.LAYOUT).read_bytes()), baseline)
            for artifact in first["artifacts"].values():
                path = Path(artifact["path"])
                self.assertEqual(stage, path.parent)
                self.assertEqual((path.stat().st_size, hotfix.sha256(path.read_bytes())),
                                 (artifact["bytes"], artifact["sha256"]))

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LAKIS_8132_BASELINE") and
                         os.environ.get("LAKIS_8132_STAGE"), "set a pinned baseline and private stage on Windows")
    def test_public_package_stock_readers_and_embedded_helpers(self):
        stage = Path(os.environ["LAKIS_8132_STAGE"])
        layout, baseline = hotfix.load_baseline(Path(os.environ["LAKIS_8132_BASELINE"]))
        report = self.assert_package(stage, layout, baseline)
        with tempfile.TemporaryDirectory(prefix="lakis-8132-stock-readers-") as tmp:
            scratch = Path(tmp)
            stock = scratch / "stock-8.1.3.1.exe"
            stock.write_bytes(baseline["LAKIS_Updater.exe"])
            readers = {"8.1.3.1": stock}
            # These source builds exercise only the historical reader and path validator.
            for version, revision in {
                "8.1.0": "v8.1.0", "8.1.1": "v8.1.1", "8.1.2": "v8.1.2",
                "8.1.3": "4ebaa03c1e50f1cfbe0cfc1dceb42915719c3fea",
            }.items():
                directory = scratch / version
                directory.mkdir()
                sources = []
                for source in UPDATER_SOURCES:
                    file = directory / Path(source).name
                    file.write_bytes(git("cat-file", "blob", f"{revision}:{source}"))
                    sources.append(str(file))
                readers[version] = directory / f"stock-{version}.exe"
                subprocess.run([
                    str(compiler()), "/nologo", "/target:winexe", "/codepage:65001", f"/out:{readers[version]}",
                    *("/reference:" + name + ".dll" for name in (
                        "System.Windows.Forms", "System.Drawing", "System.Web.Extensions",
                        "System.IO.Compression", "System.IO.Compression.FileSystem",
                    )), *sources,
                ], check=True, timeout=60)
            env = {**os.environ, "HOTFIX_MANIFEST": str(stage / hotfix.MANIFEST),
                   "HOTFIX_UPDATER": str(stage / "LAKIS_Updater.exe"),
                   "HOTFIX_READERS": json.dumps({version: str(file) for version, file in readers.items()})}
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", r"""
                $ErrorActionPreference = 'Stop'
                $flags = [Reflection.BindingFlags]'Static,NonPublic'
                $raw = [IO.File]::ReadAllText($env:HOTFIX_MANIFEST)
                $readers = ConvertFrom-Json $env:HOTFIX_READERS
                foreach ($reader in $readers.PSObject.Properties) {
                    $assembly = [Reflection.Assembly]::LoadFile($reader.Value)
                    $protocol = $assembly.GetType('UpdateProtocol', $true)
                    $manifest = $protocol.GetMethod('Read', $flags).Invoke($null, @($raw))
                    $protocol.GetMethod('ValidateForInstallation', $flags).Invoke($null, @($manifest, $reader.Name))
                    $validate = $assembly.GetType('UpdaterForm', $true).GetMethod('ValidateRelativePath', $flags)
                    foreach ($file in $manifest.files) {
                        [void] $validate.Invoke($null, @($file.path))
                    }
                }
                $assembly = [Reflection.Assembly]::LoadFile($env:HOTFIX_UPDATER)
                $sha = [Security.Cryptography.SHA256]::Create()
                foreach ($name in $assembly.GetManifestResourceNames()) {
                    if ($name.StartsWith('LAKIS.Runtime.')) {
                        $stream = $assembly.GetManifestResourceStream($name)
                        $size = $stream.Length
                        $digest = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
                        $stream.Dispose()
                        "$name $size $digest"
                    }
                }
            """], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(0, result.returncode, result.stderr)
        embedded = {}
        for line in result.stdout.splitlines():
            name, size, digest = line.split()
            embedded[name] = (int(size), digest)
        expected = {}
        for name in hotfix.RUNTIME_HELPERS:
            data = (hotfix.ROOT / "installer" / name).read_bytes()
            expected[f"LAKIS.Runtime.{name}"] = (len(data), hotfix.sha256(data))
        self.assertEqual(expected, embedded)
        self.assertEqual(expected, {name: (row["bytes"], row["sha256"])
                                    for name, row in report["embedded_runtime_helpers"].items()})


if __name__ == "__main__":
    unittest.main()
