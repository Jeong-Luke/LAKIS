param(
    [Parameter(Mandatory = $true)][string]$CandidateRoot,
    [Parameter(Mandatory = $true)][string]$TestRoot
)

$ErrorActionPreference = "Stop"
$transition = Join-Path $PSScriptRoot "Invoke-LAKISRuntimeTransition.ps1"
$candidate = (Resolve-Path -LiteralPath $CandidateRoot).Path
$testRootPath = [IO.Path]::GetFullPath($TestRoot)

function New-CandidateFixture([string]$Root) {
    New-Item -ItemType Directory -Path (Join-Path $Root "python_embeded") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root "ComfyUI\LAKIS\external_ui") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Root "VERSION") -Value "8.0.0" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "LAKIS.exe") -Value "new-runtime" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "python_embeded\python.exe") -Value "python-fixture" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "ComfyUI\main.py") -Value "runtime-fixture" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "ComfyUI\LAKIS\external_ui\launch_lakis.py") -Value "launcher-fixture" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "RUNTIME_SHA256SUMS.json") -Value "{}" -Encoding ascii
}

function New-OldFixture([string]$Root) {
    New-Item -ItemType Directory -Path (Join-Path $Root "ComfyUI\models\loras") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $Root "ComfyUI\user\default\workflows") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Root "VERSION") -Value "7.5.2" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "LAKIS.exe") -Value "old-runtime" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "ComfyUI\models\loras\USER_LORA.safetensors") -Value "protected-lora" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $Root "ComfyUI\user\default\workflows\USER.json") -Value "protected-workflow" -Encoding ascii
}

function Assert-Preserved([string]$Root) {
    if ((Get-Content (Join-Path $Root "ComfyUI\models\loras\USER_LORA.safetensors") -Raw).Trim() -ne "protected-lora") { throw "LoRA was not preserved." }
    if ((Get-Content (Join-Path $Root "ComfyUI\user\default\workflows\USER.json") -Raw).Trim() -ne "protected-workflow") { throw "Workflow was not preserved." }
}

if (Test-Path -LiteralPath $testRootPath) { Remove-Item -LiteralPath $testRootPath -Recurse -Force }
New-Item -ItemType Directory -Path $testRootPath -Force | Out-Null
$candidateFixture = Join-Path $testRootPath "candidate-fixture"
New-CandidateFixture $candidateFixture
$results = @()

foreach ($point in @("after-stage", "after-backup", "after-promote")) {
    $case = Join-Path $testRootPath $point
    $target = Join-Path $case "LAKIS"
    New-OldFixture $target
    try { & $transition -CandidateRoot $candidateFixture -TargetRoot $target -TestInterruptAfter $point | Out-Null; throw "Expected interruption at $point" }
    catch { if ($_.Exception.Message -notlike "*TEST_INTERRUPT_$point*") { throw } }
    & $transition -CandidateRoot $candidateFixture -TargetRoot $target | Out-Null
    if ((Get-Content (Join-Path $target "VERSION") -Raw).Trim() -ne "8.0.0") { throw "Recovery failed at $point" }
    Assert-Preserved $target
    $results += [ordered]@{ case=$point; recovery="PASS"; data_preservation="PASS" }
}

$lockedCase = Join-Path $testRootPath "locked-file"
$lockedTarget = Join-Path $lockedCase "LAKIS"
New-OldFixture $lockedTarget
$lockedPath = Join-Path $lockedTarget "LAKIS.exe"
$lock = [IO.File]::Open($lockedPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
try {
    try { & $transition -CandidateRoot $candidateFixture -TargetRoot $lockedTarget | Out-Null; throw "Locked runtime was unexpectedly promoted." }
    catch { if ($_.Exception.Message -notlike "*Runtime file is in use*") { throw } }
    if ((Get-Content (Join-Path $lockedTarget "VERSION") -Raw).Trim() -ne "7.5.2") { throw "Locked-file failure changed the original runtime." }
}
finally { $lock.Dispose() }
$results += [ordered]@{ case="locked-file"; fail_closed="PASS"; original_preserved="PASS" }

$evidence = [ordered]@{
    profile="RUNTIME_MAJOR transition recovery"
    timestamp=(Get-Date).ToString("o")
    candidate=$candidate
    candidate_manifest_sha256=(Get-FileHash (Join-Path $candidate "RUNTIME_SHA256SUMS.json") -Algorithm SHA256).Hash
    results=$results
}
$evidencePath = Join-Path $testRootPath "runtime-transition-evidence.json"
$evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $evidencePath -Encoding utf8
$evidence | ConvertTo-Json -Depth 6
