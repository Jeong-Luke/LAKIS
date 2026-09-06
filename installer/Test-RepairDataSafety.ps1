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

# Repair owns application binaries, packaged workflows, LAKIS-owned custom
# nodes, notices, and exactly one permissive default upscaler. The following
# user/model roots are never Repair targets. Normalizing whitespace prevents a
# formatting-only edit from bypassing the gate.
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

# Any access below ComfyUI/models must stay restricted to the intentional
# RealESRGAN target. Adding another model path makes the release fail closed.
$modelRootReferences = [System.Text.RegularExpressions.Regex]::Matches(
    $compactRepair, 'Path\.Combine\(comfy,"models"',
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
Require ($modelRootReferences.Count -eq 1) "Repair must have exactly one ComfyUI/models reference (RealESRGAN only)."
Require ($compactRepair.Contains('Array.Find(Models,item=>String.Equals(item.Name,"RealESRGAN_x4plus_anime_6B.pth",StringComparison.OrdinalIgnoreCase))')) `
    "Repair's sole model selection must be the pinned RealESRGAN default."
Require ($compactRepair.Contains('Path.Combine(comfy,"models",defaultUpscaler.Destination)')) `
    "Repair's model destination must derive only from the verified RealESRGAN item."
Require (-not $compactRepair.Contains('foreach(varmodelinModels)')) `
    "Repair must not reinstall or overwrite the general model inventory."

# Audit every recursive-destructive helper reachable directly from Repair.
# Light Control is LAKIS-owned; uiStage is a temporary extraction directory;
# Lora Manager is an app component below custom_nodes. No other target is valid.
$deleteCalls = [System.Text.RegularExpressions.Regex]::Matches($compactRepair, 'DeleteTree\(([^\)]+)\)')
Require ($deleteCalls.Count -eq 1 -and $deleteCalls[0].Groups[1].Value -eq 'lightTarget') `
    "Repair may recursively replace only the LAKIS-owned Light Control directory."

$resetCalls = [System.Text.RegularExpressions.Regex]::Matches($compactRepair, 'Reset\(([^\)]+)\)')
Require ($resetCalls.Count -eq 1 -and $resetCalls[0].Groups[1].Value -eq 'uiStage') `
    "Repair may reset only its temporary UI extraction stage."

$installZipCalls = [System.Text.RegularExpressions.Regex]::Matches($compactRepair, 'InstallZip\(([^;]+)\);')
Require ($installZipCalls.Count -eq 1) "Repair may replace exactly one ZIP component (Lora Manager)."
Require ($installZipCalls[0].Groups[1].Value -eq 'LoraManager,cache,Path.Combine(custom,LoraManager.Destination),status') `
    "Repair ZIP replacement escaped the LAKIS component allowlist."

Write-Output "REPAIR_DATA_SAFETY_OK protected_roots=7 model_exception=RealESRGAN destructive_targets=3"
