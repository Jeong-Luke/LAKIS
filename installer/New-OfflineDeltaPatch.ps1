param(
    [string]$FromVersion = "7.3.3",
    [string]$Version = "7.3.4",
    [string]$OldManifest = "",
    [string]$NewManifest = "",
    [string]$DistDirectory = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OldManifest) { $OldManifest = Join-Path $repo "manifests\update-latest.json" }
if (-not $NewManifest) { $NewManifest = Join-Path $repo "manifests\update-v$Version-rc.json" }
if (-not $DistDirectory) { $DistDirectory = Join-Path $repo "dist\v$Version-rc" }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo "dist\LAKIS_v$Version-offline-patch" }

$old = Get-Content -Raw -LiteralPath $OldManifest | ConvertFrom-Json
$new = Get-Content -Raw -LiteralPath $NewManifest | ConvertFrom-Json
$oldHashes = @{}
foreach ($item in $old.files) { $oldHashes[[string]$item.path] = [string]$item.sha256 }
$changed = @($new.files | Where-Object {
    -not $oldHashes.ContainsKey([string]$_.path) -or
    $oldHashes[[string]$_.path] -ne [string]$_.sha256
})

$output = [System.IO.Path]::GetFullPath($OutputDirectory)
$allowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repo "dist")).TrimEnd('\') + '\'
if (-not $output.StartsWith($allowedOutputRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Offline patch output must remain below $allowedOutputRoot"
}
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Recurse -Force }
$payload = Join-Path $output "payload"
New-Item -ItemType Directory -Force -Path $payload | Out-Null

function Resolve-Source([string]$Path) {
    $normalized = $Path.Replace('\', '/')
    if ($normalized -eq "ComfyUI/custom_nodes/comfyui-spectrum-ksampler/LAKIS_MODIFICATIONS.md") {
        return Join-Path $repo "patches\ComfyUI-Spectrum-KSampler\NOTICE.md"
    }
    if ($normalized -match '^(LAKIS(?:_Patcher|_Updater|_Desktop|_Model_Importer)?\.exe|Uninstall_LAKIS\.exe|Microsoft\.Web\.WebView2\..*\.dll|WebView2Loader\.dll)$') {
        return Join-Path $DistDirectory $normalized
    }
    if ($normalized.StartsWith("ComfyUI/LAKIS/external_ui/")) {
        $prefix = "ComfyUI/LAKIS/external_ui/"
        return Join-Path (Join-Path $repo "src\external_ui") $normalized.Substring($prefix.Length)
    }
    if ($normalized.StartsWith("ComfyUI/custom_nodes/")) {
        $prefix = "ComfyUI/custom_nodes/"
        return Join-Path (Join-Path $repo "src\custom_nodes") $normalized.Substring($prefix.Length)
    }
    if ($normalized.StartsWith("ComfyUI/LAKIS/workflows/")) {
        $prefix = "ComfyUI/LAKIS/workflows/"
        return Join-Path (Join-Path $repo "workflows") $normalized.Substring($prefix.Length)
    }
    return Join-Path $repo $normalized
}

$manifestFiles = [System.Collections.Generic.List[object]]::new()
foreach ($item in $changed) {
    $source = Resolve-Source ([string]$item.path)
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Delta source missing: $source" }
    $target = Join-Path $payload ([string]$item.path).Replace('/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
    if ($hash -ne ([string]$item.sha256).ToUpperInvariant()) { throw "Delta source hash mismatch: $($item.path)" }
    $manifestFiles.Add([ordered]@{ path = [string]$item.path; sha256 = $hash })
}

Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Apply-OfflineDelta.ps1") -Destination (Join-Path $output "Apply-OfflineDelta.ps1")
$launcher = "@echo off`r`nchcp 65001 >nul`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0Apply-OfflineDelta.ps1`"`r`npause`r`n"
[System.IO.File]::WriteAllText((Join-Path $output "INSTALL_LAKIS_7.3.4_RC.cmd"), $launcher, [System.Text.UTF8Encoding]::new($false))
[ordered]@{
    from_version = $FromVersion
    version = $Version
    created_at = [DateTime]::UtcNow.ToString("O")
    files = $manifestFiles
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output "patch-manifest.json") -Encoding UTF8

$zip = $output + ".zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path (Join-Path $output "*") -DestinationPath $zip -CompressionLevel Optimal
Write-Output "OFFLINE_PATCH=$zip"
Write-Output "FILES=$($manifestFiles.Count)"
Write-Output "SHA256=$((Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash)"
