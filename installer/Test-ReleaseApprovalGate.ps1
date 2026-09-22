param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [Parameter(Mandatory=$true)][string]$DistDirectory
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = $Version.TrimStart("v")
$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
$dist = [IO.Path]::GetFullPath($DistDirectory)

if (-not (Test-Path -LiteralPath $evidence -PathType Container)) {
    throw "RELEASE_APPROVAL_MISSING: evidence directory"
}
if (-not (Test-Path -LiteralPath $dist -PathType Container)) {
    throw "RELEASE_APPROVAL_MISSING: artifact directory"
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("lakis-release-approval-fingerprint-" + [guid]::NewGuid().ToString("N") + ".json")
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "New-ReleaseAuditFingerprint.ps1") -OutputPath $tmp | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "RELEASE_APPROVAL_FINGERPRINT_FAILED" }
    $current = Get-Content -Raw -Encoding UTF8 -LiteralPath $tmp | ConvertFrom-Json
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
if ([string]$current.version -ne $version) {
    throw "RELEASE_APPROVAL_VERSION_MISMATCH: candidate=$($current.version) requested=$version"
}

$requiredAssets = @(
    "LAKIS_Setup.exe",
    "LAKIS.exe",
    "LAKIS_Patcher.exe",
    "LAKIS_Updater.exe",
    "LAKIS_Desktop.exe",
    "LAKIS_Model_Importer.exe",
    "Uninstall_LAKIS.exe",
    "Microsoft.Web.WebView2.Core.dll",
    "Microsoft.Web.WebView2.WinForms.dll",
    "WebView2Loader.dll",
    "release-layout.json",
    "LAKIS_RepairPack.zip",
    ("LAKIS_CMD_Installer_" + $version + ".zip"),
    "private-rc-build.json"
)
$artifactHashes = [ordered]@{}
foreach ($name in $requiredAssets) {
    $path = Join-Path $dist $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "RELEASE_APPROVAL_ARTIFACT_MISSING: $name"
    }
    $artifactHashes[$name] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToUpperInvariant()
}
$canonical = ($artifactHashes.GetEnumerator() | ForEach-Object { $_.Key + [char]9 + $_.Value }) -join [char]10
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $artifactSetHash = ([BitConverter]::ToString($sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($canonical)))).Replace("-","")
} finally { $sha.Dispose() }

function Read-Evidence([string]$Name) {
    $path = Join-Path $evidence $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "RELEASE_APPROVAL_MISSING: $Name"
    }
    try { return Get-Content -Raw -Encoding UTF8 -LiteralPath $path | ConvertFrom-Json }
    catch { throw "RELEASE_APPROVAL_INVALID_JSON: $Name" }
}

$rc = Read-Evidence "private_rc.json"
$owner = Read-Evidence "owner.json"
foreach ($pair in @(@("private_rc.json",$rc), @("owner.json",$owner))) {
    $name = $pair[0]; $record = $pair[1]
    if ($record -isnot [pscustomobject]) { throw "RELEASE_APPROVAL_INVALID_RECORD: $name must be an object" }
    foreach ($field in @("schema","version","fingerprint_sha256","status","artifact_set_sha256")) {
        if ($record.PSObject.Properties.Name -notcontains $field) {
            throw "RELEASE_APPROVAL_INVALID_RECORD: $name missing $field"
        }
    }
    if (($record.schema -isnot [int] -and $record.schema -isnot [long]) -or $record.schema -ne 1) { throw "RELEASE_APPROVAL_INVALID_RECORD: $name schema" }
    foreach ($field in @("version","fingerprint_sha256","status","artifact_set_sha256")) {
        if ($record.$field -isnot [string]) { throw "RELEASE_APPROVAL_INVALID_RECORD: $name $field must be a string" }
    }
    if ($record.version -cne $version) { throw "RELEASE_APPROVAL_VERSION_MISMATCH: $name" }
    if ($record.fingerprint_sha256 -cne [string]$current.fingerprint_sha256) {
        throw "RELEASE_APPROVAL_STALE: $name fingerprint"
    }
    if ($record.artifact_set_sha256 -cne $artifactSetHash) {
        throw "RELEASE_APPROVAL_ARTIFACT_MISMATCH: $name"
    }
}

if ($rc.status -cne "PASS") {
    throw "RELEASE_APPROVAL_BLOCKED: private RC status=$($rc.status)"
}
if ($rc.PSObject.Properties.Name -notcontains "checks" -or $rc.checks -isnot [pscustomobject]) {
    throw "RELEASE_APPROVAL_INVALID_RECORD: private_rc.json missing checks"
}
$requiredChecks = @(
    "fresh_setup",
    "update_745_to_750",
    "updater_self_update",
    "updater_interruption_recovery",
    "automatic_restart",
    "second_restart",
    "repair",
    "runtime_identity",
    "release_layout_consistency",
    "automatic_repair_mixed_version",
    "network_consistency_bypass",
    "runtime_capability",
    "desktop_visual",
    "basic_generation",
    "inpaint",
    "two_consecutive_generations",
    "one_prompt_per_click",
    "final_saver_775",
    "actual_output_file",
    "ui_return",
    "user_data_preservation"
)
foreach ($check in $requiredChecks) {
    $prop = $rc.checks.PSObject.Properties[$check]
    if ($null -eq $prop -or $prop.Value -isnot [bool] -or $prop.Value -ne $true) {
        throw "RELEASE_APPROVAL_RC_CHECK_FAILED: $check"
    }
}
if ($rc.PSObject.Properties.Name -notcontains "artifacts" -or $rc.artifacts -isnot [pscustomobject]) {
    throw "RELEASE_APPROVAL_INVALID_RECORD: private_rc.json missing artifacts"
}
foreach ($name in $requiredAssets) {
    $prop = $rc.artifacts.PSObject.Properties[$name]
    if ($null -eq $prop -or $prop.Value -isnot [string] -or $prop.Value -cne $artifactHashes[$name]) {
        throw "RELEASE_APPROVAL_ARTIFACT_MISMATCH: private_rc.json $name"
    }
}

if ($owner.status -cne "APPROVED") {
    throw "RELEASE_APPROVAL_BLOCKED: owner status=$($owner.status)"
}
if ($owner.PSObject.Properties.Name -notcontains "approved_by" -or
    $owner.approved_by -isnot [string] -or
    [string]::IsNullOrWhiteSpace([string]$owner.approved_by)) {
    throw "RELEASE_APPROVAL_INVALID_RECORD: owner.json missing approved_by"
}

Write-Output ("RELEASE_APPROVAL_GATE_OK version={0} fingerprint={1} artifact_set={2}" -f $version,$current.fingerprint_sha256,$artifactSetHash)
