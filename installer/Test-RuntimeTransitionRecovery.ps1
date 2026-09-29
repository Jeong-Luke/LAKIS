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
    Set-Content -LiteralPath (Join-Path $Root "runtime-required.bin") -Value "required-runtime-payload" -Encoding ascii
    New-Item -ItemType Directory -Path (Join-Path $Root "ComfyUI") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Root "ComfyUI\extra_model_paths.yaml.example") -Value "manifest-protected-example" -Encoding ascii
    $manifest = [ordered]@{ schema=1; product="LAKIS"; version="8.0.0"; source_revision="fixture"; files=@() }
    $manifest.files = @(Get-ChildItem -LiteralPath $Root -File -Recurse | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path=$_.FullName.Substring($Root.Length).TrimStart('\').Replace('\','/')
            size=[int64]$_.Length
            sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    })
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Root "RUNTIME_SHA256SUMS.json") -Encoding utf8
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
$candidateManifestHash = (Get-FileHash -LiteralPath (Join-Path $candidateFixture "RUNTIME_SHA256SUMS.json") -Algorithm SHA256).Hash
$results = @()

foreach ($point in @("after-stage", "after-backup", "after-promote")) {
    $case = Join-Path $testRootPath $point
    $target = Join-Path $case "LAKIS"
    New-OldFixture $target
    try { & $transition -CandidateRoot $candidateFixture -TargetRoot $target -ExpectedManifestSha256 $candidateManifestHash -TestInterruptAfter $point | Out-Null; throw "Expected interruption at $point" }
    catch { if ($_.Exception.Message -notlike "*TEST_INTERRUPT_$point*") { throw } }
    & $transition -CandidateRoot $candidateFixture -TargetRoot $target -ExpectedManifestSha256 $candidateManifestHash | Out-Null
    if ((Get-Content (Join-Path $target "VERSION") -Raw).Trim() -ne "8.0.0") { throw "Recovery failed at $point" }
    Assert-Preserved $target
    $results += [ordered]@{ case=$point; recovery="PASS"; data_preservation="PASS" }
}

$partialCase = Join-Path $testRootPath "partial-stage-copy"
$partialTarget = Join-Path $partialCase "LAKIS"
New-OldFixture $partialTarget
$partialStage = Join-Path $partialCase ".LAKIS-8-stage"
New-Item -ItemType Directory -Path $partialStage -Force | Out-Null
foreach ($relative in @("VERSION", "LAKIS.exe", "python_embeded\python.exe", "ComfyUI\main.py", "ComfyUI\LAKIS\external_ui\launch_lakis.py", "RUNTIME_SHA256SUMS.json")) {
    $source = Join-Path $candidateFixture $relative
    $destination = Join-Path $partialStage $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}
& $transition -CandidateRoot $candidateFixture -TargetRoot $partialTarget -ExpectedManifestSha256 $candidateManifestHash | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $partialTarget "runtime-required.bin") -PathType Leaf)) {
    throw "Partial stage was promoted instead of rebuilt."
}
Assert-Preserved $partialTarget
$quarantined = @(Get-ChildItem -LiteralPath $partialCase -Directory -Filter ".LAKIS-8-stage.invalid-*")
if ($quarantined.Count -ne 1) { throw "Invalid partial stage was not quarantined." }
$results += [ordered]@{ case="partial-stage-copy"; fail_closed="PASS"; rebuilt_from_candidate="PASS"; data_preservation="PASS" }

$backupDamagedCase = Join-Path $testRootPath "backup-with-damaged-stage"
$backupDamagedTarget = Join-Path $backupDamagedCase "LAKIS"
New-OldFixture $backupDamagedTarget
try {
    & $transition -CandidateRoot $candidateFixture -TargetRoot $backupDamagedTarget -ExpectedManifestSha256 $candidateManifestHash -TestInterruptAfter "after-backup" | Out-Null
    throw "Expected interruption after backup."
}
catch { if ($_.Exception.Message -notlike "*TEST_INTERRUPT_after-backup*") { throw } }
$backupDamagedStage = Join-Path $backupDamagedCase ".LAKIS-8-stage"
Set-Content -LiteralPath (Join-Path $backupDamagedStage "runtime-required.bin") -Value "damaged-after-backup" -Encoding ascii
& $transition -CandidateRoot $candidateFixture -TargetRoot $backupDamagedTarget -ExpectedManifestSha256 $candidateManifestHash | Out-Null
Assert-Preserved $backupDamagedTarget
$results += [ordered]@{ case="backup-with-damaged-stage"; rebuilt_from_candidate="PASS"; restored_user_data_from_backup="PASS" }

$extraCase = Join-Path $testRootPath "unlisted-extra-file"
$extraTarget = Join-Path $extraCase "LAKIS"
New-OldFixture $extraTarget
$extraStage = Join-Path $extraCase ".LAKIS-8-stage"
& robocopy $candidateFixture $extraStage /E /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Extra-file test fixture copy failed." }
Set-Content -LiteralPath (Join-Path $extraStage "UNLISTED_PAYLOAD.bin") -Value "unlisted" -Encoding ascii
& $transition -CandidateRoot $candidateFixture -TargetRoot $extraTarget -ExpectedManifestSha256 $candidateManifestHash | Out-Null
if (Test-Path -LiteralPath (Join-Path $extraTarget "UNLISTED_PAYLOAD.bin")) { throw "Unlisted stage file was promoted." }
$results += [ordered]@{ case="unlisted-extra-file"; rejected_and_rebuilt="PASS" }

$junctionCase = Join-Path $testRootPath "protected-junction"
$junctionTarget = Join-Path $junctionCase "LAKIS"
$junctionExternal = Join-Path $junctionCase "shared-model-source"
New-OldFixture $junctionTarget
New-Item -ItemType Directory -Path $junctionExternal -Force | Out-Null
Set-Content -LiteralPath (Join-Path $junctionExternal "shared-model.bin") -Value "shared-model" -Encoding ascii
$junctionPath = Join-Path $junctionTarget "ComfyUI\models\shared-models"
New-Item -ItemType Junction -Path $junctionPath -Target $junctionExternal | Out-Null
& $transition -CandidateRoot $candidateFixture -TargetRoot $junctionTarget -ExpectedManifestSha256 $candidateManifestHash | Out-Null
$preservedJunction = Get-Item -LiteralPath (Join-Path $junctionTarget "ComfyUI\models\shared-models") -Force
if ($preservedJunction.LinkType -ne "Junction" -or [string]$preservedJunction.Target -ne $junctionExternal) {
    throw "Protected model junction was followed or changed instead of being preserved."
}
$results += [ordered]@{ case="protected-junction"; link_preserved="PASS"; target_not_copied="PASS" }

$prefixCase = Join-Path $testRootPath "protected-file-prefix"
$prefixTarget = Join-Path $prefixCase "LAKIS"
New-OldFixture $prefixTarget
$prefixStage = Join-Path $prefixCase ".LAKIS-8-stage"
& robocopy $candidateFixture $prefixStage /E /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Prefix test fixture copy failed." }
Set-Content -LiteralPath (Join-Path $prefixStage "ComfyUI\extra_model_paths.yaml.example") -Value "tampered-example" -Encoding ascii
& $transition -CandidateRoot $candidateFixture -TargetRoot $prefixTarget -ExpectedManifestSha256 $candidateManifestHash | Out-Null
if ((Get-Content -LiteralPath (Join-Path $prefixTarget "ComfyUI\extra_model_paths.yaml.example") -Raw).Trim() -ne "manifest-protected-example") {
    throw "Protected file prefix bypassed manifest validation."
}
$results += [ordered]@{ case="protected-file-prefix"; exact_match_only="PASS"; tampered_stage_rebuilt="PASS" }

$rollbackCase = Join-Path $testRootPath "post-promote-validation-failure"
$rollbackTarget = Join-Path $rollbackCase "LAKIS"
New-OldFixture $rollbackTarget
try {
    & $transition -CandidateRoot $candidateFixture -TargetRoot $rollbackTarget -ExpectedManifestSha256 $candidateManifestHash -TestInterruptAfter "corrupt-after-promote" | Out-Null
    throw "Expected post-promote manifest failure."
}
catch {
    if ($_.Exception.Message -notlike "*Runtime manifest size mismatch*" -and $_.Exception.Message -notlike "*Runtime manifest hash mismatch*") { throw }
}
if ((Get-Content -LiteralPath (Join-Path $rollbackTarget "VERSION") -Raw).Trim() -ne "7.5.2") { throw "Rollback did not restore the original runtime." }
Assert-Preserved $rollbackTarget
$failedTargets = @(Get-ChildItem -LiteralPath $rollbackCase -Directory -Filter "LAKIS.failed-*")
if ($failedTargets.Count -ne 1) { throw "Failed promoted target was not quarantined during rollback." }
$results += [ordered]@{ case="post-promote-validation-failure"; automatic_rollback="PASS"; original_preserved="PASS" }

$lockedCase = Join-Path $testRootPath "locked-file"
$lockedTarget = Join-Path $lockedCase "LAKIS"
New-OldFixture $lockedTarget
$lockedPath = Join-Path $lockedTarget "LAKIS.exe"
$lock = [IO.File]::Open($lockedPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
try {
    try { & $transition -CandidateRoot $candidateFixture -TargetRoot $lockedTarget -ExpectedManifestSha256 $candidateManifestHash | Out-Null; throw "Locked runtime was unexpectedly promoted." }
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
