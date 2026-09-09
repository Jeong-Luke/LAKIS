param(
    [string]$PatchDirectory = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $PatchDirectory) { $PatchDirectory = Join-Path $repo "dist\LAKIS_v7.3.4-offline-patch" }
$testRoot = Join-Path $repo "dist\.offline-delta-test-install"
if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
Set-Content -LiteralPath (Join-Path $testRoot "VERSION") -Value "7.3.3" -Encoding ASCII

$protected = @(
    "ComfyUI\models\checkpoints\KEEP_MODEL.safetensors",
    "ComfyUI\models\loras\KEEP_LORA.safetensors",
    "ComfyUI\output\KEEP_OUTPUT.webp",
    "ComfyUI\user\default\workflows\KEEP_USER_WORKFLOW.json"
)
foreach ($relative in $protected) {
    $path = Join-Path $testRoot $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
    Set-Content -LiteralPath $path -Value "preserve-user-data" -Encoding UTF8
}

& (Join-Path $PatchDirectory "Apply-OfflineDelta.ps1") -InstallRoot $testRoot
if ((Get-Content -Raw -LiteralPath (Join-Path $testRoot "VERSION")).Trim() -ne "7.3.4") {
    throw "Offline patch did not advance VERSION to 7.3.4."
}
foreach ($relative in $protected) {
    $path = Join-Path $testRoot $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        -not (Get-Content -Raw -LiteralPath $path).Contains("preserve-user-data")) {
        throw "Offline patch modified protected user data: $relative"
    }
}

$manifest = Get-Content -Raw -LiteralPath (Join-Path $PatchDirectory "patch-manifest.json") | ConvertFrom-Json
foreach ($item in $manifest.files) {
    $installed = Join-Path $testRoot ([string]$item.path)
    if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) { throw "Installed delta file missing: $($item.path)" }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $installed).Hash -ne ([string]$item.sha256).ToUpperInvariant()) {
        throw "Installed delta hash mismatch: $($item.path)"
    }
}
Write-Output "OFFLINE_DELTA_TEST_OK files=$($manifest.files.Count) protected=$($protected.Count)"
