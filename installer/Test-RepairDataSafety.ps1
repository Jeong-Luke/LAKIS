param()

$ErrorActionPreference = "Stop"
$sourcePath = Join-Path $PSScriptRoot "Setup_LAKIS_Safe.cs"
$source = Get-Content -Raw -LiteralPath $sourcePath

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "REPAIR DATA SAFETY FAILED: $Message" }
}

function Compact([string]$Text) {
    return [System.Text.RegularExpressions.Regex]::Replace($Text, "\s+", "")
}

$repairStart = $source.IndexOf("internal static void Repair", [System.StringComparison]::Ordinal)
$repairEnd = $source.IndexOf("private static string Fetch", $repairStart, [System.StringComparison]::Ordinal)
Require ($repairStart -ge 0 -and $repairEnd -gt $repairStart) "Could not isolate SafeInstaller.Repair."
$repair = $source.Substring($repairStart, $repairEnd - $repairStart)
$compactRepair = Compact $repair

# The GUI now delegates Repair to the frozen-runtime installer. Keep checking
# the active GUI entry point, not the retired per-component installation body.
# Actual data copying, model preservation and rollback are exercised below.
$protectedFragments = @(
    'Path.Combine(comfy,"user"',
    'Path.Combine(comfy,"input"',
    'Path.Combine(comfy,"output"',
    '"loras"',
    '"checkpoints"',
    '"diffusion_models"',
    'SpecialFolder.LocalApplicationData',
    'Environment.GetEnvironmentVariable("LOCALAPPDATA"',
    '"LAKISStudio"',
    'SetDefaultUpscaler(',
    'PrepareTarget(',
    'Move('
)
foreach ($fragment in $protectedFragments) {
    Require ($compactRepair.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) `
        "Repair references protected state or a broad mutation helper: $fragment"
}

foreach ($helper in @('DeleteTree(', 'Reset(', 'InstallZip(', 'CopyTree(', 'Fetch(')) {
    Require (-not $compactRepair.Contains($helper)) "Repair must delegate mutations, not call $helper"
}
Require (-not $compactRepair.Contains('Path.Combine(comfy,"models"')) "GUI Repair must not mutate the model inventory directly."
Require ($compactRepair.Contains('RunRuntimeInstaller(manifest,target,cache,"repair",false,status);')) `
    "Repair must use the runtime installer in repair mode without optional fresh-install models."
Require ($compactRepair.Contains('String.Equals(installedVersion,ReleaseVersion,StringComparison.Ordinal)')) `
    "Repair must reject a different installed release."

# Run the real runtime_install.install -> runtime_transition.activate path in
# disposable trees. Only release-bundle acquisition/verification, process/GPU
# health probes, and large pinned model payloads are substituted. Data copying,
# model conflict checks, journals, promotion and rollback remain production code.
$runtimeProbe = @'
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
import runtime_install as installer
import runtime_manifest as contract
import runtime_transition as transition


def tree(root):
    return {p.relative_to(root).as_posix(): None if p.is_dir() else p.read_bytes()
            for p in root.rglob("*")}


class RepairDataSafety(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="lakis-repair-safety-")))
        self.target, self.candidate = self.root / "installed", self.root / "candidate"
        self.version = (Path(sys.argv[1]).parent / "VERSION").read_text().strip()
        self.cache = self.root / "cache"
        release = {
            "VERSION": (self.version + "\n").encode(),
            "ComfyUI/LAKIS/STOP_AUTOMATION": b"public installation",
            "python_embeded/python.exe": b"offline runtime fixture",
            "ComfyUI/LAKIS/workflows/packaged.json": b'{"release":"current"}',
        }
        for relative, content in release.items():
            self.write(self.candidate / relative, content)
            self.write(self.target / relative, content)
        self.write(self.target / "ComfyUI/LAKIS/workflows/packaged.json", b'{"release":"damaged"}')
        self.release = release
        self.manifest = {"files": [{"path": name, "size": len(data)} for name, data in release.items()]}
        raw = json.dumps(self.manifest).encode()
        self.write(self.candidate / contract.MANIFEST_NAME, raw)
        self.digest = hashlib.sha256(raw).hexdigest()
        self.install_manifest = {"schema": 1, "version": self.version,
                                 "runtime_bundle": {"manifest_sha256": self.digest}}
        # Independent required paths: dropping a protected root from the runtime
        # contract must lose one of these sentinels and fail this test.
        self.data = {
            ".lakis/settings.json": b'{"keep":"settings"}',
            "ComfyUI/user/default/workflows/my-workflow.json": b'{"user":"workflow"}',
            "ComfyUI/input/user.png": b"user input",
            "ComfyUI/output/generated.png": b"user output",
            "ComfyUI/models/loras/user.safetensors": b"user lora",
            "ComfyUI/models/checkpoints/user.safetensors": b"user checkpoint",
            "ComfyUI/models/diffusion_models/user.safetensors": b"user diffusion model",
            "ComfyUI/models/upscale_models/RealESRGAN_x4plus_anime_6B.pth": b"user default upscaler",
            "ComfyUI/models/upscale_models/AnimeSharp.pth": b"user optional upscaler",
        }
        for relative in contract.PROTECTED_DIRECTORIES:
            self.data[relative + "/user-data.bin"] = relative.encode()
            (self.target / relative / "empty-user-directory").mkdir(parents=True)
        for relative in contract.PROTECTED_FILES:
            self.data[relative] = relative.encode()
        # Keep real model paths and real collision/preservation code, using tiny
        # authenticated fixture payloads rather than downloading 100 MB.
        pose_models = {}
        for relative, spec in contract.POSE_MODELS.items():
            data = relative.encode()
            self.data[relative] = data
            pose_models[relative] = dict(spec, size=len(data), sha256=hashlib.sha256(data).hexdigest().upper())
        for relative, content in self.data.items():
            self.write(self.target / relative, content)
        self.local = self.root / "localappdata"
        self.write(self.local / "LAKIS Studio/user-state.json", b"external user state")
        self.stack.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(self.local)))
        self.stack.enter_context(patch.object(contract, "POSE_MODELS", pose_models))
        self.stack.enter_context(patch.object(installer, "validate_bundle", return_value=self.install_manifest["runtime_bundle"]))
        self.stack.enter_context(patch.object(installer, "prepare_bundle", return_value=self.candidate))
        self.stack.enter_context(patch.object(installer, "verify_runtime", return_value=self.manifest))
        self.stack.enter_context(patch.object(transition, "verify_runtime", return_value=self.manifest))
        self.stack.enter_context(patch.object(transition, "assert_idle"))
        self.health = self.stack.enter_context(patch.object(transition, "check_runtime"))
        for name in ("prepare_default_data", "ensure_webview2_runtime", "download"):
            self.stack.enter_context(patch.object(installer, name, side_effect=AssertionError("Repair called " + name)))
        self.local_before = tree(self.local)

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def repair(self):
        return installer.install(self.install_manifest, self.target, self.cache, "repair", "gui")

    def assert_data(self, root):
        for relative, content in self.data.items():
            self.assertEqual((root / relative).read_bytes(), content, relative)
        for relative in contract.PROTECTED_DIRECTORIES:
            self.assertTrue((root / relative / "empty-user-directory").is_dir(), relative)
        self.assertEqual(tree(self.local), self.local_before)

    def test_repair_preserves_data_and_model_inventory(self):
        models_before = tree(self.target / "ComfyUI/models")
        result = self.repair()
        self.assertEqual(result["status"], "complete")
        self.assert_data(self.target)
        self.assert_data(Path(result["backup"]))
        self.assertEqual(tree(self.target / "ComfyUI/models"), models_before)
        for relative, content in self.release.items():
            self.assertEqual((self.target / relative).read_bytes(), content)
        self.assertEqual(self.health.call_count, 2)

    def test_wrong_version_is_unchanged(self):
        self.write(self.target / "VERSION", b"0.0.0\n")
        before = tree(self.target)
        with self.assertRaisesRegex(ValueError, "repair must keep the version"):
            self.repair()
        self.assertEqual(tree(self.target), before)
        self.assert_data(self.target)

    def test_existing_model_conflict_is_unchanged(self):
        relative = next(iter(contract.POSE_MODELS))
        self.write(self.target / relative, b"user conflicting model")
        before = tree(self.target)
        with self.assertRaisesRegex(ValueError, "anima_"):
            self.repair()
        self.assertEqual(tree(self.target), before)
        self.assertEqual(tree(self.local), self.local_before)

    def test_failed_final_health_restores_original(self):
        before = tree(self.target)
        def health(root):
            if root == self.target:
                raise RuntimeError("injected final health failure")
        self.health.side_effect = health
        with self.assertRaisesRegex(RuntimeError, "injected final health failure"):
            self.repair()
        self.assertEqual(tree(self.target), before)
        self.assert_data(self.target)
        state = json.loads(transition._journal_path(self.target).read_text())
        self.assertEqual(state["phase"], "rolled-back")


unittest.main(argv=[sys.argv[0]], verbosity=2)
'@
$runtimeProbe | & python -B - $PSScriptRoot
Require ($LASTEXITCODE -eq 0) "Active runtime Repair data-preservation probes failed."
Write-Output "REPAIR_DATA_SAFETY_OK runtime_cases=4 model_inventory=preserved rollback=verified"
