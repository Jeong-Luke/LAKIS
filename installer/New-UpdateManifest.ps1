param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Repository = "Jeong-Luke/LAKIS",
    [string]$DistDirectory = "",
    [string]$OutputPath = "",
    [switch]$UseLocalWorkingTreeHashes
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = $repo
$dist = if ([string]::IsNullOrWhiteSpace($DistDirectory)) {
    Join-Path $workspace "dist"
} else {
    [System.IO.Path]::GetFullPath($DistDirectory)
}
$tag = "v$Version"
$releaseBase = "https://github.com/$Repository/releases/download/$tag"
$rawBase = "https://raw.githubusercontent.com/$Repository/$tag"

$files = [System.Collections.Generic.List[object]]::new()
function Add-UpdateFile([string]$InstallPath, [string]$SourcePath, [string]$Url) {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Update source is missing: $SourcePath"
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourcePath).Hash
    # GitHub serves repository text with the line endings stored in Git. A
    # Windows working tree can contain CRLF bytes for the same LF-tagged file,
    # so release manifests must hash the published bytes by default.
    if (-not $UseLocalWorkingTreeHashes -and $Url.StartsWith($rawBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        $temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("lakis-tag-hash-" + [guid]::NewGuid().ToString("N"))
        try {
            Invoke-WebRequest -UseBasicParsing -Headers @{ "User-Agent" = "LAKIS-Manifest/$Version" } `
                -Uri ($Url + "?manifest=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) -OutFile $temporary
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash
        }
        finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
    }
    $files.Add([ordered]@{
        path = $InstallPath.Replace('\', '/')
        url = $Url
        sha256 = $hash
    })
}

foreach ($name in @(
    "LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe", "LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe",
    "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll"
)) {
    Add-UpdateFile $name (Join-Path $dist $name) "$releaseBase/$name"
}

# Legal notices are application-owned release files. Existing installations
# must receive the same notices as clean installs.
foreach ($name in @("LICENSE.md", "THIRD_PARTY_NOTICES.md")) {
    Add-UpdateFile $name (Join-Path $repo $name) "$rawBase/$name"
}
$licenceRoot = Join-Path $repo "third_party_licenses"
Get-ChildItem -LiteralPath $licenceRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($licenceRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "third_party_licenses/$relative" $_.FullName "$rawBase/third_party_licenses/$relative"
    }

# Never put a model path in the update manifest. Updaters shipped with 7.2.2
# and 7.2.3 correctly protect the whole ComfyUI/models tree and would reject
# the update before the new patcher could replace them. The 7.2.4 UI downloads
# the permissively licensed RealESRGAN default on selection and verifies its
# pinned SHA-256 instead.

# The entire external UI is an atomic runtime component. Selecting individual
# files caused workflow_bridge.py to remain on an older release.
$externalRoot = Join-Path $repo "src\external_ui"
Get-ChildItem -LiteralPath $externalRoot -File -Recurse |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($externalRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/LAKIS/external_ui/$relative" $_.FullName "$rawBase/src/external_ui/$relative"
    }

# The launcher refuses every generation without this application-owned safety
# marker. It must be restored by every repair/update, not treated as stale data.
Add-UpdateFile "ComfyUI/LAKIS/STOP_AUTOMATION" (Join-Path $repo "resources\STOP_AUTOMATION") `
    "$rawBase/resources/STOP_AUTOMATION"

# These public, release-managed providers are shared with Install and Repair.
# No model files, runtime markers, caches, or user-created workflows are added.
$packageNames = @(Get-Content -LiteralPath (Join-Path $repo "resources\PRODUCTION_NODE_PACKAGES.txt") |
    ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
if ($packageNames.Count -eq 0 -or ($packageNames | Select-Object -Unique).Count -ne $packageNames.Count) {
    throw "Managed node package inventory is empty or contains duplicates."
}
foreach ($package in $packageNames) {
    if ($package -notmatch '^[A-Za-z0-9_-]+$') { throw "Invalid package name: $package" }
    $packageRoot = Join-Path $repo "src\custom_nodes\$package"
    if (-not (Test-Path -LiteralPath (Join-Path $packageRoot "__init__.py") -PathType Leaf)) {
        throw "Required managed node package is missing: $package"
    }
    Get-ChildItem -LiteralPath $packageRoot -File -Recurse |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' -and
            $_.Name -ne 'startup_workflow.json' } |
        Sort-Object FullName | ForEach-Object {
            $relative = $_.FullName.Substring($packageRoot.Length).TrimStart('\').Replace('\', '/')
            Add-UpdateFile "ComfyUI/custom_nodes/$package/$relative" $_.FullName "$rawBase/src/custom_nodes/$package/$relative"
        }
}
Add-UpdateFile "ComfyUI/LAKIS/sync_runtime_workflow.py" (Join-Path $repo "src\runtime\sync_runtime_workflow.py") `
    "$rawBase/src/runtime/sync_runtime_workflow.py"

# Only release-owned runtime workflows are updated. Editable workflows may
# contain user changes, including the packaged editable copy, so they are
# deliberately excluded from update payloads.
foreach ($runtimeName in @(
    "LAKIS_runtime_api_v7.4.json",
    "LAKIS_runtime_visual_v7.4.json"
)) {
    Add-UpdateFile "ComfyUI/LAKIS/workflows/$runtimeName" `
        (Join-Path $repo "workflows\$runtimeName") "$rawBase/workflows/$runtimeName"
}

$retiredFiles = @(
    'ComfyUI/LAKIS/external_ui/light-control-prototype.css',
    'ComfyUI/LAKIS/external_ui/lightmap-knob-mockup.js',
    'ComfyUI/LAKIS/workflows/LAKIS_DETAIL_runtime_api_v7.3.json',
    'ComfyUI/LAKIS/workflows/LAKIS_custom_v7.3_editable.json',
    'ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.1.json',
    'ComfyUI/LAKIS/workflows/LAKIS_runtime_visual_v7.3.json',
    'ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/INSTALL_REQUIREMENTS.bat',
    'ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/LICENSE',
    'ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/NOTICE.md',
    'ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/__init__.py',
    'ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/requirements.txt',
    'ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/web/lakis_light_control.js'
)

$filePaths = @($files | ForEach-Object { [string]$_.path })

# Public update manifests must never contain DEKIS/LUKIS runtime paths or
# development-only version/icon artifacts. This is a hard product-boundary gate.
$forbiddenProductPathPattern = '(?i)(LAKIS_DEV|DEKIS|LUKIS|LAKIS_LUKE|DEV_VERSION|LUKE_VERSION|LAKIS_DEV_red|LUKIS_Desktop|Start_LUKIS_Mobile)'
$forbiddenProductPaths = @(
    @($filePaths) + @($retiredFiles) |
    Where-Object { $_ -match $forbiddenProductPathPattern }
)
if ($forbiddenProductPaths.Count) {
    throw "Public update manifest contains development/private product paths: $($forbiddenProductPaths -join ', ')"
}

$duplicatePaths = @($filePaths | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
if ($duplicatePaths.Count) {
    throw "Update manifest contains duplicate file paths: $($duplicatePaths -join ', ')"
}
$deleteOverlap = @($retiredFiles | Where-Object { $_ -in $filePaths })
if ($deleteOverlap.Count) {
    throw "Update manifest would install and delete the same paths: $($deleteOverlap -join ', ')"
}

$manifest = [ordered]@{
    version = $Version
    release_notes = "LAKIS $Version update"
    files = $files
    delete = $retiredFiles
}
$output = if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    Join-Path $repo "manifests\update-latest.json"
} else {
    [System.IO.Path]::GetFullPath($OutputPath)
}
$outputDirectory = Split-Path -Parent $output
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding utf8
Write-Output "MANIFEST=$output"
Write-Output "FILES=$($files.Count)"
