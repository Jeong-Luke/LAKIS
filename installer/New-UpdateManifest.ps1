param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Repository = "Jeong-Luke/LAKIS",
    [string]$DistDirectory = "",
    [string]$OutputPath = "",
    [switch]$UseLocalWorkingTreeHashes
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspace = (Resolve-Path (Join-Path $repo "..\..")).Path
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
        Add-UpdateFile "ComfyUI/LAKIS_DEV/external_ui/$relative" $_.FullName "$rawBase/src/external_ui/$relative"
    }

# Keep the packaged camera-to-prompt bridge workflow synchronized without
# touching any user workflow files.
$cameraBridgeRoot = Join-Path $repo "src\custom_nodes\ComfyUI-KR-Camera-PromptStudio-Bridge"
$cameraBridgeMatches = @(Get-ChildItem -LiteralPath $cameraBridgeRoot -File -Filter "KR_Camera_Anima_*_ONOFF.json")
if ($cameraBridgeMatches.Count -ne 1) {
    throw "Expected exactly one packaged KR Camera Anima bridge workflow; found $($cameraBridgeMatches.Count)."
}
$cameraBridgeFile = $cameraBridgeMatches[0].Name
Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-KR-Camera-PromptStudio-Bridge/$cameraBridgeFile" `
    $cameraBridgeMatches[0].FullName `
    "$rawBase/src/custom_nodes/ComfyUI-KR-Camera-PromptStudio-Bridge/$cameraBridgeFile"

# Public Local Inpaint V2 implementation. The model weight is intentionally
# absent: users install it manually from the official publisher.
$localInpaintRoot = Join-Path $repo "src\custom_nodes\ComfyUI-LAKIS-Local-Inpaint"
Get-ChildItem -LiteralPath $localInpaintRoot -File -Recurse |
    Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($localInpaintRoot.Length).TrimStart('\').Replace('\', '/')
        Add-UpdateFile "ComfyUI/custom_nodes/ComfyUI-LAKIS-Local-Inpaint/$relative" $_.FullName `
            "$rawBase/src/custom_nodes/ComfyUI-LAKIS-Local-Inpaint/$relative"
    }

# This is application-owned and safe to update. The editable workflow under
# ComfyUI/user is deliberately excluded because it contains user changes.
foreach ($runtimeName in @(
    "LAKIS_runtime_api_v7.4.json",
    "LAKIS_runtime_visual_v7.4.json",
    "LAKIS_custom_v7.4_editable.json"
)) {
    Add-UpdateFile "ComfyUI/LAKIS/workflows/$runtimeName" `
        (Join-Path $repo "workflows\$runtimeName") "$rawBase/workflows/$runtimeName"
}

$retiredFiles = @(
    'ComfyUI/LAKIS/STOP_AUTOMATION',
    'ComfyUI/LAKIS/external_ui/README.md',
    'ComfyUI/LAKIS/external_ui/advanced-node-settings.css',
    'ComfyUI/LAKIS/external_ui/advanced-node-settings.js',
    'ComfyUI/LAKIS/external_ui/app.js',
    'ComfyUI/LAKIS/external_ui/assets/LAKIS_windows_compatible.ico',
    'ComfyUI/LAKIS/external_ui/assets/upscaler/animesharp-v4-fast-preview.png',
    'ComfyUI/LAKIS/external_ui/assets/upscaler/realesrgan-anime-6b-preview.png',
    'ComfyUI/LAKIS/external_ui/brand-position-fix.css',
    'ComfyUI/LAKIS/external_ui/camera-3d.css',
    'ComfyUI/LAKIS/external_ui/composition-control.css',
    'ComfyUI/LAKIS/external_ui/composition-toggle.css',
    'ComfyUI/LAKIS/external_ui/data/autocomplete.csv',
    'ComfyUI/LAKIS/external_ui/error-dialog.css',
    'ComfyUI/LAKIS/external_ui/generation-actions.css',
    'ComfyUI/LAKIS/external_ui/generation-monitor.css',
    'ComfyUI/LAKIS/external_ui/history-mode-badge.css',
    'ComfyUI/LAKIS/external_ui/horizontal-overflow-fix.css',
    'ComfyUI/LAKIS/external_ui/i2i-control.css',
    'ComfyUI/LAKIS/external_ui/i2i-preview-contain.css',
    'ComfyUI/LAKIS/external_ui/index.html',
    'ComfyUI/LAKIS/external_ui/launch_lakis.py',
    'ComfyUI/LAKIS/external_ui/layout-adjustment.css',
    'ComfyUI/LAKIS/external_ui/light-control-prototype.css',
    'ComfyUI/LAKIS/external_ui/lightmap-knob-mockup.js',
    'ComfyUI/LAKIS/external_ui/lora-controls.css',
    'ComfyUI/LAKIS/external_ui/mockup-layout.css',
    'ComfyUI/LAKIS/external_ui/preview-zoom.css',
    'ComfyUI/LAKIS/external_ui/prompt-categories.css',
    'ComfyUI/LAKIS/external_ui/prompt-highlighting.css',
    'ComfyUI/LAKIS/external_ui/prompt-highlighting.js',
    'ComfyUI/LAKIS/external_ui/prompt-inspector.css',
    'ComfyUI/LAKIS/external_ui/prompt-model-controls.css',
    'ComfyUI/LAKIS/external_ui/prompt-width.css',
    'ComfyUI/LAKIS/external_ui/readability.css',
    'ComfyUI/LAKIS/external_ui/seed-controls.css',
    'ComfyUI/LAKIS/external_ui/seed-layout-fix.css',
    'ComfyUI/LAKIS/external_ui/serve_ui.py',
    'ComfyUI/LAKIS/external_ui/sidebar-links.css',
    'ComfyUI/LAKIS/external_ui/status-footer-large.css',
    'ComfyUI/LAKIS/external_ui/status-footer.css',
    'ComfyUI/LAKIS/external_ui/styles.css',
    'ComfyUI/LAKIS/external_ui/system-info-dialog.css',
    'ComfyUI/LAKIS/external_ui/system-info-dialog.js',
    'ComfyUI/LAKIS/external_ui/upscaler-license-migration.css',
    'ComfyUI/LAKIS/external_ui/upscaler-license-migration.js',
    'ComfyUI/LAKIS/external_ui/viewport-fix.css',
    'ComfyUI/LAKIS/external_ui/workflow_bridge.py',
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
