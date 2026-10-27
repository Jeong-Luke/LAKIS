"""Compile the GUI installer entry point and exercise its runtime-engine wiring."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
BOOTSTRAP_SENTINEL = "BOOTSTRAP_REACHED"

PROBE = r'''
using System;
using System.IO;

internal static class GuiWiringProbe {
    private static string Errors(Exception error) {
        string result="";
        for(Exception current=error;current!=null;current=current.InnerException)
            result+=current.GetType().FullName+": "+current.Message+"\n";
        return result;
    }
    private static void MakeInstalled(string target,string version) {
        Directory.CreateDirectory(Path.Combine(target,"ComfyUI","LAKIS"));
        Directory.CreateDirectory(Path.Combine(target,"python_embeded"));
        File.WriteAllText(Path.Combine(target,"VERSION"),version);
        File.WriteAllText(Path.Combine(target,"install.complete"),"fixture");
        File.WriteAllText(Path.Combine(target,"ComfyUI","LAKIS","STOP_AUTOMATION"),"fixture");
        File.WriteAllText(Path.Combine(target,"python_embeded","python.exe"),"installed-python-must-survive");
        File.WriteAllText(Path.Combine(target,"user-setting.txt"),"keep");
    }
    private static int Main(string[] args) {
        string mode=args[0], root=args[1], target=Path.Combine(root,"target");
        string temporary=Path.Combine(root,"temp");
        Directory.CreateDirectory(root);
        Directory.CreateDirectory(temporary);
        Environment.SetEnvironmentVariable("TMP",temporary);
        Environment.SetEnvironmentVariable("TEMP",temporary);
        Action<string> report=_=>{};
        try {
            if(mode=="fresh") {
                Environment.SetEnvironmentVariable("LAKIS_GUI_WIRING_TEST_BOOTSTRAP","allow");
                SafeInstaller.Install(target,true,report);
                if(RuntimeBundleInstaller.Calls!=1 || RuntimeBundleInstaller.Mode!="fresh" ||
                   !RuntimeBundleInstaller.IncludeAnimeSharp ||
                   RuntimeBundleInstaller.Python!="fixture-bootstrap-python.exe" ||
                   RuntimeBundleInstaller.Target!=Path.GetFullPath(target) ||
                   !RuntimeBundleInstaller.Manifest.Contains("\"version\": \"8.0.0\"") ||
                   !File.Exists(Path.Combine(target,"network-install.log")) ||
                   RuntimeBundleInstaller.Python==Path.Combine(target,"python_embeded","python.exe"))return 10;
                Console.WriteLine("FRESH_DISPATCH_PASS");return 0;
            }
            if(mode=="repair") {
                MakeInstalled(target,"8.0.0");
                Environment.SetEnvironmentVariable("LAKIS_GUI_WIRING_TEST_BOOTSTRAP","allow");
                SafeInstaller.Repair(target,report);
                if(RuntimeBundleInstaller.Calls!=1 || RuntimeBundleInstaller.Mode!="repair" ||
                   RuntimeBundleInstaller.IncludeAnimeSharp ||
                   RuntimeBundleInstaller.Python!="fixture-bootstrap-python.exe" ||
                   RuntimeBundleInstaller.Target!=Path.GetFullPath(target) ||
                   File.ReadAllText(Path.Combine(target,"python_embeded","python.exe"))!="installed-python-must-survive" ||
                   File.ReadAllText(Path.Combine(target,"user-setting.txt"))!="keep" ||
                   !File.Exists(Path.Combine(target,"repair.log")))return 20;
                Console.WriteLine("REPAIR_DISPATCH_PASS");return 0;
            }
            if(mode=="old-repair") {
                MakeInstalled(target,"7.5.3");
                try { SafeInstaller.Repair(target,report); return 30; }
                catch(InvalidOperationException error) {
                    string message=Errors(error);
                    if(!message.Contains("8.0.0") || message.Contains("BOOTSTRAP_REACHED") ||
                       RuntimeBundleInstaller.Calls!=0 ||
                       File.ReadAllText(Path.Combine(target,"VERSION"))!="7.5.3" ||
                       File.ReadAllText(Path.Combine(target,"python_embeded","python.exe"))!="installed-python-must-survive" ||
                       File.ReadAllText(Path.Combine(target,"user-setting.txt"))!="keep" ||
                       File.Exists(Path.Combine(target,"repair.log")) ||
                       Directory.Exists(Path.Combine(temporary,"LAKIS-safe-v7.1")))return 31;
                    Console.WriteLine("OLD_REPAIR_REFUSED_PASS");return 0;
                }
            }
            if(mode=="missing-python-repair") {
                MakeInstalled(target,"8.0.0");
                Directory.Delete(Path.Combine(target,"python_embeded"),true);
                Environment.SetEnvironmentVariable("LAKIS_GUI_WIRING_TEST_BOOTSTRAP","allow");
                SafeInstaller.Repair(target,report);
                if(RuntimeBundleInstaller.Calls!=1 || RuntimeBundleInstaller.Mode!="repair" ||
                   RuntimeBundleInstaller.Python!="fixture-bootstrap-python.exe" ||
                   File.ReadAllText(Path.Combine(target,"user-setting.txt"))!="keep")return 32;
                Console.WriteLine("MISSING_PYTHON_REPAIR_DISPATCH_PASS");return 0;
            }
            if(mode=="late-collision") {
                Environment.SetEnvironmentVariable("LAKIS_GUI_WIRING_TEST_BOOTSTRAP","allow");
                Environment.SetEnvironmentVariable("LAKIS_GUI_WIRING_TEST_FAIL","collision");
                try { SafeInstaller.Install(target,false,report); return 33; }
                catch(InvalidOperationException error) {
                    if(!Errors(error).Contains("simulated target collision") ||
                       File.ReadAllText(Path.Combine(target,"network-install.log"))!="concurrent-owner-log" ||
                       File.ReadAllText(Path.Combine(target,"user-file.txt"))!="concurrent-owner-data")return 34;
                    string cache=Path.Combine(temporary,"LAKIS-safe-v7.1");
                    if(Directory.GetFiles(cache,"runtime-failure-*.log").Length!=1 ||
                       !File.Exists(Path.Combine(cache,"fixture-bootstrap","failure-evidence.txt")))return 35;
                    Console.WriteLine("LATE_COLLISION_PRESERVATION_PASS");return 0;
                }
            }
            if(mode=="target-refusal") {
                Directory.CreateDirectory(target);
                string sentinel=Path.Combine(target,"user-file.txt");
                File.WriteAllText(sentinel,"preserve");
                try { SafeInstaller.Install(target,false,report); return 40; }
                catch(InvalidOperationException error) {
                    string message=Errors(error);
                    if(message.Contains("BOOTSTRAP_REACHED") || RuntimeBundleInstaller.Calls!=0 ||
                       File.ReadAllText(sentinel)!="preserve" ||
                       File.Exists(Path.Combine(target,"network-install.log")) ||
                       Directory.Exists(Path.Combine(temporary,"LAKIS-safe-v7.1")))return 41;
                    Console.WriteLine("EARLY_TARGET_REFUSAL_PASS");return 0;
                }
            }
            if(mode=="invalid-resource") {
                try { SafeInstaller.Install(target,false,report); return 50; }
                catch(Exception error) {
                    string message=Errors(error);
                    if(!message.Contains(args[2]) || message.Contains("BOOTSTRAP_REACHED") ||
                       RuntimeBundleInstaller.Calls!=0 || Directory.Exists(target) ||
                       Directory.Exists(Path.Combine(temporary,"LAKIS-safe-v7.1")))return 51;
                    Console.WriteLine("RESOURCE_REJECTED_BEFORE_DOWNLOAD_PASS");return 0;
                }
            }
            return 90;
        } catch(Exception error) {
            Console.Error.WriteLine(Errors(error));
            return 91;
        }
    }
}
'''


def valid_manifest(version="8.0.0"):
    part_name = "LAKIS-runtime.zip.part001"
    return {
        "schema": 1,
        "version": version,
        "base": {
            "name": "ComfyUI_windows_portable_nvidia.7z",
            "url": "https://example.test/portable.7z",
            "sha256": "A" * 64,
            "bytes": 1,
        },
        "models": [["model.bin", "https://example.test/model", "B" * 64, "checkpoints", 1]],
        "optional_animesharp": [
            "optional.safetensors", "https://example.test/optional", "C" * 64, "upscale_models", 1
        ],
        "webview2": {
            "name": "MicrosoftEdgeWebview2Setup.exe",
            "url": "https://example.test/webview2.exe",
            "sha256": "D" * 64,
            "bytes": 1,
        },
        "runtime_bundle": {
            "schema": 2,
            "product": "LAKIS",
            "version": "8.0.0",
            "comfyui_version": "0.42.0",
            "name": "LAKIS-runtime.zip",
            "sha256": "E" * 64,
            "manifest_sha256": "F" * 64,
            "bytes": 1,
            "files": 1,
            "parts": [{
                "name": part_name,
                "bytes": 1,
                "sha256": "1" * 64,
                "url": "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/" + part_name,
            }],
        },
    }


def replace_method(source, signature, replacement):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for position in range(opening, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[:start] + replacement + source[position + 1:]
    raise AssertionError("Unclosed C# method: " + signature)


@unittest.skipUnless(COMPILER.is_file(), "Windows .NET Framework compiler required")
class GuiRuntimeWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        source = (ROOT / "installer/Setup_LAKIS_Safe.cs").read_text(encoding="utf-8-sig")
        source = replace_method(source, "    private static string PrepareBootstrapPython(",
            '''    private static string PrepareBootstrapPython(string cache,Action<string> status,out string workspace)
    {
        workspace=Path.Combine(cache,"fixture-bootstrap");
        Directory.CreateDirectory(workspace);
        File.WriteAllText(Path.Combine(workspace,"failure-evidence.txt"),"preserve if failed");
        if(Environment.GetEnvironmentVariable("LAKIS_GUI_WIRING_TEST_BOOTSTRAP")=="allow")
            return "fixture-bootstrap-python.exe";
        throw new InvalidOperationException("BOOTSTRAP_REACHED");
    }''')
        source = replace_method(source, "    private static void CreateDesktopShortcut(",
            '''    private static void CreateDesktopShortcut(string target,Action<string> status)
    {
        status("TEST_SHORTCUT_SKIPPED");
    }''')
        cls.setup = cls.root / "Setup.cs"
        cls.setup.write_text(source, encoding="utf-8")
        cls.probe = cls.root / "GuiWiringProbe.cs"
        cls.probe.write_text(PROBE, encoding="utf-8")
        cls.stub = ROOT / "installer/tests/RuntimeBundleInstallerStub.cs"
        cls.exe_by_resource = {}
        for key, payload, resource in (
            ("valid", json.dumps(valid_manifest(), ensure_ascii=False), True),
            ("bad-json", "{not-json", True),
            ("wrong-version", json.dumps(valid_manifest("7.5.3"), ensure_ascii=False), True),
            ("wrong-schema", json.dumps(dict(valid_manifest(), schema=2), ensure_ascii=False), True),
            ("missing", None, False),
        ):
            output = cls.root / (key + ".exe")
            command = [
                str(COMPILER), "/nologo", "/target:exe", "/main:GuiWiringProbe",
                "/out:" + str(output), "/reference:System.Windows.Forms.dll",
                "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll",
                "/reference:System.IO.Compression.dll",
                "/reference:System.IO.Compression.FileSystem.dll",
                str(ROOT / "installer/SplashArtwork.cs"), str(cls.stub),
                str(cls.setup), str(cls.probe),
            ]
            if resource:
                manifest_path = cls.root / (key + ".json")
                manifest_path.write_text(payload, encoding="utf-8")
                command.append("/resource:" + str(manifest_path) + ",LAKIS.RuntimeInstallManifest")
            compiled = subprocess.run(command, capture_output=True)
            if compiled.returncode:
                cls.temporary.cleanup()
                raise RuntimeError(compiled.stdout.decode(errors="replace"))
            cls.exe_by_resource[key] = output

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_probe(self, resource, mode, expected=None):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            arguments = [str(self.exe_by_resource[resource]), mode, temporary]
            if expected is not None:
                arguments.append(expected)
            result = subprocess.run(arguments, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            return result.stdout.decode(errors="replace")

    def test_embedded_manifest_must_exist_parse_and_match_schema_and_version_before_download(self):
        cases = (
            ("missing", "내장 런타임 설치 manifest가 없습니다."),
            ("bad-json", "JSON"),
            ("wrong-version", "8.0.0"),
            ("wrong-schema", "schema"),
        )
        for resource, expected in cases:
            with self.subTest(resource=resource):
                self.assertIn("RESOURCE_REJECTED_BEFORE_DOWNLOAD_PASS",
                              self.run_probe(resource, "invalid-resource", expected))

    def test_fresh_dispatch_uses_bootstrap_python_and_optional_consent(self):
        self.assertIn("FRESH_DISPATCH_PASS", self.run_probe("valid", "fresh"))

    def test_repair_dispatch_uses_bootstrap_python_without_optional_model(self):
        self.assertIn("REPAIR_DISPATCH_PASS", self.run_probe("valid", "repair"))

    def test_repair_rejects_other_installed_version_without_mutation_or_download(self):
        self.assertIn("OLD_REPAIR_REFUSED_PASS", self.run_probe("valid", "old-repair"))

    def test_repair_can_use_bootstrap_when_installed_python_is_missing(self):
        self.assertIn("MISSING_PYTHON_REPAIR_DISPATCH_PASS",
                      self.run_probe("valid", "missing-python-repair"))

    def test_late_target_collision_preserves_user_files_and_failure_evidence(self):
        self.assertIn("LATE_COLLISION_PRESERVATION_PASS",
                      self.run_probe("valid", "late-collision"))

    def test_nonempty_target_refusal_precedes_bootstrap_and_preserves_files(self):
        self.assertIn("EARLY_TARGET_REFUSAL_PASS", self.run_probe("valid", "target-refusal"))

    def test_production_bootstrap_uses_pinned_archive_in_separate_scratch(self):
        source = (ROOT / "installer/Setup_LAKIS_Safe.cs").read_text(encoding="utf-8-sig")
        start = source.index("private static string PrepareBootstrapPython")
        end = source.index("private static void RunRuntimeInstaller", start)
        method = source[start:end]
        for expected in (
            "Fetch(Portable,cache,status)",
            'UniqueScratch(cache,"runtime-bootstrap")',
            "Extract7z(archive,workspace)",
            '"ComfyUI_windows_portable","python_embeded","python.exe"',
            "RuntimeBundleInstaller.Install(python,manifest,target,cache,mode,includeAnimeSharp,status)",
        ):
            self.assertIn(expected, method if "RuntimeBundleInstaller.Install" not in expected else source)
        self.assertIn('Path.Combine(workspace,"ComfyUI_windows_portable","python_embeded","python.exe")',method)
        self.assertIn('private const string ReleaseVersion = "8.0.0";',source)
        self.assertIn("LAKIS v8.0.0",source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
