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

# Repair delegates writes to the same verified runtime engine as fresh Setup.
# User/model roots must not be directly mutated by the GUI entry point.
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

# The GUI no longer has a separate model installation or ZIP replacement path.
Require ($compactRepair.Contains('RunRuntimeInstaller(manifest,target,cache,"repair",false,status)')) `
    "Repair must delegate to the shared runtime engine without optional model consent."
$modelRootReferences = [System.Text.RegularExpressions.Regex]::Matches(
    $compactRepair, 'Path\.Combine\(comfy,"models"',
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
Require ($modelRootReferences.Count -eq 0) "Repair entry point must not install models directly."
Require (-not $compactRepair.Contains('foreach(varmodelinModels)')) `
    "Repair must not reinstall or overwrite the general model inventory."

# Audit recursive-destructive helpers reachable directly from the GUI entry.
$deleteCalls = [System.Text.RegularExpressions.Regex]::Matches($compactRepair, 'DeleteTree\(([^\)]+)\)')
Require ($deleteCalls.Count -eq 0) `
    "Repair must not recursively replace a retired Light Control product directory."

$resetCalls = [System.Text.RegularExpressions.Regex]::Matches($compactRepair, 'Reset\(([^\)]+)\)')
Require ($resetCalls.Count -eq 0) "Repair entry point must not reset directories."

$installZipCalls = [System.Text.RegularExpressions.Regex]::Matches($compactRepair, 'InstallZip\(([^;]+)\);')
Require ($installZipCalls.Count -eq 0) "Repair entry point must not use legacy ZIP replacement."

Write-Output "REPAIR_DATA_SAFETY_OK scope=shared-runtime-entrypoint direct_model_writes=0 legacy_destructive_targets=0"
